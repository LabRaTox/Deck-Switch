"""Prüft das Plugin „Web-Anfragen“: Einstellungen lesen, senden, Werte holen, zeichnen.

Gesendet wird nur an einen eigenen http.server auf 127.0.0.1 mit freiem
Port. IFTTT wird nie angefragt, dort steht eine Attrappe an Stelle von
``sende``.

Aufruf:

    cd backend
    d=$(mktemp -d); env XDG_CONFIG_HOME=$d XDG_DATA_HOME=$d \\
        ../.venv/bin/python tests/web_requests_test.py
"""
import _wache  # bricht ab, statt in die echte Config zu schreiben
_wache.sichere_umgebung()

import asyncio
import json
import logging
import os
import pathlib
import re
import socket
import ssl
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

PLUGIN_DIR = pathlib.Path(__file__).resolve().parents[2] / "plugin-sources" / "web-requests"
import _pluginlader  # noqa: E402
_pluginlader.ueberspringe_ohne(PLUGIN_DIR)

from deckswitch.config import Appearance, Slot, default_config  # noqa: E402
from deckswitch.plugins.base import Manifest, Services, SlotContext  # noqa: E402
from deckswitch.services.icons import IconService  # noqa: E402
from deckswitch.services.render import RenderService  # noqa: E402

from _pluginlader import lade, nachbar  # noqa: E402

# Ein Proxy aus der Umgebung soll die Anfragen an 127.0.0.1 nicht umleiten.
os.environ["no_proxy"] = os.environ["NO_PROXY"] = "127.0.0.1,localhost"

modul = lade(PLUGIN_DIR)
anfrage = nachbar(modul, "anfrage")
wert = nachbar(modul, "wert")

FAILS = []

GEHEIM = "geheim-token-4711"
QUERY_GEHEIM = "abfrage-geheimnis-0815"


def check(name, bedingung, detail=""):
    print(("  ✔ " if bedingung else "  ✘ ") + name + (f"  ({detail})" if detail else ""))
    if not bedingung:
        FAILS.append(name)


# -- Der eigene Server ----------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    zaehler: dict = {}

    def log_message(self, *a):
        pass

    def _antworte(self, status, rumpf, art="application/json", kopf=None):
        daten = rumpf if isinstance(rumpf, bytes) else rumpf.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", art)
        self.send_header("Content-Length", str(len(daten)))
        for name, inhalt in (kopf or {}).items():
            self.send_header(name, inhalt)
        self.end_headers()
        self.wfile.write(daten)

    def _bearbeite(self):
        # Nach einem absichtlichen Timeout hat der Client schon aufgelegt.
        try:
            self._beantworte()
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _beantworte(self):
        pfad = self.path.split("?")[0]
        Handler.zaehler[pfad] = Handler.zaehler.get(pfad, 0) + 1
        laenge = int(self.headers.get("Content-Length") or 0)
        rumpf = self.rfile.read(laenge).decode("utf-8") if laenge else ""
        if pfad == "/json":
            self._antworte(200, json.dumps({"data": {"items": [{"name": "eins"}, {"name": "zwei"}],
                                                     "anzahl": 2, "wahr": True}}))
        elif pfad == "/echo":
            self._antworte(200, json.dumps({
                "methode": self.command, "rumpf": rumpf,
                "kopf": {k.lower(): v for k, v in self.headers.items()},
            }))
        elif pfad.startswith("/status/"):
            code = int(pfad.rsplit("/", 1)[1])
            self._antworte(code, json.dumps({"fehler": code}))
        elif pfad == "/text":
            self._antworte(200, "\nTemperatur: 21.5 Grad\nzweite Zeile\n", "text/plain; charset=utf-8")
        elif pfad == "/gross":
            self._antworte(200, b"x" * 2_000_000, "text/plain")
        elif pfad == "/langsam":
            time.sleep(2.5)
            self._antworte(200, "{}")
        elif pfad == "/weiter":
            self._antworte(302, "", kopf={"Location": "/json"})
        elif pfad == "/weiter307":
            self._antworte(307, "", kopf={"Location": "/echo"})
        elif pfad == "/fremd":
            # localhost statt 127.0.0.1: für urllib ein anderer Host.
            self._antworte(302, "", kopf={"Location": f"http://localhost:{PORT}/echo"})
        elif pfad == "/datei":
            self._antworte(302, "", kopf={"Location": "file:///etc/passwd"})
        else:
            self._antworte(404, "{}")

    do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = _bearbeite


