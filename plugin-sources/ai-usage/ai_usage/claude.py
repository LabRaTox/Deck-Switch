"""Claude direkt abfragen, wenn CodexBar fehlt oder nicht antwortet.

Das Modul liest den OAuth-Token, den Claude Code in
``~/.claude/.credentials.json`` ablegt, und fragt damit denselben Endpoint
ab, den auch CodexBar und claude.ai für die Nutzungsanzeige verwenden.

Der Token wird nur gelesen und nie erneuert. Ein Refresh würde den
Refresh-Token austauschen, und Claude Code wäre danach abgemeldet. Ist der
Token abgelaufen, zeigt die Taste „Anmeldung fehlt“. Claude Code erneuert
ihn beim nächsten Start selbst.

Der Endpoint ist nicht öffentlich dokumentiert. Die ausgewerteten Felder
stammen aus einer echten Antwort. Ändert sich die Form, zeigt die Taste
„Fehler“ und keine Zahlen.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

from .codexbar import SourceError, _t
from .model import ProviderUsage, Snapshot, UsageWindow, number, parse_time, utcnow

CREDENTIALS = "~/.claude/.credentials.json"
USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
BETA_HEADER = "oauth-2025-04-20"
TIMEOUT_S = 15

#: Für ältere Antworten ohne ``limits``: Feldname → (kind, label).
LEGACY_WINDOWS = {
    "five_hour": ("session", "Session"),
    "seven_day": ("weekly", "Weekly"),
    "seven_day_opus": ("claude-weekly-scoped-opus", "Opus only"),
    "seven_day_sonnet": ("claude-weekly-scoped-sonnet", "Sonnet only"),
}


class ClaudeLoginMissing(SourceError):
    def __init__(self, message: str) -> None:
        super().__init__("login_missing", message)


def read_credentials(path: str = CREDENTIALS) -> dict:
    file = Path(os.path.expanduser(path))
    try:
        data = json.loads(file.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ClaudeLoginMissing(_t("claude_not_logged_in")) from exc
    except (OSError, ValueError) as exc:
        raise SourceError("invalid", _t("claude_unreadable", file=file)) from exc
    oauth = data.get("claudeAiOauth") if isinstance(data, dict) else None
    if not isinstance(oauth, dict) or not oauth.get("accessToken"):
        raise ClaudeLoginMissing(_t("claude_no_login"))
    return oauth


def fetch(path: str = CREDENTIALS) -> Snapshot:
    oauth = read_credentials(path)
    expires = number(oauth.get("expiresAt"))
    if expires is not None and expires / 1000 < time.time():
        raise ClaudeLoginMissing(_t("claude_login_expired"))

    request = urllib.request.Request(USAGE_URL, headers={
        "Authorization": f"Bearer {oauth['accessToken']}",
        "anthropic-beta": BETA_HEADER,
        "Accept": "application/json",
        "User-Agent": "deckswitch-ai-usage",
    })
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
            payload = json.loads(response.read())
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise ClaudeLoginMissing(_t("claude_login_rejected", code=exc.code)) from exc
        if exc.code == 429:
            raise SourceError("http", _t("claude_rate_limited")) from exc
        raise SourceError("http", _t("claude_http", code=exc.code)) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise SourceError("unreachable", _t("claude_unreachable", reason=getattr(exc, "reason", exc))) from exc
    except ValueError as exc:
        raise SourceError("invalid", _t("claude_invalid_json")) from exc

    return Snapshot(
        providers=[parse_usage(payload, plan=_plan(oauth))],
        generated_at=utcnow(),
        source="claude",
    )


def parse_usage(payload, *, plan: str | None = None) -> ProviderUsage:
    if not isinstance(payload, dict):
        raise SourceError("invalid", _t("claude_unknown_form"))

    windows = _from_limits(payload.get("limits"))
    if windows is None:
        windows = _from_legacy(payload)

    return ProviderUsage(
        id="claude",
        name="Claude",
        plan=plan,
        windows=windows,
        credits=_credits(payload.get("spend")),
        # Dieser Endpoint liefert keine Kosten. CodexBar berechnet sie aus
        # lokalen Logs, der direkte Abruf lässt die Felder leer.
        cost_today_usd=None,
        cost_30d_usd=None,
        status="unknown",
        error=None,
        updated_at=utcnow(),
        stale=False,
        accent="#D97757",
    )


def _from_limits(limits) -> list[UsageWindow] | None:
    """Liest die Liste ``limits``. Sie enthält auch die modellspezifischen Fenster."""
    if not isinstance(limits, list):
        return None
    windows = []
    for entry in limits:
        if not isinstance(entry, dict):
            continue
        kind = entry.get("kind")
        if kind == "session":
            new_kind, label = "session", "Session"
        elif kind == "weekly_all":
            new_kind, label = "weekly", "Weekly"
        elif kind == "weekly_scoped":
            model = _scope_name(entry.get("scope"))
            if not model:
                continue
            # Dieselbe Benennung wie bei CodexBar: claude-weekly-scoped-<modell>.
            new_kind, label = f"claude-weekly-scoped-{model.lower()}", f"{model} only"
        else:
            continue
        windows.append(UsageWindow(
            kind=new_kind,
            label=label,
            used_pct=number(entry.get("percent")),
            resets_at=parse_time(entry.get("resets_at")),
        ))
    return windows


def _from_legacy(payload: dict) -> list[UsageWindow]:
    windows = []
    for field, (kind, label) in LEGACY_WINDOWS.items():
        entry = payload.get(field)
        if isinstance(entry, dict) and number(entry.get("utilization")) is not None:
            windows.append(UsageWindow(
                kind=kind,
                label=label,
                used_pct=number(entry.get("utilization")),
                resets_at=parse_time(entry.get("resets_at")),
            ))
    return windows


def _scope_name(scope) -> str | None:
    if not isinstance(scope, dict):
        return None
    model = scope.get("model")
    if isinstance(model, dict):
        return model.get("display_name") or model.get("id")
    return None


def _credits(spend) -> tuple[float, str] | None:
    """Restguthaben der Zusatznutzung, nur wenn sie eingeschaltet ist.

    ``spend`` nennt Beträge in Kleinsteinheiten mit Exponent
    (``amount_minor`` 1250 und ``exponent`` 2 sind 12,50). Ist die
    Zusatznutzung ausgeschaltet, gibt es kein Guthaben.
    """
    if not isinstance(spend, dict) or spend.get("enabled") is not True:
        return None
    used, limit = spend.get("used"), spend.get("limit")
    if not isinstance(used, dict) or not isinstance(limit, dict):
        return None
    try:
        exponent = int(limit.get("exponent", 2))
        remaining = (int(limit["amount_minor"]) - int(used["amount_minor"])) / 10**exponent
    except (KeyError, TypeError, ValueError):
        return None
    return remaining, str(limit.get("currency") or "")


def _plan(oauth: dict) -> str | None:
    value = oauth.get("subscriptionType")
    return str(value).capitalize() if value else None
