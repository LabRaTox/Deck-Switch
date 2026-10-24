"""Prüft den Kern der Runtime auf Fehler, die schon einmal aufgetreten sind.

Jeder Abschnitt stellt einen Fall nach, der früher das Backend beendet,
Daten verloren oder ein Deck stillgelegt hat:

* ein belegter Port für Netz-Decks,
* die Signal-Handler, nachdem der Netz-Server wieder aus ist,
* der Umzug aus den alten Ordnern und die Meldung einer kaputten Config,
* gleichzeitiges Speichern und Aufrufe aus Arbeitsthreads,
* ein Plugin-Update mit Hilfsmodulen und Sprachdateien,
* Restore einer Config bei virtuellen Decks und beim Platzhalter,
* ein vergessenes Deck,
* ein Bildschirmschoner, der unterwegs scheitert,
* fremde Namen im ``Host``.

Es wird kein echtes Gerät geöffnet: Die Runtime startet hier nie ihre
Gerätesuche.

Aufruf:

    cd backend
    d=$(mktemp -d); env XDG_CONFIG_HOME=$d XDG_DATA_HOME=$d \\
        ../.venv/bin/python tests/kern_test.py
"""
import _wache  # bricht ab, statt in die echte Config zu schreiben
_wache.sichere_umgebung()

import asyncio
import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
from pathlib import Path

import uvicorn
from fastapi import FastAPI

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from deckswitch import events as ev  # noqa: E402
from deckswitch import paths, texte  # noqa: E402
from deckswitch.config import Config, ConfigStore  # noqa: E402
from deckswitch.netserver import NetzService, StillerServer  # noqa: E402
from deckswitch.plugins.base import CanvasPlugin, Manifest  # noqa: E402
from deckswitch.plugins.loader import LoadedPlugin, PluginRegistry  # noqa: E402
from deckswitch.runtime import Runtime  # noqa: E402
from deckswitch.server import create_app  # noqa: E402

FAILS: list[str] = []


def check(name, condition, detail=""):
    print(("  ✔ " if condition else "  ✘ ") + name + (f"  ({detail})" if detail else ""))
    if not condition:
        FAILS.append(name)


class _LeereRuntime:
    decks: dict = {}


def _freier_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _laufende_runtime() -> Runtime:
    """Eine Runtime im laufenden Loop, ohne Gerätesuche und Dienste."""
    runtime = Runtime(None)
    runtime._loop = asyncio.get_running_loop()
    runtime.bus.bind_loop(runtime._loop)
    runtime.config.ensure_decks()
    runtime._sync_decks()
    return runtime


async def _aufraeumen():
    for task in asyncio.all_tasks():
        if task is not asyncio.current_task():
            task.cancel()
    await asyncio.sleep(0)


# ---------------------------------------------------------------------------


async def netz_port_belegt():
    print("\n== Netz-Server auf belegtem Port ==")
    blocker = socket.socket()
    blocker.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    blocker.bind(("0.0.0.0", 0))
    blocker.listen()
    port = blocker.getsockname()[1]
    try:
        dienst = NetzService(_LeereRuntime())
        await dienst.start(port)
        check("start() kehrt zurück", True)
        check("der Server gilt als nicht gestartet", not dienst.running)
        await asyncio.sleep(0.2)
        check("der Loop läuft weiter", True)
    finally:
        blocker.close()


async def signale_nach_netz_stopp():
    print("\n== Signal-Handler nach dem Abschalten des Netz-Servers ==")
    loop = asyncio.get_running_loop()
    stopping = asyncio.Event()
    vorher = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM)}

    dienst = NetzService(_LeereRuntime())
    await dienst.start(0)
    check("Netz-Server läuft", dienst.running)
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stopping.set)
    haupt = StillerServer(uvicorn.Config(FastAPI(), host="127.0.0.1", port=0, log_level="error"))
    aufgabe = asyncio.create_task(haupt.serve())
    await asyncio.sleep(0.3)

    await dienst.stop()
    check("SIGTERM steht nicht auf dem Standard", signal.getsignal(signal.SIGTERM) != signal.SIG_DFL,
          str(signal.getsignal(signal.SIGTERM)))
    os.kill(os.getpid(), signal.SIGTERM)
    try:
        await asyncio.wait_for(stopping.wait(), timeout=2)
        angekommen = True
    except TimeoutError:
        angekommen = False
    check("SIGTERM landet beim Loop und beendet nicht den Prozess", angekommen)

    haupt.should_exit = True
    await aufgabe
    for sig, handler in vorher.items():
        loop.remove_signal_handler(sig)
        signal.signal(sig, handler)


