"""Globale Kurzbefehle — ein Overlay per Tastendruck holen.

Ein virtuelles Deck hat kein Gehäuse, nach dem man greifen kann. Ohne
Kurzbefehl bleibt nur der Umweg über die Oberfläche oder eine Taste auf
einem anderen Deck — und wer nur ein virtuelles Deck hat, hat diesen
anderen Weg gar nicht. Deshalb bekommt jedes Overlay-Deck eine
Tastenkombination, die es holt und wieder wegschickt.

**Warum ``kglobalaccel`` und kein Mitlesen der Tastatur.** Gemessen am
2026-08-19 in einer laufenden Plasma-Sitzung: Plasma nimmt eine Anmeldung
über D-Bus an und meldet den Tastendruck als Signal zurück. Der Weg hat
drei Vorteile gegenüber ``/dev/input`` mitzulesen:

* Wir sehen **nur die eine Kombination**, nicht jeden Anschlag.
* Der Kurzbefehl steht danach in den KDE-Systemeinstellungen unter
  „DECK//SWITCH" — man kann ihn dort ändern oder wegnehmen.
* Ist die Kombination schon vergeben, sagt KDE das sofort, statt sie
  stillschweigend doppelt auszulösen.

Der Preis ist die Bindung an Plasma. Das ist hier keine Einschränkung:
Das Overlay selbst hängt ohnehin an ``zwlr_layer_shell_v1``, und
Zielplattform ist Plasma unter Wayland.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging

from dbus_next import BusType, Message, MessageType
from dbus_next.aio import MessageBus

from .. import events as ev
from .input import NAMED_KEYS, parse_combo

log = logging.getLogger(__name__)

KGLOBALACCEL = "org.kde.kglobalaccel"
KGLOBALACCEL_PATH = "/kglobalaccel"
KGLOBALACCEL_IFACE = "org.kde.KGlobalAccel"
COMPONENT_IFACE = "org.kde.kglobalaccel.Component"

#: Unter diesem Namen stehen unsere Kurzbefehle in den Systemeinstellungen.
COMPONENT = "deckswitch"
COMPONENT_FRIENDLY = "DECK//SWITCH"

#: ``SetPresent | NoAutoloading``: Die Kombination gilt ab sofort, und KDE
#: soll sie nicht beim nächsten Start aus seiner eigenen Datei wieder
#: hervorholen — maßgeblich ist unsere Konfiguration.
SET_FLAGS = 2 | 4

#: Qt-Modifier, wie ``setShortcut`` sie im Tastencode erwartet.
_QT_MODIFIERS = {
    "shift": 0x02000000,
    "ctrl": 0x04000000,
    "alt": 0x08000000,
    "super": 0x10000000,
}
_QT_KEYPAD = 0x20000000

#: Tastennamen aus :mod:`.input` (``KEY_ENTER`` …) auf Qt-Codes. Der Umweg
#: über die evdev-Namen spart eine zweite Aliasliste: Wie eine Taste in
#: einer Kombination heißen darf — ``entf`` wie ``delete`` — steht damit
#: weiterhin an genau einer Stelle.
_EVDEV_TO_QT = {
    "KEY_ENTER": 0x01000004,
    "KEY_TAB": 0x01000001,
    "KEY_SPACE": 0x20,
    "KEY_BACKSPACE": 0x01000003,
    "KEY_DELETE": 0x01000007,
    "KEY_ESC": 0x01000000,
    "KEY_UP": 0x01000013,
    "KEY_DOWN": 0x01000015,
    "KEY_LEFT": 0x01000012,
    "KEY_RIGHT": 0x01000014,
    "KEY_HOME": 0x01000010,
    "KEY_END": 0x01000011,
    "KEY_PAGEUP": 0x01000016,
    "KEY_PAGEDOWN": 0x01000017,
    "KEY_INSERT": 0x01000006,
    "KEY_SYSRQ": 0x01000009,
    "KEY_PAUSE": 0x01000008,
    "KEY_COMPOSE": 0x01000055,
    "KEY_CAPSLOCK": 0x01000024,
    "KEY_NUMLOCK": 0x01000025,
    "KEY_SCROLLLOCK": 0x01000026,
}
#: Qt zählt die Funktionstasten ab ``Key_F1`` durch.
_EVDEV_TO_QT.update({f"KEY_F{i}": 0x0100002F + i for i in range(1, 36)})


class ShortcutError(RuntimeError):
    """Diese Kombination lässt sich nicht als Kurzbefehl anmelden."""


def qt_keycode(combo: str) -> int:
    """Rechnet ``"ctrl+alt+d"`` in den Tastencode um, den Qt/KDE erwartet.

    Der Code ist eine einzige Zahl: Modifier-Bits plus Taste. Genau so
    liegt er auch in ``kglobalshortcutsrc``.
    """
    modifiers, key = parse_combo(combo)
    if not key:
        raise ShortcutError("Es fehlt die eigentliche Taste")

    code = 0
    for modifier in modifiers:
        bit = _QT_MODIFIERS.get(modifier)
        if bit is None:
            # AltGr ist der einzige Fall: Der ist bei Qt keine
            # Modifier-Stufe, die ein globaler Kurzbefehl abbilden kann.
            raise ShortcutError(f"'{modifier}' geht als globaler Kurzbefehl nicht")
        code |= bit

    return code | _key_code(key)


def _key_code(key: str) -> int:
    name = key.lower()

    evdev = NAMED_KEYS.get(name)
    if evdev is not None and evdev in _EVDEV_TO_QT:
        return _EVDEV_TO_QT[evdev]

    # Ziffernblock: dieselbe Taste, aber mit gesetztem Keypad-Bit — sonst
    # löste die Kombination auch über die Zifferntastenreihe aus.
    if name.startswith("kp") and len(name) == 3 and name[2].isdigit():
        return ord(name[2]) | _QT_KEYPAD
    if name == "kpenter":
        return 0x01000005 | _QT_KEYPAD

    # Alles, was ein Zeichen ist: Qt nimmt dafür den Codepunkt des
    # Großbuchstabens — ``d`` → ``Key_D``, ``ö`` → ``Key_Odiaeresis``.
    if len(name) == 1 and ord(name.upper()) < 0x100:
        return ord(name.upper())

    raise ShortcutError(f"Taste '{key}' ist nicht bekannt")


class ShortcutService:
    """Meldet die Overlay-Kurzbefehle bei Plasma an und hört auf sie."""

    def __init__(self, runtime) -> None:
        self.runtime = runtime
        self._bus: MessageBus | None = None
        #: Deck-Schlüssel → (Kombination, Deckname). Der Name gehört dazu,
        #: weil er in den KDE-Systemeinstellungen steht: Wird ein Deck
        #: umbenannt, muss die Aktion dort mit umziehen.
        self._angemeldet: dict[str, tuple[str, str]] = {}
        #: Deck-Schlüssel → warum es *nicht* geklappt hat. Leer = alles gut.
        self._gruende: dict[str, str] = {}
        self._lock = asyncio.Lock()

    # -- Zustand -----------------------------------------------------------

    def reason(self, deck_key: str) -> str:
        """Was der Kurzbefehl dieses Decks gerade verhindert. Leer = nichts."""
        return self._gruende.get(deck_key, "")

    def is_active(self, deck_key: str) -> bool:
        return deck_key in self._angemeldet

    # -- Anmelden ----------------------------------------------------------

    async def sync(self) -> None:
        """Bringt die Anmeldungen auf den Stand der Konfiguration.

        Wird nach jeder Änderung an den Decks gerufen — hinzugekommene
        Kombinationen werden angemeldet, entfernte wieder abgemeldet.
        """
        async with self._lock:
            gewuenscht = {
                deck.key: (deck.binding.overlay_hotkey.strip(), deck.label)
                for deck in self.runtime.decks.values()
                if deck.binding.is_overlay and deck.binding.overlay_hotkey.strip()
            }

            # Ohne Kurzbefehl und ohne Verbindung gibt es nichts zu tun —
            # dann bauen wir auch keine auf.
            if not gewuenscht and self._bus is None:
                self._gruende.clear()
                return

            bus = await self._connect()
            if bus is None:
                self._angemeldet.clear()
                grund = "KDE-Kurzbefehle sind nicht erreichbar (kglobalaccel läuft nicht)"
                self._gruende = dict.fromkeys(gewuenscht, grund)
                return

            for key in list(self._angemeldet):
                if self._angemeldet[key] != gewuenscht.get(key):
                    await self._abmelden(key)

            self._gruende = {k: v for k, v in self._gruende.items() if k in gewuenscht}
            for key, (combo, name) in gewuenscht.items():
                if self._angemeldet.get(key) == (combo, name):
                    continue
                await self._anmelden(key, combo, name)

    async def stop(self) -> None:
        """Alles abmelden — sonst blieben tote Einträge in Plasma stehen."""
        async with self._lock:
            for key in list(self._angemeldet):
                await self._abmelden(key)
            if self._bus is not None:
                with contextlib.suppress(Exception):
                    self._bus.disconnect()
                self._bus = None

    async def _anmelden(self, deck_key: str, combo: str, name: str) -> None:
        try:
            code = qt_keycode(combo)
        except ShortcutError as exc:
            self._gruende[deck_key] = str(exc)
            return

        # Erst fragen, dann nehmen. Gemessen am 2026-08-19: ``setShortcut``
        # meldet keinen Konflikt, sondern reißt die Kombination an sich —
        # im Versuch hätte es uns anstandslos Meta+D von KWin überschrieben.
        # Wer hier eine Taste belegt, will aber nicht heimlich seinem
        # Fenstermanager etwas wegnehmen.
        halter = await self._halter(code)
        if halter is not None:
            self._gruende[deck_key] = f"'{combo}' ist schon vergeben: {halter}"
            return

        aktion = self._aktion(deck_key, name)
        antwort = await self._ruf(
            KGLOBALACCEL_PATH, KGLOBALACCEL_IFACE, "doRegister", "as", [aktion]
        )
        if antwort is None:
            self._gruende[deck_key] = "Plasma hat die Anmeldung abgelehnt"
            return

        antwort = await self._ruf(
            KGLOBALACCEL_PATH,
            KGLOBALACCEL_IFACE,
            "setShortcut",
            "asaiu",
            [aktion, [code], SET_FLAGS],
        )
        # Plasma antwortet mit der Kombination, die die Aktion tatsächlich
        # bekommen hat. Weicht sie ab, ist etwas anderes schiefgegangen —
        # dann nehmen wir die halbe Anmeldung zurück, statt eine Taste
        # anzuzeigen, auf die nichts hört.
        vergeben = list(antwort.body[0]) if antwort is not None and antwort.body else []
        if vergeben != [code]:
            await self._ruf(
                KGLOBALACCEL_PATH, KGLOBALACCEL_IFACE, "unRegister", "as", [aktion]
            )
            self._gruende[deck_key] = f"Plasma hat '{combo}' nicht übernommen"
            return

        self._angemeldet[deck_key] = (combo, name)
        self._gruende.pop(deck_key, None)
        log.info("Kurzbefehl '%s' für Deck '%s' angemeldet", combo, deck_key)

    async def _halter(self, code: int) -> str | None:
        """Wem diese Kombination schon gehört — ``None``, wenn sie frei ist.

        Auch die eigenen Anmeldungen zählen: Zwei Decks mit derselben
        Kombination wären sonst ein stiller Fehler, bei dem nur eins von
        beiden reagiert.
        """
        antwort = await self._ruf(
            KGLOBALACCEL_PATH,
            KGLOBALACCEL_IFACE,
            "isGlobalShortcutAvailable",
            "is",
            [code, COMPONENT],
        )
        if antwort is None or not antwort.body or antwort.body[0]:
            return None

        # Der Name macht den Unterschied zwischen „geht nicht" und „geht
        # nicht, weil KWin damit die Arbeitsfläche zeigt".
        antwort = await self._ruf(
            KGLOBALACCEL_PATH, KGLOBALACCEL_IFACE, "getGlobalShortcutsByKey", "i", [code]
        )
        eintraege = list(antwort.body[0]) if antwort is not None and antwort.body else []
        if not eintraege:
            return "von einem anderen Programm"
        # (Aktion, Aktionsname, Komponente, Komponentenname, …)
        eintrag = eintraege[0]
        return f"{eintrag[3]} — {eintrag[1]}"

    async def _abmelden(self, deck_key: str) -> None:
        # Mit dem Namen abmelden, unter dem angemeldet wurde — ein
        # inzwischen umbenanntes Deck fände seine alte Aktion sonst nicht.
        eintrag = self._angemeldet.get(deck_key)
        aktion = self._aktion(deck_key, eintrag[1] if eintrag else deck_key)
        await self._ruf(KGLOBALACCEL_PATH, KGLOBALACCEL_IFACE, "unRegister", "as", [aktion])
        self._angemeldet.pop(deck_key, None)

    @staticmethod
    def _aktion(deck_key: str, name: str) -> list[str]:
        """Die vier Namen, unter denen Plasma eine Aktion führt."""
        return [
            COMPONENT,
            f"overlay:{deck_key}",
            COMPONENT_FRIENDLY,
            f"Overlay „{name}“ umschalten",
        ]

    # -- Tastendruck -------------------------------------------------------

    def _on_signal(self, msg: Message) -> None:
        if msg.message_type != MessageType.SIGNAL:
            return
        if msg.member != "globalShortcutPressed" or msg.interface != COMPONENT_IFACE:
            return
        if len(msg.body) < 2 or msg.body[0] != COMPONENT:
            return
        aktion = str(msg.body[1])
        if not aktion.startswith("overlay:"):
            return
        asyncio.create_task(self._ausloesen(aktion.split(":", 1)[1]))

    async def _ausloesen(self, deck_key: str) -> None:
        if deck_key not in self.runtime.decks:
            return
        try:
            await self.runtime.overlay.toggle(deck_key)
        except Exception as exc:
            log.warning("Overlay '%s' per Kurzbefehl: %s", deck_key, exc)
            self.runtime.notify("error", str(exc))
            return
        self.runtime.bus.publish(ev.EVT_DECKS_CHANGED, decks=self.runtime.decks_payload())

    # -- D-Bus -------------------------------------------------------------

    async def _connect(self) -> MessageBus | None:
        if self._bus is not None and self._bus.connected:
            return self._bus
        self._bus = None
        try:
            bus = await MessageBus(bus_type=BusType.SESSION).connect()
        except Exception as exc:
            log.info("Sitzungsbus nicht erreichbar: %s", exc)
            return None

        bus.add_message_handler(self._on_signal)
        # Ohne passende Regel bekämen wir das Signal gar nicht zu sehen: Der
        # Bus schickt Broadcasts nur an die, die danach gefragt haben.
        try:
            await bus.call(
                Message(
                    destination="org.freedesktop.DBus",
                    path="/org/freedesktop/DBus",
                    interface="org.freedesktop.DBus",
                    member="AddMatch",
                    signature="s",
                    body=[f"type='signal',interface='{COMPONENT_IFACE}'"],
                )
            )
        except Exception as exc:
            log.info("Signalregel ließ sich nicht setzen: %s", exc)
            with contextlib.suppress(Exception):
                bus.disconnect()
            return None

        self._bus = bus
        return bus

    async def _ruf(
        self, path: str, interface: str, member: str, signature: str = "", body=None
    ) -> Message | None:
        bus = self._bus
        if bus is None:
            return None
        try:
            antwort = await bus.call(
                Message(
                    destination=KGLOBALACCEL,
                    path=path,
                    interface=interface,
                    member=member,
                    signature=signature,
                    body=body or [],
                )
            )
        except Exception as exc:
            log.info("kglobalaccel.%s: %s", member, exc)
            return None
        if antwort is None or antwort.message_type == MessageType.ERROR:
            log.info("kglobalaccel.%s abgelehnt: %s", member, getattr(antwort, "body", ""))
            return None
        return antwort