SERVER = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
SERVER.daemon_threads = True
PORT = SERVER.server_address[1]
BASIS = f"http://127.0.0.1:{PORT}"
threading.Thread(target=SERVER.serve_forever, daemon=True).start()


def freier_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# -- Umgebung des Plugins -------------------------------------------------------

class FakeRuntime:
    def __init__(self):
        self.redraws = 0
        self.meldungen = []

    def request_redraw(self, ctx=None):
        self.redraws += 1

    def notify(self, level, message, **extra):
        self.meldungen.append((level, str(message)))


class Mitschrift(logging.Handler):
    def __init__(self):
        super().__init__(logging.DEBUG)
        self.zeilen = []

    def emit(self, record):
        self.zeilen.append(record.getMessage())


manifest = Manifest.model_validate(json.loads((PLUGIN_DIR / "manifest.json").read_text()))
config = default_config()
icons = IconService()
runtime = FakeRuntime()
services = Services(audio=None, icons=icons, render=RenderService(icons), runtime=runtime,
                    config=config, plugin_dir=PLUGIN_DIR)

zaehler = [0]


def ctx_for(action, settings, *, input_type="key"):
    zaehler[0] += 1
    slot = Slot(plugin_id="web-requests", action_id=action, settings=settings,
                appearance=Appearance())
    return SlotContext(
        action_id=action, settings=settings, appearance=slot.appearance,
        input_type=input_type, index=zaehler[0], page_id="p", profile_id="pr",
        size=(120, 120) if input_type == "key" else (200, 100),
        services=services, slot=slot,
    )


def fehler_von(funktion, *args):
    try:
        funktion(*args)
    except (anfrage.AnfrageFehler, wert.WertFehler) as exc:
        return exc
    return None


# -- Prüfungen ohne Netz --------------------------------------------------------

