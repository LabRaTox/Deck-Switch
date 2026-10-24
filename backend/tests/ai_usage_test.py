"""Prüft das Plugin „KI-Nutzung“: Datenformat, Fallback, Tasten, Übersicht.

Der CodexBar-Teil läuft gegen einen kleinen HTTP-Server in diesem Prozess.
Er liefert die Fixtures aus ``daten/ai-usage`` aus und prüft den Token wie
CodexBar (401 ohne oder mit falschem Bearer). Der Claude-Fallback wird mit
einer gespeicherten echten Antwort geprüft. Die Suite geht nicht ins Netz.

Die Bilder werden wirklich gezeichnet. Ist ``$AI_USAGE_BILDER`` gesetzt,
landen sie dort zum Ansehen.

Aufruf:

    cd backend
    d=$(mktemp -d); env XDG_CONFIG_HOME=$d XDG_DATA_HOME=$d \\
        ../.venv/bin/python tests/ai_usage_test.py
"""
import _wache  # bricht ab, statt in die echte Config zu schreiben
_wache.sichere_umgebung()

import asyncio
import json
import os
import pathlib
import sys
import tempfile
import threading
import types
import urllib.parse
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

PLUGIN_DIR = pathlib.Path(__file__).resolve().parents[2] / "plugin-sources" / "ai-usage"
import _pluginlader  # noqa: E402
_pluginlader.ueberspringe_ohne(PLUGIN_DIR)
DATEN = pathlib.Path(__file__).resolve().parent / "daten" / "ai-usage"

from PIL import Image  # noqa: E402

from deckswitch import texte  # noqa: E402
from deckswitch.config import Appearance, Page, Profile, Slot, default_config  # noqa: E402
from deckswitch.plugins.base import Manifest, Services, SlotContext  # noqa: E402
from deckswitch.services.icons import IconService  # noqa: E402
from deckswitch.services.render import RenderService  # noqa: E402

from _pluginlader import lade, nachbar  # noqa: E402

modul = lade(PLUGIN_DIR)
cb = nachbar(modul, "ai_usage.codexbar")
cl = nachbar(modul, "ai_usage.claude")
md = nachbar(modul, "ai_usage.model")
pl = nachbar(modul, "ai_usage.poller")
tx = nachbar(modul, "texte")
ub = nachbar(modul, "uebersicht")

FAILS = []
BILDER = os.environ.get("AI_USAGE_BILDER")


def englisch(funktion, *args):
    """Ruft ``funktion`` mit Englisch als eingestellter Sprache auf."""
    texte.verbinde_sprache(lambda: "en")
    try:
        return funktion(*args)
    finally:
        texte.verbinde_sprache(lambda: texte.VORGABE)


def check(name, bedingung, detail=""):
    print(("  ✔ " if bedingung else "  ✘ ") + name + (f"  ({detail})" if detail else ""))
    if not bedingung:
        FAILS.append(name)


def fixture(name):
    return json.loads((DATEN / name).read_text())


BASIS = datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc)


def frisch(payload, jetzt=None):
    """Verschiebt alle Zeitstempel so, als wäre der Snapshot eben erzeugt worden."""
    jetzt = jetzt or datetime.now(timezone.utc)
    versatz = jetzt - BASIS

    def schieben(wert):
        if isinstance(wert, dict):
            return {k: schieben(v) for k, v in wert.items()}
        if isinstance(wert, list):
            return [schieben(v) for v in wert]
        if isinstance(wert, str) and wert.startswith("2026-") and wert.endswith("Z"):
            stamp = datetime.fromisoformat(wert[:-1] + "+00:00") + versatz
            return stamp.strftime("%Y-%m-%dT%H:%M:%SZ")
        return wert

    return schieben(payload)


# --------------------------------------------------------------------------
# Attrappen
# --------------------------------------------------------------------------


class FakeBus:
    def __init__(self):
        self.events = []

    def publish(self, name, **daten):
        self.events.append(name)


class FakeDevice:
    class info:
        key_count = 8


class FakeDeckSettings:
    long_press_ms = 500


class FakeRuntime:
    def __init__(self, config):
        self.redraws = 0
        self.gespeichert = 0
        self.navigiert = []
        self.status = 0
        self.bus = FakeBus()
        self.device = FakeDevice()
        self.device_settings = FakeDeckSettings()
        self.config = config
        self._loop = None

    @property
    def deck(self):
        runtime = self

        class Deck:
            profile = runtime.config.active_profile()

        return Deck()

    def request_redraw(self, ctx=None):
        self.redraws += 1

    def save_config(self):
        self.gespeichert += 1

    def navigate(self, page_id):
        self.navigiert.append(page_id)

    def publish_plugin_status(self, plugin_id):
        self.status += 1

    def notify(self, *a, **k):
        pass


manifest = Manifest.model_validate(json.loads((PLUGIN_DIR / "manifest.json").read_text()))
config = default_config()
icons = IconService()
runtime = FakeRuntime(config)
services = Services(audio=None, icons=icons, render=RenderService(icons), runtime=runtime,
                    config=config, plugin_dir=PLUGIN_DIR)

