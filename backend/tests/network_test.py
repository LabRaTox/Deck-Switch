"""Prüft das Netzwerk-Plugin: Wake on LAN, Pi-hole 5 und 6, die eigene IP.

Netz und Programme sind durchweg Attrappen. Es geht kein Paket hinaus,
es wird nichts angepingt und kein Programm gestartet. Die Pi-hole-
Attrappen antworten so, wie es die Pi-hole-Dokumentation beschreibt.

Aufruf:

    cd backend
    d=$(mktemp -d); env XDG_CONFIG_HOME=$d XDG_DATA_HOME=$d \\
        ../.venv/bin/python tests/network_test.py
"""
import _wache  # bricht ab, statt in die echte Config zu schreiben
_wache.sichere_umgebung()

import asyncio
import hashlib
import json
import pathlib
import subprocess
import sys
import time
import urllib.error
import urllib.parse

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

PLUGIN_DIR = pathlib.Path(__file__).resolve().parents[2] / "plugin-sources" / "network"
import _pluginlader  # noqa: E402
_pluginlader.ueberspringe_ohne(PLUGIN_DIR)

from deckswitch import texte  # noqa: E402
from deckswitch.config import Appearance, Slot, default_config  # noqa: E402
from deckswitch.plugins.base import Manifest, Services, SlotContext  # noqa: E402
from deckswitch.services.icons import IconService  # noqa: E402
from deckswitch.services.render import RenderService  # noqa: E402

from _pluginlader import lade, nachbar  # noqa: E402

netmod = lade(PLUGIN_DIR)
wolmod = nachbar(netmod, "netzwerk.wol")
pihmod = nachbar(netmod, "netzwerk.pihole")
ipmod = nachbar(netmod, "netzwerk.meineip")
NetzFehler = nachbar(netmod, "netzwerk.texte").NetzFehler

texte.verbinde_sprache(lambda: "de")

FAILS = []


def check(name, bedingung, detail=""):
    print(("  ✔ " if bedingung else "  ✘ ") + name + (f"  ({detail})" if detail else ""))
    if not bedingung:
        FAILS.append(name)


def wirft(funktion, *args, **kwargs):
    try:
        funktion(*args, **kwargs)
    except NetzFehler as exc:
        return str(exc)
    return None


# -- Attrappen ---------------------------------------------------------------


class FakeRuntime:
    def __init__(self):
        self.redraws = 0
        self.meldungen = []
        self.status = 0

    def request_redraw(self, ctx=None):
        self.redraws += 1

    def notify(self, level, message, **extra):
        self.meldungen.append((level, str(message)))

    def publish_plugin_status(self, plugin_id):
        self.status += 1


class FakeSocket:
    gesendet = []
    optionen = []

    def __init__(self, familie, art):
        self.familie, self.art = familie, art

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def setsockopt(self, *a):
        FakeSocket.optionen.append(a)

    def settimeout(self, t):
        pass

    def sendto(self, daten, ziel):
        FakeSocket.gesendet.append((daten, ziel))


class PiHole6:
    """Antwortet wie die REST-API von Pi-hole 6."""

    def __init__(self, passwort="geheim"):
        self.passwort = passwort
        self.sitzungen = set()
        self.blocking = "enabled"
        self.timer = None
        self.aufrufe = []
        self.anmeldungen = 0

    def __call__(self, methode, url, rumpf, kopf, timeout, kontext):
        self.aufrufe.append((methode, url, kopf.get("X-FTL-SID")))
        assert timeout and timeout <= 10, "jeder Aufruf braucht ein Timeout"
        pfad = urllib.parse.urlsplit(url).path
        daten = json.loads(rumpf) if rumpf else None
        if pfad == "/api/auth" and methode == "GET":
            return 401, json.dumps({"session": {"valid": False, "sid": None}}).encode()
        if pfad == "/api/auth" and methode == "POST":
            self.anmeldungen += 1
            if daten.get("password") != self.passwort:
                return 401, json.dumps({"session": {"valid": False, "totp": False,
                                                    "sid": None}}).encode()
            sid = f"sid{self.anmeldungen}"
            self.sitzungen.add(sid)
            return 200, json.dumps({"session": {"valid": True, "totp": False, "sid": sid,
                                                "csrf": "x", "validity": 300}}).encode()
        if pfad == "/api/auth" and methode == "DELETE":
            self.sitzungen.discard(kopf.get("X-FTL-SID"))
            return 204, b""
        if kopf.get("X-FTL-SID") not in self.sitzungen:
            return 401, json.dumps({"error": {"key": "unauthorized"}}).encode()
        if pfad == "/api/dns/blocking" and methode == "GET":
            return 200, json.dumps({"blocking": self.blocking, "timer": self.timer}).encode()
        if pfad == "/api/dns/blocking" and methode == "POST":
            self.blocking = "enabled" if daten["blocking"] else "disabled"
            self.timer = daten["timer"]
            self.letzter_rumpf = daten
            return 200, json.dumps({"blocking": self.blocking, "timer": self.timer}).encode()
        if pfad == "/api/stats/summary":
            return 200, json.dumps({"queries": {"total": 45210, "blocked": 5102,
                                                "percent_blocked": 11.285}}).encode()
        return 404, b"{}"


