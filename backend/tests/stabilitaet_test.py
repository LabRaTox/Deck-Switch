"""Prüft Fälle, in denen Tasten hängen blieben, Sperren sich aushebeln ließen
oder das Backend nicht startete beziehungsweise nicht endete:

* Netz-Deck: Drücken und Loslassen überholen sich, Loslassen geht verloren,
  die Sitzung endet oder verstummt, das Deck wird abgeschaltet,
* die Sperre gegen Raten gilt je Deck und auch über viele Adressen hinweg,
* Drücken und Loslassen derselben Taste laufen nacheinander,
* eine wiederholende Kette endet mit ihrer Belegung,
* der Rückweg auf ein gelöschtes Profil,
* zwei Geräte mit derselben Seriennummer, eins ohne lesbare Seriennummer,
* ein wiederhergestellter Stand trennt Netz-Sitzungen,
* eine Config in falscher Kodierung, ein Port außerhalb des Bereichs,
* ein hängender Hook beim Beenden.

Es wird kein echtes Gerät geöffnet: Die Gerätesuche ist abgeklemmt.

Aufruf:

    cd backend
    d=$(mktemp -d); env XDG_CONFIG_HOME=$d XDG_DATA_HOME=$d \\
        ../.venv/bin/python tests/stabilitaet_test.py
"""
import _wache  # bricht ab, statt in die echte Config zu schreiben
_wache.sichere_umgebung()

import asyncio
import json
import os
import socket
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import uvicorn

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from deckswitch import device as device_module  # noqa: E402

# Niemals ein echtes Gerät anfassen.
device_module.enumerate_decks = lambda: []

from deckswitch import netauth, netserver, paths  # noqa: E402
from deckswitch.config import Config, ConfigLoadError, ConfigStore, Slot, Step  # noqa: E402
from deckswitch.device import DeviceInfo, StreamDeckDevice  # noqa: E402
from deckswitch.netserver import create_net_app  # noqa: E402
from deckswitch.plugins.base import ActionPlugin, Manifest  # noqa: E402
from deckswitch.plugins.loader import LoadedPlugin  # noqa: E402
from deckswitch.runtime import Runtime  # noqa: E402

FAILS: list[str] = []
LOG: list[tuple] = []


def check(name, condition, detail=""):
    print(("  ✔ " if condition else "  ✘ ") + name + (f"  ({detail})" if detail else ""))
    if not condition:
        FAILS.append(name)


class Recorder(ActionPlugin):
    langsam = 0.0

    def on_key_down(self, action_id, settings, ctx):
        LOG.append(("down-start", ctx.index))
        if self.langsam:
            time.sleep(self.langsam)
        LOG.append(("down-end", ctx.index))

    def on_key_up(self, action_id, settings, ctx):
        LOG.append(("up", ctx.index))


def _runtime() -> Runtime:
    runtime = Runtime(None)
    runtime._loop = asyncio.get_running_loop()
    runtime.bus.bind_loop(runtime._loop)
    runtime.config.ensure_decks()
    runtime._sync_decks()
    return runtime


def _registriere(runtime, cls, pid):
    manifest = Manifest(id=pid, name=pid, type="action")
    inst = cls(manifest, runtime._services_for(Path()))
    runtime.registry.plugins[pid] = LoadedPlugin(manifest=manifest, directory=Path(), instance=inst)
    return inst


def _freier_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


async def _http(basis, pfad, daten=None, token=None):
    def arbeite():
        anfrage = urllib.request.Request(basis + pfad, method="POST" if daten is not None else "GET")
        if token:
            anfrage.add_header("Authorization", f"Bearer {token}")
        koerper = None
        if daten is not None:
            koerper = json.dumps(daten).encode()
            anfrage.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(anfrage, koerper, timeout=10) as antwort:
                return antwort.status, antwort.read()
        except urllib.error.HTTPError as fehler:
            return fehler.code, fehler.read()
    return await asyncio.to_thread(arbeite)


def _zaehle(art):
    return sum(1 for e in LOG if e[0] == art)


# ---------------------------------------------------------------------------