def pruefe_eingaben():
    print("== Adressen und Kopfzeilen ==")
    check("Query und Zugangsdaten verschwinden aus der Anzeige",
          anfrage.zeige_url(f"https://ich:{GEHEIM}@host.example:8443/a/b?token={QUERY_GEHEIM}#x")
          == "https://host.example:8443/a/b",
          anfrage.zeige_url(f"https://ich:{GEHEIM}@host.example:8443/a/b?token={QUERY_GEHEIM}"))
    check("kaputte Adresse wird zu ---", anfrage.zeige_url("kein url") == "---")

    kopf = anfrage.lies_kopfzeilen("Accept: application/json\nX-Eins: 1 | X-Zwei: a:b")
    check("Zeilenumbruch und | trennen Kopfzeilen",
          kopf == [("Accept", "application/json"), ("X-Eins", "1"), ("X-Zwei", "a:b")], str(kopf))
    exc = fehler_von(anfrage.lies_kopfzeilen, f"Accept: x\nBearer {GEHEIM}")
    check("kaputte Kopfzeile wird erkannt", exc is not None)
    check("und nur mit ihrer Nummer gemeldet",
          exc is not None and "2" in exc.lang and GEHEIM not in exc.lang, exc.lang if exc else "")

    for name, geheim in (("Authorization", True), ("X-Api-Key", True), ("X-Auth-Token", True),
                         ("Cookie", True), ("Accept", False), ("Content-Type", False)):
        check(f"{name} gilt {'als' if geheim else 'nicht als'} geheim",
              anfrage.ist_geheim(name) is geheim)

    print("\n== Anfrage bauen ==")
    a = anfrage.baue_anfrage({"url": f"{BASIS}/echo"})
    check("Vorgabe ist GET ohne Rumpf", a.methode == "GET" and a.rumpf is None)
    check("Vorgabe-Timeout 10 s", a.timeout == 10.0, str(a.timeout))
    check("unbekannte Methode wird GET", anfrage.baue_anfrage(
        {"url": BASIS, "method": "TRACE"}).methode == "GET")
    for timeout, erwartet in ((0, 1.0), (500, 120.0), ("Quatsch", 10.0), (2.5, 2.5)):
        check(f"Timeout {timeout!r} wird {erwartet}",
              anfrage.baue_anfrage({"url": BASIS, "timeout": timeout}).timeout == erwartet)
    for url in ("file:///etc/passwd", "ftp://host/x", "javascript:alert(1)", "host.example/x"):
        exc = fehler_von(anfrage.baue_anfrage, {"url": url})
        check(f"{url} wird abgewiesen", exc is not None)
    check("leere Adresse wird abgewiesen", fehler_von(anfrage.baue_anfrage, {"url": " "}) is not None)

    a = anfrage.baue_anfrage({"url": BASIS, "method": "post", "body": '{"a": 1}'})
    check("POST mit JSON-Rumpf", a.methode == "POST" and a.rumpf == b'{"a": 1}')
    check("Content-Type JSON ist die Vorgabe",
          ("Content-Type", "application/json") in a.kopfzeilen, str(a.kopfzeilen))
    check("ungültiges JSON wird vor dem Senden erkannt",
          fehler_von(anfrage.baue_anfrage, {"url": BASIS, "body": "{kaputt"}) is not None)
    a = anfrage.baue_anfrage({"url": BASIS, "body": "a=1&b=2", "content_type": "form"})
    check("Formular", ("Content-Type", "application/x-www-form-urlencoded") in a.kopfzeilen)
    a = anfrage.baue_anfrage({"url": BASIS, "body": "hallo", "content_type": "text",
                              "headers": "content-type: text/csv"})
    check("eigene Content-Type-Kopfzeile hat Vorrang",
          [k for k in a.kopfzeilen if k[0].lower() == "content-type"] == [("content-type", "text/csv")],
          str(a.kopfzeilen))
    a = anfrage.baue_anfrage({"url": BASIS, "secret_header": f"Authorization: Bearer {GEHEIM}"})
    check("geheime Kopfzeile kommt dazu", ("Authorization", f"Bearer {GEHEIM}") in a.kopfzeilen)
    check("kaputte geheime Kopfzeile wird abgewiesen, ohne sie zu nennen",
          (lambda e: e is not None and GEHEIM not in e.lang)(
              fehler_von(anfrage.baue_anfrage, {"url": BASIS, "secret_header": GEHEIM})))
    a = anfrage.baue_anfrage({"url": f"http://ich:{GEHEIM}@127.0.0.1:{PORT}/echo?x={QUERY_GEHEIM}"})
    check("Zugangsdaten aus der Adresse werden Basic-Auth",
          any(n == "Authorization" and v.startswith("Basic ") for n, v in a.kopfzeilen)
          and "@" not in a.url, a.url)
    check("Anzeige ohne Zugangsdaten und Query",
          a.anzeige == f"http://127.0.0.1:{PORT}/echo", a.anzeige)

    print("\n== IFTTT bauen ==")
    i = anfrage.baue_ifttt({"event": "tür auf", "key": "ab/c?d", "value1": "x", "value3": 3})
    check("Adresse nach Doku, Teile maskiert",
          i.url == "https://maker.ifttt.com/trigger/t%C3%BCr%20auf/with/key/ab%2Fc%3Fd", i.url)
    check("POST mit JSON", i.methode == "POST" and ("Content-Type", "application/json") in i.kopfzeilen)
    check("nur gesetzte Werte", json.loads(i.rumpf) == {"value1": "x", "value3": "3"}, i.rumpf)
    check("Schlüssel steht nicht in der Anzeige", "ab" not in i.anzeige.split("/key/")[1], i.anzeige)
    check("ohne Ereignis kein Versand", fehler_von(anfrage.baue_ifttt, {"key": "k"}) is not None)
    check("ohne Schlüssel kein Versand", fehler_von(anfrage.baue_ifttt, {"event": "e"}) is not None)

    print("\n== Zertifikate ==")
    check("Vorgabe prüft das Zertifikat",
          anfrage._oeffner(False).handlers and _kontext(anfrage._oeffner(False)).verify_mode
          == ssl.CERT_REQUIRED)
    unsicher = _kontext(anfrage._oeffner(True))
    check("„nicht prüfen“ schaltet Prüfung und Hostnamen ab",
          unsicher.verify_mode == ssl.CERT_NONE and not unsicher.check_hostname)
    oeffner = anfrage._oeffner(False)
    namen = {type(h).__name__ for h in oeffner.handlers}
    check("der Öffner kennt weder file noch ftp noch data",
          not namen & {"FileHandler", "FTPHandler", "DataHandler"}, str(sorted(namen)))


