"""Datenmodell: was das Plugin über einen KI-Dienst weiß.

Beide Quellen (CodexBar und der direkte Claude-Abruf) werden in diese
Klassen übersetzt. Alles, was Tasten und Dials zeigen, liest nur von hier.

Fehlt ein Wert in der Quelle, bleibt das Feld ``None``. Es wird nichts
geschätzt, aufgefüllt oder aus anderen Werten berechnet.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone

#: Schwellen in Prozent Verbrauch. Unter ``WARN`` normal, ab ``CRIT`` kritisch.
DEFAULT_WARN = 70.0
DEFAULT_CRIT = 90.0

#: Mindestabstand zwischen zwei Abfragen in Sekunden. CodexBar selbst hält
#: seine Antworten 60 s im Speicher, öfter zu fragen bringt kaum Neues.
MIN_REFRESH_S = 30

#: Frische-Hinweis, wenn eine Quelle selbst keinen liefert. Entspricht dem
#: Minimum, das CodexBar für ``staleAfterSeconds`` garantiert.
DEFAULT_STALE_S = 180


@dataclass(slots=True)
class Pace:
    """Prognose für ein Fenster, so wie CodexBar sie liefert.

    ``will_last`` und ``eta_seconds`` stammen unverändert aus ``/usage``.
    Das Plugin berechnet keine eigene Prognose, dafür fehlen ihm die
    Verlaufsdaten.
    """

    will_last: bool | None
    eta_seconds: float | None
    stage: str | None = None


@dataclass(slots=True)
class UsageWindow:
    kind: str  # "session" | "weekly" | provider-spezifisch
    label: str
    used_pct: float | None
    resets_at: datetime | None
    pace: Pace | None = None


@dataclass(slots=True)
class ProviderUsage:
    id: str
    name: str
    plan: str | None
    windows: list[UsageWindow]
    credits: tuple[float, str] | None  # (remaining, unit)
    cost_today_usd: float | None
    cost_30d_usd: float | None
    status: str  # ok | warning | critical | unknown
    error: str | None
    updated_at: datetime | None
    stale: bool
    #: Ob die Kosten eine Schätzung sind. CodexBar berechnet Kosten aus lokalen
    #: Logs mit API-Listenpreisen, das ist keine Abrechnung des Anbieters.
    #: Solange nicht geklärt ist, dass ein Anbieter die Beträge selbst
    #: gemeldet hat, gelten sie als geschätzt.
    cost_estimated: bool = True
    #: ``login_missing`` oder ``error``. Nur gesetzt, wenn auch ``error`` gesetzt ist.
    error_kind: str | None = None
    accent: str | None = None
    sort_key: int = 0

    def window(self, kind: str) -> UsageWindow | None:
        for entry in self.windows:
            if entry.kind == kind:
                return entry
        return None

    def peak(self) -> UsageWindow | None:
        """Das Fenster mit dem höchsten Verbrauch, für die Fensterwahl „automatisch“."""
        known = [w for w in self.windows if w.used_pct is not None]
        return max(known, key=lambda w: w.used_pct) if known else None

    def peak_pct(self) -> float | None:
        best = self.peak()
        return best.used_pct if best else None


@dataclass(slots=True)
class Snapshot:
    """Ergebnis eines Abrufs mit allen Anbietern, der Quelle und dem Zeitpunkt."""

    providers: list[ProviderUsage]
    generated_at: datetime | None
    stale_after_s: int = DEFAULT_STALE_S
    #: ``codexbar`` oder ``claude`` (Fallback ohne CodexBar).
    source: str = "codexbar"
    version: str | None = None
    #: Hinweis, der den Abruf nicht verwirft, zum Beispiel ein unbekanntes Schema.
    warning: str | None = None
    #: Zeitpunkt, zu dem die Pace zuletzt geholt wurde. Sie kommt über einen eigenen Abruf.
    pace_at: datetime | None = None
    extra: dict = field(default_factory=dict)

    def provider(self, provider_id: str) -> ProviderUsage | None:
        for entry in self.providers:
            if entry.id == provider_id:
                return entry
        return None

    def with_staleness(self, now: datetime | None = None) -> "Snapshot":
        """Kopie, in der ``stale`` für den Zeitpunkt ``now`` stimmt.

        Ein Anbieter gilt als veraltet, wenn sein Stand älter ist als der
        Frische-Hinweis der Quelle. Weil das von der aktuellen Uhrzeit
        abhängt, wird es bei jedem Lesen neu bestimmt.
        """
        now = now or utcnow()
        limit = max(1, self.stale_after_s)
        providers = []
        for entry in self.providers:
            stamp = self.generated_at or entry.updated_at
            stale = stamp is not None and (now - stamp).total_seconds() > limit
            providers.append(replace(entry, stale=stale))
        return replace(self, providers=providers)


def level(used_pct: float | None, warn: float = DEFAULT_WARN, crit: float = DEFAULT_CRIT) -> str | None:
    """``ok``, ``warn`` oder ``crit``. Bewertet wird immer der Verbrauch, auch wenn die Taste „übrig“ anzeigt."""
    if used_pct is None:
        return None
    if used_pct >= crit:
        return "crit"
    if used_pct >= warn:
        return "warn"
    return "ok"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def parse_time(value) -> datetime | None:
    """Liest einen ISO-8601-Zeitstempel mit ``Z`` oder Offset. Ungültiges ergibt ``None``."""
    if not value or not isinstance(value, str):
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        stamp = datetime.fromisoformat(text)
    except ValueError:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp


def number(value) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
