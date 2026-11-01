"""Prüft das OpenRGB-Plugin gegen einen nachgebauten SDK-Server.

Der Server hier spricht das Protokoll über einen echten Socket auf
127.0.0.1. Die Gerätedaten in ``daten/openrgb/`` sind Antworten eines echten
OpenRGB 1.1 mit Debug-Geräten. Ein echtes OpenRGB wird nicht gestartet.

Aufruf:

    cd backend
    d=$(mktemp -d); env XDG_CONFIG_HOME=$d XDG_DATA_HOME=$d \\
        ../.venv/bin/python tests/openrgb_test.py
"""
import _wache  # bricht ab, statt in die echte Config zu schreiben
_wache.sichere_umgebung()

import asyncio
import json
import pathlib
import socket
import struct
import sys
import threading
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

PLUGIN_DIR = pathlib.Path(__file__).resolve().parents[2] / "plugin-sources" / "openrgb"
DATEN = pathlib.Path(__file__).resolve().parent / "daten" / "openrgb"
import _pluginlader  # noqa: E402
_pluginlader.ueberspringe_ohne(PLUGIN_DIR)

from deckswitch import texte  # noqa: E402
from deckswitch.config import Appearance, Slot, default_config  # noqa: E402
from deckswitch.plugins.base import Manifest, Services, SlotContext  # noqa: E402
from deckswitch.services.icons import IconService  # noqa: E402
from deckswitch.services.render import RenderService  # noqa: E402

from _pluginlader import lade, nachbar  # noqa: E402

modul = lade(PLUGIN_DIR)
sdk = nachbar(modul, "sdk")
texte.verbinde_sprache(lambda: "de")

FAILS = []


def check(name, bedingung, detail=""):
    print(("  ✔ " if bedingung else "  ✘ ") + name + (f"  ({detail})" if detail else ""))
    if not bedingung:
        FAILS.append(name)


# -- Bausteine einer Geräteantwort -------------------------------------------


def _t(wert):
    roh = wert.encode() + b"\0"
    return struct.pack("<H", len(roh)) + roh


def _modus(name, farbmodus, farben=(), farben_min=0, farben_max=0):
    kopf = _t(name) + struct.pack("<iIIIIIIIIIII", 0, 0, 0, 0, 0, 0, farben_min, farben_max,
                                  0, 0, 0, farbmodus)
    return kopf + sdk.farben_packen(list(farben))


def geraet_bytes(name, modi, aktiv, leds):
    rumpf = struct.pack("<i", 0)
    for wert in (name, "Hersteller", "Beschreibung", "1.0", "SN-" + name, "Ort " + name):
        rumpf += _t(wert)
    rumpf += struct.pack("<Hi", len(modi), aktiv) + b"".join(modi)
    rumpf += struct.pack("<H", 0)
    rumpf += struct.pack("<H", len(leds))
    for nummer in range(len(leds)):
        rumpf += _t(f"LED {nummer}") + struct.pack("<I", nummer)
    rumpf += sdk.farben_packen(leds)
    return struct.pack("<I", len(rumpf) + 4) + rumpf


class Simuliert:
    """Ein Gerät im Server: Modi, aktiver Modus, LEDs."""

    def __init__(self, name, modi, aktiv=0, leds=4):
        self.name = name
        self.modi = modi  # (name, farbmodus, farben, min, max)
        self.aktiv = aktiv
        self.leds = [(9, 9, 9)] * leds

    def daten(self):
        modi = [_modus(n, f, c, a, b) for n, f, c, a, b in self.modi]
        return geraet_bytes(self.name, modi, self.aktiv, self.leds)


