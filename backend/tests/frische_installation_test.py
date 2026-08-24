"""Was ein neuer Benutzer als Erstes tut — ohne angestecktes Gerät.

Diese Suite gibt es wegen eines Fehlers, der genau hier saß: Die Bindung für
„das erste Gerät" hatte keine Seriennummer und damit keinen Schlüssel. Über
``/api/decks//…`` war sie nicht erreichbar, die Adresse fiel auf die Liste
zurück, und die antwortet auf PATCH mit 405. Auf einer frischen Installation
ließ sich damit **keine** Deck-Einstellung ändern — Name, Helligkeit, Zeiten,
Bildschirmschoner, Profil. Wer ein Deck angesteckt hatte, merkte nichts
davon, weil dessen Bindung eine Seriennummer trägt.

Geprüft wird deshalb die Regel, die das verhindert: **Jedes Deck muss über
seinen Schlüssel ansprechbar sein.** Dazu die Wege, die ein neuer Benutzer in
den ersten Minuten geht.

Aufruf:

    cd backend
    d=$(mktemp -d); env XDG_CONFIG_HOME=$d XDG_DATA_HOME=$d \\
        ../.venv/bin/python tests/frische_installation_test.py
"""
import _wache  # bricht ab, statt in die echte Config zu schreiben
_wache.sichere_umgebung()

import json
import pathlib
import socket
import sys
import threading
import time
import urllib.error
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import uvicorn  # noqa: E402

from deckswitch.runtime import Runtime  # noqa: E402
from deckswitch.server import create_app  # noqa: E402

FAILS = []


def check(name, bedingung, detail=""):
    print(("  ✔ " if bedingung else "  ✘ ") + name + (f"  ({detail})" if detail else ""))
    if not bedingung:
        FAILS.append(name)


class Client:
    def __init__(self, basis: str) -> None:
        self.basis = basis

    def ruf(self, pfad, *, daten=None, methode=None):
        anfrage = urllib.request.Request(
            self.basis + pfad, method=methode or ("POST" if daten is not None else "GET")
        )
        koerper = None
        if daten is not None:
            koerper = json.dumps(daten).encode()
            anfrage.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(anfrage, koerper, timeout=10) as antwort:
                return antwort.status, antwort.read()
        except urllib.error.HTTPError as fehler:
            return fehler.code, fehler.read()


def freier_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


#: Vollständige Geräteeinstellungen — der Endpunkt nimmt nur ganze.
GERAET = {
    "brightness": 55, "idle_dim_after_s": 300, "idle_brightness": 15,
    "long_press_ms": 500, "double_press_ms": 280, "animations": True,
    "animation_fps": 10, "tick_interval_s": 1.0, "swipe_switches_page": True,
    "swipe_min_distance": 50, "swipe_wraps": True,
    "screensaver": {"enabled": False, "source": "", "after_s": 600,
                    "brightness": 40, "fit": "cover"},
}


def main() -> int:
    runtime = Runtime()
    # Dieselben zwei Schritte wie beim echten Start, nur ohne Gerätesuche:
    # Erst entsteht die Bindung für „das erste Deck", dann die Sitzung dazu.
    runtime.config.ensure_decks()
    runtime._sync_decks()
    runtime.load_plugins()
    app = create_app(runtime)

    port = freier_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port,
                                           log_level="error", access_log=False))
    faden = threading.Thread(target=server.run, daemon=True)
    faden.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.1)
    client = Client(f"http://127.0.0.1:{port}")

    try:
        print("== Die Regel ==")
        code, roh = client.ruf("/api/decks")
        decks = json.loads(roh)
        check("es gibt genau ein Deck", code == 200 and len(decks) == 1,
              f"{code}, {len(decks)}")
        check("es ist nicht verbunden", not decks[0]["connected"])
        check("seine Seriennummer ist leer", decks[0]["serial"] == "",
              repr(decks[0]["serial"]))
        check("sein Schlüssel ist es NICHT", bool(decks[0]["id"]), repr(decks[0]["id"]))
        for deck in decks:
            check(f"'{deck['name']}' ist ansprechbar",
                  client.ruf(f"/api/decks/{deck['id']}", daten={}, methode="PATCH")[0] == 200,
                  deck["id"])

        schluessel = decks[0]["id"]
        config = json.loads(client.ruf("/api/config")[1])
        profil = next(iter(config["profiles"].values()))
        seite = profil["root_page_id"]

        print("\n== Die ersten Handgriffe ==")
        wege = [
            ("das Deck umbenennen", "PATCH", f"/api/decks/{schluessel}", {"name": "Mein Deck"}),
            ("die Helligkeit stellen", "PATCH", f"/api/decks/{schluessel}",
             {"device": GERAET}),
            ("eine Seite anlegen", "POST", "/api/pages", {"name": "Zweite", "parent_id": None}),
            ("eine Taste belegen", "PUT", f"/api/pages/{seite}/slots/key/0",
             {"slot": {"plugin_id": "streamdeck", "action_id": "home",
                       "settings": {}, "appearance": {}}}),
            ("die Sprache umstellen", "PATCH", "/api/config/app", {"language": "de"}),
            ("ein Profil anlegen", "POST", "/api/profiles", {"name": "Zweites"}),
            ("ein virtuelles Deck anlegen", "POST", "/api/decks/virtual",
             {"name": "Overlay", "columns": 4, "rows": 2, "dials": 4}),
        ]
        for name, methode, pfad, daten in wege:
            code, roh = client.ruf(pfad, daten=daten, methode=methode)
            check(name, code == 200, f"{code} {roh[:90].decode(errors='replace')}")

        print("\n== Und was dabei herauskommt ==")
        code, bild = client.ruf(f"/api/preview/{seite}/key/0.png")
        check("die Vorschau zeigt die belegte Taste",
              code == 200 and bild[:8] == b"\x89PNG\r\n\x1a\n", str(code))
        check("der Export läuft", client.ruf("/api/export")[0] == 200)

        # Nach dem virtuellen Deck: Die Regel gilt weiter, für jedes Deck.
        decks = json.loads(client.ruf("/api/decks")[1])
        check("jetzt sind es zwei Decks", len(decks) == 2, str(len(decks)))
        for deck in decks:
            check(f"'{deck['name']}' ist ansprechbar",
                  client.ruf(f"/api/decks/{deck['id']}", daten={}, methode="PATCH")[0] == 200,
                  deck["id"])
        check("und keines hat einen leeren Schlüssel",
              all(deck["id"] for deck in decks), json.dumps([d["id"] for d in decks]))
    finally:
        server.should_exit = True
        faden.join(timeout=10)

    print()
    if FAILS:
        print(f"FEHLGESCHLAGEN: {len(FAILS)} — {', '.join(FAILS)}")
        return 1
    print("Alle Prüfungen bestanden.")
    return 0


sys.exit(main())
