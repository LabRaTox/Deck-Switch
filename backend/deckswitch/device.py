"""Anbindung des physischen Stream Deck+.

Kapselt die ``streamdeck``-Bibliothek: Suchen, Öffnen, Wiederverbinden,
Bildkonvertierung und Callback-Weiterleitung. Die Bibliothek liefert Events
aus einem eigenen Reader-Thread — dieses Modul reicht sie unverändert weiter,
das Einsortieren in den asyncio-Loop macht die Runtime.

Das Gerät kann jederzeit weg sein (abgezogen, noch keine udev-Regel). Genau
deshalb ist "nicht verbunden" hier ein normaler Betriebszustand und kein
Fehlerfall, der die App beendet.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from PIL import Image
from StreamDeck.DeviceManager import DeviceManager
from StreamDeck.Devices.StreamDeck import DialEventType, TouchscreenEventType
from StreamDeck.ImageHelpers import PILHelper
from StreamDeck.Transport.Transport import TransportError
from . import texte

log = logging.getLogger(__name__)

#: Nur das Plus hat Dials + Touchstrip. Andere Decks laufen im Tastenbetrieb.
SUPPORTED_TYPES = {"Stream Deck +", "Stream Deck Plus"}

#: Die Bibliothek pollt das Gerät standardmäßig nur mit 20 Hz — bis zu 50 ms
#: Verzögerung je Ereignis. Für Tastendrücke reicht das, für Wischgesten auf
#: dem Touchstrip ist es zu träge. 100 Hz kostet kaum CPU (ein Read alle
#: 10 ms) und macht die Gestenerkennung spürbar zuverlässiger.
READ_POLL_HZ = 100


@dataclass(slots=True)
class DeviceInfo:
    connected: bool = False
    deck_type: str = ""
    serial: str = ""
    firmware: str = ""
    key_count: int = 0
    dial_count: int = 0
    key_size: tuple[int, int] = (120, 120)
    touchscreen_size: tuple[int, int] = (800, 100)
    #: Anordnung der Tasten. Nicht jedes Modell ist 4x2 — der Mini hat 3x2,
    #: das Original 5x3, das XL 8x4. Die GUI baut ihr Raster daraus.
    key_rows: int = 2
    key_columns: int = 4
    #: Hat das Gerät überhaupt Displays? Das Pedal hat keine.
    has_displays: bool = True
    error: str | None = None

    @property
    def has_dials(self) -> bool:
        return self.dial_count > 0

    @property
    def has_touchscreen(self) -> bool:
        return self.touchscreen_size[0] > 0 and self.dial_count > 0

    @property
    def segment_size(self) -> tuple[int, int]:
        """Breite eines Touchstrip-Segments (ein Streifen, vier Dials)."""
        width, height = self.touchscreen_size
        return (width // max(1, self.dial_count or 4), height)

    def as_dict(self) -> dict[str, Any]:
        return {
            "connected": self.connected,
            "deck_type": self.deck_type,
            "serial": self.serial,
            "firmware": self.firmware,
            "key_count": self.key_count,
            "dial_count": self.dial_count,
            "key_size": list(self.key_size),
            "touchscreen_size": list(self.touchscreen_size),
            "segment_size": list(self.segment_size),
            "key_rows": self.key_rows,
            "key_columns": self.key_columns,
            "has_displays": self.has_displays,
            "has_dials": self.has_dials,
            "has_touchscreen": self.has_touchscreen,
            "error": texte.aktuell(self.error),
        }


class StreamDeckDevice:
    """Dünne, fehlertolerante Hülle um ein geöffnetes Deck."""

    def __init__(self) -> None:
        self.deck = None
        self.info = DeviceInfo()
        self._lock = threading.RLock()

        # Von der Runtime gesetzt. Werden aus dem Reader-Thread gerufen.
        self.on_key: Callable[[int, bool], None] | None = None
        self.on_dial_rotate: Callable[[int, int], None] | None = None
        self.on_dial_push: Callable[[int, bool], None] | None = None
        self.on_touch: Callable[[str, dict], None] | None = None
        self.on_disconnect: Callable[[], None] | None = None

    # -- Verbindung --------------------------------------------------------

    def open(self, deck=None) -> bool:
        """Öffnet ein Deck — ein bestimmtes oder das erste gefundene.

        ``deck`` ist ein noch nicht geöffnetes Gerät aus :func:`enumerate_decks`.
        Ohne Angabe wird das erste gesuchte genommen; das ist der Weg für
        Aufrufer, die nur ein Deck kennen (Tests, Einzelgerät-Betrieb).
        """
        with self._lock:
            if self.deck is not None:
                return True
            if deck is None:
                try:
                    decks = DeviceManager().enumerate()
                except Exception as exc:
                    self.info = DeviceInfo(error=texte.t("device.geraete_suche_fehlgeschlagen", exc=exc))
                    return False

                if not decks:
                    self.info = DeviceInfo(error=texte.t("device.kein_stream_deck_gefunden"))
                    return False
                deck = decks[0]

            try:
                deck.open()
                deck.reset()
                if hasattr(deck, "set_poll_frequency"):
                    deck.set_poll_frequency(READ_POLL_HZ)
            except TransportError as exc:
                self.info = DeviceInfo(
                    error=(
                        texte.t("device.geraet_gefunden_aber_nicht", exc=exc)
                    )
                )
                return False
            except Exception as exc:
                self.info = DeviceInfo(error=texte.t("device.geraet_nicht_oeffnen", exc=exc))
                return False

            self.deck = deck
            # key_layout() liefert (Reihen, Spalten) — die einzige Quelle
            # dafür, wie das Gerät wirklich aussieht.
            rows, columns = _layout(deck)
            self.info = DeviceInfo(
                connected=True,
                deck_type=deck.deck_type(),
                serial=_safe(deck.get_serial_number),
                firmware=_safe(deck.get_firmware_version),
                key_count=deck.key_count(),
                dial_count=getattr(deck, "dial_count", lambda: 0)(),
                key_size=(deck.KEY_PIXEL_WIDTH, deck.KEY_PIXEL_HEIGHT),
                touchscreen_size=(
                    getattr(deck, "TOUCHSCREEN_PIXEL_WIDTH", 0),
                    getattr(deck, "TOUCHSCREEN_PIXEL_HEIGHT", 0),
                ),
                key_rows=rows,
                key_columns=columns,
                has_displays=bool(_safe(deck.is_visual)),
            )
            self._wire_callbacks(deck)
            log.info(
                "Verbunden: %s (Serial %s, Firmware %s)",
                self.info.deck_type,
                self.info.serial,
                self.info.firmware,
            )
            return True

    def close(self) -> None:
        with self._lock:
            deck, self.deck = self.deck, None
            if deck is None:
                return
            try:
                deck.reset()
                deck.close()
            except Exception as exc:
                log.debug("Schließen ignoriert: %s", exc)
            self.info = DeviceInfo()

    @property
    def connected(self) -> bool:
        return self.deck is not None and self.info.connected

    def _handle_transport_error(self, exc: Exception) -> None:
        log.warning("Verbindung zum Deck verloren: %s", exc)
        was_connected = self.info.connected
        self.close()
        self.info.error = texte.t("device.verbindung_verloren")
        if was_connected and self.on_disconnect is not None:
            self.on_disconnect()

    # -- Callbacks ---------------------------------------------------------

    def _wire_callbacks(self, deck) -> None:
        deck.set_key_callback(self._key_callback)
        if hasattr(deck, "set_dial_callback"):
            deck.set_dial_callback(self._dial_callback)
        if hasattr(deck, "set_touchscreen_callback"):
            deck.set_touchscreen_callback(self._touch_callback)

    def _key_callback(self, _deck, key: int, pressed: bool) -> None:
        if self.on_key is not None:
            self.on_key(key, pressed)

    def _dial_callback(self, _deck, dial: int, event, value) -> None:
        if event == DialEventType.TURN:
            if self.on_dial_rotate is not None:
                self.on_dial_rotate(dial, int(value))
        elif event == DialEventType.PUSH:
            if self.on_dial_push is not None:
                self.on_dial_push(dial, bool(value))

    def _touch_callback(self, _deck, event, value: dict) -> None:
        if self.on_touch is None:
            return
        name = {
            TouchscreenEventType.SHORT: "short",
            TouchscreenEventType.LONG: "long",
            TouchscreenEventType.DRAG: "drag",
        }.get(event, "short")
        self.on_touch(name, dict(value or {}))

    # -- Ausgabe -----------------------------------------------------------

    def set_brightness(self, percent: int) -> None:
        deck = self.deck
        if deck is None:
            return
        try:
            deck.set_brightness(max(0, min(100, int(percent))))
        except (TransportError, OSError) as exc:
            self._handle_transport_error(exc)

    def set_key_image(self, index: int, image: Image.Image) -> None:
        self.write_key_image(index, self.prepare_key_image(image))

    def prepare_key_image(self, image: Image.Image) -> Any:
        """Wandelt ein Bild ins Format des Geräts. Darf in einem Thread laufen."""
        deck = self.deck
        if deck is None:
            return None
        try:
            return PILHelper.to_native_key_format(deck, _flatten(image))
        except Exception as exc:
            log.warning("Tastenbild nicht umwandelbar: %s", exc)
            return None

    def write_key_image(self, index: int, native: Any) -> None:
        """Schickt ein fertig umgewandeltes Bild ans Gerät."""
        deck = self.deck
        if deck is None or native is None:
            return
        try:
            deck.set_key_image(index, native)
        except (TransportError, OSError) as exc:
            self._handle_transport_error(exc)
        except Exception as exc:
            log.warning("Tastenbild %s fehlgeschlagen: %s", index, exc)

    def set_touchscreen_image(
        self, image: Image.Image, x: int = 0, y: int = 0
    ) -> None:
        self.write_touchscreen_image(
            self.prepare_touchscreen_image(image), x=x, y=y,
            width=image.width, height=image.height,
        )

    def prepare_touchscreen_image(self, image: Image.Image) -> Any:
        """Wie :meth:`prepare_key_image`, für den Touchstrip."""
        deck = self.deck
        if deck is None or not hasattr(deck, "set_touchscreen_image"):
            return None
        try:
            return PILHelper.to_native_touchscreen_format(deck, _flatten(image))
        except Exception as exc:
            log.warning("Touchstrip-Bild nicht umwandelbar: %s", exc)
            return None

    def write_touchscreen_image(
        self, native: Any, x: int = 0, y: int = 0, width: int = 0, height: int = 0
    ) -> None:
        deck = self.deck
        if deck is None or native is None or not hasattr(deck, "set_touchscreen_image"):
            return
        try:
            deck.set_touchscreen_image(native, x, y, width, height)
        except (TransportError, OSError) as exc:
            self._handle_transport_error(exc)
        except Exception as exc:
            log.warning("Touchstrip-Bild fehlgeschlagen: %s", exc)

    def clear(self) -> None:
        deck = self.deck
        if deck is None:
            return
        try:
            deck.reset()
        except Exception as exc:
            log.debug("Reset ignoriert: %s", exc)


def enumerate_decks() -> list:
    """Alle angeschlossenen Decks, noch ungeöffnet.

    Ein Deck verrät seine Seriennummer erst im geöffneten Zustand — bis
    dahin unterscheidet sie nur ihr Geräteknoten (:func:`deck_path`). Der
    reicht, um zu erkennen, was schon offen ist und was neu dazukam.
    """
    try:
        return list(DeviceManager().enumerate())
    except Exception as exc:
        log.warning("Geräte-Suche fehlgeschlagen: %s", exc)
        return []


def deck_path(deck) -> str:
    """Stabile Kennung eines Geräts, ohne es zu öffnen."""
    try:
        value = deck.id()
    except Exception:
        return ""
    return value.decode() if isinstance(value, bytes) else str(value)


def _flatten(image: Image.Image) -> Image.Image:
    """RGBA → RGB auf Schwarz. Das Deck erwartet JPEG ohne Alphakanal."""
    if image.mode == "RGB":
        return image
    background = Image.new("RGB", image.size, (0, 0, 0))
    rgba = image.convert("RGBA")
    background.paste(rgba, mask=rgba.getchannel("A"))
    return background


def _layout(deck) -> tuple[int, int]:
    """(Reihen, Spalten) des Tastenfelds.

    Fällt auf eine Zeile zurück, wenn ein Gerät das nicht meldet — dann
    steht wenigstens alles nebeneinander statt übereinander.
    """
    try:
        rows, columns = deck.key_layout()
        if rows > 0 and columns > 0:
            return int(rows), int(columns)
    except Exception:
        pass
    count = max(1, deck.key_count())
    return 1, count


def _safe(getter) -> str:
    try:
        return str(getter())
    except Exception:
        return ""