class Server:
    """Antwortet wie der SDK-Server von OpenRGB, auch mit ungefragten Paketen."""

    def __init__(self, geraete, version=6, port=0):
        self.geraete = geraete
        self.version = version
        self.profile = ["Abend"]
        self.geladen = []
        self.pakete = []
        self.anfragen = 0
        self.lauscher = socket.create_server(("127.0.0.1", port))
        self.port = self.lauscher.getsockname()[1]
        self.verbindungen = []
        self.laeuft = True
        threading.Thread(target=self._annehmen, daemon=True).start()

    def _annehmen(self):
        while self.laeuft:
            try:
                sock, _ = self.lauscher.accept()
            except OSError:
                return
            self.verbindungen.append(sock)
            threading.Thread(target=self._bedienen, args=(sock,), daemon=True).start()

    def _lies(self, sock, anzahl):
        puffer = b""
        while len(puffer) < anzahl:
            stueck = sock.recv(anzahl - len(puffer))
            if not stueck:
                raise ConnectionError
            puffer += stueck
        return puffer

    def _antwort(self, sock, geraet, befehl, inhalt=b""):
        sock.sendall(sdk.KOPF.pack(sdk.MAGIE, geraet, befehl, len(inhalt)) + inhalt)

    def _bedienen(self, sock):
        try:
            while True:
                _, geraet, befehl, laenge = sdk.KOPF.unpack(self._lies(sock, 16))
                inhalt = self._lies(sock, laenge)
                self.pakete.append((geraet, befehl))
                self._verarbeite(sock, geraet, befehl, inhalt)
        except (ConnectionError, OSError):
            pass

    def _verarbeite(self, sock, geraet, befehl, inhalt):
        if befehl == sdk.VERSION:
            self._antwort(sock, 0, sdk.VERSION, struct.pack("<I", self.version))
            # Das tut OpenRGB 1.1 unaufgefordert: Bestätigung, Servername.
            self._antwort(sock, 0, 10, struct.pack("<II", sdk.VERSION, 0))
        elif befehl == sdk.ANZAHL:
            self.anfragen += 1
            self._antwort(sock, 0, 100)  # ein ungefragtes DEVICE_LIST_UPDATED
            self._antwort(sock, 0, sdk.ANZAHL, struct.pack("<I", len(self.geraete)))
        elif befehl == sdk.GERAET:
            self._antwort(sock, geraet, sdk.GERAET, self.geraete[geraet].daten())
        elif befehl == sdk.PROFILE:
            rumpf = struct.pack("<H", len(self.profile)) + b"".join(_t(p) for p in self.profile)
            self._antwort(sock, 0, sdk.PROFILE, struct.pack("<I", len(rumpf) + 4) + rumpf)
        elif befehl == sdk.PROFIL_LADEN:
            self.geladen.append(inhalt.rstrip(b"\0").decode())
        elif befehl == sdk.EIGENER_MODUS:
            ziel = self.geraete[geraet]
            for nummer, modus in enumerate(ziel.modi):
                if modus[0] in ("Direct", "Static"):
                    ziel.aktiv = nummer
                    break
        elif befehl == sdk.LEDS_SETZEN:
            lesen = sdk._Lesen(inhalt)
            lesen.wert("I")
            self.geraete[geraet].leds = lesen.farben()
        elif befehl == sdk.MODUS_SETZEN:
            lesen = sdk._Lesen(inhalt)
            lesen.wert("I")
            nummer = lesen.wert("i")
            ziel = self.geraete[geraet]
            ziel.aktiv = nummer
            lesen.text()
            lesen.wert("iI" + "II" + "II" + "II" + "I" + "I" + "I" + "I")
            name, farbmodus, _, a, b = ziel.modi[nummer]
            ziel.modi[nummer] = (name, farbmodus, lesen.farben(), a, b)

    def beenden(self):
        self.laeuft = False
        for sock in self.verbindungen:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            sock.close()
        # Weckt das blockierte accept, sonst bliebe der Port belegt.
        try:
            self.lauscher.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.lauscher.close()


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


class KeineIcons:
    def __init__(self):
        self.iconsets = []

    def get(self, plugin_id):
        return None


def neues_plugin(port):
    manifest_dict = json.loads((PLUGIN_DIR / "manifest.json").read_text(encoding="utf-8"))
    config = default_config()
    config.plugin_settings["openrgb"] = {"host": "127.0.0.1", "port": port}
    icons = IconService(KeineIcons())
    laufzeit = FakeRuntime()
    dienste = Services(audio=None, icons=icons, render=RenderService(icons), runtime=laufzeit,
                       config=config, plugin_dir=PLUGIN_DIR)
    plugin = modul.OpenRgbPlugin(Manifest.model_validate(manifest_dict), dienste)
    plugin._uebernimm_konfiguration()
    return plugin, laufzeit, dienste


def kontext(dienste, action_id, settings, art="key", index=0):
    groesse = (200, 100) if art == "dial" else (120, 120)
    return SlotContext(action_id=action_id, settings=settings, appearance=Appearance(),
                       input_type=art, index=index, page_id="p", profile_id="q", size=groesse,
                       services=dienste, slot=Slot(plugin_id="openrgb", action_id=action_id))


