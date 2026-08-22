"""Zugang zu ``xdg-desktop-portal``.

Die Portale sind der einzige Weg, bestimmte Dinge desktopübergreifend zu
erledigen: einen globalen Kurzbefehl reservieren, ein Bildschirmfoto
auslösen. Wo Plasma eigene Schnittstellen hat, sind die oft besser — aber
sie gibt es eben nur unter Plasma.

**Das Antwortspiel.** Portal-Methoden antworten nicht mit dem Ergebnis,
sondern mit dem Objektpfad einer *Anfrage*; das Ergebnis kommt später als
``Response``-Signal auf diesem Pfad. Zwei Fallstricke stecken darin:

1. Zwischen Methodenaufruf und Signalregel liegt ein Zeitfenster, in dem
   die Antwort schon da sein und verlorengehen kann. Deshalb wird der
   Antwortpfad *vorher* aus dem eigenen Busnamen und dem selbst gewählten
   ``handle_token`` errechnet und die Regel gesetzt, bevor der Aufruf
   herausgeht — genau so sieht es die Spezifikation vor.
2. Wer nicht auf das Signal wartet, sondern nur auf die Methodenantwort,
   hält eine leere Hülle in der Hand. Das ist der häufigste Fehler beim
   ersten Portal-Einsatz.

**Sitzungen.** Kurzbefehle hängen an einer Portal-*Sitzung*. Fällt die weg
— Verbindungsabbruch, Programmende —, sind auch die Kurzbefehle weg. Das
ist so gewollt und der Grund, warum hier eine Verbindung dauerhaft offen
bleibt, statt sie je Aufruf auf- und abzubauen.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import shutil
from collections.abc import Callable
from pathlib import Path
from urllib.parse import unquote, urlparse

from dbus_next import BusType, Message, MessageType, Variant
from dbus_next.aio import MessageBus

log = logging.getLogger(__name__)

PORTAL_NAME = "org.freedesktop.portal.Desktop"
PORTAL_PATH = "/org/freedesktop/portal/desktop"
REQUEST_IFACE = "org.freedesktop.portal.Request"
SESSION_IFACE = "org.freedesktop.portal.Session"

GLOBAL_SHORTCUTS_IFACE = "org.freedesktop.portal.GlobalShortcuts"
SCREENSHOT_IFACE = "org.freedesktop.portal.Screenshot"

#: So lange warten wir auf eine Portal-Antwort, die *ohne* Rückfrage
#: auskommt. Großzügig, weil am anderen Ende ein Desktop-Dienst steht, der
#: unter Last auch mal ein paar Sekunden braucht.
ANTWORT_TIMEOUT_S = 15.0

#: So lange, wenn ein Dialog erscheint, den der Benutzer beantworten muss.
DIALOG_TIMEOUT_S = 180.0

#: Antwortcodes des Portals.
ERFOLG = 0
ABGEBROCHEN = 1
FEHLGESCHLAGEN = 2


class PortalError(RuntimeError):
    """Das Portal hat nicht geliefert."""


def trigger_aus_combo(combo: str) -> str:
    """Rechnet ``"ctrl+alt+d"`` in die Schreibweise der Shortcuts-Spec um.

    Das Portal erwartet Modifier in Großbuchstaben und die Meta-Taste unter
    dem Namen ``LOGO``. Anders als bei kglobalaccel ist das Ergebnis nur ein
    *Wunsch*: Welche Kombination am Ende gilt, entscheidet der Desktop
    zusammen mit dem Benutzer.
    """
    from .input import parse_combo

    namen = {"ctrl": "CTRL", "shift": "SHIFT", "alt": "ALT", "super": "LOGO"}

    modifiers, key = parse_combo(combo)
    if not key:
        raise PortalError("Es fehlt die eigentliche Taste")

    teile = []
    for modifier in modifiers:
        name = namen.get(modifier)
        if name is None:
            raise PortalError(f"'{modifier}' geht als globaler Kurzbefehl nicht")
        teile.append(name)

    teile.append(key)
    return "+".join(teile)


class PortalConnection:
    """Eine offene Verbindung zum Portal, die das Antwortspiel beherrscht."""

    def __init__(self) -> None:
        self._bus: MessageBus | None = None
        #: Antwortpfad → Warteschlange, in die das ``Response``-Signal fällt.
        self._offen: dict[str, asyncio.Queue] = {}
        #: Zusätzliche Signalhörer, die nicht zum Anfrage-Spiel gehören
        #: (``Activated`` etwa) — Schnittstelle, Mitglied → Rückruf.
        self._hoerer: dict[tuple[str, str], Callable[[Message], None]] = {}
        self._zaehler = 0

    @property
    def connected(self) -> bool:
        return self._bus is not None and self._bus.connected

    async def connect(self) -> bool:
        if self.connected:
            return True
        self._bus = None
        try:
            bus = await MessageBus(bus_type=BusType.SESSION).connect()
        except Exception as exc:  # noqa: BLE001
            log.info("Sitzungsbus nicht erreichbar: %s", exc)
            return False

        bus.add_message_handler(self._on_message)
        self._bus = bus
        return True

    async def disconnect(self) -> None:
        if self._bus is not None:
            with contextlib.suppress(Exception):
                self._bus.disconnect()
        self._bus = None
        self._offen.clear()

    def listen(self, interface: str, member: str, rueckruf: Callable[[Message], None]) -> None:
        """Auf ein Portal-Signal hören, das nicht zu einer Anfrage gehört."""
        self._hoerer[(interface, member)] = rueckruf

    # -- Nachrichten -------------------------------------------------------

    def _on_message(self, msg: Message) -> None:
        if msg.message_type is not MessageType.SIGNAL:
            return

        if msg.interface == REQUEST_IFACE and msg.member == "Response":
            warteschlange = self._offen.get(msg.path or "")
            if warteschlange is not None:
                warteschlange.put_nowait(msg.body)
            return

        rueckruf = self._hoerer.get((msg.interface or "", msg.member or ""))
        if rueckruf is not None:
            rueckruf(msg)

    async def _add_match(self, regel: str) -> bool:
        if self._bus is None:
            return False
        try:
            await self._bus.call(
                Message(
                    destination="org.freedesktop.DBus",
                    path="/org/freedesktop/DBus",
                    interface="org.freedesktop.DBus",
                    member="AddMatch",
                    signature="s",
                    body=[regel],
                )
            )
            return True
        except Exception as exc:  # noqa: BLE001
            log.info("Signalregel '%s' abgelehnt: %s", regel, exc)
            return False

    async def match_signal(self, interface: str, member: str) -> bool:
        return await self._add_match(
            f"type='signal',interface='{interface}',member='{member}'"
        )

    # -- Anfragen ----------------------------------------------------------

    def _token(self, zweck: str) -> str:
        self._zaehler += 1
        return f"deckswitch_{zweck}_{self._zaehler}"

    def _antwortpfad(self, token: str) -> str:
        """Wo die Antwort auf diesen Token erscheinen wird.

        Der Pfad ist vorhersagbar — genau dafür ist er so gebaut. Nur so
        lässt sich die Signalregel setzen, *bevor* der Aufruf herausgeht.
        """
        if self._bus is None:
            raise PortalError("Keine Verbindung zum Portal")
        sender = self._bus.unique_name[1:].replace(".", "_")
        return f"{PORTAL_PATH}/request/{sender}/{token}"

    async def request(
        self,
        interface: str,
        member: str,
        signature: str,
        body: list,
        *,
        zweck: str,
        optionen: dict[str, Variant] | None = None,
        timeout_s: float = ANTWORT_TIMEOUT_S,
    ) -> dict:
        """Eine Portal-Methode rufen und auf ihr Ergebnis warten.

        ``optionen`` wird um den ``handle_token`` ergänzt und als letztes
        Argument angehängt — alle Portal-Methoden enden so.
        """
        if self._bus is None:
            raise PortalError("Keine Verbindung zum Portal")

        token = self._token(zweck)
        pfad = self._antwortpfad(token)

        warteschlange: asyncio.Queue = asyncio.Queue()
        self._offen[pfad] = warteschlange
        try:
            if not await self._add_match(
                f"type='signal',interface='{REQUEST_IFACE}',path='{pfad}'"
            ):
                raise PortalError("Signalregel für die Antwort ließ sich nicht setzen")

            vollstaendig = dict(optionen or {})
            vollstaendig["handle_token"] = Variant("s", token)

            antwort = await self._bus.call(
                Message(
                    destination=PORTAL_NAME,
                    path=PORTAL_PATH,
                    interface=interface,
                    member=member,
                    signature=signature,
                    body=[*body, vollstaendig],
                )
            )
            if antwort is None or antwort.message_type is MessageType.ERROR:
                grund = ""
                if antwort is not None and antwort.body:
                    grund = str(antwort.body[0])
                raise PortalError(f"{member} abgelehnt: {grund or 'ohne Angabe'}")

            try:
                async with asyncio.timeout(timeout_s):
                    code, ergebnis = await warteschlange.get()
            except asyncio.TimeoutError as exc:
                raise PortalError(f"{member}: keine Antwort binnen {timeout_s:.0f} s") from exc

            if code == ABGEBROCHEN:
                raise PortalError(f"{member} wurde abgebrochen")
            if code != ERFOLG:
                raise PortalError(f"{member} fehlgeschlagen (Code {code})")

            return {k: v.value if isinstance(v, Variant) else v for k, v in ergebnis.items()}
        finally:
            self._offen.pop(pfad, None)

    async def call(
        self, interface: str, member: str, signature: str = "", body: list | None = None,
        *, path: str = PORTAL_PATH,
    ) -> Message | None:
        """Ein gewöhnlicher Aufruf ohne Antwortspiel (``Session.Close`` etwa)."""
        if self._bus is None:
            return None
        try:
            return await self._bus.call(
                Message(
                    destination=PORTAL_NAME,
                    path=path,
                    interface=interface,
                    member=member,
                    signature=signature,
                    body=body or [],
                )
            )
        except Exception as exc:  # noqa: BLE001
            log.info("%s.%s: %s", interface, member, exc)
            return None


# ==========================================================================
# Globale Kurzbefehle
# ==========================================================================


class GlobalShortcutsPortal:
    """Kurzbefehle über ``org.freedesktop.portal.GlobalShortcuts``.

    Der Unterschied zu kglobalaccel ist keine Kleinigkeit und soll hier
    festgehalten sein: Das Portal nimmt die gewünschte Kombination als
    *Vorschlag*, zeigt dem Benutzer einen Dialog und entscheidet selbst.
    Was am Ende gilt, steht in ``trigger_description`` — und genau das
    zeigen wir dann auch an, statt weiter die gewünschte Kombination zu
    behaupten.

    Alle Kurzbefehle hängen an *einer* Sitzung, und ``BindShortcuts``
    lässt sich je Sitzung nur einmal sinnvoll rufen. Ändert sich die Liste
    der Decks, wird die Sitzung darum verworfen und neu aufgebaut — mit
    einem erneuten Dialog. Deshalb passiert das nur, wenn sich wirklich
    etwas geändert hat.
    """

    def __init__(self, on_activated: Callable[[str], None]) -> None:
        self._conn = PortalConnection()
        self._on_activated = on_activated
        self._session: str | None = None
        #: Was zuletzt gebunden wurde — Deck-Schlüssel → (Kombination, Name).
        self._gebunden: dict[str, tuple[str, str]] = {}
        #: Deck-Schlüssel → Kombination, wie der Desktop sie tatsächlich
        #: vergeben hat. Kann von der gewünschten abweichen.
        self.vergeben: dict[str, str] = {}

    # -- Sitzung -----------------------------------------------------------

    async def _ensure_session(self) -> str:
        if self._session is not None and self._conn.connected:
            return self._session

        if not await self._conn.connect():
            raise PortalError("Sitzungsbus nicht erreichbar")

        await self._conn.match_signal(GLOBAL_SHORTCUTS_IFACE, "Activated")
        self._conn.listen(GLOBAL_SHORTCUTS_IFACE, "Activated", self._on_signal)

        token = f"deckswitch_gs_{id(self)}"
        ergebnis = await self._conn.request(
            GLOBAL_SHORTCUTS_IFACE,
            "CreateSession",
            "a{sv}",
            [],
            zweck="createsession",
            optionen={"session_handle_token": Variant("s", token)},
        )
        handle = ergebnis.get("session_handle")
        if not handle:
            raise PortalError("Das Portal hat keine Sitzung geliefert")
        self._session = str(handle)
        return self._session

    async def _close_session(self) -> None:
        if self._session is not None:
            await self._conn.call(SESSION_IFACE, "Close", path=self._session)
        self._session = None
        self._gebunden.clear()
        self.vergeben.clear()

    async def stop(self) -> None:
        await self._close_session()
        await self._conn.disconnect()

    # -- Binden ------------------------------------------------------------

    async def sync(self, gewuenscht: dict[str, tuple[str, str]]) -> dict[str, str]:
        """Bringt die Bindungen auf den Stand. Liefert Deck → Fehlergrund.

        Ein leeres Ergebnis heißt: alles gebunden.
        """
        if gewuenscht == self._gebunden:
            return {}

        if not gewuenscht:
            await self._close_session()
            return {}

        # Neu binden heißt: Sitzung weg, Sitzung neu. Das Portal kennt kein
        # Nachbinden — ein zweites ``BindShortcuts`` auf derselben Sitzung
        # ist laut Spezifikation nicht vorgesehen.
        await self._close_session()

        try:
            session = await self._ensure_session()
        except PortalError as exc:
            return dict.fromkeys(gewuenscht, str(exc))

        eintraege = []
        gruende: dict[str, str] = {}
        for deck_key, (combo, name) in sorted(gewuenscht.items()):
            try:
                trigger = trigger_aus_combo(combo)
            except PortalError as exc:
                gruende[deck_key] = str(exc)
                continue
            eintraege.append(
                [
                    f"overlay:{deck_key}",
                    {
                        "description": Variant("s", f"Overlay „{name}“ umschalten"),
                        "preferred_trigger": Variant("s", trigger),
                    },
                ]
            )

        if not eintraege:
            return gruende

        try:
            ergebnis = await self._conn.request(
                GLOBAL_SHORTCUTS_IFACE,
                "BindShortcuts",
                "oa(sa{sv})sa{sv}",
                [session, eintraege, ""],
                zweck="bind",
                # Hier erscheint der Dialog — der Benutzer muss ihn
                # beantworten, und das darf dauern.
                timeout_s=DIALOG_TIMEOUT_S,
            )
        except PortalError as exc:
            await self._close_session()
            for deck_key in gewuenscht:
                gruende.setdefault(deck_key, str(exc))
            return gruende

        self._gebunden = dict(gewuenscht)
        # Ob zu jedem Kurzbefehl eine Beschreibung zurückkam, ist kein
        # Gütezeichen — manche Desktops liefern sie schlicht nicht mit.
        # Gebunden ist gebunden.
        self._merke_vergeben(ergebnis)
        return gruende

    def _merke_vergeben(self, ergebnis: dict) -> None:
        """Liest aus der Antwort, welche Kombination wirklich vergeben wurde."""
        self.vergeben.clear()
        for eintrag in ergebnis.get("shortcuts") or []:
            try:
                shortcut_id, daten = eintrag[0], eintrag[1]
            except (IndexError, TypeError):
                continue
            if not str(shortcut_id).startswith("overlay:"):
                continue
            beschreibung = daten.get("trigger_description")
            if isinstance(beschreibung, Variant):
                beschreibung = beschreibung.value
            if beschreibung:
                self.vergeben[str(shortcut_id).split(":", 1)[1]] = str(beschreibung)

    # -- Auslösen ----------------------------------------------------------

    def _on_signal(self, msg: Message) -> None:
        # Activated(o session_handle, s shortcut_id, t timestamp, a{sv} options)
        if len(msg.body) < 2:
            return
        shortcut_id = str(msg.body[1])
        if not shortcut_id.startswith("overlay:"):
            return
        self._on_activated(shortcut_id.split(":", 1)[1])


# ==========================================================================
# Bildschirmfoto
# ==========================================================================


class ScreenshotPortal:
    """Bildschirmfotos über ``org.freedesktop.portal.Screenshot``.

    Der Zweitweg für alles, wo Spectacle fehlt. Er kann weniger, und das
    ehrlich zu benennen ist wichtiger, als es zu verstecken:

    * Das Portal kennt nur *ganzer Bildschirm* und *interaktiv*. Ein
      bestimmtes Fenster oder einen Bereich kann es nicht direkt aufnehmen
      — bei beidem übernimmt das Auswahlwerkzeug des Desktops, und der
      Benutzer klickt selbst.
    * In die Zwischenablage legen kann es gar nichts.
    * Eine Verzögerung kennt es nicht; die warten wir selbst ab.

    Das Ergebnis landet zuerst in einem Ordner des Portals. Wir holen es
    von dort ab, denn dieser Ordner ist nicht der, in dem der Benutzer
    seine Bilder sucht.
    """

    #: Welche unserer Aufnahmearten das Auswahlwerkzeug des Desktops braucht.
    INTERAKTIV = {"current", "window", "region"}

    def __init__(self) -> None:
        self._conn = PortalConnection()

    async def stop(self) -> None:
        await self._conn.disconnect()

    async def capture(self, mode: str, ziel: Path) -> str:
        """Nimmt auf und legt das Bild unter ``ziel`` ab. Liefert den Pfad."""
        if not await self._conn.connect():
            raise PortalError("Sitzungsbus nicht erreichbar")

        interaktiv = mode in self.INTERAKTIV
        ergebnis = await self._conn.request(
            SCREENSHOT_IFACE,
            "Screenshot",
            "sa{sv}",
            [""],
            zweck="screenshot",
            optionen={
                "interactive": Variant("b", interaktiv),
                "modal": Variant("b", True),
            },
            # Interaktiv wartet auf den Benutzer, das darf dauern. Ohne
            # Auswahl fragt das Portal beim ersten Mal einmalig um
            # Erlaubnis und merkt sich die Antwort danach.
            timeout_s=DIALOG_TIMEOUT_S if interaktiv else ANTWORT_TIMEOUT_S,
        )

        uri = ergebnis.get("uri")
        if not uri:
            raise PortalError("Das Portal hat kein Bild geliefert")

        quelle = Path(unquote(urlparse(str(uri)).path))
        if not quelle.is_file():
            raise PortalError(f"Das Bild des Portals fehlt: {quelle}")

        ziel.parent.mkdir(parents=True, exist_ok=True)
        # Verschieben, nicht kopieren: Was das Portal anlegt, räumt es nicht
        # wieder weg — ohne das bliebe von jeder Aufnahme eine zweite Datei
        # zurück, die niemand je zu sehen bekommt.
        try:
            shutil.move(str(quelle), str(ziel))
        except OSError as exc:
            raise PortalError(f"Bild ließ sich nicht ablegen: {exc}") from exc
        return str(ziel)
