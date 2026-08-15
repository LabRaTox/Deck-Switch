"""Hintergrundbild für den Touchstrip.

Ein Bild über die volle Streifenbreite (800 × 100 Pixel), das in die vier
Dial-Segmente zerlegt wird. Anders als beim Bildschirmschoner läuft es im
Normalbetrieb mit: Es wird *zuerst* gezeichnet, die Belegung kommt darüber.

Weil sich daran selten etwas ändert, werden die fertigen Segmente
zwischengespeichert — bei jedem Neuzeichnen eines Dials erneut zu skalieren
wäre reine Verschwendung.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from PIL import Image

from .screensaver import fit

log = logging.getLogger(__name__)


@dataclass
class WallpaperCache:
    """Hält die zerlegten Segmente, bis sich die Einstellung ändert."""

    #: Woraus der Inhalt entstanden ist — Quelle, Maße, Einpassung, Deckkraft.
    key: tuple | None = None
    segments: list[Image.Image] = field(default_factory=list)

    def get(self, key: tuple) -> list[Image.Image] | None:
        return self.segments if self.key == key and self.segments else None

    def put(self, key: tuple, segments: list[Image.Image]) -> None:
        self.key = key
        self.segments = segments

    def clear(self) -> None:
        self.key = None
        self.segments = []


def split(
    image: Image.Image,
    strip_size: tuple[int, int],
    segment_count: int,
    mode: str = "cover",
    opacity: int = 100,
) -> list[Image.Image]:
    """Passt ``image`` auf den Streifen ein und schneidet es in Segmente."""
    canvas = fit(image, strip_size, mode)

    if opacity < 100:
        # Über Schwarz mischen statt den Alpha-Kanal zu senken: Das Bild ist
        # die *unterste* Ebene, ein durchsichtiges Ergebnis würde nur den
        # schwarzen Grund des Displays zeigen — sähe aber anders aus als
        # gedacht, sobald etwas Halbtransparentes darüber liegt.
        base = Image.new("RGBA", canvas.size, (0, 0, 0, 255))
        canvas = Image.blend(base, canvas, max(0.0, min(1.0, opacity / 100)))

    width = strip_size[0] // max(1, segment_count)
    return [
        canvas.crop((index * width, 0, (index + 1) * width, strip_size[1]))
        for index in range(segment_count)
    ]


def load(path_or_image: Image.Image, strip_size, segment_count, mode="cover", opacity=100):
    """Wie :func:`split`, nimmt aber nur das erste Bild einer Animation.

    Ein bewegter Hintergrund hinter den Belegungen würde dauerhaft Bilder
    über USB schieben, während man nichts weiter tut, als auf sein Deck zu
    schauen. Für den Streifen ist das den Strom nicht wert.
    """
    image = path_or_image
    if getattr(image, "n_frames", 1) > 1:
        image.seek(0)
    return split(image.convert("RGBA"), strip_size, segment_count, mode, opacity)