class PiHole5:
    """Antwortet wie ``/admin/api.php`` von Pi-hole 5."""

    def __init__(self, passwort="geheim"):
        self.token = hashlib.sha256(
            hashlib.sha256(passwort.encode()).hexdigest().encode()).hexdigest()
        self.status = "enabled"
        self.aufrufe = []

    def __call__(self, methode, url, rumpf, kopf, timeout, kontext):
        self.aufrufe.append((methode, url))
        teile = urllib.parse.urlsplit(url)
        if teile.path.startswith("/api/"):
            return 404, b"<html>404</html>"
        if teile.path != "/admin/api.php":
            return 404, b""
        werte = urllib.parse.parse_qs(teile.query, keep_blank_values=True)
        ok = werte.get("auth", [""])[0] == self.token
        if "summaryRaw" in werte:
            if not ok:
                return 200, b"[]"
            return 200, json.dumps({"status": self.status, "dns_queries_today": 1200,
                                    "ads_blocked_today": 300,
                                    "ads_percentage_today": 25.0}).encode()
        if "enable" in werte or "disable" in werte:
            if not ok:
                return 200, b"Not authorized!"
            self.status = "enabled" if "enable" in werte else "disabled"
            self.letzte = teile.query
            return 200, json.dumps({"status": self.status}).encode()
        return 200, b"[]"


# -- Umgebung ----------------------------------------------------------------

manifest = Manifest.model_validate(json.loads((PLUGIN_DIR / "manifest.json").read_text()))
config = default_config()
icons = IconService()
runtime = FakeRuntime()
services = Services(audio=None, icons=icons, render=RenderService(icons), runtime=runtime,
                    config=config, plugin_dir=PLUGIN_DIR)


def ctx_for(action, settings, *, index=0, input_type="key"):
    slot = Slot(plugin_id="network", action_id=action, settings=settings,
                appearance=Appearance())
    return SlotContext(
        action_id=action, settings=settings, appearance=slot.appearance,
        input_type=input_type, index=index, page_id="p", profile_id="pr",
        size=(120, 120) if input_type == "key" else (200, 100),
        services=services, slot=slot,
    )