def _kontext(oeffner):
    for handler in oeffner.handlers:
        if type(handler).__name__ == "HTTPSHandler":
            return handler._context
    raise AssertionError("kein HTTPSHandler")


def pruefe_werte():
    print("\n== Werte aus der Antwort ==")
    daten = json.dumps({"data": {"items": [{"name": "eins"}, {"name": "zwei"}], "n": 2.5,
                                 "an": False, "leer": None}})
    for pfad, erwartet in (("data.items.0.name", "eins"), ("data.items.-1.name", "zwei"),
                           ("data.n", "2.5"), ("data.an", "false"), ("data.leer", "---"),
                           ("data.items.1", '{"name":"zwei"}')):
        check(f"{pfad} → {erwartet}", wert.lies_wert(daten, pfad) == erwartet,
              str(wert.lies_wert(daten, pfad)))
    check("leerer Pfad zeigt alles", wert.lies_wert('{"a":1}', "") == '{"a":1}')
    for pfad in ("data.fehlt", "data.items.5", "data.items.name", "data.n.x"):
        check(f"{pfad} wird gemeldet", fehler_von(wert.lies_wert, daten, pfad) is not None)
    check("kein eval im Pfad",
          fehler_von(wert.lies_wert, daten, "__import__('os').system('true')") is not None)
    check("Pfad auf Text meldet „kein JSON“",
          fehler_von(wert.lies_wert, "hallo", "a.b") is not None)
    check("ohne Pfad und Regex die erste Zeile", wert.lies_wert("\n  erste \nzweite") == "erste")
    check("Regex mit Gruppe", wert.lies_wert("Temperatur: 21.5 Grad", "", r"(\d+\.\d+)") == "21.5")
    check("Regex ohne Gruppe", wert.lies_wert("abc123", "", r"\d+") == "123")
    check("Regex vor Pfad", wert.lies_wert(daten, "data.n", r'"name": "(\w+)"') == "eins")
    check("Regex ohne Treffer", wert.lies_wert("abc", "", r"\d") is None)
    check("kaputte Regex wird gemeldet", fehler_von(wert.lies_wert, "abc", "", "(") is not None)
    check("lange Werte werden gekürzt", len(wert.lies_wert("x" * 5000)) == wert.MAX_ZEICHEN)


# -- Prüfungen gegen den eigenen Server -----------------------------------------

