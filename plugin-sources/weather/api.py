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
from typing import Any

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


# --------------------------------------------------------------------------
# Wettercodes (WMO) → Text und Icon
# --------------------------------------------------------------------------

#: WMO-Code → (Beschreibung de, Beschreibung en, Icon bei Tag, Icon bei Nacht)
WMO: dict[int, tuple[str, str, str, str]] = {
    0: ("Klar", "Clear", "sun", "moon"),
    1: ("Überwiegend klar", "Mostly clear", "sun", "moon"),
    2: ("Teils bewölkt", "Partly cloudy", "cloud", "cloud"),
    3: ("Bedeckt", "Overcast", "cloud", "cloud"),
    45: ("Nebel", "Fog", "cloud-fog", "cloud-fog"),
    48: ("Reifnebel", "Rime fog", "cloud-fog", "cloud-fog"),
    51: ("Leichter Niesel", "Light drizzle", "cloud-rain", "cloud-rain"),
    53: ("Niesel", "Drizzle", "cloud-rain", "cloud-rain"),
    55: ("Starker Niesel", "Dense drizzle", "cloud-rain", "cloud-rain"),
    56: ("Gefrierender Niesel", "Freezing drizzle", "cloud-snow", "cloud-snow"),
    57: ("Gefrierender Niesel", "Freezing drizzle", "cloud-snow", "cloud-snow"),
    61: ("Leichter Regen", "Light rain", "cloud-rain", "cloud-rain"),
    63: ("Regen", "Rain", "cloud-rain", "cloud-rain"),
    65: ("Starker Regen", "Heavy rain", "cloud-rain", "cloud-rain"),
    66: ("Gefrierender Regen", "Freezing rain", "cloud-snow", "cloud-snow"),
    67: ("Gefrierender Regen", "Freezing rain", "cloud-snow", "cloud-snow"),
    71: ("Leichter Schnee", "Light snow", "cloud-snow", "cloud-snow"),
    73: ("Schnee", "Snow", "cloud-snow", "cloud-snow"),
    75: ("Starker Schnee", "Heavy snow", "cloud-snow", "cloud-snow"),
    77: ("Schneegriesel", "Snow grains", "snowflake", "snowflake"),
    80: ("Regenschauer", "Rain showers", "cloud-rain", "cloud-rain"),
    81: ("Regenschauer", "Rain showers", "cloud-rain", "cloud-rain"),
    82: ("Starke Schauer", "Violent showers", "cloud-rain", "cloud-rain"),
    85: ("Schneeschauer", "Snow showers", "cloud-snow", "cloud-snow"),
    86: ("Schneeschauer", "Snow showers", "cloud-snow", "cloud-snow"),
    95: ("Gewitter", "Thunderstorm", "cloud-storm", "cloud-storm"),
    96: ("Gewitter mit Hagel", "Thunderstorm, hail", "cloud-bolt", "cloud-bolt"),
    99: ("Gewitter mit Hagel", "Thunderstorm, hail", "cloud-bolt", "cloud-bolt"),
}


def describe(code: int | None, language: str = "de") -> str:
    entry = WMO.get(int(code) if code is not None else -1)
    if entry is None:
        return "—"
    return entry[0] if language.startswith("de") else entry[1]


def icon_for(code: int | None, is_day: bool = True) -> str:
    entry = WMO.get(int(code) if code is not None else -1)
    if entry is None:
        return "cloud-off"
    return entry[2] if is_day else entry[3]


# --------------------------------------------------------------------------
# Luftqualität
# --------------------------------------------------------------------------

#: Europäischer AQI: (Obergrenze, Bezeichnung de, en, Farbe)
AQI_BANDS = [
    (20, "Sehr gut", "Very good", "#4ade80"),
    (40, "Gut", "Good", "#a3e635"),
    (60, "Mittel", "Moderate", "#facc15"),
    (80, "Schlecht", "Poor", "#fb923c"),
    (100, "Sehr schlecht", "Very poor", "#ef4444"),
    (10_000, "Extrem schlecht", "Extremely poor", "#a21caf"),
]


def aqi_band(value: float | None, language: str = "de") -> tuple[str, str]:
    """Liefert (Bezeichnung, Farbe) zu einem europäischen AQI-Wert."""
    if value is None:
        return ("—", "#6b7280")
    for limit, label_de, label_en, color in AQI_BANDS:
        if value <= limit:
            return (label_de if language.startswith("de") else label_en, color)
    return ("—", "#6b7280")


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
            raise WeatherError(f"Wetterdienst antwortet {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise WeatherError(f"Wetterdienst nicht erreichbar: {exc.reason}") from exc
        except (TimeoutError, json.JSONDecodeError) as exc:
            raise WeatherError(f"Antwort unbrauchbar: {exc}") from exc