def pruefe_wol():
    print("== MAC-Adressen ==")
    erwartet = bytes.fromhex("aabbccddeeff")
    for schreibweise in ("AA:BB:CC:DD:EE:FF", "aa-bb-cc-dd-ee-ff", "aabb.ccdd.eeff",
                         "AABBCCDDEEFF", "  aa:bb:cc:dd:ee:ff "):
        check(f"{schreibweise!r} wird gelesen", wolmod.mac_lesen(schreibweise) == erwartet)
    for falsch in ("AA:BB:CC:DD:EE", "AA:BB-CC:DD:EE:FF", "GG:BB:CC:DD:EE:FF",
                   "AABBCCDDEEFF00", "aa:bb:cc:dd:ee:ff:00"):
        check(f"{falsch!r} wird abgewiesen", wirft(wolmod.mac_lesen, falsch) is not None)
    check("ohne MAC eine eigene Meldung",
          "keine MAC" in (wirft(wolmod.mac_lesen, "") or ""), wirft(wolmod.mac_lesen, ""))

    print("\n== Magic Packet ==")
    paket = wolmod.magic_packet(erwartet)
    check("102 Bytes", len(paket) == 102, str(len(paket)))
    check("sechsmal FF vorweg", paket[:6] == b"\xff" * 6)
    check("sechzehnmal die MAC", paket[6:] == erwartet * 16)

    FakeSocket.gesendet.clear()
    wolmod.sende(erwartet, "255.255.255.255", 9, socket_fabrik=FakeSocket)
    daten, ziel = FakeSocket.gesendet[-1]
    check("geht an Broadcast und Port", ziel == ("255.255.255.255", 9), str(ziel))
    check("mit SO_BROADCAST", any(o[1:] == (wolmod.socket.SO_BROADCAST, 1)
                                  for o in FakeSocket.optionen))
    wolmod.sende(erwartet, "", "", socket_fabrik=FakeSocket)
    check("leere Felder nehmen die Vorgaben",
          FakeSocket.gesendet[-1][1] == ("255.255.255.255", 9), str(FakeSocket.gesendet[-1][1]))
    check("Broadcast muss IPv4 sein",
          wirft(wolmod.sende, erwartet, "nirgendwo", 9, socket_fabrik=FakeSocket) is not None)
    check("Port 0 wird abgewiesen",
          wirft(wolmod.sende, erwartet, "192.168.1.255", 0, socket_fabrik=FakeSocket) is not None)
    check("Port 70000 wird abgewiesen",
          wirft(wolmod.sende, erwartet, "192.168.1.255", 70000, socket_fabrik=FakeSocket)
          is not None)

    print("\n== Ping ==")
    aufrufe = []

    def starte(befehl, **kw):
        aufrufe.append((befehl, kw))
        return subprocess.CompletedProcess(befehl, 0 if befehl[-1] == "an" else 1)

    check("Antwort heißt erreichbar", wolmod.erreichbar("an", starte=starte) is True)
    check("keine Antwort heißt nicht erreichbar", wolmod.erreichbar("aus", starte=starte) is False)
    befehl, kw = aufrufe[0]
    check("ping -c1 -W1", befehl[:3] == ["ping", "-c1", "-W1"], str(befehl))
    check("mit Timeout", kw.get("timeout") and kw["timeout"] <= 5, str(kw.get("timeout")))

    def haengt(befehl, **kw):
        raise subprocess.TimeoutExpired(befehl, kw["timeout"])

    check("ein Timeout zählt als keine Antwort", wolmod.erreichbar("x", starte=haengt) is False)

    def fehlt(befehl, **kw):
        raise FileNotFoundError("ping")

    check("fehlt ping, kommt eine Meldung", wirft(wolmod.erreichbar, "x", starte=fehlt) is not None)
    check("ein führender Strich ist kein Host", wirft(wolmod.host_pruefen, "-f") is not None)
    check("Leerzeichen im Host fallen durch", wirft(wolmod.host_pruefen, "a b") is not None)
    check("IPv6 geht", wolmod.host_pruefen("fe80::1") == "fe80::1")
    check("Hostname geht", wolmod.host_pruefen("nas.local") == "nas.local")