_START_SKRIPT = textwrap.dedent(
    """
    import asyncio, json, os, signal, sys
    sys.path.insert(0, {backend!r})
    from deckswitch import __main__ as einstieg, paths
    from deckswitch.config import ConfigLoadError
    from deckswitch.runtime import Runtime

    bericht = {{}}

    async def start(self):
        # Statt Gerätesuche nur das, was hier zählt: laden wie die Runtime.
        try:
            self.store.load()
            bericht["fehler_gemeldet"] = False
        except ConfigLoadError:
            bericht["fehler_gemeldet"] = True
        bericht["config_port"] = json.loads(paths.CONFIG_FILE.read_text())["app"]["port"]
        bericht["upload_da"] = (paths.UPLOADS_DIR / "bild.png").is_file()
        asyncio.get_running_loop().call_later(0.5, os.kill, os.getpid(), signal.SIGTERM)

    async def stop(self):
        bericht["sauber_beendet"] = True

    Runtime.start = start
    Runtime.stop = stop
    sys.argv = ["deckswitch", "--no-tray", "--port", "{port}"]
    bericht["exit"] = einstieg.main()
    print("BERICHT " + json.dumps(bericht))
    """
)


def _starte(cfg: Path, daten: Path) -> dict:
    """Startet den echten Einstiegspunkt mit Attrappen für Start und Stopp."""
    skript = _START_SKRIPT.format(backend=str(BACKEND), port=_freier_port())
    umgebung = {**os.environ, "XDG_CONFIG_HOME": str(cfg), "XDG_DATA_HOME": str(daten)}
    umgebung.pop("DBUS_SESSION_BUS_ADDRESS", None)
    ergebnis = subprocess.run(
        [sys.executable, "-c", skript], env=umgebung, capture_output=True, text=True, timeout=60
    )
    zeile = next((z for z in ergebnis.stdout.splitlines() if z.startswith("BERICHT ")), "")
    bericht = json.loads(zeile[8:]) if zeile else {}
    bericht["rc"] = ergebnis.returncode
    if not zeile:
        print(ergebnis.stdout[-2000:], ergebnis.stderr[-2000:])
    return bericht


def start_reihenfolge():
    print("\n== Start: Umzug, kaputte Config, SIGTERM ==")
    wurzel = Path(tempfile.mkdtemp())
    cfg, daten = wurzel / "cfg", wurzel / "data"
    (cfg / "streamdeck-app").mkdir(parents=True)
    (cfg / "streamdeck-app" / "config.json").write_text(json.dumps({"app": {"port": 9123}}))
    (daten / "streamdeck-app" / "uploads").mkdir(parents=True)
    (daten / "streamdeck-app" / "uploads" / "bild.png").write_bytes(b"x")

    bericht = _starte(cfg, daten)
    check("alte Config ist umgezogen", bericht.get("config_port") == 9123, str(bericht.get("config_port")))
    check("alte Uploads sind umgezogen", bericht.get("upload_da") is True)
    check("alter Ordner liegt als -alt daneben", (cfg / "streamdeck-app-alt").is_dir())
    check("SIGTERM fährt geordnet herunter",
          bericht.get("sauber_beendet") is True and bericht.get("exit") == 0, str(bericht))

    # Zweiter Start, diesmal mit kaputter Config und ohne alte Ordner.
    wurzel = Path(tempfile.mkdtemp())
    (wurzel / "cfg" / "deckswitch").mkdir(parents=True)
    (wurzel / "cfg" / "deckswitch" / "config.json").write_text("{kaputt")
    bericht = _starte(wurzel / "cfg", wurzel / "data")
    check("kaputte Config erreicht die Runtime als Fehler", bericht.get("fehler_gemeldet") is True,
          str(bericht))
    check("eine Kopie der kaputten Datei liegt daneben",
          any(p.name.startswith("config.broken-") for p in (wurzel / "cfg" / "deckswitch").iterdir()))


