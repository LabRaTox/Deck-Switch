"""Gemeinsamer Abruf für alle Belegungen.

Das Plugin hat genau einen Poller. Tasten und Dials lesen nur dessen
letzten Stand und fragen selbst nie bei CodexBar oder Anthropic nach. Je
Intervall gibt es so einen Abruf, unabhängig davon, wie viele Tasten und
Decks die Werte zeigen.

Ablauf einer Runde:

1. CodexBar-Snapshot holen. Klappt das, ist er der neue Stand.
2. Sonst, wenn der Fallback eingeschaltet ist, Claude direkt abfragen.
3. Klappt auch das nicht, bleibt der letzte Stand stehen. Nach Ablauf des
   Frische-Hinweises wird er als veraltet markiert und die Taste gedimmt.

:meth:`poll` blockiert (``urllib``) und läuft deshalb im Executor.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from . import claude, codexbar
from .codexbar import SourceError
from .model import MIN_REFRESH_S, Pace, ProviderUsage, Snapshot, utcnow

#: Abstand in Sekunden, in dem Pace (``/usage``) und Herkunft der Kosten
#: (``/cost``) neu geholt werden. Für beide Endpoints hat CodexBar einen
#: eigenen Cache, jeder Abruf dort kann die Anbieter ein zweites Mal
#: abfragen beziehungsweise die lokalen Logs neu einlesen.
PACE_INTERVAL_S = 300


@dataclass(slots=True)
class PollSettings:
    url: str = codexbar.DEFAULT_URL
    token_file: str = codexbar.DEFAULT_TOKEN_FILE
    refresh_s: int = 60
    claude_fallback: bool = True
    fetch_pace: bool = True

    @classmethod
    def from_config(cls, config: dict) -> "PollSettings":
        def text(key, default):
            value = config.get(key)
            return str(value).strip() if value not in (None, "") else default

        try:
            refresh = int(float(config.get("refresh_seconds") or 60))
        except (TypeError, ValueError):
            refresh = 60
        return cls(
            url=text("url", codexbar.DEFAULT_URL),
            token_file=text("token_file", codexbar.DEFAULT_TOKEN_FILE),
            refresh_s=max(MIN_REFRESH_S, refresh),
            claude_fallback=config.get("claude_fallback", True) is not False,
            fetch_pace=config.get("fetch_pace", True) is not False,
        )


class Poller:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.snapshot: Snapshot | None = None
        #: Warum CodexBar zuletzt nicht geliefert hat, auch wenn der Fallback
        #: eingesprungen ist. Erscheint in der Statuszeile.
        self.codexbar_error: SourceError | None = None
        #: Warum es zuletzt überhaupt keinen neuen Stand gab.
        self.error: SourceError | None = None
        self.last_attempt: float = 0.0
        self.polls = 0
        self._pace: dict[str, dict[str, Pace]] = {}
        self._cost_estimated: dict[str, bool] = {}
        self._details_at = 0.0
        self._refresh_details = False

    # ------------------------------------------------------------------

    def poll(self, settings: PollSettings) -> bool:
        """Eine Abfragerunde. Gibt ``True`` zurück, wenn es einen neuen Stand gibt."""
        with self._lock:
            self.last_attempt = time.monotonic()
            self.polls += 1
            before = self.snapshot

            try:
                snapshot = codexbar.fetch_snapshot(settings.url, settings.token_file)
            except SourceError as exc:
                self.codexbar_error = exc
                snapshot = self._fallback(settings) if settings.claude_fallback else None
                if snapshot is None and not settings.claude_fallback:
                    self.error = exc
            else:
                self.codexbar_error = None
                self.error = None
                due = time.monotonic() - self._details_at >= PACE_INTERVAL_S or not self._details_at
                if due:
                    self._details_at = time.monotonic()
                self._refresh_details = due
                self._attach_pace(snapshot, settings)
                self._attach_cost_provenance(snapshot, settings)

            if snapshot is not None:
                self.snapshot = snapshot
            return self.snapshot is not before

    def _fallback(self, settings: PollSettings) -> Snapshot | None:
        try:
            snapshot = claude.fetch()
        except claude.ClaudeLoginMissing as exc:
            # Die Taste soll „Anmeldung fehlt“ zeigen, deshalb eine Zeile dafür.
            self.error = None
            return Snapshot(providers=[_login_missing_row(str(exc))], generated_at=utcnow(),
                            source="claude")
        except SourceError as exc:
            self.error = exc
            return None
        self.error = None
        return snapshot

    def _attach_pace(self, snapshot: Snapshot, settings: PollSettings) -> None:
        if not settings.fetch_pace:
            self._pace = {}
            return
        if self._refresh_details:
            try:
                wanted = [p.id for p in snapshot.providers if p.windows and not p.error]
                self._pace = codexbar.fetch_pace(settings.url, wanted)
            except SourceError:
                # Ohne Pace fehlt nur der Prognosetext, der Rest bleibt gültig.
                pass
        if self._pace:
            codexbar.apply_pace(snapshot, self._pace)

    def _attach_cost_provenance(self, snapshot: Snapshot, settings: PollSettings) -> None:
        """Holt die Herkunft der Kosten im selben Takt wie die Pace."""
        with_cost = [p.id for p in snapshot.providers
                     if p.cost_today_usd is not None or p.cost_30d_usd is not None]
        if self._refresh_details and with_cost:
            self._cost_estimated = codexbar.fetch_cost_provenance(settings.url, with_cost)
        for provider in snapshot.providers:
            provider.cost_estimated = self._cost_estimated.get(provider.id, True)

    # ------------------------------------------------------------------

    def current(self) -> Snapshot | None:
        """Der letzte Stand, ``stale`` bezogen auf die aktuelle Uhrzeit."""
        snapshot = self.snapshot
        return snapshot.with_staleness() if snapshot is not None else None

    def providers(self) -> list[ProviderUsage]:
        snapshot = self.current()
        return snapshot.providers if snapshot else []


def _login_missing_row(message: str) -> ProviderUsage:
    return ProviderUsage(
        id="claude", name="Claude", plan=None, windows=[], credits=None,
        cost_today_usd=None, cost_30d_usd=None, status="unknown",
        error=message, updated_at=utcnow(), stale=False, error_kind="login_missing",
        accent="#D97757",
    )


class Alerts:
    """Merkt sich, für welche Fenster schon eine Benachrichtigung kam.

    Gemeldet wird einmal, wenn ein Fenster die kritische Schwelle
    überschreitet. Fällt es wieder darunter, meist nach dem Reset, wird es
    beim nächsten Überschreiten erneut gemeldet.
    """

    def __init__(self) -> None:
        self._sent: set[tuple[str, str]] = set()
        self._primed = False

    def check(self, providers: list[ProviderUsage], crit: float) -> list[tuple[ProviderUsage, object]]:
        due = []
        for provider in providers:
            # Ohne frischen Wert ist unklar, ob das Fenster gefallen ist. Der
            # gemerkte Zustand bleibt deshalb stehen, damit nach einem
            # Aussetzer nicht dieselbe Meldung noch einmal kommt.
            if provider.error or provider.stale:
                continue
            for window in provider.windows:
                if window.used_pct is None:
                    continue
                key = (provider.id, window.kind)
                if window.used_pct < crit:
                    self._sent.discard(key)
                elif key not in self._sent:
                    self._sent.add(key)
                    due.append((provider, window))
        # Der erste Stand nach dem Start löst keine Meldung aus. Sonst käme
        # für ein Fenster, das schon länger über der Schwelle liegt, bei
        # jedem Neustart der App eine Benachrichtigung.
        if not self._primed:
            self._primed = True
            return []
        return due
