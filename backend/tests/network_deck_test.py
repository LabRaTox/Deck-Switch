"""Netz-Decks: Zugang, Absicherung und der Weg vom Browser bis zur Aktion.

Der Zweck eines Netz-Decks ist, dass jemand anderes den eigenen Rechner
steuert. Damit ist jede dieser Prüfungen eine Prüfung an einer offenen Tür:

* Ohne Passwort wird gar nichts angeboten.
* Ohne gültiges Token gibt es weder Bilder noch Eingaben.
* Die Anwendung im Netz kennt keinen Endpunkt, der etwas ändern könnte.
* Ein Passwortwechsel trennt die, die schon drin sind.
* Raten wird nach wenigen Fehlversuchen gesperrt.

Aufruf (mit eigener Config, damit die echte unangetastet bleibt):

    cd backend
    d=$(mktemp -d)
    env XDG_CONFIG_HOME=$d XDG_DATA_HOME=$d ../.venv/bin/python tests/network_deck_test.py
"""
import _wache  # bricht ab, statt in die echte Config zu schreiben

_wache.sichere_umgebung()

import asyncio
import json as jsonlib
import socket
import sys
import urllib.error
import urllib.request

import uvicorn

from deckswitch import netauth
from deckswitch.config import Appearance, Page, Slot
from deckswitch.netserver import create_net_app
from deckswitch.runtime import Runtime

FAILS = []


class Netz:
    """Winziger Client gegen einen echt laufenden Server.

    Kein ``TestClient``: Der bräuchte ein zusätzliches Paket. Und ein echter
    Server prüft ohnehin mehr — er geht durch dieselbe Schicht wie später
    der Browser des Gastes.
    """

    def __init__(self, basis: str) -> None:
        self.basis = basis

    async def _ruf(self, pfad, *, daten=None, token=None, methode=None):
        def arbeite():
            anfrage = urllib.request.Request(self.basis + pfad, method=methode or ("POST" if daten is not None else "GET"))
            if token:
                anfrage.add_header("Authorization", f"Bearer {token}")
            koerper = None
            if daten is not None:
                koerper = jsonlib.dumps(daten).encode()
                anfrage.add_header("Content-Type", "application/json")
            try:
                with urllib.request.urlopen(anfrage, koerper, timeout=10) as antwort:
                    return antwort.status, antwort.read()
            except urllib.error.HTTPError as fehler:
                return fehler.code, fehler.read()
            except urllib.error.URLError as fehler:
                return 0, str(fehler).encode()

        return await asyncio.to_thread(arbeite)

    async def get(self, pfad, token=None):
        return await self._ruf(pfad, token=token)

    async def post(self, pfad, daten=None, token=None):
        return await self._ruf(pfad, daten=daten if daten is not None else {}, token=token)


def freier_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def check(name, condition, detail=""):
    mark = "✔" if condition else "✘"
    print(f"  {mark} {name}" + (f"  ({detail})" if detail else ""))
    if not condition:
        FAILS.append(name)


