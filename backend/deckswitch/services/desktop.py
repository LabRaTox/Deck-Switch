"""Systemnahe Aktionen: Sitzung, Fenster, Bildschirmfotos.

Zielplattform ist Plasma unter Wayland, und das prägt die Wege:

* **Fenster** lassen sich unter Wayland nicht von außen verschieben — es gibt
  kein Protokoll dafür, und das ist Absicht. KDE bringt aber für jede
  Fensteraktion einen *globalen Kurzbefehl* mit, und die lassen sich über
  ``kglobalaccel`` direkt auslösen. Damit kommt man an „maximieren",
  „auf Bildschirm 2", „Arbeitsfläche 3" heran, ohne Tastendrücke zu
  simulieren und ohne dass der Benutzer die Kurzbefehle überhaupt belegt
  haben muss.
* **Abmelden und Herunterfahren** gehen über Plasmas eigene Schnittstelle,
  damit die gewohnte Rückfrage erscheint. Wer sie ohne Rückfrage will,
  bekommt sie auch — aber als eigene Auswahl, nicht als Überraschung.
* **Bildschirmfotos** macht Spectacle. Ein eigener Weg über
  ``xdg-desktop-portal`` wäre portabler, würde aber jedes Mal einen Dialog
  öffnen — auf einer Taste ist das der falsche Kompromiss.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import signal
import subprocess
import time
from concurrent.futures import TimeoutError as FuturesTimeout
from pathlib import Path

from dbus_next import BusType, Message, MessageType
from dbus_next.aio import MessageBus

log = logging.getLogger(__name__)

KGLOBALACCEL = "org.kde.kglobalaccel"
COMPONENT_IFACE = "org.kde.kglobalaccel.Component"

#: Komponenten, deren Kurzbefehle auf einer Taste Sinn ergeben — in dieser
#: Reihenfolge angeboten. Alles andere kommt danach, alphabetisch.
PREFERRED_COMPONENTS = ("kwin", "plasmashell", "org_kde_powerdevil", "ksmserver")

#: Systemkommandos, die ohne Desktop-Rückfrage laufen.
_SHELL_COMMANDS = {
    "lock": ["loginctl", "lock-session"],
    "suspend": ["systemctl", "suspend"],
    "hibernate": ["systemctl", "hibernate"],
    "reboot": ["systemctl", "reboot"],
    "poweroff": ["systemctl", "poweroff"],
    "screen_off": ["kscreen-doctor", "--dpms", "off"],
    "screen_on": ["kscreen-doctor", "--dpms", "on"],
}

#: Fensterbefehle für die wlroots-Compositoren.
#:
#: Anders als bei Plasma gibt es hier keine Liste zum Abfragen — Hyprland
#: und Sway führen aus, was man ihnen sagt, und kennen keinen Katalog
#: benannter Aktionen. Deshalb eine kuratierte Auswahl: dieselben Dinge,
#: die man auf einer Taste auch von KDE erwartet.
#:
#: Beide Sätze sind am 2026-08-22 gegen echte, verschachtelt gestartete
#: Compositoren geprüft: Sway 1.12 nahm alle 30 Befehle an, Hyprland
#: 0.56.2 alle bis auf zwei, die ein *schwebendes* Fenster voraussetzen —
#: das steht seither in ihrer Beschriftung. Was dennoch nicht ankommt,
#: meldet sich als Fehler der Aktion und bleibt nicht stumm.
_WLROOTS_WINDOW_COMMANDS = {
    "hyprland": [
        ("fullscreen, 0", "Vollbild"),
        ("fullscreen, 1", "Maximieren"),
        ("killactive", "Fenster schließen"),
        ("togglefloating", "Schwebend umschalten"),
        ("pin", "Anheften (nur schwebende Fenster)"),
        ("centerwindow", "Mittig setzen (nur schwebende Fenster)"),
        ("movewindow, l", "Fenster nach links"),
        ("movewindow, r", "Fenster nach rechts"),
        ("movewindow, u", "Fenster nach oben"),
        ("movewindow, d", "Fenster nach unten"),
        ("movecurrentworkspacetomonitor, +1", "Arbeitsfläche auf nächsten Bildschirm"),
        *[(f"workspace, {i}", f"Zur Arbeitsfläche {i}") for i in range(1, 11)],
        *[(f"movetoworkspace, {i}", f"Fenster auf Arbeitsfläche {i}") for i in range(1, 11)],
    ],
    "sway": [
        ("fullscreen toggle", "Vollbild"),
        ("kill", "Fenster schließen"),
        ("floating toggle", "Schwebend umschalten"),
        ("sticky toggle", "Auf allen Arbeitsflächen anheften"),
        ("layout toggle split", "Aufteilung umschalten"),
        ("move left", "Fenster nach links"),
        ("move right", "Fenster nach rechts"),
        ("move up", "Fenster nach oben"),
        ("move down", "Fenster nach unten"),
        ("move window to output right", "Fenster auf nächsten Bildschirm"),
        *[(f"workspace number {i}", f"Zur Arbeitsfläche {i}") for i in range(1, 11)],
        *[
            (f"move container to workspace number {i}", f"Fenster auf Arbeitsfläche {i}")
            for i in range(1, 11)
        ],
    ],
}

#: Bildschirme an und aus, je Compositor. ``kscreen-doctor`` steht dafür in
#: :data:`_SHELL_COMMANDS`, wirkt aber nur unter Plasma — am 2026-08-22 in
#: einer Sway-Sitzung gemessen: Rückgabewert 1, keine Ausgabe.
_WLROOTS_DPMS = {
    "hyprland": {"screen_off": "dpms off", "screen_on": "dpms on"},
    "sway": {"screen_off": "output * dpms off", "screen_on": "output * dpms on"},
}

#: Wie der Befehl beim jeweiligen Compositor abgeliefert wird.
_WLROOTS_ARGV = {
    "hyprland": lambda befehl: ["hyprctl", "dispatch", *befehl.split(", ", 1)],
    "sway": lambda befehl: ["swaymsg", befehl],
}

#: Kommandos, die Plasma erledigt — mit oder ohne Rückfrage.
_KDE_COMMANDS = {
    "logout": ("org.kde.Shutdown", "/Shutdown", "org.kde.Shutdown", "logout"),
    "logout_prompt": (
        "org.kde.LogoutPrompt",
        "/LogoutPrompt",
        "org.kde.LogoutPrompt",
        "promptAll",
    ),
    "reboot_prompt": (
        "org.kde.LogoutPrompt",
        "/LogoutPrompt",
        "org.kde.LogoutPrompt",
        "promptReboot",
    ),
    "poweroff_prompt": (
        "org.kde.LogoutPrompt",
        "/LogoutPrompt",
        "org.kde.LogoutPrompt",
        "promptShutDown",
    ),
}

#: Kürzere Muster werden abgelehnt. „a" oder „." trifft praktisch jeden
#: Prozess der Sitzung — und auf einer Taste merkt man den Vertipper erst,
#: wenn der Desktop weg ist.
MIN_PATTERN_LENGTH = 3

#: Mehr Treffer als das gilt als Fehlgriff, nicht als Absicht. Nachfragen
#: kann eine Taste nicht, also wird lieber nichts getan und gemeldet.
MAX_MATCHES = 8

#: Bildschirmfoto-Arten → Spectacle-Schalter.
SCREENSHOT_MODES = {
    "fullscreen": "--fullscreen",
    "current": "--current",
    "window": "--activewindow",
    "region": "--region",
}


class DesktopError(RuntimeError):
    """Die Aktion ließ sich auf diesem System nicht ausführen."""


class DesktopService:
    def __init__(self) -> None:
        self._bus: MessageBus | None = None
        self._lock = asyncio.Lock()
        #: Gesetzt von der Runtime — ohne das bleibt es beim Spectacle-Weg.
        self._session = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._screenshot_portal = None

    def bind_session(self, session, loop: asyncio.AbstractEventLoop) -> None:
        """Sagt dem Dienst, was die Sitzung kann und wo der Event-Loop läuft.

        Beides wird nur für den Portal-Weg gebraucht: Die Tastenaktionen
        laufen in einem Arbeitsthread, das Portal spricht aber asyncio.
        Ohne diesen Griff zurück in den Loop ließe sich von dort keine
        Portal-Anfrage stellen.
        """
        self._session = session
        self._loop = loop

    # -- Globale Kurzbefehle (Fenster, Arbeitsflächen, Plasma) -------------

    def _fenster_weg(self) -> str:
        """Worüber Fenster gesteuert werden — ``""``, wenn gar nicht.

        Entschieden hat das die Sitzungserkennung. Ohne sie (Tests, alte
        Aufrufe) bleibt es beim bisherigen Verhalten, also bei Plasma.
        """
        if self._session is None:
            return "kglobalaccel"
        from .session import WINDOW_CONTROL as CAP_WINDOW

        cap = self._session.caps.get(CAP_WINDOW)
        if cap is None:
            return "kglobalaccel"
        return cap.provider if cap.available else ""

    def _bildschirm_weg(self) -> str:
        """Worüber die Bildschirme geschaltet werden — ``""``, wenn gar nicht.

        Bewusst getrennt von :meth:`_fenster_weg`: Unter Plasma steuert
        kglobalaccel die Fenster, aber ``kscreen-doctor`` die Bildschirme.
        Die beiden Fähigkeiten laufen auseinander, und eine an der anderen
        aufzuhängen wäre nur zufällig richtig.
        """
        if self._session is None:
            return ""
        from .session import SCREEN_POWER as CAP_SCREEN

        cap = self._session.caps.get(CAP_SCREEN)
        return cap.provider if cap is not None and cap.available else ""

    async def list_components(self) -> list[dict[str, str]]:
        """Alle Programme, die globale Kurzbefehle anmelden.

        Auf Hyprland und Sway gibt es nichts zu wählen — dort ist der
        Compositor selbst die einzige Adresse. Die Liste hat dann genau
        einen Eintrag, damit die Oberfläche unverändert bleibt.
        """
        weg = self._fenster_weg()
        if weg in _WLROOTS_WINDOW_COMMANDS:
            return [{"value": weg, "label": weg.capitalize()}]
        if not weg:
            return []

        reply = await self._send(
            destination=KGLOBALACCEL,
            path="/kglobalaccel",
            interface="org.kde.KGlobalAccel",
            member="allComponents",
        )
        if reply is None or not reply.body:
            return []

        entries: list[dict[str, str]] = []
        for path in reply.body[0]:
            unique = str(path).rsplit("/", 1)[-1]
            friendly = await self._component_property(str(path), "friendlyName")
            entries.append({"value": unique, "label": friendly or unique})

        order = {name: i for i, name in enumerate(PREFERRED_COMPONENTS)}
        entries.sort(key=lambda e: (order.get(e["value"], len(order)), e["label"].lower()))
        return entries

    async def list_shortcuts(self, component: str) -> list[dict[str, str]]:
        """Die Kurzbefehle einer Komponente, mit lesbaren Namen."""
        weg = self._fenster_weg()
        if weg in _WLROOTS_WINDOW_COMMANDS:
            return [
                {"value": befehl, "label": beschriftung}
                for befehl, beschriftung in _WLROOTS_WINDOW_COMMANDS[weg]
            ]
        if not weg:
            return []

        if not component:
            component = "kwin"
        reply = await self._send(
            destination=KGLOBALACCEL,
            path=f"/component/{component}",
            interface=COMPONENT_IFACE,
            member="allShortcutInfos",
        )
        if reply is None or not reply.body:
            return []

        entries = []
        for info in reply.body[0]:
            # (uniqueName, friendlyName, componentUnique, componentFriendly, …)
            unique = str(info[0])
            friendly = str(info[1]) if len(info) > 1 and info[1] else unique
            entries.append({"value": unique, "label": friendly})
        entries.sort(key=lambda e: e["label"].lower())
        return entries

    async def invoke_shortcut(self, component: str, shortcut: str) -> None:
        """Löst einen globalen Kurzbefehl aus."""
        if not shortcut:
            raise DesktopError("Kein Kurzbefehl ausgewählt")

        weg = self._fenster_weg()
        if not weg:
            raise DesktopError(
                "Diese Sitzung erlaubt es nicht, Fenster von außen zu steuern"
            )
        if weg in _WLROOTS_ARGV:
            await self._wlroots_befehl(weg, shortcut)
            return

        reply = await self._send(
            destination=KGLOBALACCEL,
            path=f"/component/{component or 'kwin'}",
            interface=COMPONENT_IFACE,
            member="invokeShortcut",
            signature="s",
            body=[shortcut],
        )
        if reply is None:
            raise DesktopError(
                f"Kurzbefehl '{shortcut}' ließ sich nicht auslösen — "
                f"kennt '{component}' ihn noch?"
            )

    async def _wlroots_befehl(self, weg: str, befehl: str) -> None:
        """Schickt einen Fensterbefehl an Hyprland oder Sway.

        Beide melden Fehler nicht über den Rückgabewert, sondern im Text —
        ``hyprctl`` antwortet bei einem unbekannten Dispatcher mit
        ``Invalid dispatcher``, ``swaymsg`` liefert JSON mit
        ``"success": false``. Wer nur auf den Rückgabewert schaut, hält
        beides für erledigt.
        """
        argv = _WLROOTS_ARGV[weg](befehl)
        if shutil.which(argv[0]) is None:
            raise DesktopError(f"'{argv[0]}' ist nicht installiert")

        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, lambda: _run(argv))

        if result.returncode != 0:
            meldung = (result.stderr or result.stdout or "").strip()
            raise DesktopError(f"{argv[0]}: {meldung or result.returncode}")

        ausgabe = (result.stdout or "").strip()
        if weg == "hyprland" and ausgabe and ausgabe.lower() != "ok":
            raise DesktopError(f"hyprctl hat abgelehnt: {ausgabe}")

        if weg == "sway" and ausgabe:
            # ``swaymsg`` antwortet mit JSON: ``[{"success": true}]``. Nach
            # der Zeichenkette zu suchen wäre ein Ratespiel um Leerzeichen —
            # also richtig lesen und im Zweifel durchlassen, denn ein
            # unlesbares Format ist kein Beleg für einen Fehlschlag.
            try:
                antworten = json.loads(ausgabe)
            except (json.JSONDecodeError, TypeError):
                return
            if isinstance(antworten, dict):
                antworten = [antworten]
            for antwort in antworten if isinstance(antworten, list) else []:
                if isinstance(antwort, dict) and antwort.get("success") is False:
                    grund = antwort.get("error") or "ohne Angabe"
                    raise DesktopError(f"swaymsg hat abgelehnt: {grund}")

    async def _component_property(self, path: str, name: str) -> str:
        reply = await self._send(
            destination=KGLOBALACCEL,
            path=path,
            interface="org.freedesktop.DBus.Properties",
            member="Get",
            signature="ss",
            body=[COMPONENT_IFACE, name],
        )
        if reply is None or not reply.body:
            return ""
        value = reply.body[0]
        return str(getattr(value, "value", value) or "")

    # -- Sitzung -----------------------------------------------------------

    async def power(self, command: str) -> None:
        """Sperren, abmelden, ruhen, neu starten, ausschalten."""
        if command in _KDE_COMMANDS:
            destination, path, interface, member = _KDE_COMMANDS[command]
            reply = await self._send(
                destination=destination, path=path, interface=interface, member=member
            )
            if reply is None:
                raise DesktopError(f"Plasma hat '{command}' nicht angenommen")
            return

        # Bildschirme schalten geht auf wlroots-Compositoren über deren
        # eigene IPC — dieselbe, über die auch die Fensterbefehle laufen.
        if command in ("screen_off", "screen_on"):
            weg = self._bildschirm_weg()
            if weg in _WLROOTS_DPMS:
                await self._wlroots_befehl(weg, _WLROOTS_DPMS[weg][command])
                return

        argv = _SHELL_COMMANDS.get(command)
        if argv is None:
            raise DesktopError(f"Unbekanntes Systemkommando: {command}")
        if shutil.which(argv[0]) is None:
            raise DesktopError(f"'{argv[0]}' ist nicht installiert")

        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, lambda: _run(argv))
        if result.returncode != 0:
            raise DesktopError(
                f"{argv[0]} meldet Fehler: {result.stderr.strip() or result.returncode}"
            )

    # -- Bildschirmfoto ----------------------------------------------------

    def screenshot(
        self,
        mode: str = "fullscreen",
        *,
        directory: str = "",
        to_clipboard: bool = False,
        delay_ms: int = 0,
    ) -> str:
        """Macht ein Bildschirmfoto und liefert den Pfad (leer = Zwischenablage)."""
        if shutil.which("spectacle") is None:
            if self._nutzt_portal():
                return self._screenshot_ueber_portal(
                    mode, directory=directory, to_clipboard=to_clipboard, delay_ms=delay_ms
                )
            raise DesktopError("Spectacle ist nicht installiert")

        switch = SCREENSHOT_MODES.get(mode)
        if switch is None:
            raise DesktopError(f"Unbekannte Bildschirmfoto-Art: {mode}")

        argv = ["spectacle", "--background", "--nonotify", switch]
        if delay_ms > 0:
            argv += ["--delay", str(int(delay_ms))]

        target = ""
        if to_clipboard:
            argv.append("--copy-image")
        else:
            folder = Path(directory).expanduser() if directory else _pictures_dir()
            folder.mkdir(parents=True, exist_ok=True)
            target = str(folder / time.strftime("Bildschirmfoto_%Y-%m-%d_%H-%M-%S.png"))
            argv += ["--output", target]

        # Bereichsauswahl wartet auf den Benutzer — dafür großzügig Zeit.
        timeout = 120 if mode == "region" else 20
        result = _run(argv, timeout=timeout)
        if result.returncode != 0:
            raise DesktopError(
                f"Spectacle meldet Fehler: {result.stderr.strip() or result.returncode}"
            )
        return target

    def _nutzt_portal(self) -> bool:
        """Soll das Bildschirmfoto übers Portal gehen?"""
        if self._session is None or self._loop is None:
            return False
        from .session import SCREENSHOT as CAP_SCREENSHOT

        cap = self._session.caps.get(CAP_SCREENSHOT)
        return cap is not None and cap.available and cap.provider == "portal"

    def _screenshot_ueber_portal(
        self, mode: str, *, directory: str, to_clipboard: bool, delay_ms: int
    ) -> str:
        """Der Weg ohne Spectacle. Kann weniger — siehe :class:`ScreenshotPortal`."""
        from .portal import PortalError, ScreenshotPortal

        if mode not in SCREENSHOT_MODES:
            raise DesktopError(f"Unbekannte Bildschirmfoto-Art: {mode}")
        if to_clipboard:
            raise DesktopError(
                "In die Zwischenablage geht nur mit Spectacle — ohne das legt "
                "das Bildschirmfoto eine Datei an"
            )

        # Die Verzögerung kennt das Portal nicht; hier im Arbeitsthread zu
        # warten ist harmlos, der Event-Loop läuft davon unberührt weiter.
        if delay_ms > 0:
            time.sleep(delay_ms / 1000)

        ordner = Path(directory).expanduser() if directory else _pictures_dir()
        ziel = ordner / time.strftime("Bildschirmfoto_%Y-%m-%d_%H-%M-%S.png")

        if self._screenshot_portal is None:
            self._screenshot_portal = ScreenshotPortal()

        # Aus dem Arbeitsthread in den Event-Loop und zurück. Das Warten
        # blockiert nur diesen Thread — genau wie der Spectacle-Aufruf
        # nebenan, der auf einen Unterprozess wartet.
        aufgabe = asyncio.run_coroutine_threadsafe(
            self._screenshot_portal.capture(mode, ziel), self._loop
        )
        zeit = 200 if mode in ScreenshotPortal.INTERAKTIV else 30
        try:
            return aufgabe.result(timeout=zeit)
        except PortalError as exc:
            raise DesktopError(str(exc)) from exc
        except FuturesTimeout as exc:
            aufgabe.cancel()
            raise DesktopError("Das Portal hat nicht rechtzeitig geantwortet") from exc

    # -- Programme ---------------------------------------------------------

    @staticmethod
    def close_application(pattern: str, *, force: bool = False) -> int:
        """Beendet Prozesse, deren Name auf ``pattern`` passt.

        Erst gesucht, dann beendet — und dazwischen gezählt: Ein zu breites
        Muster (``a``, ``.``) träfe reihenweise Prozesse der Sitzung, und auf
        einer Taste fällt das erst auf, wenn die Sitzung weg ist. Deshalb
        eine Mindestlänge und eine Obergrenze für die Treffer; nachfragen
        kann eine Taste nicht.

        Der eigene Prozess wird dabei nie beendet — sonst schösse sich die
        App mit einem Muster wie „deck" selbst ab.
        """
        pattern = pattern.strip()
        if not pattern:
            raise DesktopError("Kein Programm angegeben")
        if len(pattern) < MIN_PATTERN_LENGTH:
            raise DesktopError(
                f"Muster '{pattern}' ist zu kurz (mindestens {MIN_PATTERN_LENGTH} "
                "Zeichen) — es würde zu viele Prozesse treffen"
            )
        if shutil.which("pgrep") is None:
            raise DesktopError("'pgrep' ist nicht installiert (Paket procps-ng)")

        # -f: auch auf die Kommandozeile schauen, sonst findet man Programme
        # nicht, die über einen Interpreter laufen (Electron, Python).
        result = _run(["pgrep", "-f", pattern])
        if result.returncode not in (0, 1):
            raise DesktopError(f"pgrep meldet Fehler: {result.returncode}")

        own = {os.getpid(), os.getppid()}
        pids = [
            pid
            for pid in (int(line) for line in result.stdout.split() if line.isdigit())
            if pid not in own
        ]
        if not pids:
            return 0
        if len(pids) > MAX_MATCHES:
            raise DesktopError(
                f"Muster '{pattern}' trifft {len(pids)} Prozesse — das sieht nach "
                "einem Versehen aus. Bitte genauer angeben."
            )

        signal_number = signal.SIGKILL if force else signal.SIGTERM
        closed = 0
        for pid in pids:
            try:
                os.kill(pid, signal_number)
                closed += 1
            except ProcessLookupError:
                pass  # war schon weg
            except PermissionError:
                log.debug("Kein Recht, Prozess %d zu beenden", pid)
        return closed

    # -- D-Bus -------------------------------------------------------------

    async def _connect(self) -> MessageBus | None:
        if self._bus is not None:
            return self._bus
        async with self._lock:
            if self._bus is None:
                try:
                    self._bus = await MessageBus(bus_type=BusType.SESSION).connect()
                except Exception as exc:
                    log.debug("Sitzungsbus nicht erreichbar: %s", exc)
                    return None
        return self._bus

    async def _send(
        self,
        *,
        destination: str,
        path: str,
        interface: str,
        member: str,
        signature: str = "",
        body: list | None = None,
    ) -> Message | None:
        bus = await self._connect()
        if bus is None:
            return None
        try:
            reply = await asyncio.wait_for(
                bus.call(
                    Message(
                        destination=destination,
                        path=path,
                        interface=interface,
                        member=member,
                        signature=signature,
                        body=body or [],
                    )
                ),
                timeout=6,
            )
        except Exception as exc:
            log.debug("D-Bus-Aufruf %s.%s fehlgeschlagen: %s", interface, member, exc)
            return None
        if reply is None or reply.message_type is MessageType.ERROR:
            if reply is not None:
                log.debug("D-Bus-Fehler bei %s: %s", member, reply.error_name)
            return None
        return reply


def _run(argv: list[str], timeout: int = 15) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            argv, capture_output=True, text=True, timeout=timeout, check=False
        )
    except subprocess.TimeoutExpired as exc:
        raise DesktopError(f"'{argv[0]}' hat nicht geantwortet") from exc
    except OSError as exc:
        raise DesktopError(f"'{argv[0]}' ließ sich nicht starten: {exc}") from exc


def _pictures_dir() -> Path:
    """Der Bilderordner des Benutzers, notfalls ``~/Pictures``."""
    if shutil.which("xdg-user-dir"):
        result = _run(["xdg-user-dir", "PICTURES"], timeout=5)
        value = result.stdout.strip()
        if value:
            return Path(value) / "Screenshots"
    return Path.home() / "Pictures" / "Screenshots"