def pruefe_senden():
    print("\n== Senden an 127.0.0.1 ==")
    a = anfrage.baue_anfrage({"url": f"{BASIS}/json"})
    antwort = anfrage.sende(a)
    check("GET liefert 200 und JSON", antwort.ok and json.loads(antwort.text)["data"]["anzahl"] == 2)

    a = anfrage.baue_anfrage({"url": f"{BASIS}/echo", "method": "PATCH", "body": '{"x": "ü"}',
                              "headers": "X-Eins: 1", "secret_header": f"X-Api-Key: {GEHEIM}"})
    echo = json.loads(anfrage.sende(a).text)
    check("Methode, Rumpf und Kopfzeilen kommen an",
          echo["methode"] == "PATCH" and json.loads(echo["rumpf"]) == {"x": "ü"}
          and echo["kopf"].get("x-eins") == "1" and echo["kopf"].get("x-api-key") == GEHEIM,
          json.dumps(echo)[:200])
    check("eigener User-Agent", echo["kopf"].get("user-agent", "").startswith("DECK-SWITCH"))

    a = anfrage.baue_anfrage({"url": f"http://ich:pw@127.0.0.1:{PORT}/echo"})
    echo = json.loads(anfrage.sende(a).text)
    check("Basic-Auth aus der Adresse kommt an", echo["kopf"].get("authorization") == "Basic aWNoOnB3")

    antwort = anfrage.sende(anfrage.baue_anfrage({"url": f"{BASIS}/status/404"}))
    check("404 kommt als Antwort zurück", antwort.status == 404 and not antwort.ok)

    antwort = anfrage.sende(anfrage.baue_anfrage({"url": f"{BASIS}/gross"}))
    check("große Antwort wird bei 1 MB abgeschnitten",
          antwort.abgeschnitten and len(antwort.text) == anfrage.MAX_BYTES, str(len(antwort.text)))

    start = time.monotonic()
    exc = fehler_von(anfrage.sende, anfrage.baue_anfrage({"url": f"{BASIS}/langsam", "timeout": 1}))
    dauer = time.monotonic() - start
    check("Timeout greift", exc is not None and exc.kurz == "Timeout" and dauer < 2.4,
          f"{dauer:.2f} s, {exc.lang if exc else ''}")

    exc = fehler_von(anfrage.sende, anfrage.baue_anfrage(
        {"url": f"http://127.0.0.1:{freier_port()}/?k={QUERY_GEHEIM}"}))
    check("geschlossener Port: abgelehnt", exc is not None and exc.kurz == "abgelehnt",
          exc.lang if exc else "")
    check("die Meldung nennt die Query nicht", exc is not None and QUERY_GEHEIM not in exc.lang)

    print("\n== Weiterleitungen ==")
    antwort = anfrage.sende(anfrage.baue_anfrage({"url": f"{BASIS}/weiter"}))
    check("302 wird verfolgt", antwort.ok and "eins" in antwort.text)
    a = anfrage.baue_anfrage({"url": f"{BASIS}/weiter307", "method": "POST", "body": "{\"a\":1}"})
    echo = json.loads(anfrage.sende(a).text)
    check("307 behält Methode und Rumpf", echo["methode"] == "POST" and echo["rumpf"] == '{"a":1}')
    a = anfrage.baue_anfrage({"url": f"{BASIS}/fremd", "headers": "X-Normal: ja",
                              "secret_header": f"Authorization: Bearer {GEHEIM}"})
    echo = json.loads(anfrage.sende(a).text)
    check("beim Hostwechsel fällt Authorization weg",
          "authorization" not in echo["kopf"] and echo["kopf"].get("x-normal") == "ja",
          json.dumps(echo["kopf"]))
    a = anfrage.baue_anfrage({"url": f"{BASIS}/weiter", "secret_header": f"X-Token: {GEHEIM}"})
    check("auf demselben Host bleibt sie", anfrage.sende(a).ok)
    antwort = anfrage.sende(anfrage.baue_anfrage({"url": f"{BASIS}/datei"}))
    check("eine Weiterleitung auf file:// wird nicht verfolgt",
          antwort.status == 302 and "root:" not in antwort.text, str(antwort.status))


# -- Das Plugin -----------------------------------------------------------------

async def warte(plugin, frist=8.0):
    ende = time.monotonic() + frist
    while plugin._aufgaben and time.monotonic() < ende:
        await asyncio.sleep(0.02)


