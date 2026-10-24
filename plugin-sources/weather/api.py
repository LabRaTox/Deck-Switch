"""Wetterdaten von Open-Meteo.

Open-Meteo braucht weder Konto noch API-Schlüssel und liefert alles aus einer
Hand: Ortssuche, aktuelles Wetter, stündliche und tägliche Vorhersage sowie
Luftqualität. Damit bleibt das Plugin so einrichtungsfrei wie möglich — man
tippt einen Ort ein, fertig.

Die Aufrufe sind blockierend (``urllib``); der Aufrufer führt sie im
Executor aus. Antworten werden zwischengespeichert, damit acht Kacheln nicht
acht Abfragen auslösen.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from deckswitch.plugins.base import plugin_text

log = logging.getLogger(__name__)

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
AIR_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"
USER_AGENT = "StreamDeckApp/0.1 (+local)"

#: So lange gelten abgerufene Daten als frisch. Wetter ändert sich nicht im
#: Sekundentakt, und die API soll nicht unnötig belastet werden.
CACHE_TTL_S = 600
GEOCODE_TTL_S = 86400

REQUEST_TIMEOUT_S = 12


class WeatherError(RuntimeError):
    pass


def _t(schluessel: str, **werte: Any) -> str:
    """Text aus den Sprachdateien dieses Plugins."""
    return plugin_text(Path(__file__).resolve().parent, "weather", schluessel, werte)


# --------------------------------------------------------------------------
# Wettercodes (WMO) → Text und Icon
# --------------------------------------------------------------------------

#: WMO-Code → (Schlüssel der Beschreibung, Icon bei Tag, Icon bei Nacht)
WMO: dict[int, tuple[str, str, str]] = {
    0: ("wetter_klar", "sun", "moon"),
    1: ("wetter_ueberwiegend_klar", "sun", "moon"),
    2: ("wetter_teils_bewoelkt", "cloud", "cloud"),
    3: ("wetter_bedeckt", "cloud", "cloud"),
    45: ("wetter_nebel", "cloud-fog", "cloud-fog"),
    48: ("wetter_reifnebel", "cloud-fog", "cloud-fog"),
    51: ("wetter_niesel_leicht", "cloud-rain", "cloud-rain"),
    53: ("wetter_niesel", "cloud-rain", "cloud-rain"),
    55: ("wetter_niesel_stark", "cloud-rain", "cloud-rain"),
    56: ("wetter_niesel_gefrierend", "cloud-snow", "cloud-snow"),
    57: ("wetter_niesel_gefrierend", "cloud-snow", "cloud-snow"),
    61: ("wetter_regen_leicht", "cloud-rain", "cloud-rain"),
    63: ("wetter_regen", "cloud-rain", "cloud-rain"),
    65: ("wetter_regen_stark", "cloud-rain", "cloud-rain"),
    66: ("wetter_regen_gefrierend", "cloud-snow", "cloud-snow"),
    67: ("wetter_regen_gefrierend", "cloud-snow", "cloud-snow"),
    71: ("wetter_schnee_leicht", "cloud-snow", "cloud-snow"),
    73: ("wetter_schnee", "cloud-snow", "cloud-snow"),
    75: ("wetter_schnee_stark", "cloud-snow", "cloud-snow"),
    77: ("wetter_schneegriesel", "snowflake", "snowflake"),
    80: ("wetter_regenschauer", "cloud-rain", "cloud-rain"),
    81: ("wetter_regenschauer", "cloud-rain", "cloud-rain"),
    82: ("wetter_schauer_stark", "cloud-rain", "cloud-rain"),
    85: ("wetter_schneeschauer", "cloud-snow", "cloud-snow"),
    86: ("wetter_schneeschauer", "cloud-snow", "cloud-snow"),
    95: ("wetter_gewitter", "cloud-storm", "cloud-storm"),
    96: ("wetter_gewitter_hagel", "cloud-bolt", "cloud-bolt"),
    99: ("wetter_gewitter_hagel", "cloud-bolt", "cloud-bolt"),
}


def describe(code: int | None) -> str:
    entry = WMO.get(int(code) if code is not None else -1)
    if entry is None:
        return "---"
    return _t(entry[0])


def icon_for(code: int | None, is_day: bool = True) -> str:
    entry = WMO.get(int(code) if code is not None else -1)
    if entry is None:
        return "cloud-off"
    return entry[1] if is_day else entry[2]


# --------------------------------------------------------------------------
# Luftqualität
# --------------------------------------------------------------------------

#: Europäischer AQI: (Obergrenze, Schlüssel der Bezeichnung, Farbe)
AQI_BANDS = [
    (20, "luft_sehr_gut", "#4ade80"),
    (40, "luft_gut", "#a3e635"),
    (60, "luft_mittel", "#facc15"),
    (80, "luft_schlecht", "#fb923c"),
    (100, "luft_sehr_schlecht", "#ef4444"),
    (10_000, "luft_extrem_schlecht", "#a21caf"),
]


#: US-AQI der EPA: (Obergrenze, Schlüssel der Bezeichnung, Farbe)
AQI_BANDS_US = [
    (50, "luft_us_gut", "#4ade80"),
    (100, "luft_us_maessig", "#facc15"),
    (150, "luft_us_empfindlich", "#fb923c"),
    (200, "luft_us_ungesund", "#ef4444"),
    (300, "luft_us_sehr_ungesund", "#a21caf"),
    (10_000, "luft_us_gefaehrlich", "#7f1d1d"),
]


def aqi_band(value: float | None, scale: str = "eu") -> tuple[str, str]:
    """Liefert (Bezeichnung, Farbe) zu einem AQI-Wert der gewählten Skala."""
    if value is None:
        return ("---", "#6b7280")
    for limit, label, color in (AQI_BANDS_US if scale == "us" else AQI_BANDS):
        if value <= limit:
            return (_t(label), color)
    return ("---", "#6b7280")


# --------------------------------------------------------------------------
# Datenmodelle
# --------------------------------------------------------------------------


@dataclass(slots=True)
class Location:
    name: str
    latitude: float
    longitude: float
    country: str = ""
    admin: str = ""

    @property
    def label(self) -> str:
        parts = [self.name]
        if self.admin and self.admin != self.name:
            parts.append(self.admin)
        if self.country:
            parts.append(self.country)
        return ", ".join(parts)

    def encode(self) -> str:
        """Kompakte Darstellung fürs Settings-Feld."""
        return f"{self.latitude:.4f},{self.longitude:.4f},{self.name}"

    @staticmethod
    def decode(value: str) -> "Location | None":
        if not value:
            return None
        parts = value.split(",", 2)
        if len(parts) < 2:
            return None
        try:
            return Location(
                name=parts[2].strip() if len(parts) > 2 else "",
                latitude=float(parts[0]),
                longitude=float(parts[1]),
            )
        except ValueError:
            return None


@dataclass(slots=True)
class WeatherData:
    location: Location
    fetched_at: float = 0.0
    current: dict[str, Any] = field(default_factory=dict)
    hourly: dict[str, list] = field(default_factory=dict)
    daily: dict[str, list] = field(default_factory=dict)
    air: dict[str, Any] = field(default_factory=dict)
    units: dict[str, str] = field(default_factory=dict)

    @property
    def stale(self) -> bool:
        return time.time() - self.fetched_at > CACHE_TTL_S


# --------------------------------------------------------------------------
# Client
# --------------------------------------------------------------------------


class OpenMeteo:
    def __init__(self) -> None:
        self._geocode_cache: dict[str, tuple[float, list[Location]]] = {}
        self._weather_cache: dict[str, WeatherData] = {}

    # -- Ortssuche ---------------------------------------------------------

    def search(self, query: str, language: str = "de", count: int = 8) -> list[Location]:
        """Sucht Orte nach Name oder Postleitzahl."""
        query = (query or "").strip()
        if len(query) < 2:
            return []

        key = f"{query.lower()}|{language}"
        cached = self._geocode_cache.get(key)
        if cached and time.time() - cached[0] < GEOCODE_TTL_S:
            return cached[1]

        payload = self._get(
            GEOCODE_URL,
            {"name": query, "count": count, "language": language, "format": "json"},
        )
        results = [
            Location(
                name=entry.get("name", ""),
                latitude=entry["latitude"],
                longitude=entry["longitude"],
                country=entry.get("country", ""),
                admin=entry.get("admin1", ""),
            )
            for entry in (payload.get("results") or [])
            if "latitude" in entry and "longitude" in entry
        ]
        self._geocode_cache[key] = (time.time(), results)
        return results

    def resolve(self, value: str, language: str = "de") -> Location | None:
        """Nimmt Koordinaten oder einen Ortsnamen und liefert einen Ort.

        Damit funktioniert sowohl das, was der Ortswähler einträgt, als auch
        eine von Hand eingetippte Stadt oder ein Koordinatenpaar.
        """
        value = (value or "").strip()
        if not value:
            return None

        direct = Location.decode(value)
        if direct is not None:
            return direct

        results = self.search(value, language=language, count=1)
        return results[0] if results else None

    # -- Wetter ------------------------------------------------------------

    def fetch(self, location: Location, *, units: str = "metric", force: bool = False) -> WeatherData:
        key = f"{location.latitude:.3f},{location.longitude:.3f}|{units}"
        cached = self._weather_cache.get(key)
        if cached is not None and not cached.stale and not force:
            return cached

        imperial = units == "imperial"
        params = {
            "latitude": f"{location.latitude:.4f}",
            "longitude": f"{location.longitude:.4f}",
            "current": ",".join([
                "temperature_2m", "apparent_temperature", "relative_humidity_2m",
                "precipitation", "weather_code", "wind_speed_10m", "is_day",
            ]),
            "hourly": ",".join([
                "temperature_2m", "precipitation_probability", "weather_code",
            ]),
            "daily": ",".join([
                "weather_code", "temperature_2m_max", "temperature_2m_min",
                "precipitation_probability_max", "uv_index_max", "sunrise", "sunset",
            ]),
            "timezone": "auto",
            "forecast_days": 7,
        }
        if imperial:
            params |= {
                "temperature_unit": "fahrenheit",
                "wind_speed_unit": "mph",
                "precipitation_unit": "inch",
            }

        payload = self._get(FORECAST_URL, params)
        data = WeatherData(
            location=location,
            fetched_at=time.time(),
            current=payload.get("current") or {},
            hourly=payload.get("hourly") or {},
            daily=payload.get("daily") or {},
            units=payload.get("current_units") or {},
        )

        # Luftqualität ist ein eigener Dienst — ein Ausfall dort darf das
        # normale Wetter nicht mitreißen.
        try:
            air = self._get(
                AIR_URL,
                {
                    "latitude": f"{location.latitude:.4f}",
                    "longitude": f"{location.longitude:.4f}",
                    "current": "european_aqi,us_aqi,pm10,pm2_5,ozone,nitrogen_dioxide",
                    "timezone": "auto",
                },
            )
            data.air = air.get("current") or {}
        except WeatherError as exc:
            log.debug("Luftqualität nicht abrufbar: %s", exc)

        self._weather_cache[key] = data
        return data

    def cached(self, location: Location, units: str = "metric") -> WeatherData | None:
        return self._weather_cache.get(
            f"{location.latitude:.3f},{location.longitude:.3f}|{units}"
        )

    # -- HTTP --------------------------------------------------------------

    def _get(self, url: str, params: dict) -> dict:
        full = f"{url}?{urllib.parse.urlencode(params)}"
        request = urllib.request.Request(
            full, headers={"User-Agent": USER_AGENT, "Accept": "application/json"}
        )
        try:
            with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_S) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:200]
            raise WeatherError(_t("fehler_http", code=exc.code, detail=detail)) from exc
        except urllib.error.URLError as exc:
            raise WeatherError(_t("fehler_netz", grund=exc.reason)) from exc
        except (TimeoutError, json.JSONDecodeError) as exc:
            raise WeatherError(_t("fehler_antwort", fehler=exc)) from exc
