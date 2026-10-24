"""CodexBar als Datenquelle.

CodexBar (``codexbar serve``) läuft auf demselben Rechner und fragt die
Nutzung bei den KI-Anbietern ab. Dieses Modul liest davon nur
``GET /dashboard/v1/snapshot`` mit schemaVersion 1, nie die Rohdaten
einzelner Anbieter. Dazu kommt optional ``GET /usage`` für die
Pace-Prognose, die im Snapshot fehlt.

Nur diese Datei kennt CodexBars Antwortformat. Alles andere im Plugin
arbeitet mit den Klassen aus :mod:`.model`.

Der Snapshot-Endpoint verlangt einen Bearer-Token. Das Plugin speichert ihn
nicht, sondern liest ihn bei jedem Abruf aus CodexBars eigener Datei
(``dashboard.env``, die auch der systemd-Dienst liest). Ein neuer Token
wirkt dadurch, sobald CodexBar neu gestartet ist, und in der
Deck-Konfiguration steht kein Geheimnis.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from deckswitch.plugins.base import plugin_text

from .model import (
    DEFAULT_STALE_S,
    Pace,
    ProviderUsage,
    Snapshot,
    UsageWindow,
    number,
    parse_time,
    utcnow,
)

DEFAULT_URL = "http://127.0.0.1:8790"
DEFAULT_TOKEN_FILE = "~/.config/codexbar/dashboard.env"
TOKEN_VAR = "CODEXBAR_DASHBOARD_TOKEN"
SCHEMA_VERSION = 1

#: Zeitlimit je Abruf in Sekunden. Beim ersten Abruf fragt CodexBar alle
#: Anbieter ab und braucht deutlich länger als aus dem Cache. Sein eigenes
#: Limit liegt bei 30 s, danach antwortet es mit 504.
TIMEOUT_S = 35

#: Muster, an denen eine Fehlermeldung als „Anmeldung fehlt“ erkannt wird.
#:
#: CodexBar liefert zu einem Fehler ``message``, ``kind`` und ``code``. Der
#: Code ist bei allen Anbieterfehlern 1 und unterscheidet nichts, also
#: entscheidet der Text. Die Muster decken die Meldungen ab, die CodexBar
#: 0.80.0 tatsächlich ausgibt: fehlender Login oder Schlüssel („No available
#: fetch strategy“, „API key not configured“, „Run `kilo auth login`“),
#: fehlende oder abgelaufene Cookies und abgelehnte Tokens. Passt keines,
#: zeigt die Taste „Fehler“. Einen Wert zeigt sie in beiden Fällen nicht.
LOGIN_PATTERNS = re.compile(
    r"no available fetch strategy|not configured|not (logged|signed) in|\blog ?in\b|"
    r"sign ?in|no credentials|missing credentials|credentials? not found|api[ _]?key|"
    r"session (not found|expired)|no [\w ]{0,30}session|"
    r"token (expired|missing|invalid|revoked)|expired token|invalid token|unauthori[sz]ed|"
    r"\b401\b|\b403\b|cookie|re-?auth|authenticat",
    re.IGNORECASE,
)

#: Hinweise, dass erst etwas installiert, gestartet oder auf einem anderen
#: System genutzt werden muss. Sie gehen den Login-Mustern vor: „Install the
#: Kiro CLI and run 'kiro-cli login'“ verlangt zuerst eine Installation.
SETUP_PATTERNS = re.compile(
    r"not installed|\binstall\b|not detected|not reachable|could not reach|"
    r"only supported on|start it with",
    re.IGNORECASE,
)


def _t(key: str, **werte: Any) -> str:
    """Text aus den Sprachdateien des Plugins."""
    return plugin_text(Path(__file__).resolve().parents[1], "ai-usage", key, werte)


class SourceError(Exception):
    """Abruf gescheitert. ``kind`` nennt den Grund, danach richten sich Status und Fallback."""

    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind = kind  # unreachable | unauthorized | http | invalid


# --------------------------------------------------------------------------
# Token
# --------------------------------------------------------------------------


def read_token(token_file: str | None) -> str | None:
    """Liest den Bearer-Token, zuerst aus der Umgebung, dann aus der Datei.

    Die Datei darf die Zeile ``CODEXBAR_DASHBOARD_TOKEN=…`` enthalten (das
    Format, das systemd als ``EnvironmentFile`` erwartet) oder nur den Token.
    """
    value = os.environ.get(TOKEN_VAR, "").strip()
    if value:
        return value
    path = Path(os.path.expanduser(token_file or DEFAULT_TOKEN_FILE))
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None

    lines = [line.strip() for line in text.splitlines()]
    lines = [line for line in lines if line and not line.startswith("#")]
    for line in lines:
        key, sep, rest = line.partition("=")
        if sep and key.strip().removeprefix("export ").strip() == TOKEN_VAR:
            return rest.strip().strip("'\"") or None
    if len(lines) == 1 and "=" not in lines[0]:
        return lines[0]
    return None


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------


def _get_json(url: str, *, token: str | None = None, timeout: float = TIMEOUT_S):
    headers = {"Accept": "application/json", "User-Agent": "deckswitch-ai-usage"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            raise SourceError("unauthorized", _t("codexbar_token_rejected")) from exc
        raise SourceError("http", _t("codexbar_http", code=exc.code)) from exc
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        raise SourceError("unreachable", _t("codexbar_unreachable", reason=reason)) from exc
    try:
        return json.loads(raw)
    except ValueError as exc:
        raise SourceError("invalid", _t("codexbar_invalid_json")) from exc


def fetch_snapshot(base_url: str, token_file: str | None) -> Snapshot:
    token = read_token(token_file)
    if not token:
        # Ohne Token antwortet der Endpoint immer mit 401. Der Abruf entfällt,
        # die Meldung nennt die Datei, in der der Token fehlt.
        raise SourceError(
            "unauthorized",
            _t("codexbar_no_token", file=token_file or DEFAULT_TOKEN_FILE),
        )
    url = base_url.rstrip("/") + "/dashboard/v1/snapshot"
    return parse_snapshot(_get_json(url, token=token))


def fetch_health(base_url: str) -> dict:
    return _get_json(base_url.rstrip("/") + "/health", timeout=5)


def fetch_pace(base_url: str, provider_ids: list[str]) -> dict[str, dict[str, Pace]]:
    """Pace für die genannten Anbieter, je ein ``GET /usage?provider=<id>``.

    Auf Loopback ist der Endpoint ohne Token erreichbar. ``primary`` gehört
    zur Session, ``secondary`` zur Woche und ``tertiary`` zum dritten
    Fenster eines Anbieters.

    Abgefragt wird jeder Anbieter einzeln, weil ``provider=all`` alle
    bekannten Anbieter abfragt, auch die nicht aktivierten. Scheitert ein
    einzelner Abruf, fehlt nur dessen Pace.
    """
    result: dict[str, dict[str, Pace]] = {}
    for provider_id in provider_ids:
        url = base_url.rstrip("/") + "/usage?" + urllib.parse.urlencode({"provider": provider_id})
        try:
            result.update(parse_pace(_get_json(url)))
        except SourceError:
            continue
    return result


def fetch_cost_provenance(base_url: str, provider_ids: list[str]) -> dict[str, bool]:
    """Ob die Kosten je Anbieter geschätzt sind, aus ``GET /cost?provider=<id>``.

    CodexBar nennt die Herkunft in ``provenance``. ``listPriceEstimate``
    heißt, die Beträge sind aus lokalen Token-Zahlen mit API-Listenpreisen
    berechnet. Fehlt die Angabe oder scheitert der Abruf, fehlt der Anbieter
    im Ergebnis und seine Kosten gelten weiter als geschätzt.
    """
    result: dict[str, bool] = {}
    for provider_id in provider_ids:
        url = base_url.rstrip("/") + "/cost?" + urllib.parse.urlencode({"provider": provider_id})
        try:
            result.update(parse_cost_provenance(_get_json(url)))
        except SourceError:
            continue
    return result


def parse_cost_provenance(payload) -> dict[str, bool]:
    rows = payload if isinstance(payload, list) else [payload]
    result: dict[str, bool] = {}
    for row in rows:
        if not isinstance(row, dict) or not row.get("provider"):
            continue
        totals = row.get("totals") if isinstance(row.get("totals"), dict) else {}
        provenance = row.get("provenance") or totals.get("provenance")
        if isinstance(provenance, str) and provenance:
            result[str(row["provider"])] = "estimate" in provenance.lower()
    return result


# --------------------------------------------------------------------------
# Normalisieren
# --------------------------------------------------------------------------


def parse_snapshot(payload) -> Snapshot:
    if not isinstance(payload, dict) or not isinstance(payload.get("providers"), list):
        raise SourceError("invalid", _t("codexbar_not_snapshot"))

    warning = None
    version = payload.get("schemaVersion")
    if version != SCHEMA_VERSION:
        # Ein anderes Schema bricht den Abruf nicht ab. Gelesen wird, was sich
        # lesen lässt, und der Status nennt die abweichende Version.
        warning = _t("codexbar_unknown_schema", version=repr(version), expected=SCHEMA_VERSION)

    host = payload.get("host") if isinstance(payload.get("host"), dict) else {}
    stale_after = number(payload.get("staleAfterSeconds"))
    providers = []
    for row in payload["providers"]:
        if isinstance(row, dict) and row.get("id") and row.get("enabled", True) is not False:
            providers.append(parse_provider(row))
    providers.sort(key=lambda p: p.sort_key)

    return Snapshot(
        providers=providers,
        generated_at=parse_time(payload.get("generatedAt")),
        stale_after_s=int(stale_after) if stale_after else DEFAULT_STALE_S,
        source="codexbar",
        version=host.get("codexBarVersion"),
        warning=warning,
    )


def parse_provider(row: dict) -> ProviderUsage:
    windows = []
    for entry in row.get("windows") or []:
        if not isinstance(entry, dict) or entry.get("idle") is True:
            continue
        used = number(entry.get("usedPercent"))
        if used is None:
            remaining = number(entry.get("remainingPercent"))
            used = None if remaining is None else 100.0 - remaining
        windows.append(UsageWindow(
            kind=str(entry.get("kind") or ""),
            label=str(entry.get("label") or entry.get("kind") or ""),
            used_pct=used,
            resets_at=parse_time(entry.get("resetAt")),
        ))

    credits = None
    raw_credits = row.get("credits")
    if isinstance(raw_credits, dict):
        remaining = number(raw_credits.get("remaining"))
        if remaining is not None:
            credits = (remaining, str(raw_credits.get("unit") or ""))

    cost = row.get("cost") if isinstance(row.get("cost"), dict) else {}
    status = row.get("status") if isinstance(row.get("status"), dict) else {}
    level = status.get("level")
    identity = row.get("identity") if isinstance(row.get("identity"), dict) else {}
    display = row.get("display") if isinstance(row.get("display"), dict) else {}
    raw_error = row.get("error")
    error = error_text(raw_error)
    error_kind_hint = raw_error.get("kind") if isinstance(raw_error, dict) else None
    sort_key = number(display.get("sortKey"))

    # Aus ``identity`` wird nur der Plan übernommen. Die E-Mail-Adresse
    # landet nicht im Modell und kann deshalb nirgends angezeigt werden.
    return ProviderUsage(
        id=str(row["id"]),
        name=str(row.get("name") or row["id"]),
        plan=identity.get("plan") or None,
        windows=windows,
        credits=credits,
        cost_today_usd=number(cost.get("todayUSD")),
        cost_30d_usd=number(cost.get("last30DaysUSD")),
        status=level if level in ("ok", "warning", "critical", "unknown") else "unknown",
        error=error,
        updated_at=parse_time(row.get("updatedAt")),
        stale=False,
        error_kind=classify_error(error, error_kind_hint),
        accent=display.get("accentColor") or None,
        sort_key=int(sort_key) if sort_key is not None else 0,
    )


def error_text(value) -> str | None:
    """Macht aus ``error`` einen Text. CodexBar kann Text oder ein Objekt liefern."""
    if value is None or value == "":
        return None
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, dict):
        for key in ("message", "description", "detail", "error", "code", "kind"):
            if value.get(key):
                return str(value[key])
        return json.dumps(value, ensure_ascii=False)[:200]
    return str(value)


def classify_error(text: str | None, kind: str | None = None) -> str | None:
    """``login_missing`` oder ``error``. Ohne Fehlertext ``None``.

    ``kind == "runtime"`` meldet CodexBar, wenn eine Quelle auf diesem
    System gar nicht geht (etwa „only supported on macOS“). Eine Anmeldung
    hilft dann nicht, also bleibt es bei ``error``.
    """
    if not text:
        return None
    if kind == "runtime" or SETUP_PATTERNS.search(text):
        return "error"
    return "login_missing" if LOGIN_PATTERNS.search(text) else "error"


def parse_pace(payload) -> dict[str, dict[str, Pace]]:
    rows = payload
    if isinstance(payload, dict):
        rows = payload.get("providers") if isinstance(payload.get("providers"), list) else [payload]
    if not isinstance(rows, list):
        return {}

    result: dict[str, dict[str, Pace]] = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("pace"), dict):
            continue
        provider = str(row.get("provider") or row.get("id") or "")
        if not provider:
            continue
        entries = {}
        for slot, raw in row["pace"].items():
            if not isinstance(raw, dict):
                continue
            will_last = raw.get("willLastToReset")
            entries[slot] = Pace(
                will_last=will_last if isinstance(will_last, bool) else None,
                eta_seconds=number(raw.get("etaSeconds")),
                stage=raw.get("stage"),
            )
        if entries:
            result[provider] = entries
    return result


def apply_pace(snapshot: Snapshot, pace: dict[str, dict[str, Pace]]) -> None:
    """Hängt die Pace an die passenden Fenster des Snapshots (ändert ihn direkt)."""
    for provider in snapshot.providers:
        entries = pace.get(provider.id)
        if not entries:
            continue
        for window in provider.windows:
            if window.kind == "session" and "primary" in entries:
                window.pace = entries["primary"]
            elif window.kind == "weekly" and "secondary" in entries:
                window.pace = entries["secondary"]
        if "tertiary" in entries and len(provider.windows) >= 3:
            third = provider.windows[2]
            if third.kind not in ("session", "weekly") and third.pace is None:
                third.pace = entries["tertiary"]
    snapshot.pace_at = utcnow()