async def netz_deck() -> None:
    print("\n== Netz-Deck: gehaltene Tasten ==")
    rt = _runtime()
    _registriere(rt, Recorder, "rec")
    a = rt.create_network_deck("Gast", columns=3, rows=2)
    b = rt.create_network_deck("Admin", columns=3, rows=2)
    rt.netz.set_password(a.key, "gast1234")
    rt.netz.set_password(b.key, "9137")
    for i in range(3):
        a.current_page.keys[i] = Slot(plugin_id="rec", action_id="x")

    app = create_net_app(rt, rt.netz.sitzungen)
    port = _freier_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    aufgabe = asyncio.create_task(server.serve())
    await asyncio.sleep(0.5)
    basis = f"http://127.0.0.1:{port}"

    async def anmelden():
        _, koerper = await _http(basis, "/api/login", {"deck": a.key, "password": "gast1234"})
        return json.loads(koerper)["token"]

    async def drueck(token, index, aktion, seq=None):
        daten = {"input_type": "key", "index": index, "action": aktion}
        if seq is not None:
            daten["seq"] = seq
        _, koerper = await _http(basis, "/api/input", daten, token)
        await asyncio.sleep(0.15)
        return json.loads(koerper).get("ok")

    token = await anmelden()

    # Das Loslassen überholt das Drücken.
    LOG.clear()
    await drueck(token, 0, "up", seq=2)
    angenommen = await drueck(token, 0, "down", seq=1)
    check("ein überholtes Drücken wird verworfen", angenommen is False and 0 not in a._held_slots,
          str(LOG))
    check("und löst gar nichts aus", _zaehle("down-start") == 0)

    # Loslassen ohne Drücken.
    angenommen = await drueck(token, 1, "up", seq=5)
    check("Loslassen ohne vorheriges Drücken zählt nicht", angenommen is False)

    # Die gewöhnliche Reihenfolge geht weiter.
    await drueck(token, 1, "down", seq=6)
    await drueck(token, 1, "up", seq=7)
    check("Drücken und Loslassen in Reihenfolge kommen an",
          _zaehle("down-end") == 1 and _zaehle("up") == 1, str(LOG))

    # Abmelden mit gehaltener Taste.
    LOG.clear()
    await drueck(token, 0, "down", seq=10)
    check("die Taste gilt als gehalten", 0 in a._held_slots)
    await _http(basis, "/api/logout", {}, token)
    await asyncio.sleep(0.2)
    check("Abmelden lässt sie los", 0 not in a._held_slots and _zaehle("up") == 1, str(LOG))

    # Neu laden mit demselben Token: Die Nummern beginnen bei der Uhrzeit.
    token = await anmelden()
    LOG.clear()
    await drueck(token, 2, "down", seq=int(time.time() * 1000))
    check("ein Druck vor dem Verwerfen ist gehalten", 2 in a._held_slots)
    rt.netz.sitzungen.alle_verwerfen(a.key)
    await asyncio.sleep(0.2)
    check("Verwerfen aller Sitzungen lässt los", 2 not in a._held_slots and _zaehle("up") == 1)

    # Verstummen: Die Wache lässt nach WACHHUND_S los.
    alt = netserver.WACHHUND_S
    netserver.WACHHUND_S = 1.0
    token = await anmelden()
    LOG.clear()
    await drueck(token, 0, "down", seq=100)
    await asyncio.sleep(0.5)
    check("kurz ohne Anfrage bleibt die Taste gehalten", 0 in a._held_slots)
    await asyncio.sleep(2.0)
    check("verstummt die Sitzung, lässt die Wache los",
          0 not in a._held_slots and _zaehle("up") == 1, str(LOG))
    netserver.WACHHUND_S = alt

    # Wer weiter fragt, behält seine Taste.
    netserver.WACHHUND_S = 1.0
    LOG.clear()
    await drueck(token, 1, "down", seq=200)
    for _ in range(6):
        await _http(basis, "/api/deck", token=token)
        await asyncio.sleep(0.4)
    check("solange die Seite fragt, bleibt die Taste gehalten", 1 in a._held_slots)
    await drueck(token, 1, "up", seq=201)
    netserver.WACHHUND_S = alt

    # Abschalten.
    LOG.clear()
    await drueck(token, 0, "down", seq=300)
    a.binding.network_enabled = False
    rt.netz.tasten.pruefen(rt.netz.sitzungen)
    await asyncio.sleep(0.2)
    check("Abschalten des Decks lässt los", 0 not in a._held_slots and _zaehle("up") == 1)
    check("und beendet die Sitzung", rt.netz.sitzungen.pruefe_token(token) is None)
    a.binding.network_enabled = True

    print("\n== Netz-Deck: Sperre gegen Raten ==")
    await _http(basis, "/api/login", {"deck": a.key, "password": "gast1234"})
    codes = []
    for runde in range(3):
        for pin in range(netauth.MAX_FEHLVERSUCHE):
            code, _ = await _http(basis, "/api/login", {"deck": b.key, "password": f"x{runde}{pin}"})
            codes.append(code)
        await _http(basis, "/api/login", {"deck": a.key, "password": "gast1234"})
    check("eine Anmeldung an einem anderen Deck hebt die Sperre nicht auf",
          codes.count(429) >= 2 * netauth.MAX_FEHLVERSUCHE, str(codes))
    code, _ = await _http(basis, "/api/login", {"deck": a.key, "password": "gast1234"})
    check("das andere Deck bleibt für dieselbe Adresse offen", code == 200, str(code))

    server.should_exit = True
    await asyncio.wait_for(aufgabe, timeout=5)

    sitzungen = netauth.Sitzungen()
    for i in range(netauth.MAX_FEHLVERSUCHE_DECK):
        sitzungen.melde_fehlversuch(f"10.0.{i}.1", "deck-x")
    check("viele Adressen zusammen sperren das Deck",
          sitzungen.gesperrt_bis("10.9.9.9", "deck-x") > 0)
    check("ein anderes Deck bleibt frei", sitzungen.gesperrt_bis("10.9.9.9", "deck-y") == 0)
    versuch = sitzungen.melde_fehlversuch("10.9.9.9", "deck-y")
    sitzungen.melde_erfolg("10.9.9.9", "deck-y", versuch)
    check("eine gelungene Anmeldung zählt nicht als Fehlversuch",
          not sitzungen._deck_fehlversuche.get("deck-y"))