DIRECT = ("Direct", sdk.FARBE_JE_LED, [], 0, 0)
EFFEKT = ("Rainbow", 0, [], 0, 0)
STATIC = ("Static", sdk.FARBE_IM_MODUS, [(1, 2, 3)], 1, 1)


def pruefe_echte_antwort():
    print("Antworten von OpenRGB 1.1")
    geraet = sdk.geraet_lesen(0, (DATEN / "tastatur.bin").read_bytes(), 4)
    check("Name gelesen", geraet.name == "Debug Keyboard", geraet.name)
    check("LEDs bis zum Ende gelesen", len(geraet.leds) == 11, str(len(geraet.leds)))
    check("Modus Direct je LED", geraet.aktiver_modus().name == "Direct"
          and geraet.aktiver_modus().farbmodus == sdk.FARBE_JE_LED)
    check("Kennung enthält Ort", geraet.kennung.endswith("Location String"))


def pruefe_kaputte_antwort():
    print("Kaputte Antworten")
    server = Server([Simuliert("A", [DIRECT])])
    roh = server.geraete[0].daten()
    server.beenden()
    try:
        sdk.geraet_lesen(0, roh[:30], 4)
        check("abgeschnittene Antwort wirft", False)
    except struct.error:
        check("abgeschnittene Antwort wirft", True)

    lauscher = socket.create_server(("127.0.0.1", 0))

    def fremd():
        sock, _ = lauscher.accept()
        sock.recv(64)
        sock.sendall(b"HTTP/1.1 400 Bad Request\r\n\r\n")
        sock.close()
    threading.Thread(target=fremd, daemon=True).start()
    try:
        sdk.Verbindung("127.0.0.1", lauscher.getsockname()[1]).geraete()
        check("fremder Dienst abgelehnt", False)
    except sdk.SdkFehler as exc:
        check("fremder Dienst abgelehnt", "kein OpenRGB" in str(exc), str(exc))
    lauscher.close()


def pruefe_version():
    print("Version aushandeln")
    server = Server([Simuliert("A", [DIRECT])], version=6)
    verbindung = sdk.Verbindung("127.0.0.1", server.port)
    verbindung.geraete()
    check("neuer Server: bleibt bei Version 4", verbindung.version == 4)
    verbindung.trennen()
    server.beenden()

    alt = Server([], version=1)
    try:
        sdk.Verbindung("127.0.0.1", alt.port).geraete()
        check("Version 1 abgelehnt", False)
    except sdk.SdkFehler as exc:
        check("Version 1 abgelehnt", "zu alt" in str(exc), str(exc))
    alt.beenden()


async def warte_pumpe(plugin):
    if plugin._pumpe_task is not None:
        await plugin._pumpe_task


async def pruefe_farbe():
    print("Farbe setzen")
    effekt = Simuliert("Lüfter", [EFFEKT, DIRECT])
    nur_modus = Simuliert("Streifen", [EFFEKT, STATIC])
    server = Server([effekt, nur_modus])
    plugin, laufzeit, dienste = neues_plugin(server.port)
    ctx = kontext(dienste, "color", {"target": "all", "color": "#102030"})
    await plugin.on_key_down("color", ctx.settings, ctx)
    await asyncio.sleep(0.05)
    check("Direct: Modus gewechselt, LEDs gesetzt",
          effekt.aktiv == 1 and effekt.leds == [(16, 32, 48)] * 4, str(effekt.leds[0]))
    check("Feste Farbliste: Farbe im Modus",
          nur_modus.aktiv == 1 and nur_modus.modi[1][2] == [(16, 32, 48)])
    check("Kein Fehler gemeldet", not laufzeit.meldungen, str(laufzeit.meldungen))

    effekt.leds = [(9, 9, 9)] * 4
    kennung = plugin._geraete[1].kennung
    ctx = kontext(dienste, "color", {"target": kennung, "color": "#ff0000"})
    await plugin.on_key_down("color", ctx.settings, ctx)
    await asyncio.sleep(0.05)
    check("Einzelnes Gerät: das andere bleibt", effekt.leds == [(9, 9, 9)] * 4
          and nur_modus.modi[1][2] == [(255, 0, 0)])

    ctx = kontext(dienste, "color", {"target": "weg", "color": "#ff0000"})
    await plugin.on_key_down("color", ctx.settings, ctx)
    check("Fehlendes Gerät wird gemeldet",
          any("nicht" in text for _, text in laufzeit.meldungen), str(laufzeit.meldungen))
    await plugin.teardown()
    server.beenden()


