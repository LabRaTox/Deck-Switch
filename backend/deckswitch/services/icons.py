"""Icon-Auflösung und SVG-Rasterung.

Auflösungs-Priorität laut Spec:
  1. vom User pro Belegung hochgeladenes Icon
  2. Icon aus dem aktiven Iconset (Standard: Tabler, als Iconset-Plugin)
  3. generischer Platzhalter

Das Basis-Iconset ist bewusst nicht einkompiliert — es kommt genauso über die
Plugin-Registry wie jedes nachinstallierte Set.
"""

from __future__ import annotations

import io
import logging
import re
from pathlib import Path

import cairosvg
from PIL import Image, ImageDraw

from .. import paths
from ..config import IconRef
from .backgrounds import parse_color

log = logging.getLogger(__name__)

_CURRENT_COLOR = re.compile(r"currentColor", re.IGNORECASE)
ALLOWED_UPLOAD_SUFFIXES = {".svg", ".png", ".jpg", ".jpeg", ".webp", ".gif"}

#: Obergrenze für Einzelbilder einer Animation. Ein langes GIF hätte sonst
#: hunderte Bilder im Speicher — auf einer 120-px-Kachel sieht man den
#: Unterschied nicht, die Länge bleibt durch gleichmäßiges Auslassen erhalten.
MAX_FRAMES = 60

#: Längste Kante, in der Einzelbilder überhaupt gehalten werden.
#:
#: Gemessen: Ein 70-kB-GIF mit 40 Bildern in 1280×720 belegte in
#: Originalauflösung **139 MB** Arbeitsspeicher — für Kacheln, die 120×120
#: groß sind. Ein 4K-GIF wären über 2 GB gewesen. Größer als der Touchstrip
#: (800 px) wird nie etwas gebraucht; 512 deckt jede Kachel und jedes
#: Segment mit Reserve ab.
MAX_FRAME_EDGE = 512