# Wie in der App: Ohne Registry kennt der IconService das Tabler-Set nicht
# und zeichnet Platzhalter, und der Renderer findet die Symbole aus dem
# Manifest nicht. Mit Registry entsprechen die Bilder denen auf dem Gerät.
from deckswitch import paths  # noqa: E402
from deckswitch.plugins.loader import PluginRegistry  # noqa: E402

registry = PluginRegistry()
registry.discover(lambda ordner: services,
                  search_paths=[(paths.BUILTIN_PLUGINS_DIR, True), (PLUGIN_DIR.parent, False)])
icons.bind_registry(registry)
runtime.registry = registry


def vorgaben(action):
    beschreibung = manifest.action(action)
    return {f.key: f.default for f in beschreibung.settings_schema if f.default is not None}


def ctx_for(action, settings, *, input_type="key", index=0, page_id="p"):
    slot = Slot(plugin_id="ai-usage", action_id=action, settings=settings, appearance=Appearance())
    return SlotContext(
        action_id=action, settings=settings, appearance=slot.appearance,
        input_type=input_type, index=index, page_id=page_id, profile_id="pr",
        size=(120, 120) if input_type == "key" else (200, 100),
        services=services, slot=slot,
    )


def speichern(bild, name):
    if BILDER:
        pathlib.Path(BILDER).mkdir(parents=True, exist_ok=True)
        bild.save(pathlib.Path(BILDER) / f"{name}.png")


def farbig(bild, farbe, toleranz=40):
    """Gibt es Pixel in ungefähr dieser Farbe?"""
    ziel = tuple(int(farbe[i:i + 2], 16) for i in (1, 3, 5))
    for pixel in bild.convert("RGB").getdata():
        if all(abs(pixel[i] - ziel[i]) <= toleranz for i in range(3)):
            return True
    return False


# --------------------------------------------------------------------------
# Kleiner CodexBar
# --------------------------------------------------------------------------


class CodexBarAttrappe:
    TOKEN = "a" * 64

    def __init__(self):
        self.snapshot = frisch(fixture("snapshot-ok.json"))
        self.pace = fixture("usage-pace.json")
        self.abrufe = []
        attrappe = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                attrappe.abrufe.append(self.path)
                if self.path.startswith("/dashboard/v1/snapshot"):
                    if self.headers.get("Authorization") != f"Bearer {attrappe.TOKEN}":
                        return self._json(401, {"error": "unauthorized"})
                    return self._json(200, attrappe.snapshot)
                if self.path.startswith("/usage"):
                    # Wie CodexBar: je Anbieter eine Liste mit einem Eintrag,
                    # unbekannte Anbieter ergeben 400.
                    wanted = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
                    provider = (wanted.get("provider") or [""])[0]
                    rows = [r for r in attrappe.pace if r["provider"] == provider]
                    if provider == "all":
                        rows = attrappe.pace
                    elif not rows and provider not in ("claude", "openrouter"):
                        return self._json(400, {"error": f"Unknown provider '{provider}'."})
                    return self._json(200, rows)
                if self.path.startswith("/cost"):
                    wanted = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
                    provider = (wanted.get("provider") or [""])[0]
                    herkunft = {"claude": "listPriceEstimate", "codex": "reported"}
                    if provider not in herkunft:
                        return self._json(400, {"error": f"Unknown provider '{provider}'."})
                    return self._json(200, [{"provider": provider, "provenance": herkunft[provider]}])
                if self.path == "/health":
                    return self._json(200, {"status": "ok", "version": "0.80.0"})
                return self._json(404, {"error": "not found"})

            def _json(self, code, body):
                raw = json.dumps(body).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def stop(self):
        self.server.shutdown()


# --------------------------------------------------------------------------