async def reihenfolge_und_ketten() -> None:
    print("\n== Eingaben nacheinander ==")
    rt = _runtime()
    langsam = _registriere(rt, Recorder, "rec")
    langsam.langsam = 0.3
    deck = rt.create_virtual_deck("V", columns=3, rows=2)
    deck.current_page.keys[0] = Slot(plugin_id="rec", action_id="x")
    deck.current_page.keys[2] = Slot(plugin_id="rec", action_id="x")
    LOG.clear()

    def leser():
        deck.device.on_key(0, True)
        deck.device.on_key(0, False)
        deck.device.on_key(2, True)
    threading.Thread(target=leser).start()
    await asyncio.sleep(0.15)
    andere = [e for e in LOG if e[1] == 2]
    check("eine andere Taste wartet nicht auf die langsame",
          ("down-start", 2) in andere, str(LOG))
    await asyncio.sleep(0.6)
    reihe = [e[0] for e in LOG if e[1] == 0]
    check("das Loslassen wartet, bis das Drücken durch ist",
          reihe == ["down-start", "down-end", "up"], str(reihe))
    langsam.langsam = 0.0

    print("\n== Wiederholende Ketten ==")
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "multi_plugin_stab", BACKEND / "plugins" / "multi" / "plugin.py")
    modul = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modul)
    _registriere(rt, modul.MultiPlugin, "multi")

    def kette():
        return Slot(plugin_id="multi", action_id="multi", repeat=True,
                    steps=[Step(plugin_id="rec", action_id="x"), Step(kind="delay", delay_ms=50)])

    async def starte():
        await deck.handle_key(1, True)
        await deck.handle_key(1, False)
        await asyncio.sleep(0.2)
        return bool(deck._chains)

    deck.current_page.keys[1] = kette()
    check("die Kette läuft", await starte())
    # Dieselbe Belegung als neues, gleiches Objekt (die GUI schickt die
    # ganze Config zurück): Die Kette darf weiterlaufen.
    rt.apply_config(Config.model_validate(rt.config.model_dump(mode="json")), save=False)
    check("eine unveränderte Config hält die Kette nicht an", bool(deck._chains))
    deck.current_page.keys.pop(1)
    deck.drop_context(deck.current_page_id_value, "key", 1)
    await asyncio.sleep(0.05)
    vorher = _zaehle("down-start")
    await asyncio.sleep(0.4)
    check("Löschen der Taste beendet die Kette",
          not deck._chains and _zaehle("down-start") == vorher)

    deck.current_page.keys[1] = kette()
    await starte()
    deck.current_page.keys[1] = Slot(plugin_id="rec", action_id="x")
    deck.drop_context(deck.current_page_id_value, "key", 1)
    check("Ersetzen der Taste beendet die Kette", not deck._chains)

    deck.current_page.keys[1] = kette()
    await starte()
    zweites = rt.config.new_profile_for_deck("Zweit")
    check("vor dem Profilwechsel läuft sie", bool(deck._chains))
    deck.switch_profile(zweites.name)
    await asyncio.sleep(0.05)
    check("ein Profilwechsel beendet die Kette", not deck._chains)

    print("\n== Zurück auf ein gelöschtes Profil ==")
    erstes = deck._voriges_profil
    del rt.config.profiles[erstes]
    deck.apply_config()
    check("ein gelöschtes Profil ist kein Rückweg mehr", deck._voriges_profil == "")
    check("und zurück schaltet dann nicht", deck.switch_profile("") is False)
    check("das Deck bleibt auf einem vorhandenen Profil",
          deck.binding.profile_id in rt.config.profiles)
    deck._auto_grundprofil = "gibt-es-nicht"
    check("automatischer Rückweg ins Leere wird nicht genommen",
          deck.auto_profil(None) is False and deck.binding.profile_id in rt.config.profiles)

    for d in rt.decks.values():
        await d.stop()


