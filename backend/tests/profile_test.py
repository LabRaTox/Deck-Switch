"""Profile: anlegen, kopieren, umbenennen, löschen, wechseln.

Geprüft wird gegen ein laufendes Backend, nicht gegen das Datenmodell allein
— die Fragen, die wehtun, stehen zwischen Endpunkt und Deck: Was passiert mit
einem Deck, dessen Profil gelöscht wird? Zeigt eine Kopie auf ihre eigenen
Seiten oder auf die des Originals?

Aufruf:

    cd backend
    d=$(mktemp -d); env XDG_CONFIG_HOME=$d XDG_DATA_HOME=$d \\
        ../.venv/bin/python tests/profile_test.py
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

from deckswitch.config import Page, Slot  # noqa: E402
from deckswitch.runtime import Runtime  # noqa: E402
from deckswitch.server import create_app  # noqa: E402


class Client:
    """Winziger Client gegen einen echt laufenden Server.

    Kein ``TestClient``: Der bräuchte ein zusätzliches Paket, und ein echter
    Server geht durch dieselbe Schicht wie später die GUI.
    """

    def __init__(self, basis: str) -> None:
        self.basis = basis

    def ruf(self, pfad, *, daten=None, methode=None):
        anfrage = urllib.request.Request(
            self.basis + pfad,
            method=methode or ("POST" if daten is not None else "GET"),
        )
        koerper = None
        if daten is not None:
            koerper = json.dumps(daten).encode()
            anfrage.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(anfrage, koerper, timeout=10) as antwort:
                return antwort.status, antwort.read().decode()
        except urllib.error.HTTPError as fehler:
            return fehler.code, fehler.read().decode()

    def get(self, pfad):
        return self.ruf(pfad)

    def post(self, pfad, daten):
        return self.ruf(pfad, daten=daten)

    def patch(self, pfad, daten):
        return self.ruf(pfad, daten=daten, methode="PATCH")

    def delete(self, pfad):
        return self.ruf(pfad, methode="DELETE")


class _GeraeteInfo:
    """So viel Gerät, wie ``Deck.attach`` wissen will."""

    def __init__(self, serial: str, deck_type: str) -> None:
        self.serial = serial
        self.deck_type = deck_type
        self.firmware = "1.0"
        self.key_count = 8
        self.dial_count = 4
        self.key_size = (120, 120)
        self.touchscreen_size = (800, 100)
        self.segment_size = (200, 100)
        self.key_rows = 2
        self.key_columns = 4
        self.has_displays = True
        self.has_dials = True
        self.has_touchscreen = True

    def as_dict(self):
        return {"serial": self.serial, "deck_type": self.deck_type}


class _Geraet:
    """Ein Stellvertreter statt echter Hardware — er soll nur angenommen werden."""

    def __init__(self, serial: str, deck_type: str) -> None:
        self.info = _GeraeteInfo(serial, deck_type)
        self.on_key = self.on_dial_rotate = self.on_dial_push = None
        self.on_touch = self.on_disconnect = None
        self.geschlossen = False

    def close(self):
        self.geschlossen = True

    def set_brightness(self, wert):
        self.helligkeit = wert

    @property
    def connected(self):
        return True


def _stelle_geraet(serial: str, deck_type: str) -> _Geraet:
    return _Geraet(serial, deck_type)


def _binde_an(runtime, geraet):
    """``_bind_device`` ohne laufende Schleifen — die braucht die Frage nicht."""
    from unittest.mock import patch

    with patch.object(type(runtime.primary), "start", lambda self: None):
        return runtime._adopt(geraet)


def freier_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]

FAILS = []


def check(name, bedingung, detail=""):
    print(("  ✔ " if bedingung else "  ✘ ") + name + (f"  ({detail})" if detail else ""))
    if not bedingung:
        FAILS.append(name)


def main() -> int:
    runtime = Runtime()
    runtime.load_plugins()
    app = create_app(runtime)

    # Der Server läuft in einem eigenen Thread: Die Prüfungen rufen ihn
    # blockierend auf, und in derselben Schleife käme er nie zum Antworten.
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
        config = runtime.config
        erstes = config.active_profile()

        # Eine Seite mit Inhalt, damit die Kopie etwas zu kopieren hat.
        unterseite = Page(name="Unterseite", parent_id=erstes.root_page_id)
        erstes.pages[unterseite.id] = unterseite
        erstes.root_page().keys[0] = Slot(
            plugin_id="streamdeck", action_id="folder",
            settings={"page_id": unterseite.id},
        )
        runtime.save_config()

        print("== Auflisten ==")
        code, roh = client.get("/api/profiles")
        check("die Liste kommt", code == 200, str(code))
        liste = json.loads(roh)["profiles"]
        check("mit dem vorhandenen Profil", len(liste) == 1, json.dumps(liste))
        check("samt Seitenzahl", liste[0]["pages"] == 2, str(liste[0]["pages"]))

        print("\n== Anlegen ==")
        code, roh = client.post("/api/profiles", {"name": "Arbeit"})
        check("ein leeres Profil entsteht", code == 200, roh)
        arbeit_id = json.loads(roh)["profile"]["id"]
        arbeit = config.profiles[arbeit_id]
        check("es hat eine Startseite", len(arbeit.pages) == 1 and arbeit.root_page_id in arbeit.pages)
        check("und heißt wie gewünscht", arbeit.name == "Arbeit")

        code, roh = client.post("/api/profiles", {"name": "", "copy_from": arbeit_id})
        check("ohne Namen bekommt es einen",
              config.profiles[json.loads(roh)["profile"]["id"]].name == "Neues Profil")

        print("\n== Kopieren ==")
        code, roh = client.post("/api/profiles", {"name": "Kopie", "copy_from": erstes.id})
        check("die Kopie entsteht", code == 200, roh)
        kopie = config.profiles[json.loads(roh)["profile"]["id"]]
        check("mit denselben Seiten", len(kopie.pages) == len(erstes.pages),
              f"{len(kopie.pages)} statt {len(erstes.pages)}")
        check("aber mit eigenen Kennungen",
              not (set(kopie.pages) & set(erstes.pages)), str(set(kopie.pages) & set(erstes.pages)))

        # Der springende Punkt: Verweise dürfen nicht ins Original zeigen.
        wurzel = kopie.pages[kopie.root_page_id]
        ziel = wurzel.keys[0].settings["page_id"]
        check("eine Ordnertaste zeigt in die Kopie", ziel in kopie.pages, ziel)
        check("und nicht mehr ins Original", ziel not in erstes.pages)
        unter_kopie = next(p for p in kopie.pages.values() if p.parent_id)
        check("auch die Unterseite hängt an der Kopie",
              unter_kopie.parent_id == kopie.root_page_id, str(unter_kopie.parent_id))

        print("\n== Umbenennen ==")
        check("ein neuer Name geht durch",
              client.patch(f"/api/profiles/{arbeit_id}", {"name": "Büro"})[0] == 200)
        check("und steht in der Config", config.profiles[arbeit_id].name == "Büro")
        check("ein leerer Name wird abgelehnt",
              client.patch(f"/api/profiles/{arbeit_id}", {"name": "  "})[0] == 422)
        check("ein unbekanntes Profil ebenso",
              client.patch("/api/profiles/gibtsnicht", {"name": "X"})[0] == 404)

        print("\n== Wechseln ==")
        deck = runtime.primary
        vorher = deck.binding.profile_id
        check("das Deck steht auf dem ersten Profil", vorher == erstes.id)
        check("ein Wechsel über den Namen klappt", deck.switch_profile("Büro"))
        check("und das Deck zeigt jetzt dorthin", deck.binding.profile_id == arbeit_id)
        check("die Seite kommt aus dem neuen Profil",
              deck.current_page_id_value in config.profiles[arbeit_id].pages)
        check("ein leerer Name führt zurück", deck.switch_profile(""))
        check("also wieder zum ersten", deck.binding.profile_id == erstes.id)
        check("ein Name, den es nicht gibt, ändert nichts",
              not deck.switch_profile("Gibt es nicht")
              and deck.binding.profile_id == erstes.id)
        check("und derselbe Name zweimal auch nicht",
              not deck.switch_profile(config.profiles[erstes.id].name))

        print("\n== Löschen ==")
        deck.binding.profile_id = arbeit_id
        code, roh = client.delete(f"/api/profiles/{arbeit_id}")
        check("das benutzte Profil lässt sich löschen", code == 200, roh)
        check("das Deck wandert auf ein anderes",
              deck.binding.profile_id != arbeit_id
              and deck.binding.profile_id in config.profiles,
              deck.binding.profile_id)
        check("und die Antwort nennt das Deck", json.loads(roh)["moved"], roh)
        check("die Seite des Decks stimmt wieder",
              deck.current_page_id_value in config.profiles[deck.binding.profile_id].pages)

        for pid in list(config.profiles):
            if len(config.profiles) > 1:
                client.delete(f"/api/profiles/{pid}")
        code, roh = client.delete(f"/api/profiles/{next(iter(config.profiles))}")
        check("das letzte Profil bleibt stehen", code == 409, roh)
        check("ein unbekanntes meldet sich ab",
              client.delete("/api/profiles/gibtsnicht")[0] == 404)

        print("\n== Ein Deck ohne Seriennummer ==")
        # Die Bindung für „das erste Gerät" hat keine Seriennummer. In der
        # Konfiguration steht sie deshalb unter ``""`` — daran erkennt die
        # Runtime, welche Bindung ein neu angestecktes Deck übernehmen darf.
        # Ansprechbar ist sie trotzdem, über einen Namen.
        from deckswitch.deck import PLATZHALTER_KEY

        ziel = next(iter(config.profiles))
        check("in der Konfiguration steht sie ohne Seriennummer",
              "" in config.decks and config.decks[""].serial == "",
              str(list(config.decks)))
        check("die Runtime führt sie unter einem Namen",
              runtime.primary.key == PLATZHALTER_KEY, runtime.primary.key)
        check("und findet sie darunter auch",
              runtime.decks.get(PLATZHALTER_KEY) is runtime.primary)
        check("der Marker zum Übernehmen bleibt erhalten",
              any(not d.binding.serial for d in runtime.decks.values()))

        code, roh = client.patch(f"/api/decks/{PLATZHALTER_KEY}", {"profile_id": ziel})
        check("über den Namen geht der Wechsel", code == 200, f"{code} {roh[:80]}")
        check("und kommt an", runtime.primary.binding.profile_id == ziel)
        code, _ = client.patch("/api/decks/", {"profile_id": ziel})
        check("ein leeres Segment fiele weiter auf die Liste", code == 405, str(code))

        # Der eigentliche Grund für das Ganze: Ein zweiter Abgleich mit der
        # Konfiguration darf den Platzhalter nicht wegräumen.
        runtime._sync_decks()
        check("ein Abgleich lässt ihn stehen",
              runtime.decks.get(PLATZHALTER_KEY) is not None
              and runtime.decks[PLATZHALTER_KEY].binding.profile_id == ziel)
        check("und legt ihn nicht doppelt an", len(runtime.decks) == len(config.decks),
              f"{len(runtime.decks)} Sitzungen zu {len(config.decks)} Bindungen")

        print("\n== Ein Deck wird angesteckt ==")
        # Der Kern der Sache: Wer ohne Gerät Tasten belegt und es dann
        # ansteckt, muss seine Belegung wiederfinden. Genau das hängt an der
        # leeren Seriennummer — deshalb wird sie hier nicht gefälscht.
        platzhalter = runtime.decks[PLATZHALTER_KEY]
        profil_vorher = platzhalter.binding.profile_id
        seite = config.profiles[profil_vorher].root_page()
        seite.keys[3] = Slot(plugin_id="streamdeck", action_id="home")

        angesteckt = _stelle_geraet("WA-PRUEF-4711", "Stream Deck +")
        deck = _binde_an(runtime, angesteckt)

        check("das Gerät übernimmt den Platzhalter", deck is platzhalter,
              f"{deck!r} statt {platzhalter!r}")
        check("und trägt jetzt seine Seriennummer",
              deck.binding.serial == "WA-PRUEF-4711", deck.binding.serial)
        check("der Schlüssel wandert mit", deck.key == "WA-PRUEF-4711", deck.key)
        check("die Runtime kennt ihn unter dem neuen Namen",
              runtime.decks.get("WA-PRUEF-4711") is deck)
        check("und nicht mehr unter dem alten",
              PLATZHALTER_KEY not in runtime.decks, str(list(runtime.decks)))
        check("die Konfiguration ebenso",
              "WA-PRUEF-4711" in config.decks and "" not in config.decks,
              str(list(config.decks)))
        check("das Profil ist dasselbe geblieben",
              deck.binding.profile_id == profil_vorher)
        check("und die Belegung steht noch da",
              config.profiles[profil_vorher].root_page().keys.get(3) is not None)

        print("\n== Automatik nach Programm ==")
        # Der Compositor bleibt hier außen vor: Geprüft wird die Regel, nicht
        # KWin. Ob das Skript dort läuft, hängt am Desktop und gehört nicht
        # in eine Suite, die überall laufen soll.
        import asyncio as _asyncio

        automatik = runtime.smartprofile
        alltag = config.profiles[deck.binding.profile_id]

        # Ohne eine einzige Regel fasst der Dienst den Compositor gar nicht
        # erst an — das spart ein Skript, das nichts zu melden hätte.
        _asyncio.run(automatik.start())
        check("ohne Regeln meldet sich die Automatik ab",
              not automatik.verfuegbar and "Regel" in automatik.grund, automatik.grund)

        streaming = config.new_profile_for_deck("Streaming-Profil")
        streaming.auto_apps = ["obs", "Broadcaster"]

        automatik._auf_fenster("obs", "OBS 30.2 — Profil: Stream")
        check("ein passendes Fenster schaltet um",
              deck.binding.profile_id == streaming.id,
              config.profiles[deck.binding.profile_id].name)
        check("und die Automatik merkt sich das Fenster",
              automatik.letztes_fenster[0] == "obs")

        automatik._auf_fenster("firefox", "Irgendeine Seite")
        check("ein fremdes Fenster führt zurück",
              deck.binding.profile_id == alltag.id,
              config.profiles[deck.binding.profile_id].name)

        automatik._auf_fenster("kate", "notizen.md — Broadcaster")
        check("auch der Titel wird durchsucht",
              deck.binding.profile_id == streaming.id,
              config.profiles[deck.binding.profile_id].name)

        # Der Punkt, an dem eine schlichte Umschaltung falsch wäre: Wer
        # während eines automatischen Wechsels von Hand etwas wählt, will
        # nicht beim nächsten Fensterwechsel zurückgeworfen werden.
        deck.switch_profile(alltag.name)
        automatik._auf_fenster("thunderbird", "Posteingang")
        check("eine Wahl von Hand hebt die Leihgabe auf",
              deck.binding.profile_id == alltag.id,
              config.profiles[deck.binding.profile_id].name)

        check("Groß- und Kleinschreibung ist egal",
              automatik._passendes_profil("OBS-Studio", "") is streaming)
        check("ein Fenster ohne Treffer ergibt nichts",
              automatik._passendes_profil("dolphin", "Ordner") is None)

        code, roh = client.get("/api/profiles/automatik")
        check("der Status ist abrufbar", code == 200 and "available" in json.loads(roh),
              roh[:80])

        print("\n== Die Taste dazu ==")
        plugin = runtime.registry.instance("streamdeck")
        auswahl = plugin.get_dynamic_options("profiles")
        check("die Aktion bietet alle Profile an",
              len(auswahl) == len(config.profiles) + 1, json.dumps(auswahl))
        check("mit dem Weg zurück an erster Stelle", auswahl[0]["value"] == "")
        aktion = runtime.registry.get("streamdeck").manifest.action("profile")
        check("die Aktion steht im Manifest", aktion is not None)
        check("und läuft auf Taste und Dial",
              aktion is not None and sorted(aktion.inputs) == ["dial", "key"])

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