def gleichzeitiges_speichern():
    print("\n== Gleichzeitiges Speichern ==")
    store = ConfigStore(Path(tempfile.mkdtemp()) / "config.json")
    store.load()
    for i in range(200):
        store.config.plugin_settings[f"p{i}"] = {"x": "y" * 200}
    fehler: list[str] = []

    def arbeit():
        for _ in range(40):
            try:
                store.save()
            except Exception as exc:  # noqa: BLE001
                fehler.append(type(exc).__name__)

    threads = [threading.Thread(target=arbeit) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    check("kein Fehler bei vier Threads", not fehler, str(set(fehler)))
    check("Datei bleibt gültig", isinstance(json.loads(store.path.read_text()), dict))
    check("keine Zwischendateien bleiben liegen",
          not [p for p in store.path.parent.iterdir() if p.suffix == ".tmp"])


async def aufrufe_aus_threads():
    print("\n== Aufrufe aus Arbeitsthreads ==")
    runtime = _laufende_runtime()
    deck = runtime.create_virtual_deck("Thread")
    profil = deck.profile
    from deckswitch.config import Page
    ziel = Page(name="Ziel", parent_id=profil.root_page().id)
    profil.pages[ziel.id] = ziel
    loop = asyncio.get_running_loop()

    # Blättern aus einem Arbeitsthread, wie es ein synchroner Hook tut. Alles,
    # was dabei am Zustand des Loops dreht, muss im Loop-Thread geschehen.
    threads: list[int] = []
    original_dirty = deck._mark_all_dirty

    def dirty_merken():
        threads.append(threading.get_ident())
        original_dirty()

    deck._mark_all_dirty = dirty_merken
    async with runtime.bus.subscribe() as queue:
        await loop.run_in_executor(None, deck.view.navigate, ziel.id)
        typen = []
        while not queue.empty():
            typen.append(queue.get_nowait().type)
    deck._mark_all_dirty = original_dirty
    check("Blättern aus einem Thread läuft im Loop", bool(threads) and set(threads) == {threading.get_ident()}, str(threads))
    check("und meldet den Seitenwechsel", ev.EVT_PAGE_CHANGED in typen, str(typen))
    check("die Seite ist gewechselt", deck.current_page_id() == ziel.id)

    thread_ids: list[int] = []
    original = runtime.store.save

    def merken(*a, **k):
        thread_ids.append(threading.get_ident())
        return original(*a, **k)

    runtime.store.save = merken
    await loop.run_in_executor(None, runtime.save_config)
    check("Speichern aus einem Thread läuft im Loop", thread_ids == [threading.get_ident()])
    runtime.store.save = original

    await loop.run_in_executor(None, runtime.notify, "error", "aus dem Thread")
    check("Fehler aus einem Thread landen in der Liste",
          any(e["message"] == "aus dem Thread" for e in runtime.errors))
    check("Plugins können über ihr Deck das Profil wechseln", hasattr(deck.view, "switch_profile"))
    await _aufraeumen()


def plugin_update():
    print("\n== Plugin-Update mit Hilfsmodul und Sprachdatei ==")
    wurzel = Path(tempfile.mkdtemp())
    ordner = wurzel / "0001"
    (ordner / "locales").mkdir(parents=True)

    def schreiben(fassung: str, wert: str):
        (ordner / "manifest.json").write_text(json.dumps(
            {"id": "kern-demo", "name": "Demo", "entry": "plugin.py", "class": "P", "version": fassung}
        ))
        (ordner / "plugin.py").write_text(
            "from deckswitch.plugins.base import ActionPlugin\n"
            "from .helper import WERT\n"
            "class P(ActionPlugin):\n    wert = WERT\n"
        )
        helper = ordner / "helper.py"
        helper.write_text(f"WERT = {wert!r}\n")
        # Eine echte neue Fassung hat eine andere Änderungszeit. Ohne das
        # hielte Python die zwischengespeicherte .pyc derselben Sekunde für
        # aktuell, und der Test prüfte den Bytecode-Cache statt des Laders.
        zeit = time.time() + (10 if fassung != "1.0" else 0)
        os.utime(helper, (zeit, zeit))
        (ordner / "locales" / "de.json").write_text(json.dumps({"gruss": wert}))

    registry = PluginRegistry()
    suchpfad = [(wurzel, False)]

    class _Dienste:
        plugin_dir = ordner

    schreiben("1.0", "alt")
    registry.discover(lambda _p: _Dienste(), search_paths=suchpfad)
    erste = registry.instance("kern-demo")
    check("erste Fassung geladen", erste is not None and erste.wert == "alt")
    check("Text der ersten Fassung", erste is not None and erste.t("gruss") == "alt")

    schreiben("2.0", "neu")
    registry.discover(lambda _p: _Dienste(), search_paths=suchpfad)
    zweite = registry.instance("kern-demo")
    check("Hilfsmodul der neuen Fassung", zweite is not None and zweite.wert == "neu",
          getattr(zweite, "wert", None))
    check("Text der neuen Fassung", zweite is not None and zweite.t("gruss") == "neu")


async def restore_und_bindungen():
    print("\n== Config ersetzen: virtuelle Decks und Platzhalter ==")
    runtime = _laufende_runtime()
    platzhalter = runtime.decks["erstes-deck"]
    neu = Config.model_validate(runtime.config.model_dump(mode="json"))
    neu.decks[""].device.brightness = 33
    runtime.apply_config(neu, save=False)
    check("Platzhalter übernimmt die neue Bindung", platzhalter.binding is runtime.config.decks[""])
    check("und deren Helligkeit", platzhalter.settings.brightness == 33)

    virtuell = runtime.create_virtual_deck("V", columns=4, rows=2)
    runtime.apply_config(Config.model_validate(runtime.config.model_dump(mode="json")), save=False)
    virtuell.binding.columns = 8
    runtime.update_virtual_geometry(virtuell)
    check("Raster wirkt nach dem Ersetzen", virtuell.device.info.key_count == 16,
          str(virtuell.device.info.key_count))
    await _aufraeumen()


async def deck_vergessen():
    print("\n== Deck vergessen ==")
    runtime = _laufende_runtime()
    weg = runtime.create_virtual_deck("Weg")
    bleibt = runtime.create_virtual_deck("Bleibt")
    aufgaben = list(weg._tasks)
    check("Schleifen laufen vorher", aufgaben and not any(t.done() for t in aufgaben))
    runtime.forget_deck(weg.key)
    await asyncio.sleep(0.2)
    check("Schleifen des vergessenen Decks sind beendet", all(t.done() for t in aufgaben))
    check("anderes Deck läuft weiter", bleibt._tasks and not any(t.done() for t in bleibt._tasks))

    runtime.forget_deck("erstes-deck")
    gespeichert = json.loads(paths.CONFIG_FILE.read_text())["decks"]
    check("Platzhalter verschwindet aus der Config", "" not in gespeichert, str(list(gespeichert)))
    await _aufraeumen()


async def schoner_scheitert():
    print("\n== Bildschirmschoner scheitert unterwegs ==")
    runtime = _laufende_runtime()
    deck = runtime.create_virtual_deck("Schoner")

    class Kaputt(CanvasPlugin):
        interval_s = 0.05

        def render(self, size, elapsed_s):
            raise RuntimeError("kaputt")

    manifest = Manifest(id="kern-schoner", name="K", type="screensaver")
    runtime.registry.plugins[manifest.id] = LoadedPlugin(
        manifest=manifest, directory=Path(), instance=Kaputt(manifest, None)
    )
    deck.settings.screensaver.source = "plugin:kern-schoner"
    deck.start_screensaver_now()
    await asyncio.sleep(0.5)
    check("der Schoner gibt das Deck wieder frei", deck._screensaver_task is None)
    check("der Fehler steht in der Liste", any(e["plugin_id"] == "kern-schoner" for e in runtime.errors))
    deck.device.close()  # Bilder weg, damit Neuzeichnen sichtbar wird
    vorher = deck.device.revision
    deck._mark_all_dirty()
    await asyncio.sleep(0.3)
    check("das Deck zeichnet wieder", deck.device.revision > vorher)
    await _aufraeumen()


def fremder_host():
    print("\n== Host-Prüfung ==")
    runtime = Runtime(None)
    app = create_app(runtime, host="127.0.0.1", port=8770)

    def status(host: bytes, pfad="/api/errors") -> int:
        empfangen = {"status": 0}

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(nachricht):
            if nachricht["type"] == "http.response.start":
                empfangen["status"] = nachricht["status"]

        scope = {
            "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
            "method": "GET", "scheme": "http", "path": pfad, "raw_path": pfad.encode(),
            "query_string": b"", "root_path": "", "headers": [(b"host", host)],
            "client": ("127.0.0.1", 1), "server": ("127.0.0.1", 8770),
        }
        asyncio.run(app(scope, receive, send))
        return empfangen["status"]

    for host in (b"127.0.0.1:8770", b"127.0.0.1", b"localhost:8770", b"[::1]:8770", b"::1"):
        check(f"{host.decode()} ist erlaubt", status(host) == 200)
    for host in (b"evil.example:8770", b"evil.example", b"127.0.0.1.evil.example"):
        check(f"{host.decode()} wird abgewiesen", status(host) == 400)
    check("die Meldung ist übersetzt", texte.t("server.unbekannter_host") != "server.unbekannter_host")


def main():
    asyncio.run(netz_port_belegt())
    asyncio.run(signale_nach_netz_stopp())
    start_reihenfolge()
    gleichzeitiges_speichern()
    asyncio.run(aufrufe_aus_threads())
    plugin_update()
    asyncio.run(restore_und_bindungen())
    asyncio.run(deck_vergessen())
    asyncio.run(schoner_scheitert())
    fremder_host()

    print()
    if FAILS:
        print(f"FEHLGESCHLAGEN ({len(FAILS)}): " + ", ".join(FAILS))
        sys.exit(1)
    print("ALLES GRÜN")


if __name__ == "__main__":
    main()
