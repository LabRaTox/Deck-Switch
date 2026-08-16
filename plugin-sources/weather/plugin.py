"""Wetter, Vorhersage und Luftqualität auf Tasten und Dials.

Datenquelle ist Open-Meteo: kein Konto, kein API-Schlüssel, keine
Einrichtung außer der Ortsangabe. Ortssuche, Wetter und Luftqualität kommen
alle von dort.

Die Daten werden alle paar Minuten geholt und zwischengespeichert — das
Rendering greift immer auf den gespiegelten Zustand zu und wartet nie auf
das Netz.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from datetime import datetime

from PIL import Image, ImageDraw

from deckswitch.plugins.base import ActionPlugin
from deckswitch.services.backgrounds import parse_color

from api import Location, OpenMeteo, WeatherData, WeatherError, aqi_band, describe, icon_for

ACCENT = "#0ea5e9"

#: So lange bleibt die eingeblendete Zusatzinfo nach einem Druck stehen.
DETAIL_S = 4.0

#: Am Dial wird in Dreistundenschritten geblättert.
HOUR_STEP = 3


class WeatherPlugin(ActionPlugin):
    def __init__(self, manifest, services):
        super().__init__(manifest, services)
        self.api = OpenMeteo()
        self._task: asyncio.Task | None = None
        self._data: dict[str, WeatherData] = {}
        self._locations: dict[str, Location] = {}
        self._last_error: str | None = None

    # ======================================================================
    # Lebenszyklus
    # ======================================================================

    async def setup(self):
        self._task = asyncio.create_task(self._refresh_loop(), name="weather-refresh")

    async def teardown(self):
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    def on_plugin_config_changed(self, config):
        # Ort oder Einheiten geändert → alles neu holen.
        self._data.clear()
        self._locations.clear()
        self.run_async(self._refresh_all(force=True))

    async def _refresh_loop(self):
        while True:
            await self._refresh_all()
            minutes = max(5, int(self.plugin_config.get("refresh_minutes") or 10))
            await asyncio.sleep(minutes * 60)

    async def _refresh_all(self, *, force: bool = False):
        """Holt die Daten für alle gerade verwendeten Orte."""
        wanted = set(self._locations)
        if not wanted:
            default = self.plugin_config.get("location")
            if default:
                wanted.add(str(default))

        changed = False
        for key in wanted:
            if await self._fetch(key, force=force):
                changed = True

        if changed:
            self.services.runtime.request_redraw()
            self.services.runtime.publish_plugin_status(self.manifest.id)

    async def _fetch(self, key: str, *, force: bool = False) -> bool:
        location = self._locations.get(key) or await self._resolve(key)
        if location is None:
            return False

        units = self._units()
        try:
            data = await self._in_thread(
                lambda: self.api.fetch(location, units=units, force=force)
            )
        except WeatherError as exc:
            if self._last_error != str(exc):
                self._last_error = str(exc)
                self.notify_error(f"Wetter: {exc}")
            return False

        self._last_error = None
        previous = self._data.get(key)
        self._data[key] = data
        return previous is None or previous.fetched_at != data.fetched_at

    async def _resolve(self, key: str) -> Location | None:
        try:
            location = await self._in_thread(
                lambda: self.api.resolve(key, language=self._language())
            )
        except WeatherError as exc:
            self.notify_error(f"Ort '{key}' nicht auflösbar: {exc}")
            return None
        if location is None:
            self.notify_error(f"Ort '{key}' nicht gefunden")
            return None
        self._locations[key] = location
        return location

    async def _in_thread(self, function):
        return await asyncio.get_running_loop().run_in_executor(None, function)

    # ======================================================================
    # Ort und Einstellungen
    # ======================================================================

    def _units(self) -> str:
        return "imperial" if self.plugin_config.get("units") == "imperial" else "metric"

    def _language(self) -> str:
        try:
            return self.services.config.app.language
        except AttributeError:
            return "de"

    def _location_key(self, settings) -> str:
        """Welcher Ort gilt für diese Belegung — eigener oder der globale."""
        override = (settings.get("location_override") or "").strip()
        return override or str(self.plugin_config.get("location") or "").strip()

    def _weather(self, settings) -> WeatherData | None:
        key = self._location_key(settings)
        if not key:
            return None
        data = self._data.get(key)
        if data is None:
            # Noch nie geholt (z. B. frisch belegte Taste) — im Hintergrund
            # nachziehen, diesmal aber ohne Daten zeichnen.
            self.run_async(self._fetch_and_redraw(key))
        return data

    async def _fetch_and_redraw(self, key: str):
        if await self._fetch(key):
            self.services.runtime.request_redraw()

    def get_status(self):
        key = str(self.plugin_config.get("location") or "").strip()
        if not key:
            return {"connected": False, "detail": "kein Ort eingestellt"}
        data = self._data.get(key)
        if data is None:
            return {"connected": False, "detail": self._last_error or "noch keine Daten"}
        temperature = data.current.get("temperature_2m")
        return {
            "connected": True,
            "detail": f"{data.location.name} · {_round(temperature)}{self._degree()}",
        }

    def _degree(self) -> str:
        return "°F" if self._units() == "imperial" else "°C"

    # ======================================================================
    # Eingaben
    # ======================================================================

    async def on_key_down(self, action_id, settings, ctx):
        # Kurzer Druck blendet Zusatzinfos ein; bei fehlenden Daten wird
        # stattdessen ein neuer Versuch gestartet.
        key = self._location_key(settings)
        if key and self._data.get(key) is None:
            await self._fetch(key)
        ctx.scratch["detail_until"] = time.monotonic() + DETAIL_S
        ctx.request_redraw()

    async def on_dial_push(self, action_id, settings, ctx):
        if action_id == "current":
            # Ansicht durchschalten: Stundenverlauf → Diagramm → Details
            views = ["hourly", "chart", "details"]
            current = ctx.scratch.get("view") or ctx.setting("dial_view", "hourly")
            ctx.scratch["view"] = views[(views.index(current) + 1) % len(views)] if current in views else views[0]
        else:
            ctx.scratch["detail_until"] = time.monotonic() + DETAIL_S
        ctx.request_redraw()

    async def on_dial_rotate(self, action_id, settings, delta, ctx):
        if action_id == "current":
            # Durch den Tagesverlauf blättern, in Dreistundenschritten.
            offset = int(ctx.scratch.get("hour_offset", 0)) + delta * HOUR_STEP
            ctx.scratch["hour_offset"] = max(0, min(48, offset))
        elif action_id == "forecast":
            day = int(ctx.scratch.get("day", int(ctx.setting("day", 1)))) + delta
            ctx.scratch["day"] = max(0, min(6, day))
        ctx.request_redraw()

    async def on_touch(self, action_id, settings, x, y, ctx):
        ctx.scratch["detail_until"] = time.monotonic() + DETAIL_S
        ctx.request_redraw()

    def on_tick(self, action_id, settings, ctx):
        # Eingeblendete Zusatzinfo wieder abräumen.
        until = ctx.scratch.get("detail_until", 0)
        if until and until < time.monotonic():
            ctx.scratch["detail_until"] = 0
            ctx.request_redraw()

    # ======================================================================
    # Darstellung
    # ======================================================================

    def get_state(self, action_id, settings, ctx):
        return "ok" if self._weather(settings) is not None else "offline"

    def render(self, action_id, settings, ctx):
        data = self._weather(settings)
        if data is None:
            return self._render_missing(ctx)

        if ctx.input_type == "dial":
            if action_id == "current":
                return self._render_current_segment(settings, ctx, data)
            if action_id == "forecast":
                return self._render_forecast_segment(settings, ctx, data)
            return self._render_air_segment(settings, ctx, data)

        if action_id == "current":
            return self._render_current_key(settings, ctx, data)
        if action_id == "forecast":
            return self._render_forecast_key(settings, ctx, data)
        return self._render_air_key(settings, ctx, data)

    def _render_missing(self, ctx):
        render = self.services.render
        image = render.background(ctx.size, ctx.appearance, accent=ACCENT)
        icon = self.services.icons.resolve(
            ctx.appearance.icon_for_state("offline"),
            size=max(20, round(min(ctx.size) * 0.4)),
            fallback_name="cloud-off",
            fallback_set=self.services.config.app.active_iconset,
            color="#6b7280",
        )
        image.alpha_composite(icon, ((ctx.size[0] - icon.width) // 2,
                                     (ctx.size[1] - icon.height) // 2 - 8))
        render.draw_text(image, "kein Ort" if not self.plugin_config.get("location")
                         else "…", y=ctx.size[1] - 24, size=13, color="#9ca3af")
        return image

    # -- Aktuelles Wetter --------------------------------------------------

    def _render_current_key(self, settings, ctx, data: WeatherData):
        render = self.services.render
        image = render.background(ctx.size, ctx.appearance, accent=ACCENT)
        width, height = ctx.size

        current = data.current
        code = current.get("weather_code")
        is_day = bool(current.get("is_day", 1))
        showing_detail = ctx.scratch.get("detail_until", 0) > time.monotonic()
        mode = "high_low" if showing_detail else ctx.setting("show", "temp_condition")

        icon = self.services.icons.resolve(
            ctx.appearance.icon_for_state("ok"),
            size=max(24, round(min(ctx.size) * ctx.appearance.icon_size / 100 * 0.8)),
            fallback_name=icon_for(code, is_day),
            fallback_set=self.services.config.app.active_iconset,
            color=ctx.appearance.label_color,
        )
        image.alpha_composite(icon, ((width - icon.width) // 2, 8))

        temperature = f"{_round(current.get('temperature_2m'))}{self._degree()}"
        render.draw_text(image, temperature, y=height - 46, size=26,
                         color=ctx.appearance.label_color, bold=True)

        daily = data.daily
        if mode == "high_low" and daily.get("temperature_2m_max"):
            second = (
                f"{_round(daily['temperature_2m_min'][0])}° / "
                f"{_round(daily['temperature_2m_max'][0])}°"
            )
        elif mode == "temp_location":
            second = data.location.name
        elif mode == "temp":
            second = ""
        else:
            second = describe(code, self._language())

        if second:
            render.draw_text_at(image, second, x=width // 2, y=height - 18, size=12,
                                color="#c7c7d1", align="center", max_width=width - 8)
        return image

    def _render_current_segment(self, settings, ctx, data: WeatherData):
        view = ctx.scratch.get("view") or ctx.setting("dial_view", "hourly")
        if view == "chart":
            return self._render_chart(ctx, data)
        if view == "details":
            return self._render_details(ctx, data)
        return self._render_hourly(ctx, data)

    def _render_hourly(self, ctx, data: WeatherData):
        """Stundenverlauf: gewählte Stunde groß, Uhrzeit und Regenrisiko dazu."""
        render = self.services.render
        image = render.background(ctx.size, ctx.appearance, accent=ACCENT)
        width, height = ctx.size

        index = self._hour_index(data, ctx.scratch.get("hour_offset", 0))
        hourly = data.hourly
        if index is None:
            render.draw_text(image, "—", y=height // 2 - 10, size=20, color="#9ca3af")
            return image

        temperature = hourly["temperature_2m"][index]
        code = hourly.get("weather_code", [None])[index]
        rain = (hourly.get("precipitation_probability") or [None])[index]
        stamp = _hour_label(hourly["time"][index])

        icon = self.services.icons.resolve(
            None,
            size=max(28, height - 44),
            fallback_name=icon_for(code, _is_daytime(hourly["time"][index])),
            fallback_set=self.services.config.app.active_iconset,
            color=ctx.appearance.label_color,
        )
        image.alpha_composite(icon, (10, (height - icon.height) // 2))

        left = 10 + icon.width + 10
        render.draw_text_at(image, f"{data.location.name} · {stamp}", x=left, y=8,
                            size=12, color="#c7c7d1", max_width=width - left - 12)
        render.draw_text_at(image, f"{_round(temperature)}{self._degree()}", x=left, y=30,
                            size=24, color=ctx.appearance.label_color, bold=True)
        if rain is not None:
            render.draw_text_at(image, f"{_round(rain)}% Regen", x=width - 12, y=36,
                                size=12, color="#93c5fd", align="right")
        _hint(render, image, "drehen: Stunden · drücken: Ansicht")
        return image

    def _render_details(self, ctx, data: WeatherData):
        render = self.services.render
        image = render.background(ctx.size, ctx.appearance, accent=ACCENT)
        width, height = ctx.size
        current = data.current
        daily = data.daily

        render.draw_text_at(image, data.location.name, x=10, y=6, size=12,
                            color="#c7c7d1", max_width=width - 20)

        entries = [
            ("Gefühlt", f"{_round(current.get('apparent_temperature'))}{self._degree()}"),
            ("Regen", f"{_round((data.hourly.get('precipitation_probability') or [0])[0])}%"),
            ("Wind", f"{_round(current.get('wind_speed_10m'))}"),
            ("UV", f"{_round((daily.get('uv_index_max') or [None])[0])}"),
        ]
        column = width // len(entries)
        for i, (label, value) in enumerate(entries):
            x = i * column + column // 2
            render.draw_text_at(image, label, x=x, y=30, size=11, color="#9ca3af",
                                align="center")
            render.draw_text_at(image, value, x=x, y=46, size=17,
                                color=ctx.appearance.label_color, align="center", bold=True)
        _hint(render, image, "drücken: Ansicht")
        return image

    def _render_chart(self, ctx, data: WeatherData):
        """Temperaturverlauf der nächsten 24 Stunden als Liniendiagramm."""
        render = self.services.render
        image = render.background(ctx.size, ctx.appearance, accent=ACCENT)
        width, height = ctx.size

        hourly = data.hourly
        temperatures = (hourly.get("temperature_2m") or [])[:24]
        times = (hourly.get("time") or [])[:24]
        if len(temperatures) < 2:
            render.draw_text(image, "—", y=height // 2 - 10, size=18, color="#9ca3af")
            return image

        low, high = min(temperatures), max(temperatures)
        span = max(0.5, high - low)
        top, bottom = 26, height - 16
        draw = ImageDraw.Draw(image)

        points = [
            (
                8 + i * (width - 16) / (len(temperatures) - 1),
                bottom - (value - low) / span * (bottom - top),
            )
            for i, value in enumerate(temperatures)
        ]

        # Fläche unter der Kurve, damit der Verlauf auch bei 100 px Höhe
        # sofort lesbar ist.
        area = [*points, (points[-1][0], bottom), (points[0][0], bottom)]
        overlay = Image.new("RGBA", ctx.size, (0, 0, 0, 0))
        ImageDraw.Draw(overlay).polygon(area, fill=(*parse_color(ACCENT)[:3], 70))
        image.alpha_composite(overlay)
        draw.line(points, fill=parse_color("#7dd3fc"), width=2, joint="curve")

        render.draw_text_at(image, f"{data.location.name} · 24 h", x=8, y=6, size=11,
                            color="#c7c7d1", max_width=width - 100)
        render.draw_text_at(image, f"{_round(high)}° / {_round(low)}°", x=width - 10, y=6,
                            size=12, color=ctx.appearance.label_color, align="right")

        # Zeitmarken alle sechs Stunden.
        for i in range(0, len(times), 6):
            render.draw_text_at(image, _hour_label(times[i]), x=points[i][0], y=height - 14,
                                size=9, color="#9ca3af", align="center")
        return image

    # -- Vorhersage --------------------------------------------------------

    def _day_index(self, settings, ctx) -> int:
        if ctx.input_type == "dial":
            return int(ctx.scratch.get("day", int(ctx.setting("day", 1))))
        return max(0, min(6, int(ctx.setting("day", 1))))

    def _render_forecast_key(self, settings, ctx, data: WeatherData):
        render = self.services.render
        image = render.background(ctx.size, ctx.appearance, accent=ACCENT)
        width, height = ctx.size
        daily = data.daily
        index = self._day_index(settings, ctx)

        if not daily.get("time") or index >= len(daily["time"]):
            return self._render_missing(ctx)

        icon = self.services.icons.resolve(
            ctx.appearance.icon_for_state("ok"),
            size=max(22, round(min(ctx.size) * ctx.appearance.icon_size / 100 * 0.7)),
            fallback_name=icon_for(daily["weather_code"][index], True),
            fallback_set=self.services.config.app.active_iconset,
            color=ctx.appearance.label_color,
        )
        image.alpha_composite(icon, ((width - icon.width) // 2, 20))

        render.draw_text_at(image, _day_label(daily["time"][index], self._language()),
                            x=width // 2, y=4, size=12, color="#c7c7d1", align="center")
        render.draw_text_at(
            image,
            f"{_round(daily['temperature_2m_max'][index])}° / "
            f"{_round(daily['temperature_2m_min'][index])}°",
            x=width // 2, y=height - 34, size=17,
            color=ctx.appearance.label_color, align="center", bold=True,
        )

        if ctx.setting("show_rain", True):
            rain = (daily.get("precipitation_probability_max") or [None])[index]
            if rain is not None:
                render.draw_text_at(image, f"{_round(rain)}% Regen", x=width // 2,
                                    y=height - 16, size=11, color="#93c5fd", align="center")
        return image

    def _render_forecast_segment(self, settings, ctx, data: WeatherData):
        """Mehrere Tage nebeneinander, der gewählte hervorgehoben."""
        render = self.services.render
        image = render.background(ctx.size, ctx.appearance, accent=ACCENT)
        width, height = ctx.size
        daily = data.daily
        if not daily.get("time"):
            return self._render_missing(ctx)

        selected = self._day_index(settings, ctx)
        days = min(5, len(daily["time"]))
        column = width // days

        # Die Hervorhebung muss über ein Overlay laufen: ImageDraw ersetzt die
        # Pixel, statt die Alphawerte zu verrechnen — ein halbtransparentes
        # Weiß würde sonst als deckender Block landen.
        if 0 <= selected < days:
            overlay = Image.new("RGBA", ctx.size, (0, 0, 0, 0))
            ImageDraw.Draw(overlay).rounded_rectangle(
                (selected * column + 2, 2, selected * column + column - 2, height - 2),
                radius=6,
                fill=(255, 255, 255, 28),
            )
            image.alpha_composite(overlay)

        for i in range(days):
            centre = i * column + column // 2
            render.draw_text_at(image, _day_label(daily["time"][i], self._language(), short=True),
                                x=centre, y=6, size=10, color="#c7c7d1", align="center")

            icon = self.services.icons.resolve(
                None, size=22,
                fallback_name=icon_for(daily["weather_code"][i], True),
                fallback_set=self.services.config.app.active_iconset,
                color=ctx.appearance.label_color,
            )
            image.alpha_composite(icon, (centre - icon.width // 2, 20))

            # Höchst- und Tiefstwert untereinander: nebeneinander passen sie
            # bei fünf Spalten auf 200 px nicht ohne Überlappung.
            render.draw_text_at(
                image, f"{_round(daily['temperature_2m_max'][i])}°",
                x=centre, y=height - 30, size=11,
                color=ctx.appearance.label_color, align="center",
                max_width=column - 4,
            )
            render.draw_text_at(
                image, f"{_round(daily['temperature_2m_min'][i])}°",
                x=centre, y=height - 16, size=10, color="#9ca3af", align="center",
                max_width=column - 4,
            )
        return image

    # -- Luftqualität ------------------------------------------------------

    def _aqi_value(self, settings, data: WeatherData):
        field = "us_aqi" if settings.get("scale") == "us" else "european_aqi"
        return data.air.get(field)

    def _render_air_key(self, settings, ctx, data: WeatherData):
        render = self.services.render
        value = self._aqi_value(settings, data)
        label, color = aqi_band(
            data.air.get("european_aqi"), self._language()
        )
        use_color = ctx.setting("color_by_severity", True)

        image = render.background(ctx.size, ctx.appearance, accent=color if use_color else ACCENT)
        width, height = ctx.size

        if value is None:
            return self._render_missing(ctx)

        showing_detail = ctx.scratch.get("detail_until", 0) > time.monotonic()

        render.draw_text_at(image, "AQI", x=width // 2, y=8, size=12, color="#c7c7d1",
                            align="center")
        render.draw_text_at(image, str(_round(value)), x=width // 2, y=28, size=32,
                            color=color if use_color else ctx.appearance.label_color,
                            align="center", bold=True)

        if showing_detail:
            second = f"PM2.5 {_round(data.air.get('pm2_5'))} · PM10 {_round(data.air.get('pm10'))}"
        else:
            second = label
        render.draw_text_at(image, second, x=width // 2, y=height - 20, size=11,
                            color="#e5e7eb", align="center", max_width=width - 6)
        return image

    def _render_air_segment(self, settings, ctx, data: WeatherData):
        render = self.services.render
        value = self._aqi_value(settings, data)
        label, color = aqi_band(data.air.get("european_aqi"), self._language())
        image = render.background(ctx.size, ctx.appearance,
                                  accent=color if ctx.setting("color_by_severity", True) else ACCENT)
        width, height = ctx.size
        if value is None:
            return self._render_missing(ctx)

        render.draw_text_at(image, f"{data.location.name} · Luftqualität", x=10, y=8,
                            size=12, color="#c7c7d1", max_width=width - 20)
        render.draw_text_at(image, str(_round(value)), x=14, y=28, size=30,
                            color=color, bold=True)
        render.draw_text_at(image, label, x=90, y=38, size=14, color="#e5e7eb")

        details = f"PM2.5 {_round(data.air.get('pm2_5'))}   PM10 {_round(data.air.get('pm10'))}"
        render.draw_text_at(image, details, x=width - 12, y=40, size=11,
                            color="#9ca3af", align="right")
        return image

    # ======================================================================
    # GUI
    # ======================================================================

    def get_dynamic_options(self, source, context=None):
        if source != "locations":
            return []

        query = ((context or {}).get("search") or "").strip()
        if len(query) < 2:
            # Bereits gewählten Ort weiter anbieten, damit er beim Öffnen der
            # Einstellungen nicht aus der Liste verschwindet.
            current = str(self.plugin_config.get("location") or "")
            location = Location.decode(current)
            return [{"value": current, "label": location.name or current}] if location else []

        try:
            results = self.api.search(query, language=self._language())
        except WeatherError as exc:
            self.log.warning("Ortssuche fehlgeschlagen: %s", exc)
            return []
        return [{"value": entry.encode(), "label": entry.label} for entry in results]

    async def gui_command(self, command, payload):
        if command == "status":
            return self.get_status() or {}
        if command == "refresh":
            await self._refresh_all(force=True)
            return {"ok": True, "locations": len(self._data)}
        raise NotImplementedError(f"Wetter kennt kein Kommando '{command}'")

    # -- Intern ------------------------------------------------------------

    @staticmethod
    def _hour_index(data: WeatherData, offset: int) -> int | None:
        """Index in der Stundenliste, ausgehend von der aktuellen Stunde."""
        times = data.hourly.get("time") or []
        if not times:
            return None
        now = datetime.now().strftime("%Y-%m-%dT%H:00")
        try:
            base = times.index(now)
        except ValueError:
            base = 0
        return max(0, min(len(times) - 1, base + int(offset)))


# --------------------------------------------------------------------------
# Formatierung
# --------------------------------------------------------------------------


def _round(value) -> str:
    if value is None:
        return "—"
    try:
        return str(round(float(value)))
    except (TypeError, ValueError):
        return "—"


def _hour_label(stamp: str) -> str:
    try:
        return datetime.fromisoformat(stamp).strftime("%H:%M")
    except (ValueError, TypeError):
        return "—"


def _is_daytime(stamp: str) -> bool:
    try:
        hour = datetime.fromisoformat(stamp).hour
    except (ValueError, TypeError):
        return True
    return 6 <= hour < 20


DAYS_DE = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
DAYS_EN = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _day_label(stamp: str, language: str = "de", short: bool = False) -> str:
    try:
        date = datetime.fromisoformat(stamp)
    except (ValueError, TypeError):
        return "—"
    today = datetime.now().date()
    if date.date() == today:
        return "Heute" if language.startswith("de") else "Today"
    names = DAYS_DE if language.startswith("de") else DAYS_EN
    name = names[date.weekday()]
    return name if short else f"{name} {date.day}."


def _hint(render, image: Image.Image, text: str) -> None:
    """Dezenter Bedienhinweis am unteren Rand eines Segments."""
    render.draw_text_at(image, text, x=image.width - 8, y=image.height - 14,
                        size=9, color="#6b7280", align="right")