class _Roh:
    def __init__(self, pfad, serial):
        self.pfad, self.serial = pfad, serial

    def id(self):
        return self.pfad


async def seriennummern() -> None:
    print("\n== Seriennummern ==")
    geoeffnet: list[str] = []

    class Fake(StreamDeckDevice):
        def __init__(self, roh):
            super().__init__()
            self.roh = roh
            self.deck = object()
            self.info = DeviceInfo(connected=True, deck_type="Stream Deck MK.2", serial=roh.serial,
                                   key_count=15, key_rows=3, key_columns=5, dial_count=0,
                                   touchscreen_size=(0, 0))

        def close(self):
            self.deck = None

        def set_brightness(self, p):
            pass

        def prepare_key_image(self, image):
            return None

    async def lauf(geraete, runden):
        geoeffnet.clear()
        rt = _runtime()
        alt = device_module.enumerate_decks
        device_module.enumerate_decks = lambda: list(geraete)

        def oeffne(roh):
            geoeffnet.append(roh.pfad)
            return Fake(roh)
        rt._open_device = oeffne
        try:
            for _ in range(runden):
                await rt._scan_devices()
        finally:
            device_module.enumerate_decks = alt
        return rt

    rt = await lauf([_Roh("/dev/hidraw1", "AL12"), _Roh("/dev/hidraw2", "AL12")], 4)
    check("ein Gerät mit schon verbundener Seriennummer wird nur einmal geöffnet",
          geoeffnet == ["/dev/hidraw1", "/dev/hidraw2"], str(geoeffnet))
    check("das erste behält seine Sitzung",
          rt.decks["AL12"].connected and rt._open_paths.get("AL12") == "/dev/hidraw1")
    check("und der Fehler steht einmal in der Liste",
          sum(1 for e in rt.errors if "AL12" in e.get("message", "")) == 1)
    for d in rt.decks.values():
        await d.stop()

    rt = await lauf([_Roh("/dev/hidraw1", "AL12"), _Roh("/dev/hidraw2", "")], 1)
    rt.apply_config(rt.config, save=False)
    await asyncio.sleep(0.05)
    await rt._scan_devices()
    sitzungen = list(rt.decks.values())
    check("ein Gerät ohne Seriennummer hat genau eine Sitzung",
          len(sitzungen) == len({id(d) for d in sitzungen}) and "" not in rt.decks,
          str(list(rt.decks)))
    check("und genau eine Bindung",
          sorted(rt.config.decks) == ["", "AL12"], str(list(rt.config.decks)))
    for d in rt.decks.values():
        await d.stop()


async def wiederherstellen() -> None:
    print("\n== Wiederherstellen und Netz-Sitzungen ==")
    rt = _runtime()
    syncs = []

    async def zaehle():
        syncs.append(1)
    rt.netz.sync = zaehle
    deck = rt.create_network_deck("Netz", columns=3, rows=2)
    rt.netz.set_password(deck.key, "altes-pw")
    alt = rt.config.model_copy(deep=True)
    rt.netz.set_password(deck.key, "neues-pw")
    token, _ = rt.netz.sitzungen.neues_token(deck.key)

    rt.apply_config(alt, save=False)
    await asyncio.sleep(0.01)
    check("ein Stand mit anderem Passwort trennt die Sitzungen",
          rt.netz.sitzungen.pruefe_token(token) is None)
    check("und gleicht den Netz-Server ab", len(syncs) == 1, str(len(syncs)))

    token, _ = rt.netz.sitzungen.neues_token(deck.key)
    gleich = rt.config.model_copy(deep=True)
    rt.apply_config(gleich, save=False)
    await asyncio.sleep(0.01)
    check("ein Stand mit demselben Passwort lässt sie bestehen",
          rt.netz.sitzungen.pruefe_token(token) is not None)

    aus = rt.config.model_copy(deep=True)
    aus.decks[deck.key].network_enabled = False
    rt.apply_config(aus, save=False)
    await asyncio.sleep(0.01)
    check("ein Stand mit abgeschaltetem Deck trennt ebenfalls",
          rt.netz.sitzungen.pruefe_token(token) is None)


