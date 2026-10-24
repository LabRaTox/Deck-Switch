"""Texte auf dem Deck und die Formatierung von Zahlen.

Die Wörter stehen in ``locales/de.json`` und ``locales/en.json``.

Eine Taste ist 120 Pixel breit. Deshalb stehen dort kurze Formen wie
„3T 4h“ statt „3 Tage 4 Stunden“, und vor dem Prozentzeichen steht kein
Leerzeichen.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from deckswitch.plugins.base import plugin_text


def text(key: str, **werte: Any) -> str:
    """Text aus ``locales/de.json`` bzw. ``locales/en.json`` dieses Plugins."""
    return plugin_text(Path(__file__).resolve().parent, "ai-usage", key, werte)


def window_label(kind: str, label: str) -> str:
    """Kurzname eines Fensters. Session und Woche werden übersetzt, der Rest bleibt wie geliefert.

    Modellfenster heißen bei CodexBar „Fable only“ oder „Sonnet only“. Auf
    Deutsch wird daraus „nur Fable“.
    """
    if kind in ("session", "weekly"):
        return text(kind)
    if label.endswith(" only"):
        return text("only", modell=label[: -len(" only")])
    return label or kind


def countdown(target: datetime | None, now: datetime) -> str | None:
    """Restzeit bis ``target`` als „2h 30m“, „3T 4h“ oder „12m“. Ohne Zeitpunkt ``None``."""
    if target is None:
        return None
    seconds = (target - now).total_seconds()
    if seconds <= 0:
        return "0m"
    return duration(seconds)


def duration(seconds: float) -> str:
    minutes = int(seconds // 60)
    days, rest = divmod(minutes, 24 * 60)
    hours, mins = divmod(rest, 60)
    if days:
        return f"{days}{text('day_unit')} {hours}h"
    if hours:
        return f"{hours}h {mins}m"
    return f"{max(1, mins)}m" if seconds >= 60 else "<1m"


def percent(value: float | None) -> str:
    if value is None:
        return "---"
    return f"{round(value)}%"


def pace(window) -> str | None:
    """Kurztext zur Prognose aus den Pace-Daten. Ohne Pace ``None``."""
    entry = getattr(window, "pace", None)
    if entry is None:
        return None
    if entry.will_last is True:
        return text("lasts")
    if entry.eta_seconds is not None and entry.eta_seconds > 0:
        return text("empty_in", zeit=duration(entry.eta_seconds))
    return None


def money(value: float | None, unit: str = "USD") -> str:
    if value is None:
        return "---"
    symbol = {"USD": "$", "EUR": "€", "GBP": "£"}.get(unit.upper())
    amount = f"{value:,.2f}" if abs(value) < 1000 else f"{value:,.0f}"
    if symbol == "$":
        return f"${amount}"
    if symbol:
        return f"{amount} {symbol}"
    return amount


def credits(value: float, unit: str) -> tuple[str, str]:
    """Betrag und Einheit getrennt, weil die Einheit klein darunter steht."""
    if unit.upper() in ("USD", "EUR", "GBP"):
        return money(value, unit), ""
    if abs(value) >= 1000:
        amount = f"{value:,.0f}"
    elif value == int(value):
        amount = str(int(value))
    else:
        amount = f"{value:.1f}"
    return amount, unit