async def main():
    # ==================================================================
    print("\n== Passwörter ==")
    # ==================================================================
    gespeichert = netauth.hash_passwort("streamteam")
    check("das Passwort steht nicht im Klartext darin",
          "streamteam" not in gespeichert, gespeichert[:24] + "…")
    check("das richtige Passwort passt", netauth.pruefe_passwort("streamteam", gespeichert))
    check("ein falsches nicht", not netauth.pruefe_passwort("Streamteam", gespeichert))
    check("und ein leeres erst recht nicht",
          not netauth.pruefe_passwort("", gespeichert)
          and not netauth.pruefe_passwort("x", ""))
    check("zweimal dasselbe Passwort ergibt verschiedene Werte",
          netauth.hash_passwort("gleich") != netauth.hash_passwort("gleich"))
    check("ein beschädigter Eintrag sperrt, statt zu öffnen",
          not netauth.pruefe_passwort("egal", "kaputt$$$"))

    # ==================================================================
    print("\n== Sitzungen ==")
    # ==================================================================
    sitzungen = netauth.Sitzungen()
    token, gueltig = sitzungen.neues_token("deck-a")
    check("ein Token zeigt auf sein Deck", sitzungen.pruefe_token(token) == "deck-a")
    check("und gilt befristet", gueltig > 0, f"{gueltig}s")
    check("ein erfundenes Token gilt nicht", sitzungen.pruefe_token("ausgedacht") is None)
    check("ein leeres auch nicht", sitzungen.pruefe_token("") is None)

    zweites, _ = sitzungen.neues_token("deck-a")
    check("zwei Anmeldungen ergeben verschiedene Token", token != zweites)
    sitzungen.alle_verwerfen("deck-a")
    check("ein Passwortwechsel wirft beide raus",
          sitzungen.pruefe_token(token) is None and sitzungen.pruefe_token(zweites) is None)

    for _ in range(netauth.MAX_FEHLVERSUCHE):
        sitzungen.melde_fehlversuch("10.0.0.5")
    check("nach genug Fehlversuchen ist die Adresse gesperrt",
          sitzungen.gesperrt_bis("10.0.0.5") > 0)
    check("eine andere Adresse bleibt frei", sitzungen.gesperrt_bis("10.0.0.6") == 0)
    sitzungen.melde_erfolg("10.0.0.5")
    check("eine gelungene Anmeldung räumt die Sperre weg",
          sitzungen.gesperrt_bis("10.0.0.5") == 0)

    # ==================================================================
    print("\n== Deck im Netz ==")
    # ==================================================================
    rt = Runtime()
    await rt.start()
    await asyncio.sleep(0.3)

    deck = rt.create_network_deck("Mod-Deck", columns=3, rows=2, dials=1)
    check("es ist angelegt und gilt als verbunden", deck.connected)
    check("mit eigenem Profil", deck.profile.id != rt.primary.profile.id)
    check("und eigener Bauart", deck.binding.is_network and deck.binding.is_virtual)
    check("ein Netz-Deck ist kein Overlay", not deck.binding.is_overlay)

    app = create_net_app(rt, rt.netz.sitzungen)
    port = freier_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port,
                                           log_level="error", access_log=False))
    aufgabe = asyncio.create_task(server.serve())
    await asyncio.sleep(0.6)
    client = Netz(f"http://127.0.0.1:{port}")

    # -- Ohne Passwort ist zu -------------------------------------------
    code, _ = await client.post("/api/login", {"deck": deck.key, "password": ""})
    check("ohne gesetztes Passwort kommt niemand herein", code == 401, str(code))
    _, start = await client.get("/")
    check("und das Deck taucht nirgends auf", deck.label.encode() not in start)
    code, _ = await client.get(f"/deck/{deck.key}")
    check("auch seine Seite gibt es nicht", code == 404, str(code))

    # -- Mit Passwort ----------------------------------------------------
    rt.netz.set_password(deck.key, "streamteam2026")
    _, start = await client.get("/")
    check("jetzt wird es angeboten", deck.label.encode() in start)
    code, _ = await client.get(f"/deck/{deck.key}")
    check("und die Seite steht bereit", code == 200, str(code))

    code, _ = await client.post("/api/login", {"deck": deck.key, "password": "falsch"})
    check("ein falsches Passwort reicht nicht", code == 401, str(code))

    code, koerper = await client.post("/api/login",
                                      {"deck": deck.key, "password": "streamteam2026"})
    check("mit dem richtigen schon", code == 200, str(code))
    token = jsonlib.loads(koerper).get("token", "") if code == 200 else ""
    check("und es gibt ein Token", len(token) > 20)

    # -- Nichts ohne Token ------------------------------------------------
    ohne = {}
    for pfad in ("/api/deck", "/api/tile/key/0.png"):
        ohne[pfad], _ = await client.get(pfad)
    ohne["/api/input"], _ = await client.post("/api/input", {"input_type": "key", "index": 0})
    check("ohne Token gibt es nichts", all(c == 401 for c in ohne.values()), str(ohne))
    code, _ = await client.get("/api/deck", token="ausgedacht")
    check("ein erfundenes Token hilft auch nicht", code == 401, str(code))

    # -- Die Netz-Anwendung kann nichts ändern ----------------------------
    verboten = ["/api/state", "/api/config", "/api/export", "/api/pages",
                "/api/plugins", "/api/decks"]
    codes = {}
    for pfad in verboten:
        codes[pfad], _ = await client.get(pfad, token=token)
    check("die volle API gibt es hier nicht",
          all(c == 404 for c in codes.values()), str(codes))

    # -- Anzeigen und drücken ---------------------------------------------
    _, koerper = await client.get("/api/deck", token=token)
    layout = jsonlib.loads(koerper)
    check("das Layout kommt an",
          layout["columns"] == 3 and layout["rows"] == 2 and layout["dials"] == 1,
          f"{layout['columns']}x{layout['rows']}, {layout['dials']} Dial")

    seite = deck.profile.root_page()
    ziel = Page(name="Szene 2", parent_id=None, order=1)
    deck.profile.pages[ziel.id] = ziel
    seite.keys[0] = Slot(
        plugin_id="streamdeck",
        action_id="folder",
        settings={"page_id": ziel.id},
        appearance=Appearance(),
    )
    deck._mark_all_dirty()
    await asyncio.sleep(0.5)

    code, bild = await client.get("/api/tile/key/0.png", token=token)
    check("die Kachel kommt als PNG",
          code == 200 and bild[:4] == b"\x89PNG", f"{code}, {len(bild)} Bytes")

    vorher = deck.current_page_id()
    await client.post("/api/input",
                      {"input_type": "key", "index": 0, "action": "click"}, token=token)
    await asyncio.sleep(0.4)
    check("ein Druck aus dem Netz steuert das Deck",
          deck.current_page_id() == ziel.id and vorher != ziel.id,
          f"{vorher} → {deck.current_page_id()}")

    # -- Passwortwechsel trennt -------------------------------------------
    rt.netz.set_password(deck.key, "anderes")
    code, _ = await client.get("/api/deck", token=token)
    check("nach dem Wechsel gilt das alte Token nicht mehr", code == 401, str(code))

    # -- Abgeschaltet ist abgeschaltet ------------------------------------
    _, koerper = await client.post("/api/login", {"deck": deck.key, "password": "anderes"})
    token = jsonlib.loads(koerper)["token"]
    code, _ = await client.get("/api/deck", token=token)
    check("neu anmelden geht", code == 200, str(code))

    deck.binding.network_enabled = False
    code, _ = await client.get("/api/deck", token=token)
    check("ausgeschaltet fliegt auch die laufende Sitzung raus", code == 403, str(code))
    code, _ = await client.post("/api/login", {"deck": deck.key, "password": "anderes"})
    check("und anmelden geht nicht mehr", code == 401, str(code))

    deck.binding.network_enabled = True
    rt.netz.set_password(deck.key, "")
    code, _ = await client.post("/api/login", {"deck": deck.key, "password": ""})
    check("ohne Passwort ist wieder zu", code == 401, str(code))

    # -- Bremse gegen Raten ------------------------------------------------
    rt.netz.set_password(deck.key, "streamteam2026")
    codes = []
    for i in range(netauth.MAX_FEHLVERSUCHE + 2):
        code, _ = await client.post("/api/login", {"deck": deck.key, "password": f"raten{i}"})
        codes.append(code)
    check("nach einigen Fehlversuchen wird gesperrt",
          codes[-1] == 429 and codes[0] == 401, str(codes))

    server.should_exit = True
    await asyncio.wait_for(aufgabe, timeout=5)
    await rt.stop()

    print()
    if FAILS:
        print(f"FEHLGESCHLAGEN ({len(FAILS)}): " + ", ".join(FAILS))
        sys.exit(1)
    print("Alle Prüfungen bestanden.")


asyncio.run(main())
