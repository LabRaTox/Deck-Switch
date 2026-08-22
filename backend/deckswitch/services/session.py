"""Was diese Sitzung hergibt.

Eine Stream-Deck-Software besteht zum guten Teil aus Aktionen, die etwas
*außerhalb* der App auslösen: ein Fenster maximieren, ein Bildschirmfoto
machen, die Monitorhelligkeit ändern. Ob das geht, hängt nicht an der
Distribution, sondern an der laufenden Sitzung — am Compositor, am
Desktop, an installierten Programmen.

Bis hierher stand jede dieser Prüfungen dort, wo sie gebraucht wurde:
achtzehn verstreute ``shutil.which``-Aufrufe, jeder mit eigener
Fehlermeldung, jeder erst *nachdem* der Benutzer die Taste gedrückt hat.
Das Ergebnis war eine Aktionsbibliothek, die auf jedem System gleich
aussieht, und Tasten, die auf manchen Systemen stumm bleiben.

Dieses Modul fragt einmal beim Start alles ab und beantwortet danach die
Frage „kann diese Sitzung X?" aus dem Gedächtnis. Die Aktionsbibliothek
zeigt dann nur noch, was hier auch wirklich funktioniert.

**Warum nicht einfach den Desktop abfragen und daraus schließen?** Weil
``XDG_CURRENT_DESKTOP=KDE`` nichts darüber sagt, ob ``ddcutil``
installiert ist oder ob der Benutzer in der Gruppe ``input`` steht. Der
Desktop-Name ist hier nur ein Hinweis unter mehreren; entschieden wird je
Fähigkeit und am konkreten Beleg — Programm vorhanden, Bus-Name belegt,
Geräteknoten beschreibbar.

**Warum die Prüfung nichts kostet, was sie nicht muss.** Alles, was hier
passiert, ist Dateisystem und D-Bus-Namensabfrage. Kein einziges externes
Programm wird *ausgeführt*: ``ddcutil detect`` allein braucht rund 1,8
Sekunden, und beim Start des Backends ist das Gerät wichtiger als die
Frage, wie viele Monitore DDC sprechen.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

#: Wie lange die D-Bus-Abfrage höchstens dauern darf. Steht ein Bus nicht
#: zur Verfügung, hängt ``connect()`` sonst bis zum Sankt-Nimmerleins-Tag,
#: und das Backend käme gar nicht erst hoch.
BUS_TIMEOUT_S = 3.0


# ==========================================================================
# Die Fähigkeiten
# ==========================================================================

#: Tastendrücke und Text schicken (virtuelle Tastatur über ``/dev/uinput``).
KEYBOARD_INPUT = "keyboard_input"

#: Fenster steuern — maximieren, auf anderen Bildschirm, Arbeitsfläche.
WINDOW_CONTROL = "window_control"

#: Eine Tastenkombination systemweit für uns reservieren.
GLOBAL_SHORTCUTS = "global_shortcuts"

#: Bildschirmfoto auslösen.
SCREENSHOT = "screenshot"

#: Bildschirme an- und ausschalten.
SCREEN_POWER = "screen_power"

#: Abmelden, neu starten, herunterfahren.
SESSION_POWER = "session_power"

#: Abmelden und die gewohnten Rückfragen („Wirklich herunterfahren?") über
#: die Sitzungsverwaltung des Desktops. Getrennt von :data:`SESSION_POWER`,
#: weil das etwas anderes ist: Ausschalten kann ``systemctl`` überall,
#: aber den Dialog davor bringt nur Plasma mit.
SESSION_MANAGER = "session_manager"

#: Das virtuelle Deck als Overlay über allen Fenstern zeigen. Zwei Wege
#: führen dahin — ``zwlr_layer_shell_v1`` unter Wayland und die alten
#: Fenster-Hinweise unter X11 —, deshalb heißt die Fähigkeit nach ihrem
#: Zweck und nicht nach einem der beiden Protokolle.
OVERLAY = "overlay"

#: Monitorhelligkeit über DDC/CI.
DDC = "ddc"

#: Lautstärke und Audiogeräte.
AUDIO = "audio"

#: Klänge abspielen (Soundboard).
SOUND_PLAYBACK = "sound_playback"

#: Symbol im Systemabschnitt der Kontrollleiste.
TRAY = "tray"

#: Ordner, Dateien und Adressen im Standardprogramm öffnen.
OPEN_URI = "open_uri"

#: Laufende Programme finden und beenden.
PROCESS_CONTROL = "process_control"

#: Reihenfolge für die Anzeige in der Oberfläche — grob nach Wichtigkeit.
ALL_CAPABILITIES = (
    KEYBOARD_INPUT,
    WINDOW_CONTROL,
    GLOBAL_SHORTCUTS,
    SCREENSHOT,
    SCREEN_POWER,
    SESSION_POWER,
    SESSION_MANAGER,
    OVERLAY,
    DDC,
    AUDIO,
    SOUND_PLAYBACK,
    TRAY,
    OPEN_URI,
    PROCESS_CONTROL,
)


@dataclass(slots=True)
class Capability:
    """Eine Fähigkeit und woran sie hängt."""

    id: str
    available: bool = False
    #: Womit sie umgesetzt wird — ``"spectacle"``, ``"portal"``, ``"kwin"``.
    #: Die Oberfläche zeigt das in der Diagnose; für Fehlerberichte ist es
    #: die halbe Miete.
    provider: str = ""
    #: Warum nicht, in einem Satz und für Menschen. Leer, wenn verfügbar.
    reason: str = ""

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "available": self.available,
            "provider": self.provider,
            "reason": self.reason,
        }


# ==========================================================================
# Die Sitzung
# ==========================================================================


@dataclass(slots=True)
class SessionInfo:
    """Der grobe Rahmen — Hinweis, nicht Beweis."""

    #: ``kde``, ``gnome``, ``hyprland``, ``sway``, … oder ``""``.
    desktop: str = ""
    #: ``wayland``, ``x11`` oder ``""``.
    display_server: str = ""

    @property
    def is_plasma(self) -> bool:
        return self.desktop == "kde"

    def as_dict(self) -> dict:
        return {"desktop": self.desktop, "display_server": self.display_server}


class SessionCapabilities:
    """Fragt einmal ab, was geht, und beantwortet es danach aus dem Kopf."""

    def __init__(self) -> None:
        self.info = SessionInfo()
        self.caps: dict[str, Capability] = {
            cap_id: Capability(cap_id) for cap_id in ALL_CAPABILITIES
        }
        self._detected = False
        #: War der Sitzungsbus beim letzten Abtasten erreichbar? Wichtig
        #: für den Unterschied zwischen „geht auf diesem Desktop nicht" und
        #: „konnten wir noch nicht feststellen" — nur Letzteres lohnt einen
        #: zweiten Versuch.
        self.bus_reachable = False

    # -- Abfrage -----------------------------------------------------------

    def has(self, cap_id: str) -> bool:
        """Kann die Sitzung das?

        Unbekannte Namen gelten als vorhanden. Ein Plugin, das eine
        Fähigkeit fordert, die wir gar nicht kennen, soll dadurch nicht
        unbenutzbar werden — wir wissen dann schlicht nichts über sie, und
        das ist kein Grund, dem Benutzer die Aktion wegzunehmen.
        """
        cap = self.caps.get(cap_id)
        return True if cap is None else cap.available

    def missing(self, required: list[str] | tuple[str, ...]) -> list[str]:
        """Welche der geforderten Fähigkeiten fehlen."""
        return [cap_id for cap_id in required if not self.has(cap_id)]

    def reason_for(self, cap_id: str) -> str:
        cap = self.caps.get(cap_id)
        return cap.reason if cap else ""

    def as_dict(self) -> dict:
        return {
            "session": self.info.as_dict(),
            "capabilities": [self.caps[c].as_dict() for c in ALL_CAPABILITIES],
        }

    # -- Erkennung ---------------------------------------------------------

    async def detect(self) -> None:
        """Alles abtasten. Mehrfach aufrufbar — etwa nach einer Nachinstallation."""
        self.info = _detect_session()
        self._detect_local()
        await self._detect_bus()
        self._detected = True

        fehlend = [c for c in ALL_CAPABILITIES if not self.caps[c].available]
        if fehlend:
            log.info(
                "Sitzung erkannt (%s/%s). Nicht verfügbar: %s",
                self.info.desktop or "unbekannt",
                self.info.display_server or "unbekannt",
                ", ".join(fehlend),
            )
        else:
            log.info("Sitzung erkannt — alle Fähigkeiten vorhanden")

    def _set(self, cap_id: str, available: bool, provider: str = "", reason: str = "") -> None:
        cap = self.caps[cap_id]
        cap.available = available
        cap.provider = provider if available else ""
        cap.reason = "" if available else reason

    def _detect_local(self) -> None:
        """Alles, wofür Dateisystem und ``PATH`` genügen."""
        # -- Tastatur ------------------------------------------------------
        ok, grund = _uinput_usable()
        self._set(KEYBOARD_INPUT, ok, "uinput", grund)

        # -- Bildschirme ---------------------------------------------------
        # ``kscreen-doctor`` ist ein Plasma-Werkzeug: Es spricht mit KScreen
        # und scheitert anderswo, auch wenn es installiert ist. Am
        # 2026-08-22 in einer Sway-Sitzung gemessen — Rückgabewert 1, keine
        # Ausgabe. „Programm vorhanden" genügt hier also nicht.
        if self.info.is_plasma and shutil.which("kscreen-doctor"):
            self._set(SCREEN_POWER, True, "kscreen-doctor")
        elif _hyprland_laeuft():
            self._set(SCREEN_POWER, True, "hyprland")
        elif _sway_laeuft():
            self._set(SCREEN_POWER, True, "sway")
        elif shutil.which("kscreen-doctor"):
            self._set(
                SCREEN_POWER,
                False,
                reason=(
                    "'kscreen-doctor' ist zwar da, wirkt aber nur unter KDE Plasma"
                ),
            )
        else:
            self._set(
                SCREEN_POWER,
                False,
                reason="Kein Weg, die Bildschirme zu schalten (kscreen-doctor, Sway oder Hyprland)",
            )

        # -- DDC -----------------------------------------------------------
        if shutil.which("ddcutil"):
            self._set(DDC, True, "ddcutil")
        else:
            self._set(DDC, False, reason="'ddcutil' ist nicht installiert")

        # -- Ton -----------------------------------------------------------
        if shutil.which("wpctl") or shutil.which("pactl"):
            self._set(AUDIO, True, "wpctl" if shutil.which("wpctl") else "pactl")
        else:
            self._set(AUDIO, False, reason="Weder 'wpctl' noch 'pactl' gefunden")

        for programm in ("pw-play", "mpv", "ffplay"):
            if shutil.which(programm):
                self._set(SOUND_PLAYBACK, True, programm)
                break
        else:
            self._set(
                SOUND_PLAYBACK,
                False,
                reason="Kein Abspielprogramm gefunden (pw-play, mpv oder ffplay)",
            )

        # -- Öffnen und Prozesse -------------------------------------------
        if shutil.which("xdg-open"):
            self._set(OPEN_URI, True, "xdg-open")
        else:
            self._set(OPEN_URI, False, reason="'xdg-open' ist nicht installiert")

        if shutil.which("pgrep"):
            self._set(PROCESS_CONTROL, True, "pgrep")
        else:
            self._set(
                PROCESS_CONTROL, False, reason="'pgrep' ist nicht installiert (procps)"
            )

        # -- Sitzung beenden -----------------------------------------------
        # Der Weg über Plasma bringt die gewohnte Rückfrage, ``systemctl``
        # tut es ohne. Für die Frage „geht es überhaupt?" genügt eins von
        # beiden; welches genommen wird, entscheidet ``desktop.py`` je
        # Aktion selbst.
        if shutil.which("systemctl") or shutil.which("loginctl"):
            self._set(SESSION_POWER, True, "systemd")
        else:
            self._set(
                SESSION_POWER, False, reason="Weder 'systemctl' noch 'loginctl' gefunden"
            )

        # -- Overlay -------------------------------------------------------
        # Zwei Bedingungen: Das Anzeigeprogramm muss da sein *und* der
        # Compositor muss ``zwlr_layer_shell_v1`` sprechen. Mutter (GNOME)
        # tut das nicht und wird es absehbar auch nicht tun — dort bleibt
        # das virtuelle Deck aus, und zwar sichtbar statt stillschweigend.
        self._detect_overlay()

    def _detect_overlay(self) -> None:
        """Lässt sich das virtuelle Deck über allen Fenstern zeigen?

        Zwei Wege, und der ältere ist der breitere:

        * **Wayland** braucht ``zwlr_layer_shell_v1``. KWin, Hyprland, Sway
          und die übrigen wlroots-Compositoren können es, Mutter nicht —
          und das ist bei GNOME Absicht, keine Lücke.
        * **X11** kennt das Protokoll nicht, hat dafür aber die alten
          Fenster-Hinweise. Am 2026-08-21 unter XWayland nachgemessen:
          ``_NET_WM_STATE_ABOVE``, Fenstertyp ``UTILITY`` und vor allem
          ``WM_HINTS: Client accepts input focus: False``. Ein Klick auf
          eine Kachel lässt den Tastaturfokus stehen, wo er war — geprüft
          über ``XGetInputFocus`` vor und nach dem Klick. Damit taugt der
          X11-Weg für dasselbe wie die Layer-Surface.

        Das Programm selbst ist in beiden Fällen dasselbe.
        """
        if shutil.which("qml6") is None:
            self._set(OVERLAY, False, reason="'qml6' fehlt (Paket qt6-declarative)")
            return

        # Der Import von LayerShellQt steht in der QML-Datei und wird auch
        # unter X11 aufgelöst — ohne das Paket startet das Overlay nirgends.
        if not Path("/usr/lib/qt6/qml/org/kde/layershell/qmldir").exists():
            self._set(OVERLAY, False, reason="LayerShellQt fehlt (Paket layer-shell-qt)")
            return

        if self.info.display_server == "x11":
            self._set(OVERLAY, True, "x11")
            return

        # Bei unbekannten Compositoren gehen wir von „ja" aus: Eine Liste
        # kann nur veralten, und ein falsches Nein wäre schlimmer als ein
        # Versuch, der eine Meldung nach sich zieht.
        ohne_layer_shell = {"gnome", "unity"}
        if self.info.desktop in ohne_layer_shell:
            self._set(
                OVERLAY,
                False,
                reason=(
                    f"Der Compositor von {self.info.desktop.upper()} unterstützt "
                    "zwlr_layer_shell_v1 nicht"
                ),
            )
            return

        self._set(OVERLAY, True, "layer-shell-qt")

    async def _detect_bus(self) -> None:
        """Alles, was am Sitzungsbus hängt.

        Fällt die Verbindung aus, gelten diese Fähigkeiten als nicht
        vorhanden — mit einer Begründung, die das auch sagt. Ein
        Backend ohne Bus ist ein seltener, aber echter Fall (Dienst startet
        vor der Sitzung), und dann ist „geht nicht, weil kein Bus" die
        einzig ehrliche Antwort.
        """
        namen = await _bus_names()
        self.bus_reachable = namen is not None

        if namen is None:
            for cap_id in (
                WINDOW_CONTROL, GLOBAL_SHORTCUTS, TRAY, SCREENSHOT, SESSION_MANAGER
            ):
                self._set(
                    cap_id, False, reason="Kein Sitzungsbus erreichbar (D-Bus)"
                )
            return

        # -- Fenster -------------------------------------------------------
        # Drei Wege, je nach Compositor. Alle drei tun dasselbe: einen
        # Befehl an den Fenstermanager schicken, der ihn ausführt.
        #
        # Unter Wayland gibt es keinen allgemeinen Weg dafür — kein
        # Protokoll erlaubt es einem Client, fremde Fenster zu bewegen, und
        # das ist Absicht. Wer es trotzdem anbietet, tut das über eine
        # eigene Schnittstelle: Plasma über kglobalaccel, Hyprland und Sway
        # über ihre IPC. GNOME bietet gar keine — dort bleibt es aus.
        if "org.kde.kglobalaccel" in namen:
            self._set(WINDOW_CONTROL, True, "kglobalaccel")
        elif _hyprland_laeuft():
            self._set(WINDOW_CONTROL, True, "hyprland")
        elif _sway_laeuft():
            self._set(WINDOW_CONTROL, True, "sway")
        else:
            self._set(
                WINDOW_CONTROL,
                False,
                reason=(
                    "Fenster steuern geht nur über eine eigene Schnittstelle des "
                    "Compositors — Plasma, Hyprland und Sway haben eine, GNOME nicht"
                ),
            )

        # -- Globale Kurzbefehle -------------------------------------------
        # kglobalaccel zuerst, obwohl das Portal der neuere Standard ist —
        # die beiden können nicht dasselbe:
        #
        # * Über kglobalaccel *setzt* die App die Kombination, die der
        #   Benutzer in unserer Oberfläche eingetippt hat. Ist sie vergeben,
        #   sagt Plasma auch, an wen.
        # * Das Portal nimmt die Kombination nur als *Wunsch* entgegen
        #   (``preferred_trigger``) und zeigt einen Bestätigungsdialog;
        #   geändert wird sie danach in den Systemeinstellungen des
        #   Desktops, nicht mehr bei uns.
        #
        # Auf Plasma wäre das Portal also ein Rückschritt. Überall sonst
        # ist es der einzige Weg — und dort ein guter.
        if "org.kde.kglobalaccel" in namen:
            self._set(GLOBAL_SHORTCUTS, True, "kglobalaccel")
        elif "org.freedesktop.portal.Desktop" in namen and _portal_backend_fuer(
            "org.freedesktop.impl.portal.GlobalShortcuts", self.info.desktop
        ):
            self._set(GLOBAL_SHORTCUTS, True, "portal")
        else:
            self._set(
                GLOBAL_SHORTCUTS,
                False,
                reason="Weder xdg-desktop-portal noch kglobalaccel erreichbar",
            )

        # -- Abmelden und Rückfragen ---------------------------------------
        # ``org.kde.LogoutPrompt`` und ``org.kde.Shutdown`` stehen nicht
        # dauerhaft am Bus, sondern werden bei Bedarf gestartet. Deshalb
        # zählen hier auch die *aktivierbaren* Namen — sonst gälte die
        # Fähigkeit als fehlend, solange sie niemand gebraucht hat.
        if "org.kde.LogoutPrompt" in namen or "org.kde.Shutdown" in namen:
            self._set(SESSION_MANAGER, True, "plasma")
        else:
            self._set(
                SESSION_MANAGER,
                False,
                reason=(
                    "Abmelden und die Rückfrage davor gibt es nur über Plasmas "
                    "Sitzungsverwaltung"
                ),
            )

        # -- Bildschirmfoto ------------------------------------------------
        # Spectacle zuerst, aber nur unter Plasma: Dort macht es das Foto
        # ohne Rückfrage. Anderswo ist es der gefährlichste Fall überhaupt —
        # am 2026-08-22 unter Sway gemessen: Rückgabewert 0, *und keine
        # Datei*. Es meldet also Erfolg und tut nichts. Das Portal fragt
        # beim ersten Mal nach, merkt sich die Antwort danach und liefert
        # wenigstens, was es verspricht.
        if self.info.is_plasma and shutil.which("spectacle"):
            self._set(SCREENSHOT, True, "spectacle")
        elif "org.freedesktop.portal.Desktop" in namen and _portal_backend_fuer(
            "org.freedesktop.impl.portal.Screenshot", self.info.desktop
        ):
            self._set(SCREENSHOT, True, "portal")
        else:
            self._set(
                SCREENSHOT,
                False,
                reason="Weder Spectacle noch xdg-desktop-portal gefunden",
            )

        # -- Tray ----------------------------------------------------------
        if "org.kde.StatusNotifierWatcher" in namen:
            self._set(TRAY, True, "StatusNotifierItem")
        else:
            self._set(
                TRAY,
                False,
                reason=(
                    "Kein StatusNotifierWatcher am Bus — eine Kontrollleiste mit "
                    "Systemabschnitt fehlt (unter GNOME die Erweiterung "
                    "'AppIndicator Support', auf wlroots etwa waybar)"
                ),
            )


# ==========================================================================
# Einzelprüfungen
# ==========================================================================


def _detect_session() -> SessionInfo:
    """Desktop und Anzeigeserver aus der Umgebung.

    ``XDG_CURRENT_DESKTOP`` darf mehrere Werte mit Doppelpunkt enthalten
    (``ubuntu:GNOME``); maßgeblich ist der letzte, denn der ist der
    eigentliche Desktop — die davor sind Geschmacksrichtungen.
    """
    roh = os.environ.get("XDG_CURRENT_DESKTOP", "")
    desktop = roh.split(":")[-1].strip().lower() if roh else ""

    if not desktop:
        sitzung = os.environ.get("DESKTOP_SESSION", "")
        desktop = Path(sitzung).stem.lower() if sitzung else ""

    server = os.environ.get("XDG_SESSION_TYPE", "").strip().lower()
    if not server:
        server = "wayland" if os.environ.get("WAYLAND_DISPLAY") else ""
        if not server and os.environ.get("DISPLAY"):
            server = "x11"

    return SessionInfo(desktop=desktop, display_server=server)


#: Wo die Backends von ``xdg-desktop-portal`` sich eintragen.
PORTAL_BACKENDS = Path("/usr/share/xdg-desktop-portal/portals")


def _portal_backend_fuer(interface: str, desktop: str) -> bool:
    """Gibt es ein Portal-Backend, das diese Schnittstelle hier bedient?

    Dass ``org.freedesktop.portal.Desktop`` am Bus steht, heißt nur, dass
    der *Vermittler* läuft. Ob dahinter jemand steht, der die Arbeit
    macht, ist eine zweite Frage: Auf einem schlanken wlroots-Desktop ohne
    ``xdg-desktop-portal-wlr`` nimmt das Portal die Anfrage an und bricht
    sie dann ab. Die Backends deklarieren sich in ``*.portal``-Dateien mit
    ``Interfaces=`` und ``UseIn=``; genau das wird hier gelesen.

    **Was diese Prüfung nicht leistet:** Ein Backend, das sich für einen
    Desktop einträgt, dort aber trotzdem nicht arbeitet, gilt hier als
    vorhanden. ``hyprland.portal`` nennt etwa ``sway`` in seinem
    ``UseIn``, funktioniert dort aber nicht. Solche Fälle melden sich als
    Fehler der Aktion — sichtbar, nicht stumm.

    Im Zweifel ``True``: Ist das Verzeichnis nicht lesbar oder leer, wissen
    wir schlicht nichts, und ein falsches Nein nähme dem Benutzer eine
    Aktion weg, die vielleicht läuft.
    """
    try:
        dateien = list(PORTAL_BACKENDS.glob("*.portal"))
    except OSError:
        return True
    if not dateien:
        return True

    gesucht = desktop.lower()
    for datei in dateien:
        try:
            text = datei.read_text()
        except OSError:
            continue
        if interface not in text:
            continue
        for zeile in text.splitlines():
            if not zeile.startswith("UseIn="):
                continue
            eintraege = {e.strip().lower() for e in zeile[6:].split(";") if e.strip()}
            # ``wlroots`` steht stellvertretend für die ganze Familie.
            if gesucht in eintraege or (
                "wlroots" in eintraege and gesucht in {"sway", "river", "wayfire", "labwc"}
            ):
                return True
    return False


def _hyprland_laeuft() -> bool:
    """Läuft gerade eine Hyprland-Sitzung, die wir ansprechen können?

    Maßgeblich ist ``HYPRLAND_INSTANCE_SIGNATURE``: Die Variable setzt
    Hyprland selbst und nur für seine eigene Sitzung. ``hyprctl`` im Pfad
    allein sagt nichts — das kann auch nur installiert sein.
    """
    return bool(os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")) and bool(
        shutil.which("hyprctl")
    )


def _sway_laeuft() -> bool:
    """Dasselbe für Sway — dort heißt die Variable ``SWAYSOCK``."""
    return bool(os.environ.get("SWAYSOCK")) and bool(shutil.which("swaymsg"))


def _uinput_usable() -> tuple[bool, str]:
    """Lässt sich ``/dev/uinput`` beschreiben?

    Dieselbe Prüfung wie in :mod:`.input`, hier aber ohne Nebenwirkung: Es
    wird nur geöffnet und sofort wieder geschlossen, kein Gerät angemeldet.
    """
    knoten = Path("/dev/uinput")
    if not knoten.exists():
        return False, "/dev/uinput fehlt — das Kernel-Modul 'uinput' ist nicht geladen"
    try:
        with open(knoten, "wb"):
            pass
    except PermissionError:
        return False, (
            "Kein Schreibrecht auf /dev/uinput — der Benutzer muss in der Gruppe "
            "'input' sein (danach ab- und wieder anmelden)"
        )
    except OSError as exc:
        return False, f"/dev/uinput nicht nutzbar: {exc}"
    return True, ""


async def _bus_names() -> set[str] | None:
    """Alle Namen am Sitzungsbus. ``None``, wenn kein Bus erreichbar ist.

    Ein einziger Aufruf für alle Bus-Fragen: ``ListNames`` liefert die
    fertigen *und* die aktivierbaren Namen. Getrennte ``NameHasOwner``-Rufe
    je Fähigkeit wären vier Rundreisen statt einer.
    """
    from dbus_next import BusType, Message, MessageType
    from dbus_next.aio import MessageBus

    bus = None
    try:
        async with asyncio.timeout(BUS_TIMEOUT_S):
            bus = await MessageBus(bus_type=BusType.SESSION).connect()

            namen: set[str] = set()
            for aufruf in ("ListNames", "ListActivatableNames"):
                antwort = await bus.call(
                    Message(
                        destination="org.freedesktop.DBus",
                        path="/org/freedesktop/DBus",
                        interface="org.freedesktop.DBus",
                        member=aufruf,
                    )
                )
                if antwort is not None and antwort.message_type is MessageType.METHOD_RETURN:
                    namen.update(antwort.body[0])
            return namen
    except Exception as exc:  # noqa: BLE001 — jeder Fehler heißt hier „kein Bus"
        log.debug("Sitzungsbus nicht erreichbar: %s", exc)
        return None
    finally:
        if bus is not None:
            bus.disconnect()
