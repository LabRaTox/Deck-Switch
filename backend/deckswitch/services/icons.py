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


class IconService:
    def __init__(self, registry=None, uploads_dir: Path | None = None) -> None:
        self.registry = registry
        self.uploads_dir = uploads_dir or paths.UPLOADS_DIR
        self._cache: dict[tuple, Image.Image] = {}

    def bind_registry(self, registry) -> None:
        self.registry = registry
        self.clear_cache()

    def clear_cache(self) -> None:
        self._cache.clear()

    # -- Öffentliche API ---------------------------------------------------

    def resolve(
        self,
        icon: IconRef | None,
        *,
        size: int,
        fallback_name: str | None = None,
        fallback_set: str | None = None,
        color: str | None = None,
    ) -> Image.Image:
        """Liefert das Icon als RGBA-Bild in ``size``×``size``.

        ``fallback_name`` ist typischerweise das ``default_icon`` der Action
        aus dem Manifest — es greift, wenn der User nichts eigenes gewählt hat.
        """
        size = max(8, int(size))
        tint = (icon.color if icon and icon.color else color)

        if icon is not None and icon.kind == "upload" and icon.upload:
            image = self._load_upload(icon.upload, size, tint)
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

    def load_upload_image(self, filename: str) -> Image.Image | None:
        """Hochgeladenes Bild in Originalgröße (für Hintergrund-Uploads)."""
        path = self._upload_path(filename)
        if path is None:
            return None
        try:
            if path.suffix.lower() == ".svg":
                return self._raster_svg(path.read_text(encoding="utf-8"), 512, None)
            return Image.open(path).convert("RGBA")
        except Exception as exc:
            log.warning("Upload '%s' nicht lesbar: %s", filename, exc)
            return None

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

    def _load_upload(self, filename: str, size: int, color: str | None) -> Image.Image | None:
        path = self._upload_path(filename)
        if path is None:
            return None

        key = ("upload", str(path), path.stat().st_mtime_ns, size, color)
        cached = self._cache.get(key)
        if cached is not None:
            return cached.copy()

        try:
            if path.suffix.lower() == ".svg":
                image = self._raster_svg(path.read_text(encoding="utf-8"), size, color)
            else:
                image = _fit_contain(Image.open(path).convert("RGBA"), size)
        except Exception as exc:
            log.warning("Upload '%s' nicht ladbar: %s", filename, exc)
            return None

        self._cache[key] = image
        return image.copy()

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
