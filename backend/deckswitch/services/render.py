"""Gemeinsames Rendering von Tasten und Touchstrip-Segmenten.

Die Anmutung ist bewusst an die offizielle Elgato-Software angelehnt: Icon
zentriert im oberen/mittleren Bereich, Label in ähnlicher Größe darunter.
Wer die Originalsoftware kennt, soll sich sofort zurechtfinden.

Jedes Action-Plugin liefert nur seinen State — gezeichnet wird hier. Plugins
dürfen ``render`` überschreiben (z. B. für den Lautstärke-Balken), bekommen
aber mit :meth:`draw_bar` & Co. Bausteine, damit sie es selten müssen.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from ..config import Appearance
from . import backgrounds
from .backgrounds import parse_color

log = logging.getLogger(__name__)

#: Schriften, in dieser Reihenfolge gesucht — als fontconfig-Muster, nicht
#: als Pfad: Arch legt Noto unter /usr/share/fonts/noto/ ab, Debian unter
#: /usr/share/fonts/truetype/noto/. Feste Pfade wären auf der falschen
#: Distribution still auf Pillows winzige Standardschrift zurückgefallen.
FONT_PATTERNS_REGULAR = ["Noto Sans", "DejaVu Sans", "Liberation Sans", "sans-serif"]
FONT_PATTERNS_BOLD = [
    "Noto Sans:bold",
    "DejaVu Sans:bold",
    "Liberation Sans:bold",
    "sans-serif:bold",
]

#: Nur für den Fall, dass fontconfig fehlt (minimale Container).
FONT_FALLBACK_PATHS = [
    "/usr/share/fonts/noto/NotoSans-Regular.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
    "/usr/share/fonts/TTF/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
]
FONT_FALLBACK_PATHS_BOLD = [
    p.replace("-Regular", "-Bold").replace("DejaVuSans", "DejaVuSans-Bold")
    for p in FONT_FALLBACK_PATHS
]


@lru_cache(maxsize=64)
def _resolve_font(family: str = "", bold: bool = False, italic: bool = False) -> str | None:
    """Sucht eine Schriftdatei über fontconfig, sonst über feste Pfade.

    ``family`` ist der Familienname, wie ihn auch die Schriftauswahl in der
    GUI anbietet. Leer heißt „irgendeine brauchbare serifenlose".
    """
    style = ""
    if bold:
        style += ":bold"
    if italic:
        style += ":italic"

    patterns = (
        [f"{family}{style}"]
        if family
        else [f"{p}{style}" for p in FONT_PATTERNS_REGULAR]
    )

    if shutil.which("fc-match"):
        for pattern in patterns:
            try:
                result = subprocess.run(
                    ["fc-match", pattern, "-f", "%{file}"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    check=False,
                )
            except (OSError, subprocess.SubprocessError):
                break
            path = result.stdout.strip()
            # fc-match liefert immer etwas — auch eine völlig andere Familie.
            # Nur echte TrueType-/OpenType-Dateien sind brauchbar.
            if path and Path(path).is_file() and path.lower().endswith((".ttf", ".otf")):
                return path

    for candidate in FONT_FALLBACK_PATHS_BOLD if bold else FONT_FALLBACK_PATHS:
        if Path(candidate).is_file():
            return candidate
    return None


@lru_cache(maxsize=128)
def load_font(
    size: int, bold: bool = False, family: str = "", italic: bool = False
) -> ImageFont.FreeTypeFont:
    path = _resolve_font(family, bold, italic)
    if path is not None:
        try:
            return ImageFont.truetype(path, size)
        except OSError as exc:
            log.warning("Schrift '%s' nicht ladbar: %s", path, exc)

    log.warning(
        "Keine TrueType-Schrift gefunden — Beschriftungen bleiben winzig. "
        "Abhilfe: ein Schriftpaket installieren (z. B. noto-fonts)."
    )
    return ImageFont.load_default()


@lru_cache(maxsize=1)
def list_font_families() -> list[str]:
    """Alle installierten Schriftfamilien — für die Auswahl in der GUI."""
    if not shutil.which("fc-list"):
        return []
    try:
        result = subprocess.run(
            ["fc-list", ":", "family"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return []

    families: set[str] = set()
    for line in result.stdout.splitlines():
        # Eine Zeile listet alle Namen einer Datei, durch Komma getrennt —
        # oft derselbe Name mehrfach übersetzt. Der erste reicht.
        name = line.split(",")[0].strip()
        if name:
            families.add(name)
    return sorted(families, key=str.lower)


class RenderService:
    def __init__(self, icons) -> None:
        self.icons = icons

    # -- Hauptweg ----------------------------------------------------------

    def render_slot(
        self,
        ctx,
        *,
        state: str | None = None,
        label_override: str | None = None,
        accent: str | None = None,
        icon_override: Image.Image | None = None,
        reserve_bottom: int = 0,
    ) -> Image.Image:
        """Standard-Layout: Hintergrund → Icon → Label.

        ``icon_override`` setzt ein fertiges Bild an die Stelle des Icons —
        für Plugins, deren Symbol aus der Ferne kommt (Serverlogo, Cover).
        Es wird unverändert übernommen; die Größe bestimmt :meth:`icon_px`.
        """
        appearance = ctx.appearance
        frame_time = getattr(ctx, "frame_time", 0.0)
        image = self.background(ctx.size, appearance, accent=accent, frame_time=frame_time)

        label = label_override if label_override is not None else appearance.label_text
        show_label = appearance.show_label and bool(label)

        icon_ref = appearance.icon_for_state(state)
        fallback_name = self._fallback_icon_name(ctx, state)

        # ``none`` heißt ausdrücklich „kein Symbol" — auch nicht das aus dem
        # Manifest. Genau das braucht ein fertig gestaltetes Tastenbild:
        # Symbol und Text stecken schon darin.
        if icon_ref is not None and icon_ref.kind == "none":
            icon_ref = None
            fallback_name = None

        self.compose(
            image,
            icon=icon_override
            if icon_override is not None
            else self.icons.resolve(
                icon_ref,
                size=self.icon_px(ctx.size, appearance.icon_size),
                fallback_name=fallback_name,
                fallback_set=self._active_set(ctx),
                color=appearance.label_color if icon_ref is None else None,
                frame_time=frame_time,
            )
            if (icon_ref is not None or fallback_name)
            else None,
            label=label if show_label else "",
            label_size=appearance.label_size,
            label_color=appearance.label_color,
            label_position=appearance.label_position,
            label_font=appearance.label_font,
            label_bold=appearance.label_bold,
            label_italic=appearance.label_italic,
            label_underline=appearance.label_underline,
            label_align=appearance.label_align,
            reserve_bottom=reserve_bottom,
        )
        return image

    def background(
        self,
        size: tuple[int, int],
        appearance: Appearance,
        *,
        accent: str | None = None,
        frame_time: float = 0.0,
    ) -> Image.Image:
        return backgrounds.render_background(
            size,
            appearance.background,
            accent=accent,
            upload_loader=self.icons.load_upload_image,
            frame_time=frame_time,
        )

    def compose(
        self,
        image: Image.Image,
        *,
        icon: Image.Image | None,
        label: str,
        label_size: int = 16,
        label_color: str = "#ffffff",
        label_position: str = "bottom",
        label_font: str = "",
        label_bold: bool = False,
        label_italic: bool = False,
        label_underline: bool = False,
        label_align: str = "center",
        reserve_bottom: int = 0,
    ) -> Image.Image:
        """Legt Icon und Label auf ein bestehendes Hintergrundbild.

        Getrennt von :meth:`render_slot`, damit ein Plugin eigenen Content
        zeichnen und trotzdem dasselbe Label-Layout erben kann.

        ``reserve_bottom`` hält unten Platz frei — für einen Pegelbalken.
        Ohne das legte sich der Balken schlicht über das Label, denn das
        steht standardmäßig genau dort.
        """
        width, height = image.size
        # Nutzbare Höhe: Was unten reserviert ist, gibt es fürs Layout nicht.
        nutzbar = max(1, height - max(0, reserve_bottom))
        draw = ImageDraw.Draw(image)

        font = load_font(
            max(6, int(label_size)), bold=label_bold, family=label_font, italic=label_italic
        )
        lines = self._wrap(draw, label, font, width - 6) if label else []
        line_height = int(label_size * 1.15)
        text_block = len(lines) * line_height

        pad = max(2, height // 20)
        if label_position == "top":
            text_top = pad
        elif label_position == "center":
            text_top = (nutzbar - text_block) // 2
        else:
            text_top = nutzbar - text_block - pad

        # Das Icon sitzt immer mittig auf der Kachel — unabhängig davon, wo
        # das Label steht. Es am Restplatz auszurichten ließe es beim
        # Umstellen der Textposition sichtbar springen; der Text liegt
        # stattdessen darüber und bleibt durch seinen dunklen Rand lesbar.
        if icon is not None:
            icon_x = (width - icon.width) // 2
            icon_y = (nutzbar - icon.height) // 2
            image.alpha_composite(icon, (max(0, icon_x), max(0, icon_y)))

        if lines:
            color = parse_color(label_color, (255, 255, 255, 255))
            for i, line in enumerate(lines):
                y = text_top + i * line_height
                bbox = draw.textbbox((0, 0), line, font=font)
                text_width = bbox[2] - bbox[0]
                if label_align == "left":
                    x = pad - bbox[0]
                elif label_align == "right":
                    x = width - pad - text_width - bbox[0]
                else:
                    x = (width - text_width) // 2 - bbox[0]
                # Dünner dunkler Rand hält den Text auch auf hellen
                # Hintergründen lesbar.
                draw.text((x, y), line, font=font, fill=color,
                          stroke_width=1, stroke_fill=(0, 0, 0, 190))
                if label_underline:
                    # Pillow kennt kein Unterstreichen — die Linie wird
                    # gezogen, wo die Schrift ihre Unterlänge beginnt.
                    baseline = y + bbox[3] + max(1, label_size // 12)
                    thickness = max(1, label_size // 12)
                    draw.line(
                        [(x + bbox[0], baseline), (x + bbox[0] + text_width, baseline)],
                        fill=color,
                        width=thickness,
                    )
        return image

    # -- Bausteine für Plugins --------------------------------------------

    def bar_box(self, size: tuple[int, int]) -> tuple[int, int, int, int]:
        """Zone für einen Pegelbalken am unteren Rand — proportional.

        Feste Pixelabstände sind hier eine Falle: Der Touchstrip des Geräts
        ist 200×100 groß, ein virtuelles Deck legt seine Dial-Segmente aber
        frei fest. Bei halber Höhe saß ein fest gesetzter Balken mitten im
        Text darüber. Alles hängt deshalb an der tatsächlichen Höhe.
        """
        width, height = size
        rand = max(4, round(height * 0.08))
        balken = max(4, round(height * 0.11))
        return (rand, height - rand - balken, width - rand, height - rand)

    def bar_reserve(self, size: tuple[int, int], box: tuple[int, int, int, int]) -> int:
        """Wie viel Höhe ein Balken unten belegt — für ``reserve_bottom``."""
        return max(0, size[1] - box[1])

    def draw_bar(
        self,
        image: Image.Image,
        value: float,
        *,
        box: tuple[int, int, int, int] | None = None,
        color: str = "#3b82f6",
        track: str = "#3f3f46",
        radius: int | None = None,
    ) -> None:
        """Waagerechter Fortschritts-/Pegelbalken (0.0 … 1.0)."""
        width, height = image.size
        if box is None:
            bar_h = max(6, height // 10)
            box = (12, height - bar_h - 10, width - 12, height - 10)
        x0, y0, x1, y1 = box
        if radius is None:
            radius = max(2, (y1 - y0) // 2)

        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle(box, radius=radius, fill=parse_color(track, (63, 63, 70, 255)))

        value = max(0.0, min(1.0, value))
        filled = round((x1 - x0) * value)
        if filled >= 2:
            draw.rounded_rectangle(
                (x0, y0, x0 + filled, y1),
                radius=radius,
                fill=parse_color(color, (59, 130, 246, 255)),
            )

    def draw_text(
        self,
        image: Image.Image,
        text: str,
        *,
        y: int,
        size: int = 16,
        color: str = "#ffffff",
        bold: bool = False,
    ) -> None:
        draw = ImageDraw.Draw(image)
        font = load_font(max(6, size), bold=bold)
        bbox = draw.textbbox((0, 0), text, font=font)
        x = (image.width - (bbox[2] - bbox[0])) // 2 - bbox[0]
        draw.text((x, y), text, font=font, fill=parse_color(color, (255, 255, 255, 255)),
                  stroke_width=1, stroke_fill=(0, 0, 0, 190))

    def draw_text_at(
        self,
        image: Image.Image,
        text: str,
        *,
        x: int,
        y: int,
        size: int = 14,
        color: str = "#ffffff",
        max_width: int | None = None,
        bold: bool = False,
        align: str = "left",
    ) -> None:
        """Einzeiliger Text an fester Position, bei Bedarf mit „…“ gekürzt.

        Für Segment-Layouts, in denen Umbruch keinen Platz hat.
        """
        draw = ImageDraw.Draw(image)
        font = load_font(max(6, size), bold=bold)
        if max_width is not None:
            text = _ellipsize(draw, text, font, max_width)
        width = draw.textlength(text, font=font)
        if align == "right":
            x = int(x - width)
        elif align == "center":
            x = int(x - width / 2)
        draw.text(
            (x, y),
            text,
            font=font,
            fill=parse_color(color, (255, 255, 255, 255)),
            stroke_width=1,
            stroke_fill=(0, 0, 0, 190),
        )

    def draw_badge(
        self, image: Image.Image, color: str = "#22c55e", *, width: int = 4
    ) -> None:
        """Farbiger Rahmen — z. B. „dieses Ausgabegerät ist gerade aktiv“."""
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle(
            (0, 0, image.width - 1, image.height - 1),
            radius=max(4, image.width // 12),
            outline=parse_color(color, (34, 197, 94, 255)),
            width=width,
        )

    # -- Sonderkacheln -----------------------------------------------------

    def blank(self, size: tuple[int, int], color: str = "#000000") -> Image.Image:
        return Image.new("RGBA", size, parse_color(color))

    def empty_slot(self, size: tuple[int, int]) -> Image.Image:
        """Unbelegte Taste: fast schwarz mit angedeutetem Rahmen."""
        image = Image.new("RGBA", size, (10, 10, 11, 255))
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle(
            (2, 2, size[0] - 3, size[1] - 3),
            radius=max(4, size[0] // 12),
            outline=(32, 32, 36, 255),
            width=2,
        )
        return image

    def error_slot(self, size: tuple[int, int], text: str = "Fehler") -> Image.Image:
        """Kachel für ein Plugin, dessen ``render`` geworfen hat.

        Der Fehler soll auf dem Gerät auffallen, nicht nur im Log stehen.
        """
        image = Image.new("RGBA", size, (60, 10, 12, 255))
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle(
            (1, 1, size[0] - 2, size[1] - 2),
            radius=max(4, size[0] // 12),
            outline=(220, 38, 38, 255),
            width=3,
        )
        font = load_font(max(9, size[1] // 8), bold=True)
        lines = self._wrap(draw, text, font, size[0] - 10)[:3]
        line_h = font.size + 2
        top = (size[1] - len(lines) * line_h) // 2
        for i, line in enumerate(lines):
            bbox = draw.textbbox((0, 0), line, font=font)
            x = (size[0] - (bbox[2] - bbox[0])) // 2 - bbox[0]
            draw.text((x, top + i * line_h), line, font=font, fill=(255, 226, 226, 255))
        return image

    @staticmethod
    def icon_px(size: tuple[int, int], percent: int) -> int:
        """Kantenlänge des Icons auf einer Kachel dieser Größe.

        Öffentlich, damit ein Plugin sein eigenes Bild (siehe
        ``icon_override``) genauso groß hinlegt wie ein normales Icon.
        """
        short_edge = min(size)
        return max(8, round(short_edge * max(5, min(100, percent)) / 100))

    # -- Intern ------------------------------------------------------------

    @staticmethod
    def _active_set(ctx) -> str | None:
        try:
            return ctx.services.config.app.active_iconset
        except AttributeError:
            return None

    @staticmethod
    def _fallback_icon_name(ctx, state: str | None) -> str | None:
        """``default_icon`` aus dem Manifest — pro State, sonst pro Action."""
        registry = getattr(ctx.services.runtime, "registry", None)
        if registry is None:
            return None
        loaded = registry.get(ctx.slot.plugin_id)
        if loaded is None:
            return None
        action = loaded.manifest.action(ctx.action_id)
        if action is None:
            return None
        if state:
            for entry in action.states:
                if entry.id == state and entry.default_icon:
                    return entry.default_icon
        return action.default_icon

    @staticmethod
    def _wrap(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> list[str]:
        """Wortweiser Umbruch; überlange Wörter werden hart getrennt."""
        if not text:
            return []
        lines: list[str] = []
        for paragraph in text.split("\n"):
            current = ""
            for word in paragraph.split(" "):
                candidate = f"{current} {word}".strip()
                if draw.textlength(candidate, font=font) <= max_width or not current:
                    current = candidate
                else:
                    lines.append(current)
                    current = word
            while draw.textlength(current, font=font) > max_width and len(current) > 1:
                cut = len(current) - 1
                while cut > 1 and draw.textlength(current[:cut], font=font) > max_width:
                    cut -= 1
                lines.append(current[:cut])
                current = current[cut:]
            if current:
                lines.append(current)
        return lines[:3]


def _ellipsize(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> str:
    if draw.textlength(text, font=font) <= max_width:
        return text
    ellipsis = "…"
    cut = len(text)
    while cut > 0 and draw.textlength(text[:cut] + ellipsis, font=font) > max_width:
        cut -= 1
    return (text[:cut] + ellipsis) if cut > 0 else ""
