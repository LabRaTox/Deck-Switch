"""Ein Deck, das auf dem Bildschirm liegt statt am USB-Anschluss.

Für die Deck-Sitzung (:mod:`deckswitch.deck`) ist das kein Sonderfall: Sie
ruft ``set_key_image``, ``set_brightness`` und bekommt Tastendrücke über
dieselben Rückrufe. Nur landen die Bilder hier im Speicher statt auf einem
USB-Bus, und die Drücke kommen aus dem Overlay statt aus dem Reader-Thread
der ``streamdeck``-Bibliothek.

Genau deshalb konnte das virtuelle Deck klein bleiben: Seiten, Tastenlogik,
Doppeldruck, Multi-Aktionen, Dial-Stacks, Bildschirmschoner — all das gilt
dort unverändert, ohne eine Zeile Sonderbehandlung.

Das Overlay selbst ist ein QML-Programm (siehe ``packaging/overlay/``), das
über ``zwlr_layer_shell_v1`` auf der Overlay-Ebene liegt. Gemessen am
2026-08-16: Es nimmt Klicks entgegen, ohne den Tastaturfokus zu stehlen —
eine Hotkey-Aktion tippt also weiter in das Fenster, aus dem man kam.
"""

from __future__ import annotations

import io
import logging
import threading
from collections.abc import Callable

from PIL import Image, ImageChops, ImageDraw

from .config import DeckBinding
from .device import DeviceInfo

log = logging.getLogger(__name__)

#: Wie das Modell in der GUI heißt.
DECK_TYPE = "Virtuelles Deck"

#: Eckenradius der Kacheln, als Anteil der kurzen Kante.
#:
#: Gerundet wird **hier** und nicht im Overlay: Qt Quick schneidet nur
#: rechteckig zu (``clip`` kennt keinen Radius), die quadratischen Ecken des
#: PNG blieben also stehen. Und bei durchsichtigem Grund braucht es ohnehin
#: echte Transparenz in den Ecken, keine schwarze Fläche.
CORNER_RATIO = 0.12