def pruefe_pihole():
    print("\n== Pi-hole: Adresse ==")
    for roh, basis in (("pi.hole", "http://pi.hole"), ("http://192.168.1.2/admin/", "http://192.168.1.2"),
                       ("https://pi.hole:8443/api", "https://pi.hole:8443"),
                       ("http://x/admin/api.php", "http://x")):
        check(f"{roh!r} → {basis}", pihmod.adresse_lesen(roh) == basis, pihmod.adresse_lesen(roh))
    check("ftp:// wird abgewiesen", wirft(pihmod.adresse_lesen, "ftp://pi.hole") is not None)

    print("\n== Pi-hole 6 ==")
    server = PiHole6()
    ph = pihmod.PiHole("http://pi.hole", "geheim", oeffne=server)
    stand = ph.abrufen()
    check("Version 6 erkannt", ph.version == 6)
    check("blockiert", stand.blockiert is True)
    check("Zahlen aus /stats/summary",
          (stand.anfragen, stand.geblockt, round(stand.prozent, 2)) == (45210, 5102, 11.29),
          f"{stand.anfragen} {stand.geblockt} {stand.prozent}")
    check("die sid geht im Kopf X-FTL-SID mit",
          any(sid == "sid1" for _, url, sid in server.aufrufe if url.endswith("/api/dns/blocking")))
    ph.abrufen()
    check("die Sitzung wird wiederverwendet", server.anmeldungen == 1, str(server.anmeldungen))

    stand = ph.schalte(False, 300)
    check("Pause mit Timer", server.letzter_rumpf == {"blocking": False, "timer": 300},
          str(server.letzter_rumpf))
    check("danach pausiert mit Restzeit", stand.blockiert is False and stand.rest == 300)
    stand = ph.schalte(False, None)
    check("dauerhaft heißt timer null", server.letzter_rumpf == {"blocking": False, "timer": None})
    check("ohne Restzeit", stand.rest is None)
    stand = ph.schalte(True)
    check("wieder an", stand.blockiert is True and server.letzter_rumpf["timer"] is None)

    server.sitzungen.clear()  # Sitzung abgelaufen
    stand = ph.abrufen()
    check("nach 401 neu angemeldet", server.anmeldungen == 2 and stand.blockiert is True,
          str(server.anmeldungen))

    ph.abmelden()
    check("abmelden gibt die Sitzung frei", not server.sitzungen, str(server.sitzungen))

    falsch = pihmod.PiHole("pi.hole", "falsch", oeffne=PiHole6())
    meldung = wirft(falsch.abrufen)
    check("falsches Passwort gemeldet", meldung and "Passwort" in meldung, meldung)

    leer = PiHole6(passwort="")

    def ohne_passwort(methode, url, rumpf, kopf, timeout, kontext):
        if url.endswith("/api/auth") and methode == "POST":
            return 200, json.dumps({"session": {"valid": True, "sid": None,
                                                "validity": -1}}).encode()
        kopf = dict(kopf)
        leer.sitzungen.add(None)
        return leer(methode, url, rumpf, kopf, timeout, kontext)

    ph = pihmod.PiHole("pi.hole", "", oeffne=ohne_passwort)
    check("ohne Passwort geht es ohne sid", ph.abrufen().blockiert is True)

    def kaputt(*a):
        raise urllib.error.URLError(ConnectionRefusedError(111, "Connection refused"))

    meldung = wirft(pihmod.PiHole("pi.hole", "x", version="6", oeffne=kaputt).abrufen)
    check("nicht erreichbar gemeldet", meldung and "nicht erreichbar" in meldung, meldung)

    print("\n== Pi-hole 5 ==")
    server = PiHole5()
    ph = pihmod.PiHole("pi.hole", "geheim", oeffne=server)
    stand = ph.abrufen()
    check("Version 5 erkannt", ph.version == 5)
    check("Zahlen aus summaryRaw", (stand.anfragen, stand.geblockt, stand.prozent) == (1200, 300, 25.0))
    check("auth ist der doppelte SHA-256",
          any(f"auth={server.token}" in url for _, url in server.aufrufe))
    check("ein eingefügter Token bleibt, wie er ist", pihmod.v5_token(server.token.upper()) == server.token)
    stand = ph.schalte(False, 60)
    check("disable=60", server.letzte.startswith("disable=60&"), server.letzte)
    check("die Restzeit merkt sich das Plugin", stand.blockiert is False and 55 < (stand.rest or 0) <= 60,
          str(stand.rest))
    stand = ph.abrufen()
    check("auch beim nächsten Abruf", stand.rest is not None and stand.rest > 55)
    ph.schalte(False, None)
    check("dauerhaft heißt disable ohne Zahl", server.letzte.startswith("disable&"), server.letzte)
    stand = ph.schalte(True)
    check("enable", server.letzte.startswith("enable&") and stand.blockiert is True)
    meldung = wirft(pihmod.PiHole("pi.hole", "falsch", oeffne=PiHole5()).abrufen)
    check("falsches Passwort bei v5 gemeldet", meldung and "Passwort" in meldung, meldung)