async def pruefe_plugin():
    plugin = modul.WebRequestsPlugin(manifest, services)
    await plugin.setup()
    mitschrift = Mitschrift()
    logging.getLogger().addHandler(mitschrift)
    logging.getLogger().setLevel(logging.DEBUG)
    try:
        print("\n== Tastendruck ==")
        s = {"url": f"{BASIS}/json", "method": "GET"}
        c = ctx_for("send", s)
        check("vor dem Druck kein Zustand", plugin.get_state("send", s, c) is None)
        start = time.monotonic()
        await plugin.on_key_down("send", s, c)
        check("der Druck kehrt sofort zurück", time.monotonic() - start < 0.1)
        check("während der Anfrage läuft sie", c.scratch["web"].laeuft)
        await warte(plugin)
        check("danach Erfolg", plugin.get_state("send", s, c) == "ok")
        check("mit Statuscode auf der Taste", c.scratch["web"].blitz_gross == "200")
        bild = plugin.render("send", s, c)
        check("die Taste wird gezeichnet", bild.size == (120, 120))

        s404 = {"url": f"{BASIS}/status/404?token={QUERY_GEHEIM}",
                "secret_header": f"Authorization: Bearer {GEHEIM}"}
        c404 = ctx_for("send", s404)
        runtime.meldungen.clear()
        await plugin.on_key_down("send", s404, c404)
        await warte(plugin)
        check("404 zeigt Fehler", plugin.get_state("send", s404, c404) == "fehler")
        check("mit dem Code", c404.scratch["web"].blitz_gross == "404")
        check("und einer Meldung", len(runtime.meldungen) == 1, str(runtime.meldungen))
        await plugin.on_key_down("send", s404, c404)
        await warte(plugin)
        check("dieselbe Meldung kommt nicht noch einmal", len(runtime.meldungen) == 1,
              str(runtime.meldungen))
        bild = plugin.render("send", s404, c404)
        check("Fehlerkachel wird gezeichnet", bild.size == (120, 120))

        print("\n== Keine Geheimnisse in Meldungen und Log ==")
        alles = "\n".join([m for _, m in runtime.meldungen] + mitschrift.zeilen)
        check("das Token steht nirgends", GEHEIM not in alles)
        check("die Query steht nirgends", QUERY_GEHEIM not in alles)
        check("die Adresse ohne Query schon", f"127.0.0.1:{PORT}/status/404" in alles)

        print("\n== Anzeige eines Werts ==")
        sw = {"url": f"{BASIS}/json", "show_value": True, "json_path": "data.items.1.name",
              "prefix": "> ", "suffix": " <"}
        cw = ctx_for("send", sw)
        await plugin.on_key_down("send", sw, cw)
        await warte(plugin)
        check("der Wert steht im Zustand", cw.scratch["web"].wert == "zwei")
        check("mit Präfix und Suffix", plugin._anzeigewert(sw, cw.scratch["web"]) == "> zwei <")
        sr = {"url": f"{BASIS}/text", "show_value": True, "regex": r"(\d+\.\d) Grad", "suffix": " °C"}
        cr = ctx_for("send", sr)
        await plugin.on_key_down("send", sr, cr)
        await warte(plugin)
        check("Regex auf Text", cr.scratch["web"].wert == "21.5")
        sf = {"url": f"{BASIS}/json", "show_value": True, "json_path": "data.gibtsnicht"}
        cf = ctx_for("send", sf)
        await plugin.on_key_down("send", sf, cf)
        await warte(plugin)
        check("fehlender Pfad: kein Wert, kurzer Hinweis",
              cf.scratch["web"].wert is None and cf.scratch["web"].wert_fehler == "Pfad?")
        for kontext, einstellungen in ((cw, sw), (cr, sr), (cf, sf)):
            check("Wertkachel wird gezeichnet",
                  plugin.render("send", einstellungen, kontext).size == (120, 120))

        print("\n== Geänderte Einstellungen ==")
        sw2 = dict(sw, json_path="data.anzahl")
        check("ein neuer Pfad verwirft den alten Wert",
              plugin._zustand("send", sw2, cw).wert is None)

        print("\n== Regelmäßig abrufen ==")
        Handler.zaehler.clear()
        sp = {"url": f"{BASIS}/json", "poll": True, "interval": 5, "show_value": True,
              "json_path": "data.anzahl"}
        cp = ctx_for("send", sp)
        start = time.monotonic()
        await plugin.on_tick("send", sp, cp)
        check("der Tick wartet nicht auf die Antwort", time.monotonic() - start < 0.1)
        await warte(plugin)
        check("der erste Tick fragt sofort", Handler.zaehler.get("/json") == 1, str(Handler.zaehler))
        check("und zeigt den Wert", cp.scratch["web"].wert == "2")
        check("ohne Blitz", cp.scratch["web"].blitz_bis == 0.0)
        await plugin.on_tick("send", sp, cp)
        await warte(plugin)
        check("der nächste Tick wartet das Intervall ab", Handler.zaehler.get("/json") == 1)
        cp.scratch["web"].naechster = 0
        await plugin.on_tick("send", sp, cp)
        await warte(plugin)
        check("nach Ablauf wird wieder gefragt", Handler.zaehler.get("/json") == 2)
        check("ohne Tick, also ohne sichtbare Taste, fragt niemand",
              Handler.zaehler.get("/json") == 2)

        sx = {"url": f"{BASIS}/status/500", "poll": True, "interval": 5}
        cx = ctx_for("send", sx)
        runtime.meldungen.clear()
        await plugin.on_tick("send", sx, cx)
        await warte(plugin)
        z = cx.scratch["web"]
        check("Fehler beim Abruf verlängert den Abstand",
              z.naechster - time.monotonic() > 8, f"{z.naechster - time.monotonic():.1f} s")
        z.naechster = 0
        await plugin.on_tick("send", sx, cx)
        await warte(plugin)
        check("der Abstand wächst weiter", z.naechster - time.monotonic() > 18
              and z.fehlschlaege == 2)
        check("die Meldung kam einmal", len(runtime.meldungen) == 1, str(runtime.meldungen))
        check("der Abruf blitzt nicht", z.blitz_bis == 0.0)
        check("aber die Taste zeigt den Fehler", z.abruf_fehler == "500")
        sl = {"url": f"{BASIS}/langsam", "poll": True, "interval": 5}
        cl = ctx_for("send", sl)
        start = time.monotonic()
        await plugin.on_tick("send", sl, cl)
        await plugin.on_tick("send", sl, cl)
        check("auch bei langsamer Gegenstelle kehrt der Tick sofort zurück",
              time.monotonic() - start < 0.1)
        check("und es läuft nur eine Anfrage", len(plugin._aufgaben) == 1)
        await warte(plugin)
        cn = ctx_for("send", {"url": "", "poll": True})
        await plugin.on_tick("send", cn.settings, cn)
        check("ohne Adresse wird nicht abgefragt", not plugin._aufgaben)

        print("\n== Zeichnen ohne Netz ==")
        original = modul.sende

        def verboten(*a, **k):
            raise AssertionError("sende im Zeichnen")

        modul.sende = verboten
        try:
            for kontext, einstellungen in ((c, s), (cw, sw), (cp, sp), (cx, sx)):
                plugin.render("send", einstellungen, kontext)
                plugin.get_state("send", einstellungen, kontext)
            dial = ctx_for("send", sp, input_type="dial")
            check("Segment wird gezeichnet", plugin.render("send", sp, dial).size == (200, 100))
            check("render und get_state senden nie", True)
        finally:
            modul.sende = original

        print("\n== Blitz läuft ab ==")
        c.scratch["web"].blitz_bis = time.monotonic() - 1
        vorher = runtime.redraws
        await plugin.on_tick("send", s, c)
        check("nach Ablauf wird neu gezeichnet", runtime.redraws == vorher + 1)
        check("und der Zustand ist wieder neutral", plugin.get_state("send", s, c) is None)

        print("\n== IFTTT mit Attrappe ==")
        gesendet = []

        def attrappe(a, oeffner=None):
            gesendet.append(a)
            return anfrage.Antwort(status=200, grund="OK", text="Congratulations!")

        modul.sende = attrappe
        try:
            si = {"event": "deck", "key": GEHEIM, "value1": "eins"}
            ci = ctx_for("ifttt", si)
            await plugin.on_key_down("ifttt", si, ci)
            await warte(plugin)
            check("genau ein POST an maker.ifttt.com",
                  len(gesendet) == 1 and gesendet[0].methode == "POST"
                  and gesendet[0].url == f"https://maker.ifttt.com/trigger/deck/with/key/{GEHEIM}")
            check("mit value1 als JSON", json.loads(gesendet[0].rumpf) == {"value1": "eins"})
            check("Erfolg auf der Taste", plugin.get_state("ifttt", si, ci) == "ok")
            check("IFTTT-Segment wird gezeichnet",
                  plugin.render("ifttt", si, ctx_for("ifttt", si, input_type="dial")).size == (200, 100))
            runtime.meldungen.clear()
            cl2 = ctx_for("ifttt", {"event": "deck"})
            await plugin.on_dial_push("ifttt", cl2.settings, cl2)
            await warte(plugin)
            check("ohne Schlüssel kein Versand, aber eine Meldung",
                  len(gesendet) == 1 and len(runtime.meldungen) == 1
                  and plugin.get_state("ifttt", cl2.settings, cl2) == "fehler")
        finally:
            modul.sende = original

        alles = "\n".join([m for _, m in runtime.meldungen] + mitschrift.zeilen)
        check("der IFTTT-Schlüssel steht in keiner Meldung und keinem Log", GEHEIM not in alles)

        print("\n== Beenden ==")
        await plugin.on_key_down("send", sl, ctx_for("send", sl))
        await plugin.teardown()
        check("teardown räumt laufende Anfragen ab", not plugin._aufgaben)
    finally:
        logging.getLogger().removeHandler(mitschrift)