class VirtualDevice:
    """Gerätehülle ohne Gerät — dieselbe Schnittstelle, andere Ausgabe."""

    def __init__(self, binding: DeckBinding) -> None:
        self.binding = binding
        self._lock = threading.Lock()

        #: Fertige PNG-Bilder je Kachel, plus eine Fassung je Kachel. Über
        #: die Fassung fragt das Overlay „was hat sich geändert?" — das
        #: erspart es, zehnmal je Sekunde alle Bilder zu holen.
        self._keys: dict[int, bytes] = {}
        self._segments: dict[int, bytes] = {}
        self._versions: dict[str, int] = {}
        self._revision = 0

        #: Von der Deck-Sitzung gesetzt, genau wie beim echten Gerät.
        self.on_key: Callable[[int, bool], None] | None = None
        self.on_dial_rotate: Callable[[int, int], None] | None = None
        self.on_dial_push: Callable[[int, bool], None] | None = None
        self.on_touch: Callable[[str, dict], None] | None = None
        self.on_disconnect: Callable[[], None] | None = None

        #: Wird gerufen, wenn sich ein Bild geändert hat — die GUI und das
        #: Overlay erfahren so, dass es etwas Neues gibt.
        self.on_image: Callable[[str, int], None] | None = None

        self.brightness = binding.device.brightness
        self.info = self._build_info()

    # -- Stammdaten --------------------------------------------------------

    def _build_info(self) -> DeviceInfo:
        columns = max(1, self.binding.columns)
        rows = max(1, self.binding.rows)
        dials = max(0, self.binding.dials)
        size = max(48, min(256, self.binding.key_size))
        # Der Touchstrip ist so breit wie das Tastenfeld — damit sieht ein
        # Seiten-Hintergrundbild im Overlay so aus wie auf dem Gerät.
        strip_width = size * max(1, dials) if dials else 0
        return DeviceInfo(
            connected=True,
            deck_type=DECK_TYPE,
            serial=self.binding.serial,
            firmware="—",
            key_count=columns * rows,
            dial_count=dials,
            key_size=(size, size),
            touchscreen_size=(strip_width, size // 2 if dials else 0),
            key_rows=rows,
            key_columns=columns,
            has_displays=True,
        )

    def refresh_geometry(self) -> None:
        """Nach einer Änderung an Raster oder Kachelgröße neu vermessen."""
        with self._lock:
            self._keys.clear()
            self._segments.clear()
            self._versions.clear()
            self._revision += 1
        self.info = self._build_info()

    @property
    def connected(self) -> bool:
        # Ein Overlay ist immer da. „Nicht verbunden" gibt es hier nicht —
        # sichtbar oder nicht ist eine Frage des Overlays, nicht des Geräts.
        return True

    @property
    def revision(self) -> int:
        """Zählt jede Bildänderung. Das Overlay fragt danach."""
        return self._revision

    # -- Ausgabe (von der Deck-Sitzung gerufen) ----------------------------

    def open(self, deck=None) -> bool:
        return True

    def close(self) -> None:
        with self._lock:
            self._keys.clear()
            self._segments.clear()

    def clear(self) -> None:
        self.close()

    def set_brightness(self, percent: int) -> None:
        """Wird angenommen, wirkt aber nicht — ein Overlay hat kein Licht.

        Am Gerät regelt das die Hintergrundbeleuchtung. Auf dem Bildschirm
        gäbe es dafür nur zwei Übertragungen, und beide sind schlechter als
        gar keine: Als Deckkraft wird die Kachel durchscheinend und auf
        hellem Grund unlesbar, als Abdunkeln stimmen die Farben nicht mehr
        mit der Vorschau überein. Also bleibt die Kachel so, wie sie
        gestaltet wurde.
        """
        self.brightness = max(0, min(100, int(percent)))

    def set_key_image(self, index: int, image: Image.Image) -> None:
        data = _encode(image)
        with self._lock:
            if self._keys.get(index) == data:
                return  # unverändert — kein Grund, das Overlay zu wecken
            self._keys[index] = data
        self._bump("key", index)

    def set_touchscreen_image(self, image: Image.Image, x: int = 0, y: int = 0) -> None:
        width = self.info.segment_size[0] or 1
        index = max(0, x // width)
        data = _encode(image)
        with self._lock:
            if self._segments.get(index) == data:
                return
            self._segments[index] = data
        self._bump("dial", index)

    # -- Abholen (vom Server für das Overlay) ------------------------------

    def image(self, input_type: str, index: int) -> bytes | None:
        with self._lock:
            source = self._keys if input_type == "key" else self._segments
            return source.get(index)

    def versions(self) -> dict[str, int]:
        """Fassung je Kachel — das Overlay lädt nur, was sich geändert hat."""
        with self._lock:
            return dict(self._versions)

    def _bump(self, input_type: str, index: int) -> None:
        with self._lock:
            self._revision += 1
            self._versions[f"{input_type}:{index}"] = self._revision
        if self.on_image is not None:
            try:
                self.on_image(input_type, index)
            except Exception:
                log.debug("Rückmeldung ans Overlay fehlgeschlagen", exc_info=True)

    # -- Eingaben (vom Server aus dem Overlay) -----------------------------

    def press(self, input_type: str, index: int, pressed: bool) -> None:
        if input_type == "key":
            if self.on_key is not None:
                self.on_key(index, pressed)
        elif self.on_dial_push is not None:
            self.on_dial_push(index, pressed)

    def rotate(self, index: int, delta: int) -> None:
        if self.on_dial_rotate is not None:
            self.on_dial_rotate(index, delta)

    def touch(self, index: int, x: int, y: int) -> None:
        if self.on_touch is not None:
            width = self.info.segment_size[0] or 1
            self.on_touch("short", {"x": index * width + x, "y": y})


def _encode(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    _round_corners(image.convert("RGBA")).save(buffer, format="PNG")
    return buffer.getvalue()


def _round_corners(image: Image.Image) -> Image.Image:
    """Schneidet die Ecken rund — mit echter Transparenz dahinter.

    Auf dem Gerät sitzen die Tasten in Aussparungen, das Bild darf dort ruhig
    quadratisch sein. Ein Overlay hat diesen Rahmen nicht: Ohne runde Ecken
    liegen harte Quadrate auf dem Bildschirm.
    """
    radius = max(2, round(min(image.size) * CORNER_RATIO))
    maske = Image.new("L", image.size, 0)
    ImageDraw.Draw(maske).rounded_rectangle(
        (0, 0, image.width - 1, image.height - 1), radius=radius, fill=255
    )
    gerundet = image.copy()
    # Multiplizieren statt Ersetzen: Was vorher schon durchsichtig war,
    # bleibt es — die Maske darf nur zusätzlich wegnehmen.
    gerundet.putalpha(ImageChops.multiply(image.getchannel("A"), maske))
    return gerundet
