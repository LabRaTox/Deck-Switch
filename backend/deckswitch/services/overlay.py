"""Das Overlay zeigen und verstecken.

Das virtuelle Deck ist ein eigenes kleines Programm (``qml6`` mit der Datei
aus ``packaging/overlay/``). Hier steht nur, wann es startet, wo es
erscheint und wann es wieder verschwindet.

**Warum ein eigener Prozess und keine Fläche in der GUI?** Weil es unter
Wayland kein Fenster sein soll: Die Overlay-Ebene (``zwlr_layer_shell_v1``)
erreicht man nur über eine Toolkit-Anbindung, die das Protokoll spricht —
LayerShellQt. Die GUI läuft dagegen in einer WebView. Der Preis ist ein
zweiter Prozess, der Gewinn ist ein Overlay, das den Tastaturfokus gar nicht
bekommen *kann*: Ein Klick auf eine Taste lässt die Anwendung im
Vordergrund, in die eine Hotkey-Aktion dann auch tippt.

**Die Zeigerposition** verrät unter Wayland kein Client-Protokoll — das ist
Absicht. KWin weiß sie aber, und KWin-Skripte dürfen D-Bus rufen. Also
fragen wir über ein winziges Skript zurück an uns selbst. Ohne KDE bleibt
das Overlay an seiner gemerkten Stelle stehen; das ist kein Fehler, nur
weniger bequem.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import shutil
import subprocess
from pathlib import Path

from dbus_next import BusType, Message, MessageType
from dbus_next.aio import MessageBus
from dbus_next.service import ServiceInterface, method

log = logging.getLogger(__name__)

#: Die QML-Datei des Overlays — im Repo neben der udev-Regel.
OVERLAY_QML = Path(__file__).resolve().parents[3] / "packaging" / "overlay" / "deck-overlay.qml"

#: Unter diesem Namen meldet sich das Backend am Bus, damit ein KWin-Skript
#: uns die Zeigerposition zurückgeben kann.
BUS_NAME = "org.deckswitch.Overlay"
BUS_PATH = "/Overlay"

KWIN = "org.kde.KWin"

#: Das Skript, das KWin für uns ausführt. Mehr braucht es nicht: Position
#: lesen, zurückrufen.
CURSOR_SCRIPT = """
var c = workspace.cursorPos;
callDBus("%(name)s", "%(path)s", "%(name)s", "Cursor", Math.round(c.x), Math.round(c.y));
""" % {"name": BUS_NAME, "path": BUS_PATH}


class _CursorReceiver(ServiceInterface):
    """Nimmt entgegen, was das KWin-Skript zurückmeldet."""

    def __init__(self, ziel: "OverlayService") -> None:
        super().__init__(BUS_NAME)
        self._ziel = ziel

    # Ohne Rückgabe-Annotation: dbus_next liest die Signatur aus den
    # Annotationen und akzeptiert dort nur D-Bus-Typen, kein ``None``.
    @method()
    def Cursor(self, x: "i", y: "i"):  # noqa: N802,F821 - D-Bus-Signatur
        self._ziel._cursor_reported(x, y)


class OverlayService:
    def __init__(self, runtime) -> None:
        self.runtime = runtime
        self._prozesse: dict[str, subprocess.Popen] = {}
        self._bus: MessageBus | None = None
        self._cursor: asyncio.Future | None = None
        self._script_id: int | None = None

    # -- Zustand -----------------------------------------------------------

    def available(self) -> tuple[bool, str]:
        if shutil.which("qml6") is None:
            return False, "'qml6' fehlt (Paket qt6-declarative)"
        if not Path("/usr/lib/qt6/qml/org/kde/layershell/qmldir").exists():
            return False, "'layer-shell-qt' fehlt — ohne das gibt es keine Overlay-Ebene"
        if not OVERLAY_QML.is_file():
            return False, f"Overlay-Datei nicht gefunden: {OVERLAY_QML}"
        return True, ""

    def is_visible(self, deck_key: str) -> bool:
        prozess = self._prozesse.get(deck_key)
        return prozess is not None and prozess.poll() is None

    # -- Zeigen und verstecken --------------------------------------------

    async def toggle(self, deck_key: str, *, at_cursor: bool = True) -> bool:
        """Umschalten. Liefert, ob das Overlay jetzt zu sehen ist."""
        if self.is_visible(deck_key):
            self.hide(deck_key)
            return False
        await self.show(deck_key, at_cursor=at_cursor)
        return True

    async def show(self, deck_key: str, *, at_cursor: bool = True) -> None:
        deck = self.runtime.decks.get(deck_key)
        if deck is None:
            raise RuntimeError(f"Deck '{deck_key}' gibt es nicht")
        ok, grund = self.available()
        if not ok:
            raise RuntimeError(grund)

        self.hide(deck_key)

        position = await self._position(deck, at_cursor)
        port = self.runtime.config.app.port
        befehl = [
            "qml6",
            str(OVERLAY_QML),
            "--",
            "--deck", deck_key,
            "--base", f"http://127.0.0.1:{port}",
            "--x", str(position[0]),
            "--y", str(position[1]),
        ]
        try:
            self._prozesse[deck_key] = subprocess.Popen(
                befehl,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                start_new_session=True,
                env=os.environ.copy(),
            )
        except OSError as exc:
            raise RuntimeError(f"Overlay ließ sich nicht starten: {exc}") from exc

        # Alles neu zeichnen — das frische Overlay hat noch keine Bilder.
        deck._mark_all_dirty()
        log.info("Overlay für '%s' gestartet bei %s", deck.label, position)

    def hide(self, deck_key: str) -> None:
        prozess = self._prozesse.pop(deck_key, None)
        if prozess is None or prozess.poll() is not None:
            return
        prozess.terminate()
        try:
            prozess.wait(timeout=2)
        except subprocess.TimeoutExpired:
            prozess.kill()

    def close(self) -> None:
        for key in list(self._prozesse):
            self.hide(key)

    # -- Position ----------------------------------------------------------

    async def _position(self, deck, at_cursor: bool) -> tuple[int, int]:
        """Wo das Overlay erscheint — am Zeiger oder an der abgelegten Stelle."""
        breite, hoehe = self._groesse(deck)
        if at_cursor:
            zeiger = await self.cursor_position()
            if zeiger is not None:
                # Leicht versetzt unter den Zeiger, damit er auf einer Taste
                # steht und nicht auf dem Rand.
                return (max(0, zeiger[0] - breite // 2), max(0, zeiger[1] - hoehe // 2))

        # Ohne Zeiger zählt, wohin es zuletzt gezogen wurde. Das ist der
        # ganze Sinn des Ablegens: Es soll da liegen bleiben.
        binding = deck.binding
        if binding.overlay_x >= 0 and binding.overlay_y >= 0:
            return (binding.overlay_x, binding.overlay_y)
        return (200, 200)

    def remember_position(self, deck_key: str, x: int, y: int) -> tuple[int, int]:
        """Merkt sich, wo das Overlay abgelegt wurde.

        Wird vom Overlay selbst gerufen, sobald man es losgelassen hat.
        Negative Werte hätten die Bedeutung „noch nie verschoben" — deshalb
        wird hier bei 0 abgeschnitten.
        """
        deck = self.runtime.decks.get(deck_key)
        if deck is None or not deck.binding.is_virtual:
            raise RuntimeError(f"Kein virtuelles Deck: '{deck_key}'")
        deck.binding.overlay_x = max(0, int(x))
        deck.binding.overlay_y = max(0, int(y))
        self.runtime.save_config()
        return (deck.binding.overlay_x, deck.binding.overlay_y)

    @staticmethod
    def _groesse(deck) -> tuple[int, int]:
        binding = deck.binding
        kachel, abstand, rand = binding.key_size, 8, 12
        breite = rand * 2 + binding.columns * kachel + (binding.columns - 1) * abstand
        hoehe = rand * 2 + binding.rows * kachel + (binding.rows - 1) * abstand
        if binding.dials:
            hoehe += abstand + kachel // 2
        return breite, hoehe

    async def cursor_position(self) -> tuple[int, int] | None:
        """Fragt KWin nach der Zeigerposition. ``None``, wenn das nicht geht."""
        bus = await self._ensure_bus()
        if bus is None:
            return None

        pfad = Path("/tmp") / f"deckswitch-cursor-{os.getuid()}.js"
        try:
            pfad.write_text(CURSOR_SCRIPT, encoding="utf-8")
        except OSError as exc:
            log.debug("Skript nicht schreibbar: %s", exc)
            return None

        loop = asyncio.get_running_loop()
        self._cursor = loop.create_future()

        antwort = await self._kwin(
            "/Scripting", "org.kde.kwin.Scripting", "loadScript", "ss",
            [str(pfad), "deckswitch-cursor"],
        )
        if antwort is None or not antwort.body:
            return None
        script_id = int(antwort.body[0])

        await self._kwin(f"/Scripting/Script{script_id}", "org.kde.kwin.Script", "run")
        try:
            return await asyncio.wait_for(self._cursor, timeout=1.5)
        except asyncio.TimeoutError:
            log.debug("KWin hat die Zeigerposition nicht gemeldet")
            return None
        finally:
            self._cursor = None
            await self._kwin(
                "/Scripting", "org.kde.kwin.Scripting", "unloadScript", "s",
                ["deckswitch-cursor"],
            )

    def _cursor_reported(self, x: int, y: int) -> None:
        if self._cursor is not None and not self._cursor.done():
            self._cursor.set_result((x, y))

    # -- D-Bus -------------------------------------------------------------

    async def _ensure_bus(self) -> MessageBus | None:
        if self._bus is not None:
            return self._bus
        try:
            bus = await MessageBus(bus_type=BusType.SESSION).connect()
            bus.export(BUS_PATH, _CursorReceiver(self))
            await bus.request_name(BUS_NAME)
        except Exception as exc:
            log.debug("Overlay-Bus nicht verfügbar: %s", exc)
            return None
        self._bus = bus
        return bus

    async def _kwin(
        self, path: str, interface: str, member: str, signature: str = "", body=None
    ) -> Message | None:
        bus = await self._ensure_bus()
        if bus is None:
            return None
        try:
            antwort = await asyncio.wait_for(
                bus.call(
                    Message(
                        destination=KWIN,
                        path=path,
                        interface=interface,
                        member=member,
                        signature=signature,
                        body=body or [],
                    )
                ),
                timeout=4,
            )
        except Exception as exc:
            log.debug("KWin-Aufruf %s fehlgeschlagen: %s", member, exc)
            return None
        if antwort is None or antwort.message_type is MessageType.ERROR:
            return None
        return antwort

    async def shutdown(self) -> None:
        self.close()
        bus, self._bus = self._bus, None
        if bus is not None:
            with contextlib.suppress(Exception):
                bus.disconnect()