# -- Texte ------------------------------------------------------------------------

def pruefe_texte():
    print("\n== Texte ==")
    de = json.loads((PLUGIN_DIR / "locales" / "de.json").read_text())
    en = json.loads((PLUGIN_DIR / "locales" / "en.json").read_text())
    check("beide Sprachen haben dieselben Schlüssel", set(de) == set(en), str(set(de) ^ set(en)))
    platz = [k for k in de if set(re.findall(r"\{(\w+)", de[k]))
             != set(re.findall(r"\{(\w+)", en.get(k, "")))]
    check("Platzhalter stimmen überein", not platz, str(platz))
    benutzt = set()
    for datei in PLUGIN_DIR.glob("*.py"):
        quelltext = datei.read_text()
        benutzt |= set(re.findall(r'(?:self\.t|text)\(\s*"([^"]+)"', quelltext))
    fehlt = sorted(benutzt - set(de))
    check("jeder benutzte Schlüssel steht im Katalog", not fehlt, str(fehlt))
    unbenutzt = sorted(set(de) - benutzt)
    check("kein Schlüssel ohne Verwendung", not unbenutzt, str(unbenutzt))
    roh = "".join(p.read_text() for p in [*PLUGIN_DIR.rglob("*.json"), *PLUGIN_DIR.glob("*.py")])
    check("nirgends ein Gedankenstrich", "—" not in roh)
    check("das Manifest ist gültig", manifest.id == "web-requests" and len(manifest.actions) == 2)


def main() -> int:
    pruefe_eingaben()
    pruefe_werte()
    pruefe_senden()
    asyncio.run(pruefe_plugin())
    pruefe_texte()
    SERVER.shutdown()
    print()
    if FAILS:
        print(f"FEHLGESCHLAGEN: {len(FAILS)} · {', '.join(FAILS)}")
        return 1
    print("Alle Prüfungen bestanden.")
    return 0


sys.exit(main())