async def config_und_port() -> None:
    print("\n== Config und Port ==")
    paths.ensure_dirs()
    with tempfile.TemporaryDirectory() as ordner:
        datei = Path(ordner) / "config.json"
        text = json.dumps({"profiles": {"p": {"id": "p", "name": "Lautstärke"}},
                           "active_profile_id": "p"}, ensure_ascii=False)
        datei.write_bytes(text.encode("latin-1"))
        check("peek_app fällt bei falscher Kodierung auf die Vorgaben zurück",
              ConfigStore(datei).peek_app().port == 8770)
        store = ConfigStore(datei)
        try:
            store.load()
            fehler = None
        except ConfigLoadError as exc:
            fehler = exc
        except Exception as exc:  # noqa: BLE001
            fehler = exc
        check("eine Config in falscher Kodierung wird gemeldet statt abzustürzen",
              isinstance(fehler, ConfigLoadError), repr(fehler)[:80])
        check("und als Kopie aufbewahrt", any(Path(ordner).glob("config.broken-*.json")))

    roh = Config().model_dump(mode="json")
    # Ein unmöglicher Port darf nicht die ganze Config verwerfen, sondern
    # fällt auf den Standard zurück. Der Rest der Datei bleibt.
    for feld, standard in (("port", 8770), ("network_port", 8771)):
        geladen = Config.model_validate({**roh, "app": {**roh["app"], feld: 70000}})
        wert = getattr(geladen.app, feld)
        check(f"{feld} außerhalb 0..65535 fällt auf {standard} zurück", wert == standard, str(wert))

    rt = _runtime()
    try:
        await rt.netz.start(70000)
        ok = True
    except Exception:  # noqa: BLE001
        ok = False
    check("ein ungültiger Port legt den Start nicht lahm", ok and not rt.netz.running)


def hartes_ende() -> None:
    print("\n== Beenden mit hängendem Hook ==")
    skript = textwrap.dedent(f"""
        import asyncio, sys, time
        from pathlib import Path
        sys.path.insert(0, {str(BACKEND)!r})
        from deckswitch import device as device_module
        device_module.enumerate_decks = lambda: []
        from deckswitch.config import Slot
        from deckswitch.plugins.base import ActionPlugin, Manifest
        from deckswitch.plugins.loader import LoadedPlugin
        from deckswitch.runtime import Runtime
        from deckswitch.__main__ import stoppe_runtime

        class Haengt(ActionPlugin):
            def on_key_down(self, action_id, settings, ctx):
                time.sleep(30)

        async def leer(*a, **k):
            return None

        async def lauf():
            rt = Runtime(None)
            rt._loop = asyncio.get_running_loop()
            rt.bus.bind_loop(rt._loop)
            rt.config.ensure_decks()
            rt._sync_decks()
            rt.shortcuts.stop = leer
            rt.smartprofile.stop = leer
            rt.overlay.shutdown = leer
            rt.media.close = leer
            rt.audio.stop_watcher = lambda: None
            rt.sound.close = lambda: None
            rt.input.close = lambda: None
            m = Manifest(id="h", name="h", type="action")
            rt.registry.plugins["h"] = LoadedPlugin(
                manifest=m, directory=Path(), instance=Haengt(m, rt._services_for(Path())))
            rt.primary.current_page.keys[0] = Slot(plugin_id="h", action_id="x")
            asyncio.get_running_loop().create_task(rt.primary.handle_key(0, True))
            await asyncio.sleep(0.2)
            await stoppe_runtime(rt, timeout=1)

        asyncio.run(lauf())
    """)
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as datei:
        datei.write(skript)
    beginn = time.monotonic()
    try:
        ergebnis = subprocess.run([sys.executable, datei.name], capture_output=True,
                                  timeout=25, env=os.environ.copy())
        dauer = time.monotonic() - beginn
        check("der Prozess endet kurz nach dem Zeitlimit",
              dauer < 10 and ergebnis.returncode == 0,
              f"{dauer:.1f} s, Code {ergebnis.returncode}")
    except subprocess.TimeoutExpired:
        check("der Prozess endet kurz nach dem Zeitlimit", False, "hängt")
    finally:
        os.unlink(datei.name)


async def main() -> None:
    await netz_deck()
    await reihenfolge_und_ketten()
    await seriennummern()
    await wiederherstellen()
    await config_und_port()
    hartes_ende()

    print()
    if FAILS:
        print(f"FEHLGESCHLAGEN ({len(FAILS)}): " + ", ".join(FAILS))
        sys.exit(1)
    print("Alle Prüfungen bestanden.")


asyncio.run(main())