class IconService:
    def __init__(self, registry=None, uploads_dir: Path | None = None) -> None:
        self.registry = registry
        self.uploads_dir = uploads_dir or paths.UPLOADS_DIR
        self._cache: dict[tuple, Image.Image] = {}
        #: Einzelbilder animierter Dateien, samt Anzeigedauer.
        self._frames: dict[tuple, list[tuple[Image.Image, float]]] = {}
        #: Ob eine Datei überhaupt bewegt ist — aus dem Dateikopf, ohne sie
        #: zu dekodieren. Wird sehr oft gefragt.
        self._animated: dict[tuple, bool] = {}

    def bind_registry(self, registry) -> None:
        self.registry = registry
        self.clear_cache()

    def clear_cache(self) -> None:
        self._cache.clear()
        self._frames.clear()
        self._animated.clear()

    # -- Öffentliche API ---------------------------------------------------

    def resolve(
        self,
        icon: IconRef | None,
        *,
        size: int,
        fallback_name: str | None = None,
        fallback_set: str | None = None,
        color: str | None = None,
        frame_time: float = 0.0,
    ) -> Image.Image:
        """Liefert das Icon als RGBA-Bild in ``size``×``size``.

        ``fallback_name`` ist typischerweise das ``default_icon`` der Action
        aus dem Manifest — es greift, wenn der User nichts eigenes gewählt hat.
        ``frame_time`` wählt bei animierten Bildern das Einzelbild aus; die
        Runtime zählt dafür die Laufzeit hoch.
        """
        size = max(8, int(size))
        tint = (icon.color if icon and icon.color else color)

        if icon is not None and icon.kind == "upload" and icon.upload:
            image = self._load_upload(icon.upload, size, tint, frame_time)
            if image is not None:
                return image

        if icon is not None and icon.kind == "iconset" and icon.name:
            image = self._load_from_set(icon.set_id or fallback_set, icon.name, size, tint)
            if image is not None:
                return image

        if fallback_name:
            image = self._load_from_set(fallback_set, fallback_name, size, tint)
            if image is not None:
                return image

        return self.placeholder(size, tint)

    def list_sets(self) -> list[dict]:
        """Alle verfügbaren Iconsets samt Icon-Namen — für den Picker."""
        result: list[dict] = []
        if self.registry is None:
            return result
        for loaded in self.registry.iconsets:
            names = self.list_icons(loaded.id)
            result.append(
                {
                    "id": loaded.id,
                    "name": loaded.manifest.name,
                    "license": loaded.manifest.license,
                    "count": len(names),
                    "icons": names,
                }
            )
        return result

    def list_icons(self, set_id: str) -> list[str]:
        loaded = self.registry.get(set_id) if self.registry else None
        if loaded is None or not loaded.is_iconset:
            return []
        directory = loaded.icons_path
        if not directory.is_dir():
            return []
        return sorted(p.stem for p in directory.glob("*.svg"))

    def icon_svg_source(self, set_id: str, name: str) -> str | None:
        """Roh-SVG für die Icon-Vorschau in der GUI."""
        path = self._icon_path(set_id, name)
        if path is None:
            return None
        try:
            return path.read_text(encoding="utf-8")
        except OSError:
            return None

    def load_upload_image(
        self, filename: str, frame_time: float = 0.0
    ) -> Image.Image | None:
        """Hochgeladenes Bild in Originalgröße (für Hintergrund-Uploads)."""
        path = self._upload_path(filename)
        if path is None:
            return None
        try:
            if path.suffix.lower() == ".svg":
                return self._raster_svg(path.read_text(encoding="utf-8"), 512, None)
            frames = self._raw_frames(path)
            if not frames:
                return None
            return _pick_frame(frames, frame_time)
        except Exception as exc:
            log.warning("Upload '%s' nicht lesbar: %s", filename, exc)
            return None

    # -- Animation ---------------------------------------------------------

    def is_animated_upload(self, filename: str | None) -> bool:
        """Hat diese Datei mehr als ein Einzelbild?

        Die Runtime fragt das zehnmal je Sekunde, um nur wirklich bewegte
        Kacheln neu zu zeichnen. Beantwortet wird es deshalb aus dem
        Dateikopf — die Bilder dafür zu dekodieren hieße, jedes GIF im
        Profil in den Speicher zu holen, auch wenn es niemand sieht.
        """
        if not filename:
            return False
        path = self._upload_path(filename)
        if path is None or path.suffix.lower() == ".svg":
            return False

        key = ("animated", str(path), path.stat().st_mtime_ns)
        cached = self._animated.get(key)
        if cached is not None:
            return cached

        try:
            with Image.open(path) as source:
                animated = getattr(source, "n_frames", 1) > 1
        except Exception:
            animated = False
        self._animated[key] = animated
        return animated

    def _raw_frames(self, path: Path) -> list[tuple[Image.Image, float]]:
        """Alle Einzelbilder einer Datei, mit Dauer — auf Maß gebracht.

        Herunterskaliert wird schon hier und nicht erst beim Zeichnen: In
        Originalauflösung gehalten, belegt ein gewöhnliches HD-GIF dreistellige
        Megabyte, obwohl davon nur eine 120-px-Kachel zu sehen ist.
        """
        key = ("frames", str(path), path.stat().st_mtime_ns)
        cached = self._frames.get(key)
        if cached is not None:
            return cached

        frames: list[tuple[Image.Image, float]] = []
        with Image.open(path) as source:
            count = getattr(source, "n_frames", 1)
            indices = range(count)
            # Zu viele Einzelbilder kosten nur Speicher — was darüber liegt,
            # sieht auf einer 120-px-Kachel ohnehin niemand. Ausgelassen wird
            # gleichmäßig, damit die Animation ihre Länge behält.
            if count > MAX_FRAMES:
                step = count / MAX_FRAMES
                indices = [min(count - 1, int(i * step)) for i in range(MAX_FRAMES)]

            for index in indices:
                source.seek(index)
                # ``copy`` ist Pflicht: Pillow gibt bei animierten Dateien
                # immer denselben Puffer zurück, der beim nächsten ``seek``
                # überschrieben wird.
                frame = source.convert("RGBA").copy()
                if max(frame.size) > MAX_FRAME_EDGE:
                    scale = MAX_FRAME_EDGE / max(frame.size)
                    frame = frame.resize(
                        (
                            max(1, round(frame.width * scale)),
                            max(1, round(frame.height * scale)),
                        ),
                        Image.LANCZOS,
                    )
                duration = float(source.info.get("duration", 100) or 100) / 1000
                frames.append((frame, max(0.02, duration)))

        self._frames[key] = frames
        return frames

    def placeholder(self, size: int, color: str | None = None) -> Image.Image:
        """Generischer Platzhalter — bewusst neutral, nicht als Fehler lesbar."""
        key = ("placeholder", size, color)
        cached = self._cache.get(key)
        if cached is not None:
            return cached.copy()

        image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        rgba = parse_color(color or "#9ca3af", (156, 163, 175, 255))
        inset = max(2, size // 8)
        radius = max(3, size // 6)
        draw.rounded_rectangle(
            (inset, inset, size - inset - 1, size - inset - 1),
            radius=radius,
            outline=rgba,
            width=max(2, size // 20),
        )
        dot = max(2, size // 12)
        cx = cy = size // 2
        draw.ellipse((cx - dot, cy - dot, cx + dot, cy + dot), fill=rgba)
        self._cache[key] = image
        return image.copy()

    # -- Intern ------------------------------------------------------------

    def _icon_path(self, set_id: str | None, name: str) -> Path | None:
        if self.registry is None or not name:
            return None
        candidates = []
        if set_id:
            loaded = self.registry.get(set_id)
            if loaded is not None and loaded.is_iconset:
                candidates.append(loaded)
        else:
            candidates.extend(self.registry.iconsets)

        for loaded in candidates:
            # Name kann "outline/volume" o. ä. enthalten — Traversal ausschließen.
            safe = Path(name).with_suffix(".svg")
            if safe.is_absolute() or ".." in safe.parts:
                continue
            path = loaded.icons_path / safe
            if path.is_file():
                return path
        return None

    def _load_from_set(
        self, set_id: str | None, name: str, size: int, color: str | None
    ) -> Image.Image | None:
        path = self._icon_path(set_id, name)
        if path is None and set_id is not None:
            # Icon fehlt im gewählten Set → in den anderen Sets nachsehen,
            # damit ein deinstalliertes Set nicht alle Tasten leert.
            path = self._icon_path(None, name)
        if path is None:
            return None

        key = ("set", str(path), size, color)
        cached = self._cache.get(key)
        if cached is not None:
            return cached.copy()

        try:
            image = self._raster_svg(path.read_text(encoding="utf-8"), size, color)
        except Exception as exc:
            log.warning("SVG '%s' nicht rasterbar: %s", path, exc)
            return None

        self._cache[key] = image
        return image.copy()

    def _upload_path(self, filename: str) -> Path | None:
        # Auch in den Touchstrip-Hintergründen suchen: die Auswahl trennt die
        # Ablagen, eine bereits eingestellte Datei muss aber weiter gefunden
        # werden — egal, in welcher der beiden sie liegt.
        candidate = paths.image_path(filename, self.uploads_dir, paths.WALLPAPERS_DIR)
        if candidate is None:
            return None
        if candidate.suffix.lower() not in ALLOWED_UPLOAD_SUFFIXES:
            return None
        return candidate

    def _load_upload(
        self, filename: str, size: int, color: str | None, frame_time: float = 0.0
    ) -> Image.Image | None:
        path = self._upload_path(filename)
        if path is None:
            return None

        stamp = path.stat().st_mtime_ns
        key = ("upload", str(path), stamp, size, color)
        cached = self._cache.get(key)
        if cached is not None:
            return cached.copy()

        try:
            if path.suffix.lower() == ".svg":
                image = self._raster_svg(path.read_text(encoding="utf-8"), size, color)
                self._cache[key] = image
                return image.copy()

            frames = self._raw_frames(path)
            if not frames:
                return None
            if len(frames) == 1:
                image = _fit_contain(frames[0][0], size)
                self._cache[key] = image
                return image.copy()

            # Animiert: alle Einzelbilder einmal auf Zielgröße bringen und
            # merken — pro Bild neu zu skalieren wäre bei zehn Bildern je
            # Sekunde und acht Tasten spürbar.
            scaled_key = ("scaled", str(path), stamp, size)
            scaled = self._frames.get(scaled_key)
            if scaled is None:
                scaled = [
                    (_fit_contain(frame, size), duration) for frame, duration in frames
                ]
                self._frames[scaled_key] = scaled
            return _pick_frame(scaled, frame_time).copy()
        except Exception as exc:
            log.warning("Upload '%s' nicht ladbar: %s", filename, exc)
            return None

    def _raster_svg(self, source: str, size: int, color: str | None) -> Image.Image:
        had_current_color = bool(_CURRENT_COLOR.search(source))
        if color and had_current_color:
            source = _CURRENT_COLOR.sub(color, source)

        png = cairosvg.svg2png(
            bytestring=source.encode("utf-8"),
            output_width=size,
            output_height=size,
            background_color="transparent",
        )
        image = Image.open(io.BytesIO(png)).convert("RGBA")

        if color and not had_current_color:
            # Set ohne currentColor: über die Alpha-Maske einfärben, damit die
            # Farbwahl in der GUI trotzdem sichtbar wirkt.
            image = _tint(image, color)
        return image


def _pick_frame(
    frames: list[tuple[Image.Image, float]], frame_time: float
) -> Image.Image:
    """Das Einzelbild, das zum Zeitpunkt ``frame_time`` zu sehen ist.

    Gerechnet wird über die tatsächlichen Anzeigedauern, nicht über eine
    feste Bildrate: Ein GIF mit langem Standbild und kurzer Bewegung läuft
    sonst falsch ab.
    """
    if not frames:
        raise ValueError("Keine Einzelbilder")
    if len(frames) == 1:
        return frames[0][0]

    total = sum(duration for _, duration in frames)
    position = frame_time % total if total > 0 else 0.0
    for image, duration in frames:
        if position < duration:
            return image
        position -= duration
    return frames[-1][0]


def _tint(image: Image.Image, color: str) -> Image.Image:
    rgba = parse_color(color, (255, 255, 255, 255))
    solid = Image.new("RGBA", image.size, (*rgba[:3], 255))
    solid.putalpha(image.getchannel("A"))
    return solid


def _fit_contain(image: Image.Image, size: int) -> Image.Image:
    """Bild proportional in ein Quadrat einpassen (transparent aufgefüllt)."""
    src_w, src_h = image.size
    scale = min(size / src_w, size / src_h)
    resized = image.resize(
        (max(1, round(src_w * scale)), max(1, round(src_h * scale))), Image.LANCZOS
    )
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.paste(
        resized, ((size - resized.width) // 2, (size - resized.height) // 2), resized
    )
    return canvas