def pruefe_format():
    print("== Snapshot einlesen ==")
    snap = cb.parse_snapshot(fixture("snapshot-ok.json"))
    check("drei Anbieter, nach sortKey", [p.id for p in snap.providers] == ["codex", "claude", "openrouter"],
          str([p.id for p in snap.providers]))
    claude = snap.provider("claude")
    check("idle-Fenster fällt weg", [w.kind for w in claude.windows]
          == ["session", "weekly", "claude-weekly-scoped-fable"])
    check("Plan übernommen", claude.plan == "Max")
    check("E-Mail nirgends im Modell", "example.com" not in repr(snap))
    check("Kosten übernommen", claude.cost_today_usd == 1.04 and claude.cost_30d_usd == 18.22)
    codex = snap.provider("codex")
    check("Guthaben als (Wert, Einheit)", codex.credits == (112.4, "credits"))
    check("fehlende Kosten bleiben None", codex.cost_today_usd is None)
    check("Status warning", codex.status == "warning")
    check("Version aus host", snap.version == "0.80.0")
    check("kein Schema-Hinweis bei v1", snap.warning is None)
    openrouter = snap.provider("openrouter")
    check("Anbieter ohne Fenster, ohne Status", openrouter.windows == [] and openrouter.status == "unknown")
    check("peak = höchstes Fenster", claude.peak().kind == "weekly")

    print("\n== Teilfehler, veraltet, leer, Schema 2 ==")
    teil = cb.parse_snapshot(fixture("snapshot-teilfehler.json"))
    check("Codex: Fehler", teil.provider("codex").error_kind == "error", teil.provider("codex").error)
    check("Cursor: Anmeldung fehlt", teil.provider("cursor").error_kind == "login_missing")
    check("Claude bleibt heil", teil.provider("claude").error is None)

    alt = cb.parse_snapshot(fixture("snapshot-veraltet.json"))
    check("eine Stunde alt → veraltet",
          alt.with_staleness(BASIS).providers[0].stale is True)
    ok = cb.parse_snapshot(fixture("snapshot-ok.json"))
    check("zwei Minuten alt → frisch",
          ok.with_staleness(BASIS + timedelta(seconds=120)).providers[0].stale is False)
    check("vier Minuten alt → veraltet",
          ok.with_staleness(BASIS + timedelta(seconds=240)).providers[0].stale is True)

    leer = cb.parse_snapshot(fixture("snapshot-leer.json"))
    check("leer ist kein Fehler", leer.providers == [] and leer.warning is None)
    s2 = cb.parse_snapshot(fixture("snapshot-schema2.json"))
    check("Schema 2 → Warnung, Daten trotzdem da", s2.warning is not None and len(s2.providers) == 1,
          s2.warning)
    try:
        cb.parse_snapshot({"foo": 1})
        check("Unsinn wird abgelehnt", False)
    except cb.SourceError as exc:
        check("Unsinn wird abgelehnt", exc.kind == "invalid")

    print("\n== Fehlertext einordnen ==")
    for text, erwartet in (
        ("Token expired. Switch to this account in claude-swap to refresh it.", "login_missing"),
        ("Cookie expired. Paste a fresh Cookie header in Settings.", "login_missing"),
        ("Not logged in", "login_missing"),
        ("HTTP 401 Unauthorized", "login_missing"),
        ("Codex request failed: HTTP 500", "error"),
        ("timed out", "error"),
    ):
        check(f"{text[:40]!r} → {erwartet}", cb.classify_error(text) == erwartet)
    check("Fehler als Objekt", cb.error_text({"message": "boom"}) == "boom")
    check("kind=runtime bleibt Fehler", cb.classify_error("Paste a cookie", "runtime") == "error")

    print("\n== Echte Fehlertexte von CodexBar 0.80.0 ==")
    for row in fixture("fehlertexte-echt.json"):
        ergebnis = cb.classify_error(row["message"], row["kind"])
        check(f"{row['provider']}: {row['erwartet']}", ergebnis == row["erwartet"],
              f"{ergebnis}: {row['message'][:60]}")

    print("\n== Echter Snapshot ==")
    echt = cb.parse_snapshot(fixture("snapshot-echt.json"))
    check("Codex und Claude, nach sortKey", [p.id for p in echt.providers] == ["codex", "claude"])
    check("Codex ohne Einrichtung → Anmeldung fehlt",
          echt.provider("codex").error_kind == "login_missing", echt.provider("codex").error)
    check("Fehlertext aus dem Objekt", echt.provider("codex").error == "No available fetch strategy for codex.")
    check("Claude: drei Fenster", [w.kind for w in echt.provider("claude").windows]
          == ["session", "weekly", "claude-weekly-scoped-fable"])
    check("Claude: Plan", echt.provider("claude").plan == "Max 5x")
    check("Status null → unknown", echt.provider("claude").status == "unknown")
    check("bekannte 0 bei Kosten bleibt 0", echt.provider("codex").cost_30d_usd == 0)
    pace_echt = cb.parse_pace(fixture("usage-echt.json"))
    check("echte Pace: nur Claude", list(pace_echt) == ["claude"])
    check("echte Pace: reicht bis Reset, ohne ETA",
          pace_echt["claude"]["primary"].will_last is True
          and pace_echt["claude"]["primary"].eta_seconds is None)

    print("\n== Herkunft der Kosten ==")
    check("echte /cost-Antwort: Claude ist geschätzt",
          cb.parse_cost_provenance(fixture("cost-echt.json")) == {"claude": True})
    check("gemeldete Kosten sind nicht geschätzt",
          cb.parse_cost_provenance([{"provider": "openrouter", "provenance": "reported"}])
          == {"openrouter": False})
    check("Herkunft in totals genügt",
          cb.parse_cost_provenance({"provider": "x", "totals": {"provenance": "listPriceEstimate"}})
          == {"x": True})
    check("ohne Angabe keine Aussage", cb.parse_cost_provenance([{"provider": "x"}]) == {})
    check("frisch eingelesen gilt als geschätzt", echt.provider("codex").cost_estimated is True)

    print("\n== Pace ==")
    pace = cb.parse_pace(fixture("usage-pace.json"))
    check("Codex hat Pace, Claude nicht", "codex" in pace and "claude" not in pace)
    cb.apply_pace(snap, pace)
    check("Session: leer in 2h 30m", tx.pace(snap.provider("codex").window("session")) == "leer in 2h 30m",
          tx.pace(snap.provider("codex").window("session")))
    check("Woche: reicht bis Reset", tx.pace(snap.provider("codex").window("weekly")) == "reicht bis Reset")
    check("ohne Pace kein Text", tx.pace(snap.provider("claude").window("session")) is None)

    print("\n== Claude direkt (gespeicherte echte Antwort) ==")
    row = cl.parse_usage(fixture("claude-oauth-usage.json"), plan="Max")
    check("drei Fenster aus limits", [w.kind for w in row.windows]
          == ["session", "weekly", "claude-weekly-scoped-fable"], str([w.kind for w in row.windows]))
    check("Werte wie gemeldet", [w.used_pct for w in row.windows] == [1.0, 1.0, 0.0])
    check("Reset-Zeit gelesen", row.windows[0].resets_at == datetime(2026, 10, 24, 11, 40, 0, 140812,
                                                                    tzinfo=timezone.utc))
    check("Zusatznutzung aus → kein Guthaben", row.credits is None)
    check("Kosten liefert der Endpoint nicht", row.cost_today_usd is None and row.cost_30d_usd is None)
    an = fixture("claude-oauth-usage.json")
    an["spend"]["enabled"] = True
    an["spend"]["used"]["amount_minor"] = 1250
    check("Zusatznutzung an → Rest in Euro", cl.parse_usage(an).credits == (47.5, "EUR"))
    alt = {"five_hour": {"utilization": 12.0, "resets_at": "2026-10-24T11:40:00+00:00"},
           "seven_day": {"utilization": 40.0, "resets_at": None}}
    check("ältere Form ohne limits", [w.used_pct for w in cl.parse_usage(alt).windows] == [12.0, 40.0])

    with tempfile.TemporaryDirectory() as tmp:
        datei = pathlib.Path(tmp) / "creds.json"
        try:
            cl.fetch(str(datei))
            check("ohne Datei: Anmeldung fehlt", False)
        except cl.ClaudeLoginMissing:
            check("ohne Datei: Anmeldung fehlt", True)
        datei.write_text(json.dumps({"claudeAiOauth": {"accessToken": "x", "expiresAt": 1000}}))
        try:
            cl.fetch(str(datei))
            check("abgelaufener Token: Anmeldung fehlt, kein Netzabruf", False)
        except cl.ClaudeLoginMissing as exc:
            check("abgelaufener Token: Anmeldung fehlt, kein Netzabruf", "abgelaufen" in str(exc))

    print("\n== Token-Datei ==")
    with tempfile.TemporaryDirectory() as tmp:
        datei = pathlib.Path(tmp) / "dashboard.env"
        alt_env = os.environ.pop(cb.TOKEN_VAR, None)
        datei.write_text("# Kommentar\nCODEXBAR_DASHBOARD_TOKEN=abc123\n")
        check("Zeile KEY=wert", cb.read_token(str(datei)) == "abc123")
        datei.write_text("export CODEXBAR_DASHBOARD_TOKEN='abc456'\n")
        check("export und Anführungszeichen", cb.read_token(str(datei)) == "abc456")
        datei.write_text("nurdertoken\n")
        check("nur der Token", cb.read_token(str(datei)) == "nurdertoken")
        check("fehlende Datei → None", cb.read_token(str(pathlib.Path(tmp) / "gibtsnicht")) is None)
        os.environ[cb.TOKEN_VAR] = "ausderumgebung"
        check("Umgebung gewinnt", cb.read_token(str(datei)) == "ausderumgebung")
        del os.environ[cb.TOKEN_VAR]
        if alt_env is not None:
            os.environ[cb.TOKEN_VAR] = alt_env

    print("\n== Schwellen und Texte ==")
    check("69.9 % normal", md.level(69.9) == "ok")
    check("70 % Warnung", md.level(70) == "warn")
    check("90 % kritisch", md.level(90) == "crit")
    check("eigene Schwellen", md.level(55, 50, 60) == "warn" and md.level(61, 50, 60) == "crit")
    check("kein Wert, kein Zustand", md.level(None) is None)
    jetzt = datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)
    for delta, erwartet in ((timedelta(hours=2, minutes=30), "2h 30m"),
                            (timedelta(days=3, hours=4, minutes=5), "3T 4h"),
                            (timedelta(minutes=12, seconds=30), "12m"),
                            (timedelta(seconds=20), "<1m"),
                            (timedelta(seconds=-5), "0m")):
        check(f"Countdown {erwartet}", tx.countdown(jetzt + delta, jetzt) == erwartet,
              tx.countdown(jetzt + delta, jetzt))
    check("englisch: Tage als d", englisch(tx.countdown, jetzt + timedelta(days=2), jetzt) == "2d 0h")
    check("Modellfenster deutsch", tx.window_label("x", "Fable only") == "nur Fable")
    check("Modellfenster englisch", englisch(tx.window_label, "x", "Fable only") == "Fable only")


