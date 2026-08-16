"""Bildschirmschoner für das ganze Deck.

Nach einer Zeit ohne Eingabe legt sich *ein* Bild über alle acht Tasten und
den Touchstrip. Damit das Motiv durchläuft und nicht achtmal zerhackt
wirkt, wird es zuerst auf eine Fläche in Geräteproportionen gerechnet und
erst dann zerschnitten — die Stege zwischen den Tasten zählen dabei mit,
verbrauchen also einen Teil des Bildes, den man nie sieht.

Quellen sind entweder hochgeladene Dateien oder Plugins vom Typ
``screensaver``. Beide liefern am Ende dasselbe: eine Folge von Bildern in
Canvas-Größe, die diese Datei in Kacheln zerlegt.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from PIL import Image, ImageSequence

log = logging.getLogger(__name__)

#: Abstand zwischen zwei Tasten, als Anteil der Tastenbreite. Geschätzt nach
#: dem Aussehen des Geräts — die Stege sind schmaler als eine halbe Taste
#: und breiter als ein Zehntel. Der Wert bestimmt nur, wie viel vom Bild in
#: den Fugen verschwindet; er muss nicht auf den Millimeter stimmen.
KEY_GAP_RATIO = 0.25

#: Abstand zwischen der unteren Tastenreihe und dem Touchstrip, ebenfalls
#: als Anteil der Tastenbreite. Dort sitzt am Gerät mehr Rahmen.
STRIP_GAP_RATIO = 0.38

#: Untergrenze für die Bildrate animierter Schoner. Ein GIF mit 10 ms pro
#: Bild würde sonst neun Bilder über USB schieben, so schnell es kann.
MIN_FRAME_S = 1 / 15
DEFAULT_FRAME_S = 0.1

#: Obergrenze für Einzelbilder. Jedes Bild kostet acht Tastenbilder plus
#: Streifen im Speicher; ein langes GIF würde sonst hunderte Megabyte
#: belegen, ohne dass es jemandem auffiele.
MAX_FRAMES = 240


@dataclass(frozen=True)
class DeckLayout:
    """Wo die Kacheln auf der gedachten Gesamtfläche sitzen."""

    canvas: tuple[int, int]
    #: Ein Rechteck ``(x, y, w, h)`` je Taste, in Lesereihenfolge.
    keys: list[tuple[int, int, int, int]]
    #: Rechteck des Touchstrips auf der Canvas.
    strip: tuple[int, int, int, int]
    key_size: tuple[int, int]
    strip_size: tuple[int, int]


def layout(
    key_size: tuple[int, int],
    key_count: int,
    touchscreen_size: tuple[int, int],
    columns: int = 4,
) -> DeckLayout:
    """Rechnet die Gesamtfläche aus, auf die ein Schoner gemalt wird.

    Der Touchstrip ist mit 800×100 Pixeln viel breiter, als er am Gerät
    *aussieht* — physisch ist er ungefähr so breit wie die vier Tasten
    darüber. Auf der Canvas bekommt er deshalb die Breite des Tastenfelds
    und eine daraus abgeleitete Höhe; erst beim Ausschneiden wird er auf
    seine echte Pixelbreite gezogen.
    """
    key_w, key_h = key_size
    rows = max(1, -(-key_count // columns))  # aufrunden
    gap = round(key_w * KEY_GAP_RATIO)
    strip_gap = round(key_w * STRIP_GAP_RATIO)

    width = columns * key_w + (columns - 1) * gap
    keys_height = rows * key_h + (rows - 1) * gap

    strip_w, strip_h = touchscreen_size
    # Höhe proportional zur Breite, die der Streifen auf der Canvas einnimmt.
    canvas_strip_h = max(1, round(strip_h * width / max(1, strip_w)))

    keys = [
        (
            (index % columns) * (key_w + gap),
            (index // columns) * (key_h + gap),
            key_w,
            key_h,
        )
        for index in range(key_count)
    ]
    strip = (0, keys_height + strip_gap, width, canvas_strip_h)
    height = keys_height + strip_gap + canvas_strip_h

    return DeckLayout(
        canvas=(width, height),
        keys=keys,
        strip=strip,
        key_size=key_size,
        strip_size=touchscreen_size,
    )


def fit(image: Image.Image, size: tuple[int, int], mode: str = "cover") -> Image.Image:
    """Skaliert ``image`` auf ``size``.

    ``cover`` füllt die Fläche und schneidet Überstand ab, ``contain`` zeigt
    das ganze Bild und lässt Ränder schwarz. Für einen Schoner ist ``cover``
    das Übliche — Balken auf einem Tastenfeld sehen nach Fehler aus.
    """
    target_w, target_h = size
    source = image.convert("RGBA")
    if source.size == size:
        return source

    scale_w = target_w / source.width
    scale_h = target_h / source.height
    scale = max(scale_w, scale_h) if mode == "cover" else min(scale_w, scale_h)
    scaled = source.resize(
        (max(1, round(source.width * scale)), max(1, round(source.height * scale))),
        Image.LANCZOS,
    )

    canvas = Image.new("RGBA", size, (0, 0, 0, 255))
    canvas.paste(scaled, ((target_w - scaled.width) // 2, (target_h - scaled.height) // 2))
    return canvas


def split(frame: Image.Image, deck: DeckLayout) -> tuple[list[Image.Image], Image.Image]:
    """Zerlegt ein Canvas-Bild in Tastenbilder und den Streifen."""
    keys = [
        frame.crop((x, y, x + w, y + h)).resize(deck.key_size, Image.LANCZOS)
        for x, y, w, h in deck.keys
    ]
    x, y, w, h = deck.strip
    strip = frame.crop((x, y, x + w, y + h)).resize(deck.strip_size, Image.LANCZOS)
    return keys, strip


@dataclass
class Frame:
    """Ein fertig zerlegtes Einzelbild samt Standzeit."""

    keys: list[Image.Image]
    strip: Image.Image
    duration_s: float


def load_frames(
    path_or_image: Image.Image, deck: DeckLayout, mode: str = "cover"
) -> list[Frame]:
    """Bereitet ein Bild — auch ein animiertes GIF — vollständig auf.

    Alle Einzelbilder werden *vorab* zerlegt. Ein Schoner läuft potenziell
    stundenlang; ihn währenddessen Bild für Bild neu zu skalieren wäre
    Dauerlast für etwas, das sich nie ändert.
    """
    frames: list[Frame] = []
    for raw in ImageSequence.Iterator(path_or_image):
        duration = raw.info.get("duration")
        seconds = (duration / 1000) if duration else DEFAULT_FRAME_S
        canvas = fit(raw.copy(), deck.canvas, mode)
        keys, strip = split(canvas, deck)
        frames.append(Frame(keys=keys, strip=strip, duration_s=max(MIN_FRAME_S, seconds)))
        if len(frames) >= MAX_FRAMES:
            log.warning(
                "Schoner hat mehr als %d Einzelbilder — der Rest wird verworfen", MAX_FRAMES
            )
            break
    return frames
