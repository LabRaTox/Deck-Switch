"""Uhr als Bildschirmschoner — eine Ziffer pro Taste.

Obere Reihe die Uhrzeit (Stunden, Minuten), untere Reihe das Datum (Tag,
Monat), beide zweistellig mit führender Null. Auf einem Deck mit vier
Spalten steht damit auf jeder Taste genau eine Ziffer.

Das Plugin malt dafür nicht einfach über die ganze Leinwand, sondern setzt
jede Ziffer mittig auf *ihre* Kachel — die App liefert die Geometrie in
``deck_layout`` mit. Ohne das landete die Hälfte der Ziffern in den Fugen
zwischen den Tasten und wäre nie zu sehen.
"""

from __future__ import annotations

import time

from PIL import Image, ImageDraw

from deckswitch.plugins.base import ScreensaverPlugin
from deckswitch.services.backgrounds import parse_color
from deckswitch.services.render import load_font

#: Anteil der Tastenhöhe, den eine Ziffer einnimmt.
DIGIT_HEIGHT = 0.72

#: Höhe der Beschriftung im Touchstrip, als Anteil der Streifenhöhe.
STRIP_TEXT_HEIGHT = 0.5

#: Wochentage selbst übersetzt, statt ``locale.setlocale`` zu rufen: Das
#: wirkt prozessweit und würde auch die Formatierung in allen anderen
#: Plugins verändern — ein hoher Preis für ein Wort.
DAYS = {
    "de": ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"],
    "en": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
}


class ClockScreensaver(ScreensaverPlugin):
    interval_s = 30.0

    def on_plugin_config_changed(self, config: dict) -> None:
        self._apply_interval(config)

    def _apply_interval(self, config: dict) -> None:
        # Ohne Sekundenanzeige ändert sich frühestens jede Minute etwas.
        # Trotzdem alle 30 s zeichnen, damit der Minutenwechsel nicht bis zu
        # einer Minute zu spät kommt.
        self.interval_s = 1.0 if config.get("show_seconds", False) else 30.0

    def render(self, size: tuple[int, int], elapsed_s: float) -> Image.Image:
        config = self.plugin_config
        self._apply_interval(config)

        colour = parse_color(config.get("color", "#e2e8f0"), (226, 232, 240, 255))
        now = time.localtime()

        image = Image.new("RGBA", size, (0, 0, 0, 255))
        draw = ImageDraw.Draw(image)

        layout = self.deck_layout
        if layout is None or not layout.keys:
            # Ohne Geometrie bleibt nur, die Uhrzeit mittig hinzuschreiben.
            # Sollte nicht vorkommen, ist aber besser als ein schwarzes Deck.
            self._fallback(draw, size, now, colour)
            return image

        # Obere Reihe Uhrzeit, untere Reihe Datum — beide zweistellig, damit
        # jede der vier Spalten genau eine Ziffer bekommt.
        digits = [
            f"{now.tm_hour:02d}{now.tm_min:02d}",
            f"{now.tm_mday:02d}{now.tm_mon:02d}",
        ]

        columns = self._columns(layout.keys)
        for index, (x, y, width, height) in enumerate(layout.keys):
            row, column = divmod(index, columns)
            if row >= len(digits) or column >= len(digits[row]):
                continue
            self._centered(
                draw,
                digits[row][column],
                (x + width / 2, y + height / 2),
                height * DIGIT_HEIGHT,
                colour,
            )

        if config.get("show_weekday", True):
            x, y, width, height = layout.strip
            language = self.services.config.app.language
            weekday = DAYS.get(language, DAYS["en"])[now.tm_wday]
            self._centered(
                draw,
                weekday,
                (x + width / 2, y + height / 2),
                height * STRIP_TEXT_HEIGHT,
                (*colour[:3], 160),
            )

        return image

    # -- Intern ------------------------------------------------------------

    def _columns(self, keys: list) -> int:
        """Spaltenzahl aus den Kachelpositionen ableiten.

        Alle Kacheln der ersten Reihe haben dieselbe y-Koordinate; sobald
        sie springt, fängt die zweite Reihe an. So bleibt das Plugin von
        der Tastenzahl unabhängig.
        """
        first_y = keys[0][1]
        for index, key in enumerate(keys):
            if key[1] != first_y:
                return index
        return len(keys)

    def _centered(self, draw, text, center, target_height, colour) -> None:
        """Setzt ``text`` mittig auf den Punkt ``center``."""
        font = load_font(max(8, round(target_height)), bold=True)
        left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
        draw.text(
            (
                center[0] - (right - left) / 2 - left,
                center[1] - (bottom - top) / 2 - top,
            ),
            text,
            font=font,
            fill=colour,
        )

    def _fallback(self, draw, size, now, colour) -> None:
        width, height = size
        self._centered(
            draw,
            time.strftime("%H:%M", now),
            (width / 2, height / 2),
            height * 0.4,
            colour,
        )