def pruefe_http():
    print("\n== HTTP gegen eine CodexBar-Attrappe ==")
    attrappe = CodexBarAttrappe()
    with tempfile.TemporaryDirectory() as tmp:
        token = pathlib.Path(tmp) / "dashboard.env"
        token.write_text(f"CODEXBAR_DASHBOARD_TOKEN={attrappe.TOKEN}\n")
        settings = pl.PollSettings(url=attrappe.url, token_file=str(token))

        poller = pl.Poller()
        check("Abruf mit Token klappt", poller.poll(settings) and poller.snapshot.source == "codexbar")
        check("Pace mitgeholt", poller.snapshot.provider("codex").window("session").pace is not None)
        check("frisch → nicht veraltet", not poller.current().providers[0].stale)
        pace_abrufe = sum(p.startswith("/usage") for p in attrappe.abrufe)
        poller.poll(settings)
        check("Pace nicht bei jeder Runde", sum(p.startswith("/usage") for p in attrappe.abrufe) == pace_abrufe)
        usage_abrufe = sorted(p for p in attrappe.abrufe if p.startswith("/usage"))
        check("Pace nur für Anbieter mit Werten, einzeln, nie provider=all",
              usage_abrufe == ["/usage?provider=claude", "/usage?provider=codex"], str(usage_abrufe))
        cost_abrufe = sorted(p for p in attrappe.abrufe if p.startswith("/cost"))
        check("Kostenherkunft nur für Anbieter mit Kosten, einmal in zwei Runden",
              cost_abrufe == ["/cost?provider=claude", "/cost?provider=codex"], str(cost_abrufe))
        check("Claude: geschätzt, Codex: gemeldet",
              poller.snapshot.provider("claude").cost_estimated is True
              and poller.snapshot.provider("codex").cost_estimated is False)
        check("Herkunft hängt auch am Stand der zweiten Runde",
              poller.snapshot.provider("codex").cost_estimated is False)
        check("Pace bleibt am neuen Stand hängen",
              poller.snapshot.provider("codex").window("session").pace is not None)

        # Falscher Token bei ausgeschaltetem Fallback ergibt 401 und keinen Stand.
        token.write_text("CODEXBAR_DASHBOARD_TOKEN=falsch\n")
        poller = pl.Poller()
        poller.poll(pl.PollSettings(url=attrappe.url, token_file=str(token), claude_fallback=False))
        check("falscher Token → 401 erkannt",
              poller.error is not None and poller.error.kind == "unauthorized", str(poller.error))
        check("… und kein ausgedachter Stand", poller.snapshot is None)

        # Falscher Token bei eingeschaltetem Fallback, dann liefert Claude direkt.
        echt = cl.fetch
        cl.fetch = lambda path=cl.CREDENTIALS: md.Snapshot(
            providers=[cl.parse_usage(fixture("claude-oauth-usage.json"))],
            generated_at=md.utcnow(), source="claude")
        try:
            poller = pl.Poller()
            poller.poll(pl.PollSettings(url=attrappe.url, token_file=str(token)))
            check("Fallback liefert Claude", poller.snapshot is not None
                  and poller.snapshot.source == "claude" and poller.snapshot.providers[0].id == "claude")
            check("CodexBar-Grund bleibt sichtbar", poller.codexbar_error is not None)

            def ohne_login(path=cl.CREDENTIALS):
                raise cl.ClaudeLoginMissing("Claude Code ist nicht angemeldet")

            cl.fetch = ohne_login
            poller = pl.Poller()
            poller.poll(pl.PollSettings(url=attrappe.url, token_file=str(token)))
            row = poller.snapshot.providers[0]
            check("ohne Login: Zeile mit login_missing", row.error_kind == "login_missing")
        finally:
            cl.fetch = echt

        # Ist der Dienst weg, meldet der Poller „unreachable“ und behält den letzten Stand.
        token.write_text(f"CODEXBAR_DASHBOARD_TOKEN={attrappe.TOKEN}\n")
        poller = pl.Poller()
        poller.poll(settings)
        vorher = poller.snapshot
        attrappe.stop()
        poller.poll(pl.PollSettings(url=attrappe.url, token_file=str(token), claude_fallback=False))
        check("Dienst weg → unreachable", poller.error is not None and poller.error.kind == "unreachable",
              str(poller.error))
        check("letzter Stand bleibt stehen", poller.snapshot is vorher)

    check("Intervall nie unter 30 s", pl.PollSettings.from_config({"refresh_seconds": 5}).refresh_s == 30)