async def pruefe_dial():
    print("Dial")
    geraet = Simuliert("Lüfter", [DIRECT])
    server = Server([geraet])
    plugin, _, dienste = neues_plugin(server.port)
    ctx = kontext(dienste, "color", {"target": "all", "color": "#ff0000"}, art="dial")
    vorher = sum(1 for _, b in server.pakete if b == sdk.LEDS_SETZEN)
    for _ in range(20):
        await plugin.on_dial_rotate("color", ctx.settings, 1, ctx)
    await warte_pumpe(plugin)
    await asyncio.sleep(0.05)
    sendungen = sum(1 for _, b in server.pakete if b == sdk.LEDS_SETZEN) - vorher
    check("Schnelles Drehen wird zusammengefasst", sendungen < 20, str(sendungen))
    check("Letzte Farbe kommt an (120°)", geraet.leds[0] == (0, 255, 0), str(geraet.leds[0]))
    bild = plugin.render("color", ctx.settings, ctx)
    check("Kachel hat Segmentgröße", bild.size == (200, 100))

    ctx.settings["color"] = "#0000ff"
    check("Neue Einstellung setzt den Farbton zurück",
          plugin._farbe(ctx.settings, ctx) == (0, 0, 255))
    weiss = modul.mit_farbton((255, 255, 255), 0)
    check("Weiß bekommt beim Drehen Sättigung", weiss == (255, 0, 0), str(weiss))
    check("Kaputte Farbe wird Weiß", modul.hex_zu_rgb("kaputt") == (255, 255, 255))
    await plugin.teardown()
    server.beenden()


async def pruefe_licht():
    print("Licht aus und an")
    geraet = Simuliert("Lüfter", [EFFEKT, DIRECT], aktiv=0)
    server = Server([geraet])
    plugin, _, dienste = neues_plugin(server.port)
    ctx = kontext(dienste, "power", {"target": "all", "restore_profile": ""})
    await plugin._auf_leitung(plugin._abrufen)
    check("Effekt zählt nicht als aus", plugin.get_state("power", ctx.settings, ctx) == "an")
    await plugin.on_key_down("power", ctx.settings, ctx)
    await asyncio.sleep(0.05)
    check("Aus: schwarz im Modus Direct", geraet.leds == [(0, 0, 0)] * 4 and geraet.aktiv == 1)
    check("Taste zeigt aus", plugin.get_state("power", ctx.settings, ctx) == "aus")
    await plugin.on_key_down("power", ctx.settings, ctx)
    await asyncio.sleep(0.05)
    check("An: Effekt wieder aktiv", geraet.aktiv == 0)
    check("Taste zeigt an", plugin.get_state("power", ctx.settings, ctx) == "an")

    geraet.aktiv = 1
    geraet.leds = [(0, 0, 0)] * 4
    await plugin.on_key_down("power", ctx.settings, ctx)
    check("Ohne gemerkten Stand: Hinweis", "kurz" in ctx.scratch)

    ctx = kontext(dienste, "power", {"target": "all", "restore_profile": "Abend"})
    await plugin.on_key_down("power", ctx.settings, ctx)
    await asyncio.sleep(0.05)
    check("Mit Profil: wird geladen", server.geladen == ["Abend"], str(server.geladen))
    await plugin.teardown()
    server.beenden()


async def pruefe_profil_und_listen():
    print("Profile und Auswahllisten")
    server = Server([Simuliert("Lüfter", [DIRECT])])
    plugin, _, dienste = neues_plugin(server.port)
    werte = await asyncio.to_thread(plugin.get_dynamic_options, "profile")
    check("Profilliste", [w["value"] for w in werte] == ["Abend"], str(werte))
    werte = await asyncio.to_thread(plugin.get_dynamic_options, "geraete")
    check("Geräteliste beginnt mit allen", [w["value"] for w in werte][0] == "all"
          and werte[1]["label"] == "Lüfter", str(werte))
    werte = await asyncio.to_thread(plugin.get_dynamic_options, "profile_oder_keins")
    check("Einschalt-Liste hat den gemerkten Stand", werte[0]["value"] == "")

    ctx = kontext(dienste, "profile", {"profile": "Abend"})
    await plugin.on_key_down("profile", ctx.settings, ctx)
    await asyncio.sleep(0.05)
    check("Profil geladen", server.geladen == ["Abend"])
    check("Taste bestätigt", plugin.get_label("profile", ctx.settings, ctx) == "geladen")
    ctx = kontext(dienste, "profile", {})
    await plugin.on_key_down("profile", ctx.settings, ctx)
    check("Ohne Profil: nichts gesendet", server.geladen == ["Abend"])
    await plugin.teardown()
    server.beenden()