def pruefe_ip():
    print("\n== Meine IP ==")

    class Antwort:
        def __init__(self, text):
            self.text = text

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self, n):
            return self.text.encode()[:n]

    gefragt = []

    def oeffne(anfrage, timeout):
        gefragt.append((anfrage.full_url, timeout))
        return Antwort({"https://api.ipify.org": "198.51.100.7\n",
                        "https://api6.ipify.org": "2001:db8::7",
                        "https://ipv4.icanhazip.com": "kaputt"}.get(anfrage.full_url, ""))

    check("IPv4 über ipify", ipmod.oeffentlich("4", "ipify", oeffne=oeffne) == "198.51.100.7")
    check("mit Timeout", gefragt[-1][1] and gefragt[-1][1] <= 10)
    check("IPv6 über api6.ipify.org", ipmod.oeffentlich("6", "ipify", oeffne=oeffne) == "2001:db8::7")
    check("eine unlesbare Antwort wird gemeldet",
          wirft(ipmod.oeffentlich, "4", "icanhazip", oeffne=oeffne) is not None)

    def falsch(anfrage, timeout):
        return Antwort("2001:db8::1")

    check("IPv6 auf die IPv4-Frage wird abgewiesen",
          wirft(ipmod.oeffentlich, "4", "ipify", oeffne=falsch) is not None)

    print("\n== Zwischenablage ==")
    gestartet = []

    def starte(befehl, **kw):
        gestartet.append((befehl, kw))
        return subprocess.CompletedProcess(befehl, 0)

    alles = {"wl-copy": "/usr/bin/wl-copy", "xclip": "/usr/bin/xclip"}
    check("Wayland nimmt wl-copy",
          ipmod.kopiere("1.2.3.4", starte=starte, finde=alles.get,
                        umgebung={"WAYLAND_DISPLAY": "wayland-1"}) == "wl-copy")
    check("mit dem Text auf stdin und Timeout",
          gestartet[-1][1]["input"] == b"1.2.3.4" and gestartet[-1][1]["timeout"] <= 5)
    check("Ausgaben umgelenkt, sonst wartete run() auf wl-copy",
          gestartet[-1][1]["stdout"] == subprocess.DEVNULL)
    check("X11 nimmt xclip",
          ipmod.kopiere("1.2.3.4", starte=starte, finde=alles.get,
                        umgebung={"DISPLAY": ":0"}) == "xclip")
    check("xclip in die Zwischenablage", gestartet[-1][0] == ["xclip", "-selection", "clipboard"])
    meldung = wirft(ipmod.kopiere, "1.2.3.4", starte=starte, finde=lambda n: None,
                    umgebung={"WAYLAND_DISPLAY": "wayland-1"})
    check("ohne wl-copy ein Hinweis", meldung and "wl-copy" in meldung, meldung)
    meldung = wirft(ipmod.kopiere, "1.2.3.4", starte=starte, finde=alles.get, umgebung={})
    check("ganz ohne Anzeige auch", meldung is not None, meldung)