def pruefe_alerts():
    print("\n== Benachrichtigungen ==")
    snap = cb.parse_snapshot(frisch(fixture("snapshot-ok.json"))).with_staleness()
    alerts = pl.Alerts()
    check("erster Stand meldet nichts", alerts.check(snap.providers, 90) == [])
    check("zweiter auch nicht — schon gemeldet", alerts.check(snap.providers, 90) == [])
    snap.provider("codex").windows[0].used_pct = 50
    alerts.check(snap.providers, 90)
    snap.provider("codex").windows[0].used_pct = 95
    neu = alerts.check(snap.providers, 90)
    check("nach Fallen und Steigen genau eine Meldung",
          [(p.id, w.kind) for p, w in neu] == [("codex", "session")])
    snap.provider("codex").error = "weg"
    alerts.check(snap.providers, 90)
    snap.provider("codex").error = None
    check("Aussetzer meldet nicht erneut", alerts.check(snap.providers, 90) == [])


async def pruefe_plugin():
    print("\n== Plugin: Zustände und Bilder ==")
    plugin = modul.AIUsagePlugin(manifest, services)
    poller = plugin.poller
    poller.snapshot = cb.parse_snapshot(frisch(fixture("snapshot-ok.json")))
    poller.polls = 1

    def zustand(action, **settings):
        s = {**vorgaben(action), **settings}
        return plugin.get_state(action, s, ctx_for(action, s))

    check("Claude Session 20 % → ok", zustand("provider", provider="claude") == "ok")
    check("Claude Woche 75 % → warn", zustand("provider", provider="claude", window="weekly") == "warn")
    check("Codex Session 92 % → crit", zustand("provider", provider="codex") == "crit")
    check("automatisch nimmt das höchste Fenster",
          zustand("provider", provider="claude", window="auto") == "warn")
    check("eigene Schwelle je Taste", zustand("provider", provider="claude", warn_pct=10) == "warn")
    check("ohne Anbieter → error", zustand("provider") == "error")
    check("unbekannter Anbieter → error", zustand("provider", provider="gibtsnicht") == "error")
    check("Anbieter ohne Fenster → ok mit „—“", zustand("provider", provider="openrouter") == "ok")

    bilder = {}
    for name, action, settings, art in (
        ("ring-ok", "provider", {"provider": "claude"}, "key"),
        ("ring-crit", "provider", {"provider": "codex"}, "key"),
        ("bar-warn", "provider", {"provider": "claude", "window": "weekly", "style": "bar"}, "key"),
        ("icon-crit", "provider", {"provider": "codex", "style": "icon"}, "key"),
        ("hintergrund", "provider", {"provider": "codex", "color_target": "background"}, "key"),
        ("uebrig", "provider", {"provider": "codex", "display": "remaining"}, "key"),
        ("ohne-fenster", "provider", {"provider": "openrouter"}, "key"),
        ("hoechste", "highest", {}, "key"),
        ("guthaben", "credits", {"provider": "codex"}, "key"),
        ("kosten", "credits", {"provider": "claude"}, "key"),
        ("dial", "dial", {"provider": "codex"}, "dial"),
        ("dial-guthaben", "dial", {"provider": "openrouter"}, "dial"),
        ("uebersicht", "overview", {}, "key"),
    ):
        s = {**vorgaben(action), **settings}
        bild = plugin.render(action, s, ctx_for(action, s, input_type=art))
        bilder[name] = bild
        speichern(bild, name)
        groesse = (120, 120) if art == "key" else (200, 100)
        check(f"{name}: {groesse[0]}×{groesse[1]}", bild.size == groesse, str(bild.size))

    check("kritischer Ring ist rot", farbig(bilder["ring-crit"], "#ef4444"))
    check("normaler Ring ist grün", farbig(bilder["ring-ok"], "#22c55e"))
    check("Warnbalken ist gelb", farbig(bilder["bar-warn"], "#eab308"))
    check("„übrig“ bleibt rot — Farbe nach Verbrauch", farbig(bilder["uebrig"], "#ef4444"))

    s = {**vorgaben("highest")}
    ctx = ctx_for("highest", s)
    check("höchste Auslastung: zuerst Codex", plugin._highest_view(s, ctx).provider.id == "codex")

    # Teilfehler und veraltet
    poller.snapshot = cb.parse_snapshot(frisch(fixture("snapshot-teilfehler.json")))
    check("Fehler beim Anbieter → error", zustand("provider", provider="codex") == "error")
    check("Cookie abgelaufen → login_missing", zustand("provider", provider="cursor") == "login_missing")
    for name, action, settings, art in (
        ("fehler", "provider", {"provider": "codex"}, "key"),
        ("login", "provider", {"provider": "cursor"}, "key"),
        ("dial-login", "dial", {"provider": "cursor"}, "dial"),
    ):
        s = {**vorgaben(action), **settings}
        bild = plugin.render(action, s, ctx_for(action, s, input_type=art))
        speichern(bild, name)
        check(f"{name} gezeichnet", bild.size[0] > 0)
    s = {**vorgaben("highest")}
    check("höchste Auslastung überspringt Fehler",
          plugin._highest_view(s, ctx_for("highest", s)).provider.id == "claude")

    alt = frisch(fixture("snapshot-ok.json"), datetime.now(timezone.utc) - timedelta(minutes=10))
    poller.snapshot = cb.parse_snapshot(alt)
    check("zehn Minuten alt → stale", zustand("provider", provider="claude") == "stale")
    s = {**vorgaben("provider"), "provider": "codex"}
    bild = plugin.render("provider", s, ctx_for("provider", s))
    speichern(bild, "veraltet")
    check("veraltet: kein sattes Rot mehr", not farbig(bild, "#ef4444", toleranz=25))

    print("\n== Plugin: Bedienung ==")
    poller.snapshot = cb.parse_snapshot(frisch(fixture("snapshot-ok.json")))
    s = {**vorgaben("provider"), "provider": "claude"}
    ctx = ctx_for("provider", s)
    await plugin.on_key_down("provider", s, ctx)
    await plugin.on_key_up("provider", s, ctx)
    check("Druck: Session → Woche", plugin._view("provider", s, ctx).window.kind == "weekly")
    await plugin.on_key_down("provider", s, ctx)
    await plugin.on_key_up("provider", s, ctx)
    check("Druck: Woche → Session", plugin._view("provider", s, ctx).window.kind == "session")

    geholt = []

    async def zaehlen():
        geholt.append(1)
        return False

    plugin.refresh = zaehlen
    await plugin.on_key_down("provider", s, ctx)
    ctx.scratch["pressed_at"] -= 0.8
    await plugin.on_key_up("provider", s, ctx)
    check("langer Druck: sofort aktualisieren", geholt == [1])
    check("… ohne das Fenster zu wechseln", plugin._view("provider", s, ctx).window.kind == "session")

    s = {**vorgaben("highest")}
    ctx = ctx_for("highest", s)
    reihenfolge = []
    for _ in range(3):
        reihenfolge.append(plugin._highest_view(s, ctx).provider.id)
        await plugin.on_key_down("highest", s, ctx)
        await plugin.on_key_up("highest", s, ctx)
    check("höchste: Codex → Claude → wieder Codex", reihenfolge == ["codex", "claude", "codex"],
          str(reihenfolge))

    s = {**vorgaben("credits"), "provider": "codex"}
    ctx = ctx_for("credits", s)
    werte = []
    for _ in range(3):
        werte.append(plugin._view("credits", s, ctx).caption)
        await plugin.on_key_down("credits", s, ctx)
        await plugin.on_key_up("credits", s, ctx)
    check("Guthaben → 30 Tage → Guthaben (Heute fehlt bei Codex)",
          werte == ["Guthaben", "30 Tage", "Guthaben"], str(werte))

    teil = cb.parse_snapshot(frisch(fixture("snapshot-teilfehler.json")))
    vorher = poller.snapshot
    poller.snapshot = teil
    s = {**vorgaben("dial")}
    check("Dial ohne Auswahl beginnt beim ersten Anbieter mit Werten",
          plugin._dial_provider(s, ctx_for("dial", s, input_type="dial")).id == "claude")
    poller.snapshot = vorher

    s = {**vorgaben("credits"), "provider": "claude"}
    ansicht = plugin._view("credits", s, ctx_for("credits", s))
    check("geschätzte Kosten tragen den Hinweis", ansicht.caption == "Heute"
          and ansicht.unit == "API-Preis, geschätzt", f"{ansicht.caption} / {ansicht.unit}")
    poller.snapshot.provider("codex").cost_estimated = False
    s = {**vorgaben("credits"), "provider": "codex", "show": "cost_30d"}
    ansicht = plugin._view("credits", s, ctx_for("credits", s))
    check("gemeldete Kosten ohne Hinweis", ansicht.caption == "30 Tage" and ansicht.unit == "",
          f"{ansicht.caption} / {ansicht.unit}")
    s = {**vorgaben("dial"), "provider": "claude"}
    ctx = ctx_for("dial", s, input_type="dial")
    await plugin.on_touch("dial", s, 10, 10, ctx)
    speichern(plugin.render("dial", s, ctx), "dial-detail-geschaetzt")

    s = {**vorgaben("dial"), "provider": "codex"}
    ctx = ctx_for("dial", s, input_type="dial")
    await plugin.on_dial_rotate("dial", s, 1, ctx)
    check("Drehen: nächster Anbieter", plugin._dial_provider(s, ctx).id == "claude")
    await plugin.on_dial_rotate("dial", s, -1, ctx)
    await plugin.on_dial_rotate("dial", s, -1, ctx)
    check("rückwärts über den Anfang", plugin._dial_provider(s, ctx).id == "openrouter")
    await plugin.on_dial_push("dial", s, ctx)
    check("Drücken: übrig", plugin._display(s, ctx) == "remaining")
    await plugin.on_touch("dial", s, 10, 10, ctx)
    ctx.scratch["provider"] = "claude"
    bild = plugin.render("dial", s, ctx)
    speichern(bild, "dial-detail")
    check("Tippen: Detailansicht offen", plugin._detail_open(ctx))
    await plugin.on_touch("dial", s, 10, 10, ctx)
    check("nochmal Tippen: zu", not plugin._detail_open(ctx))

    print("\n== Plugin: nur zeichnen, wenn sich etwas ändert ==")
    s = {**vorgaben("provider"), "provider": "claude"}
    ctx = ctx_for("provider", s)
    runtime.redraws = 0
    plugin.on_tick("provider", s, ctx)
    plugin.on_tick("provider", s, ctx)
    check("gleicher Stand: ein Bild, nicht zwei", runtime.redraws == 1, str(runtime.redraws))
    poller.snapshot.provider("claude").windows[0].used_pct = 21
    plugin.on_tick("provider", s, ctx)
    check("neuer Wert: neues Bild", runtime.redraws == 2, str(runtime.redraws))

    s = {**vorgaben("provider"), "provider": "codex", "pulse": True}
    ctx = ctx_for("provider", s)
    echte_uhr = modul.time
    phasen = []
    try:
        for sekunde in (10.0, 11.0):
            modul.time = types.SimpleNamespace(monotonic=lambda s=sekunde: s)
            phasen.append(plugin._view("provider", s, ctx).pulse)
        aus = {**s, "pulse": False}
        ohne = plugin._view("provider", aus, ctx_for("provider", aus)).pulse
        ok = {**s, "provider": "claude"}
        unkritisch = plugin._view("provider", ok, ctx_for("provider", ok)).pulse
    finally:
        modul.time = echte_uhr
    check("Puls wechselt im Sekundentakt", phasen == [True, False], str(phasen))
    check("ohne Einstellung kein Puls", ohne is False)
    check("unter der kritischen Schwelle kein Puls", unkritisch is False)

    print("\n== Plugin: Status, Optionen, Nutzung ==")
    status = plugin.get_status()
    check("Status nennt CodexBar und Anzahl", status["connected"] and "3 Anbieter" in status["detail"],
          status["detail"])
    optionen = plugin.get_dynamic_options("providers", {"provider": "weg"})
    check("Dropdown: alle Anbieter plus der verschwundene",
          [o["value"] for o in optionen] == ["codex", "claude", "openrouter", "weg"])
    check("ohne Belegung kein Abruf", plugin._in_use() is False)
    page = config.active_profile().root_page()
    page.dials[0] = Slot(plugin_id="streamdeck", action_id="none",
                         stack=[Slot(plugin_id="ai-usage", action_id="dial")])
    check("Belegung im Dial-Stack zählt", plugin._in_use() is True)
    del page.dials[0]

    print("\n== Übersicht ==")
    profile = config.active_profile()
    root = profile.root_page()
    s = {**vorgaben("overview")}
    ctx = ctx_for("overview", s, page_id=root.id)
    await plugin.on_key_down("overview", s, ctx)
    kinder = [p for p in profile.children(root.id) if ub.is_overview_page(p)]
    check("eine Ordnerseite unter der aktuellen Seite", len(kinder) == 1)
    seite = kinder[0]
    check("links oben Zurück", seite.keys[0].plugin_id == "streamdeck" and seite.keys[0].action_id == "back")
    check("je Anbieter eine Taste", [seite.keys[i].settings["provider"] for i in (1, 2, 3)]
          == ["codex", "claude", "openrouter"])
    check("gespeichert, GUI benachrichtigt, hingesprungen",
          runtime.gespeichert == 1 and "config_changed" in runtime.bus.events
          and runtime.navigiert[-1] == seite.id)

    seite.keys[1].appearance.label_color = "#ff00ff"
    gemerkt = seite.keys[1]
    await plugin.on_key_down("overview", s, ctx)
    kinder = [p for p in profile.children(root.id) if ub.is_overview_page(p)]
    check("zweiter Druck legt keine zweite Seite an", len(kinder) == 1 and kinder[0].id == seite.id)
    check("umgestaltete Taste bleibt dieselbe", kinder[0].keys[1] is gemerkt
          and gemerkt.appearance.label_color == "#ff00ff")

    # Deck mit drei Tasten, je Seite passen Zurück, ein Anbieter und Weiter.
    test = Profile(name="klein")
    oben = Page(name="Start")
    test.pages[oben.id] = oben
    test.root_page_id = oben.id
    seiten = ub.sync(test, oben.id, [("a", "A"), ("b", "B"), ("c", "C")], key_count=3,
                     settings={}, texts=tx.text)
    check("drei Anbieter auf drei Tasten → zwei Seiten", len(seiten) == 2, str(len(seiten)))
    check("erste Seite: Zurück, a, Weiter",
          seiten[0].keys[1].settings["provider"] == "a" and seiten[0].keys[2].action_id == "folder"
          and seiten[0].keys[2].settings["page_id"] == seiten[1].id)
    check("zweite Seite hängt unter der ersten", seiten[1].parent_id == seiten[0].id)
    seiten = ub.sync(test, oben.id, [("a", "A")], key_count=3, settings={}, texts=tx.text)
    check("ein Anbieter: Folgeseite wieder weg", len(seiten) == 1 and len(test.pages) == 2,
          str(len(test.pages)))
    check("… und kein Weiter mehr", 2 not in seiten[0].keys)

    await plugin.teardown()


async def main_async() -> int:
    pruefe_format()
    pruefe_http()
    pruefe_alerts()
    await pruefe_plugin()
    print()
    if FAILS:
        print(f"FEHLGESCHLAGEN ({len(FAILS)}): " + ", ".join(FAILS))
        return 1
    print("Alle Prüfungen bestanden.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main_async()))