async def pruefe_ausfall():
    print("Server fällt aus und kommt wieder")
    server = Server([Simuliert("Lüfter", [DIRECT])])
    port = server.port
    plugin, laufzeit, dienste = neues_plugin(port)
    await plugin._abfrage()
    check("Status verbunden", plugin.get_status()["connected"], str(plugin.get_status()))
    ctx = kontext(dienste, "color", {"target": "all", "color": "#ff0000"})

    server.beenden()
    await asyncio.sleep(0.05)
    await plugin._abfrage()
    check("Status getrennt", plugin.get_status()["connected"] is False)
    check("Taste zeigt getrennt", plugin.get_state("color", ctx.settings, ctx) == "getrennt")
    await plugin._abfrage()
    await plugin._abfrage()
    fehler = [m for m in laufzeit.meldungen if m[0] == "error"]
    check("Dieselbe Meldung nur einmal", len(fehler) == 1, str(fehler))
    check("Backoff wächst", plugin._naechste - time.monotonic() > 40,
          str(plugin._naechste - time.monotonic()))
    plugin._gesehen = time.monotonic()
    check("Im Backoff keine Abfrage", plugin._runde() is None)

    server = Server([Simuliert("Lüfter", [DIRECT])], port=port)
    await plugin.on_key_down("color", ctx.settings, ctx)
    await asyncio.sleep(0.05)
    check("Tastendruck verbindet sofort neu", server.geraete[0].leds[0] == (255, 0, 0))
    check("Status wieder verbunden", plugin.get_status()["connected"])

    # Der Server startet neu, ohne dass der Socket es bisher gemerkt hat.
    server.beenden()
    server = Server([Simuliert("Lüfter", [DIRECT])], port=port)
    await plugin._abfrage()
    check("Toter Socket wird still ersetzt", plugin.get_status()["connected"])
    await plugin.teardown()
    server.beenden()


async def pruefe_sparsam():
    print("Nur fragen, was zu sehen ist")
    server = Server([Simuliert("Lüfter", [DIRECT])])
    plugin, laufzeit, dienste = neues_plugin(server.port)
    check("Niemand sichtbar: keine Abfrage", plugin._runde() is None)
    ctx = kontext(dienste, "power", {"target": "all"})
    plugin.on_tick("power", ctx.settings, ctx)
    aufgabe = plugin._runde()
    check("Sichtbar: Abfrage startet", aufgabe is not None)
    await aufgabe
    check("Danach Pause bis zur nächsten", plugin._runde() is None)
    vorher = laufzeit.redraws
    plugin._naechste = 0.0
    await plugin._runde()
    check("Ohne Änderung kein Neuzeichnen", laufzeit.redraws == vorher)
    await plugin.teardown()
    server.beenden()


def pruefe_manifest():
    print("Manifest und Texte")
    manifest = json.loads((PLUGIN_DIR / "manifest.json").read_text(encoding="utf-8"))
    check("Erste Fassung ohne changelog", "changelog" not in manifest)
    check("Keine Abhängigkeiten", "dependencies" not in manifest)
    check("Gültiges Manifest", Manifest.model_validate(manifest).id == "openrgb")
    de = json.loads((PLUGIN_DIR / "locales/de.json").read_text(encoding="utf-8"))
    en = json.loads((PLUGIN_DIR / "locales/en.json").read_text(encoding="utf-8"))
    check("Beide Sprachen gleich vollständig", set(de) == set(en), str(set(de) ^ set(en)))
    roh = (PLUGIN_DIR / "manifest.json").read_text(encoding="utf-8")
    check("Kein langer Strich", "—" not in roh + json.dumps(de, ensure_ascii=False))


async def alles():
    await pruefe_farbe()
    await pruefe_dial()
    await pruefe_licht()
    await pruefe_profil_und_listen()
    await pruefe_ausfall()
    await pruefe_sparsam()


pruefe_echte_antwort()
pruefe_kaputte_antwort()
pruefe_version()
asyncio.run(alles())
pruefe_manifest()

print()
if FAILS:
    print(f"{len(FAILS)} FEHLGESCHLAGEN: {FAILS}")
    sys.exit(1)
print("Alle Prüfungen bestanden.")