async def pruefe_plugin() -> None:
    print("\n== Das Plugin ==")
    server = PiHole6()
    pihmod._oeffne = server  # jede neue PiHole-Instanz spricht mit der Attrappe
    pings = []
    wolmod_erreichbar = wolmod.erreichbar

    def ping(host):
        pings.append(host)
        return host == "an.local"

    wolmod.erreichbar = ping
    ip_aufrufe = []

    def oeffentlich(familie, dienst):
        ip_aufrufe.append((familie, dienst))
        if dienst == "icanhazip":
            raise NetzFehler("kaputt")
        return "198.51.100.7" if familie == "4" else "2001:db8:1234:5678:9abc:def0:1234:5678"

    ipmod.oeffentlich = oeffentlich
    FakeSocket.gesendet.clear()
    gesendet_mit = []

    def sende(mac, broadcast, port):
        gesendet_mit.append((mac, broadcast, port))

    wolmod.sende = sende

    config.plugin_settings["network"] = {"pihole_url": "http://pi.hole",
                                         "pihole_password": "geheim"}
    plugin = netmod.NetworkPlugin(manifest, services)
    await plugin.setup()
    try:
        # Die Schleife arbeitet sonst nebenher mit; hier wird von Hand gedreht.
        plugin._schleife_task.cancel()

        print("-- nur bei sichtbarer Kachel --")
        check("ohne Tick wird nichts gefragt", not plugin._runde() and not server.aufrufe)
        blk = ctx_for("pihole_blocking", {"pause": 300}, index=1)
        plugin.on_tick("pihole_blocking", blk.settings, blk)
        aufgaben = plugin._runde()
        await asyncio.gather(*aufgaben)
        check("nach dem Tick wird gefragt", len(aufgaben) == 1 and server.anmeldungen == 1)
        check("die Taste zeigt AN", plugin._anzeige("pihole_blocking", blk.settings, blk)[0] == "AN")
        check("und nicht gleich noch einmal", not plugin._runde())
        plugin._abfragen["pihole"].gesehen -= netmod.SICHTBAR_S + 1
        plugin._abfragen["pihole"].naechste = 0
        check("unsichtbar ruht die Abfrage", not plugin._runde())

        print("-- Schalten --")
        await plugin.on_key_down("pihole_blocking", blk.settings, blk)
        check("Druck pausiert für die eingestellte Zeit",
              server.letzter_rumpf == {"blocking": False, "timer": 300}, str(server.letzter_rumpf))
        gross, klein, rand, _ = plugin._anzeige("pihole_blocking", blk.settings, blk)
        check("die Taste zeigt die Restzeit", gross in ("05:00", "04:59"), gross)
        check("in Orange", rand == netmod.FARBE_PAUSE)
        check("Zustand pause", plugin.get_state("pihole_blocking", blk.settings, blk) == "pause")
        await plugin.on_key_down("pihole_blocking", blk.settings, blk)
        check("zweiter Druck schaltet wieder an", server.blocking == "enabled")

        print("-- Dial --")
        dial = ctx_for("pihole_blocking", {"pause": 300}, index=2, input_type="dial")
        plugin.on_dial_rotate("pihole_blocking", dial.settings, 1, dial)
        check("Drehen nach rechts verlängert", dial.scratch["pause"] == 600, str(dial.scratch))
        plugin.on_dial_rotate("pihole_blocking", dial.settings, -1, dial)
        plugin.on_dial_rotate("pihole_blocking", dial.settings, -1, dial)
        check("nach links verkürzt", dial.scratch["pause"] == 120, str(dial.scratch))
        for _ in range(20):
            plugin.on_dial_rotate("pihole_blocking", dial.settings, 1, dial)
        check("am Ende steht unbegrenzt", dial.scratch["pause"] == 0)
        await plugin.on_dial_push("pihole_blocking", dial.settings, dial)
        check("Drücken pausiert ohne Timer",
              server.letzter_rumpf == {"blocking": False, "timer": None}, str(server.letzter_rumpf))
        check("die Taste zeigt AUS", plugin._anzeige("pihole_blocking", blk.settings, blk)[0] == "AUS")
        await plugin.on_dial_push("pihole_blocking", dial.settings, dial)
        check("Drücken schaltet wieder an", server.blocking == "enabled")

        print("-- Statistik --")
        for zeigen, erwartet in (("percent", "11,3%"), ("total", "45.210"), ("blocked", "5.102")):
            c = ctx_for("pihole_stats", {"show": zeigen}, index=3)
            gross = plugin._anzeige("pihole_stats", c.settings, c)[0]
            check(f"{zeigen} → {erwartet}", gross == erwartet, gross)
        texte.verbinde_sprache(lambda: "en")
        c = ctx_for("pihole_stats", {"show": "total"}, index=3)
        check("auf Englisch mit Komma als Tausender",
              plugin._anzeige("pihole_stats", c.settings, c)[0] == "45,210")
        texte.verbinde_sprache(lambda: "de")
        check("große Zahlen werden kurz", plugin._menge(1_234_567) == "1,2M", plugin._menge(1_234_567))
        check("ab hunderttausend in k", plugin._menge(234_567) == "235k", plugin._menge(234_567))

        print("-- Statistik weiterschalten --")
        def gross_von(c):
            return plugin._anzeige("pihole_stats", c.settings, c)[0]

        taste = ctx_for("pihole_stats", {"show": "percent"}, index=4)
        gesehen = [gross_von(taste)]
        for _ in range(3):
            await plugin.on_key_down("pihole_stats", taste.settings, taste)
            gesehen.append(gross_von(taste))
        check("Drücken geht Prozent, Anfragen, Geblockt und wieder von vorn",
              gesehen == ["11,3%", "45.210", "5.102", "11,3%"], str(gesehen))
        start = ctx_for("pihole_stats", {"show": "blocked"}, index=5)
        await plugin.on_key_down("pihole_stats", start.settings, start)
        check("die Einstellung bestimmt, wo es losgeht", gross_von(start) == "11,3%", gross_von(start))

        drehen = ctx_for("pihole_stats", {"show": "percent"}, index=6, input_type="dial")
        plugin.on_dial_rotate("pihole_stats", drehen.settings, 1, drehen)
        check("Drehen nach rechts zeigt die Anfragen", gross_von(drehen) == "45.210", gross_von(drehen))
        plugin.on_dial_rotate("pihole_stats", drehen.settings, -1, drehen)
        plugin.on_dial_rotate("pihole_stats", drehen.settings, -1, drehen)
        check("nach links zurück bis zu den geblockten", gross_von(drehen) == "5.102", gross_von(drehen))
        await plugin.on_dial_push("pihole_stats", drehen.settings, drehen)
        check("ein Druck am Dial schaltet auch weiter", gross_von(drehen) == "11,3%", gross_von(drehen))

        print("-- Status --")
        status = plugin.get_status()
        check("Status verbunden", status["connected"] and "Pi-hole 6" in status["detail"], str(status))

        print("-- Fehler und Backoff --")
        server.sitzungen.clear()
        server.passwort = "anders"
        meldungen_vorher = len(runtime.meldungen)
        abfrage = plugin._abfragen["pihole"]
        plugin.on_tick("pihole_stats", c.settings, c)
        abfrage.naechste = 0
        await asyncio.gather(*plugin._runde())
        erste = abfrage.naechste - time.monotonic()
        check("nach dem Fehler wird gewartet", 14 < erste <= 15, f"{erste:.1f}")
        check("die Taste zeigt den Fehler", plugin._anzeige("pihole_stats", c.settings, c)[0] == "!")
        abfrage.naechste = 0
        plugin.on_tick("pihole_stats", c.settings, c)
        await asyncio.gather(*plugin._runde())
        zweite = abfrage.naechste - time.monotonic()
        check("der Abstand wächst", 29 < zweite <= 30, f"{zweite:.1f}")
        neu = runtime.meldungen[meldungen_vorher:]
        check("dieselbe Meldung kommt nur einmal", len(neu) == 1, str(neu))
        check("kein Passwort in der Meldung", not any("anders" in m for _, m in neu))
        check("Status zeigt den Fehler", plugin.get_status()["connected"] is False)
        server.passwort = "geheim"
        abfrage.naechste = 0
        await asyncio.gather(*plugin._runde())
        check("danach klappt es wieder", not abfrage.fehler and abfrage.fehlschlaege == 0)

        print("-- Wake on LAN --")
        w = ctx_for("wol", {"mac": "aa-bb-cc-dd-ee-ff", "broadcast": "192.168.1.255", "port": 9,
                            "host": "an.local"}, index=4)
        check("vor dem Ping bereit", plugin.get_state("wol", w.settings, w) == "bereit")
        plugin.on_tick("wol", w.settings, w)
        await asyncio.gather(*plugin._runde())
        check("sichtbar wird gepingt", pings == ["an.local"], str(pings))
        check("und zeigt erreichbar", plugin.get_state("wol", w.settings, w) == "online")
        await plugin.on_key_down("wol", w.settings, w)
        check("Druck schickt das Paket",
              gesendet_mit and gesendet_mit[-1] == (bytes.fromhex("aabbccddeeff"),
                                                    "192.168.1.255", 9), str(gesendet_mit))
        check("und bestätigt", plugin.get_label("wol", w.settings, w) == "gesendet")
        check("Zustand gesendet", plugin.get_state("wol", w.settings, w) == "gesendet")
        aus = ctx_for("wol", {"mac": "aabbccddeeff", "host": "aus.local"}, index=5)
        plugin.on_tick("wol", aus.settings, aus)
        await asyncio.gather(*plugin._runde())
        check("ein stummes Gerät zeigt offline", plugin.get_state("wol", aus.settings, aus) == "offline")
        ohne = ctx_for("wol", {"mac": "quatsch"}, index=6)
        meldungen_vorher = len(runtime.meldungen)
        await plugin.on_key_down("wol", ohne.settings, ohne)
        check("eine falsche MAC wird gemeldet", len(runtime.meldungen) == meldungen_vorher + 1)
        check("die Taste sagt es", plugin.get_label("wol", ohne.settings, ohne) == "keine MAC")
        boese = ctx_for("wol", {"mac": "aabbccddeeff", "host": "-c 99 x"}, index=7)
        plugin.on_tick("wol", boese.settings, boese)
        check("ein Host mit Strich wird nicht gepingt",
              not any(k.startswith("ping:-") for k in plugin._abfragen))

        print("-- Meine IP --")
        ip = ctx_for("myip", {"where": "public", "family": "4", "service": "ipify",
                              "interval": 10, "copy": True}, index=8)
        plugin.on_tick("myip", ip.settings, ip)
        await asyncio.gather(*plugin._runde())
        check("die IP wird geholt", plugin._anzeige("myip", ip.settings, ip)[0] == "198.51.100.7")
        abfrage = plugin._abfragen["ip:public:4:ipify"]
        check("Vorgabe zehn Minuten", abfrage.intervall == 600, str(abfrage.intervall))
        kopiert = []

        def kopiere(text):
            kopiert.append(text)
            return "wl-copy"

        ipmod.kopiere = kopiere
        await plugin.on_key_down("myip", ip.settings, ip)
        check("Druck fragt neu", ip_aufrufe.count(("4", "ipify")) == 2, str(ip_aufrufe))
        check("und kopiert", kopiert == ["198.51.100.7"], str(kopiert))
        check("die Taste bestätigt", plugin._anzeige("myip", ip.settings, ip)[1] == "kopiert")

        def ohne_programm(text):
            raise NetzFehler("Zum Kopieren fehlt wl-copy.")

        ipmod.kopiere = ohne_programm
        vorher = len(runtime.meldungen)
        ip.scratch.clear()
        await plugin.on_key_down("myip", ip.settings, ip)
        await plugin.on_key_down("myip", ip.settings, ip)
        check("ohne Programm ein Hinweis, nur einmal", len(runtime.meldungen) == vorher + 1,
              str(runtime.meldungen[vorher:]))
        check("die Taste sagt es", plugin._anzeige("myip", ip.settings, ip)[1] == "nicht kopiert")

        kaputt = ctx_for("myip", {"where": "public", "family": "4", "service": "icanhazip"}, index=9)
        plugin.on_tick("myip", kaputt.settings, kaputt)
        await asyncio.gather(*plugin._runde())
        check("ein Dienstfehler zeigt !", plugin._anzeige("myip", kaputt.settings, kaputt)[0] == "!")

        sechs = ctx_for("myip", {"where": "public", "family": "6", "service": "ipify"}, index=10)
        plugin.on_tick("myip", sechs.settings, sechs)
        await asyncio.gather(*plugin._runde())

        print("-- Zeichnen --")
        faelle = [
            ("wol", w.settings), ("pihole_blocking", {"pause": 300}),
            ("pihole_stats", {"show": "percent"}), ("myip", ip.settings),
            ("myip", sechs.settings),
        ]
        for aktion, einstellungen in faelle:
            for art, groesse in (("key", (120, 120)), ("dial", (200, 100))):
                c = ctx_for(aktion, dict(einstellungen), index=20, input_type=art)
                bild = plugin.render(aktion, c.settings, c)
                check(f"{aktion} als {art}", bild.size == groesse, str(bild.size))

        from PIL import ImageDraw
        from deckswitch.services.render import load_font

        bild = plugin.render("myip", sechs.settings, ctx_for("myip", sechs.settings, index=21))
        zeilen = plugin._umbrechen(ImageDraw.Draw(bild), "2001:db8:1234:5678:9abc:def0:1234:5678",
                                   load_font(14, bold=True), 104, True)
        check("IPv6 wird an Doppelpunkten umbrochen",
              len(zeilen) > 1 and "".join(zeilen) == "2001:db8:1234:5678:9abc:def0:1234:5678",
              str(zeilen))

        print("-- ohne Pi-hole --")
        config.plugin_settings["network"] = {}
        plugin.on_plugin_config_changed({})
        c = ctx_for("pihole_blocking", {"pause": 300}, index=11)
        check("ohne Adresse zeigt die Taste ---",
              plugin._anzeige("pihole_blocking", c.settings, c)[0] == "---")
        check("ohne Adresse kein Status", plugin.get_status() is None)
        plugin.on_tick("pihole_blocking", c.settings, c)
        check("und es wird nichts gefragt", not any(
            k == "pihole" for k in [k for k in plugin._abfragen if plugin._abfragen[k].laeuft]))
        config.plugin_settings["network"] = {"pihole_url": "ftp://pi.hole"}
        plugin.on_plugin_config_changed({})
        check("eine falsche Adresse steht im Status",
              plugin.get_status()["connected"] is False)
    finally:
        await plugin.teardown()
        wolmod.erreichbar = wolmod_erreichbar

    print("\n== Texte ==")
    de = json.loads((PLUGIN_DIR / "locales" / "de.json").read_text())
    en = json.loads((PLUGIN_DIR / "locales" / "en.json").read_text())
    check("beide Sprachen haben dieselben Schlüssel", de.keys() == en.keys(),
          str(set(de) ^ set(en)))
    import re
    platz = [k for k in de if set(re.findall(r"\{(\w+)\}", de[k])) !=
             set(re.findall(r"\{(\w+)\}", en[k]))]
    check("mit denselben Platzhaltern", not platz, str(platz))
    roh = (PLUGIN_DIR / "manifest.json").read_text() + json.dumps(de, ensure_ascii=False) + \
        json.dumps(en, ensure_ascii=False)
    check("kein Gedankenstrich", "—" not in roh)
    quelltext = "".join(p.read_text() for p in PLUGIN_DIR.rglob("*.py"))
    benutzt = set(re.findall(r'(?:self\.t|text)\(\s*"([a-z_.0-9]+)"', quelltext))
    check("jeder benutzte Schlüssel steht in de.json", benutzt <= de.keys(), str(benutzt - de.keys()))


def main() -> int:
    pruefe_wol()
    pruefe_pihole()
    pruefe_ip()
    asyncio.run(pruefe_plugin())
    print()
    if FAILS:
        print(f"FEHLGESCHLAGEN: {len(FAILS)} — {', '.join(FAILS)}")
        return 1
    print("Alle Prüfungen bestanden.")
    return 0


sys.exit(main())
