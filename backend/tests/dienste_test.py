"""Prüft Randfälle der Systemdienste, ohne den Desktop anzufassen.

Kein Aufruf hier startet wpctl, pactl, pgrep oder KWin: Wo ein Dienst nach
außen greift, steht eine Attrappe. Geprüft wird, was der Dienst aus den
Antworten macht.

Aufruf:

    cd backend
    d=$(mktemp -d)
    env XDG_CONFIG_HOME=$d XDG_DATA_HOME=$d ../.venv/bin/python tests/dienste_test.py
"""
import _wache  # bricht ab, statt in die echte Config zu schreiben
_wache.sichere_umgebung()

import asyncio
import io
import json
import sys
import threading
import time
import zipfile
from unittest import mock

FAILS = []


def check(n, c, d=""):
    print(("  ✔ " if c else "  ✘ ") + n + (f"  ({d})" if d else ""))
    if not c:
        FAILS.append(n)


# ==========================================================================
print("\nAudio: Eingänge erkennen")
from deckswitch.services import audio as A

QUELLEN = [
    {"index": 51, "name": "easyeffects_source"},
    {"index": 52, "name": "bluez_input.AA_BB.0"},
    {"index": 53, "name": "alsa_input.usb-Mic"},
]


def neuer_audio(quellen=QUELLEN, senken=()):
    svc = A.AudioService()
    svc.has_wpctl = svc.has_pactl = True
    aufrufe = []

    def list_raw(what):
        aufrufe.append(("list", what))
        return list(quellen) if what == "sources" else list(senken)

    svc._list_raw = list_raw
    svc._aufrufe = aufrufe
    return svc


svc = neuer_audio()
check("easyeffects_source gilt als Eingang", svc._is_source("easyeffects_source"))
check("bluez_input gilt als Eingang", svc._is_source("bluez_input.AA_BB.0"))
check("alsa_output gilt als Ausgang", not svc._is_source("alsa_output.usb-Speaker"))
check("ein unbekannter Name gilt als Ausgang", not svc._is_source("game_sink"))
check("Quellen-Index zählt auch", svc._is_source("51"))

befehle = []
svc._run = lambda cmd: befehle.append(cmd) or ""
svc.set_mute("easyeffects_source", True)
check("Stummschalten trifft set-source-mute",
      befehle and befehle[-1][:2] == ["pactl", "set-source-mute"], str(befehle[-1:]))

print("\nAudio: ohne wpctl")
svc = neuer_audio(senken=[{"index": 1, "name": "alsa_output.x", "mute": True,
                           "volume": {"fl": {"value": 32768}}}])
svc.has_wpctl = False
befehle = []


def lauf(cmd):
    befehle.append(cmd)
    if cmd[:2] == ["pactl", "get-default-sink"]:
        return "alsa_output.x\n"
    return ""


svc._run = lauf
zustand = svc.get_volume(A.DEFAULT_SINK)
check("Standardausgang wird über seinen Namen gelesen",
      zustand.available and abs(zustand.volume - 0.5) < 0.01 and zustand.muted, str(zustand))
svc.set_volume(A.DEFAULT_SINK, 0.3)
check("pactl bekommt @DEFAULT_SINK@ statt des wpctl-Namens",
      befehle[-1] == ["pactl", "set-sink-volume", "@DEFAULT_SINK@", "30%"], str(befehle[-1]))
svc.toggle_mute(A.DEFAULT_SOURCE)
check("und @DEFAULT_SOURCE@ für den Standardeingang",
      any(b[:3] == ["pactl", "set-source-mute", "@DEFAULT_SOURCE@"] for b in befehle))

print("\nAudio: Zwischenspeicher und Invalidierung")
svc = neuer_audio()
gestartet, weiter = threading.Event(), threading.Event()


def langsam_lesen(target):
    gestartet.set()
    weiter.wait(2)
    return A.VolumeState(0.1, False, True)


svc._read_volume = langsam_lesen
t = threading.Thread(target=svc.get_volume, args=("alsa_output.x",))
t.start()
gestartet.wait(2)
svc.invalidate()  # Änderung kommt, während noch gelesen wird
weiter.set()
t.join(2)
check("ein vor der Änderung begonnenes Lesen wird nicht abgelegt",
      "alsa_output.x" not in svc._cache)

svc = neuer_audio()
zaehler = {"n": 0}


def zaehl_lesen(target):
    zaehler["n"] += 1
    return A.VolumeState(0.2, False, True)


svc._read_volume = zaehl_lesen
svc.get_volume("x")
svc._cache["x"] = (time.monotonic() - 1.0, svc._cache["x"][1])
svc.get_volume("x")
check("ohne Watcher gilt die kurze Frist", zaehler["n"] == 2, str(zaehler))
svc._watched = lambda: True
svc._cache["x"] = (time.monotonic() - 1.0, svc._cache["x"][1])
svc.get_volume("x")
check("mit laufendem Watcher gilt die lange Frist", zaehler["n"] == 2, str(zaehler))

print("\nAudio: pactl subscribe, das sofort endet")
svc = A.AudioService()
svc.has_pactl = True
abstaende = []


def warte(sekunden):
    abstaende.append(sekunden)
    return len(abstaende) >= 4


svc._stop.wait = warte
echtes_popen = A.subprocess.Popen
with mock.patch.object(A.subprocess, "Popen",
                       lambda argv, **kw: echtes_popen(["true"], **kw)):
    svc._watch()
check("der Abstand wächst, statt bei 1 s zu bleiben",
      abstaende[:4] == [1.0, 2.0, 4.0, 8.0], str(abstaende))
check("kein Unterprozess bleibt als aktuell stehen", svc._subscriber is None)


# ==========================================================================
print("\nTastatur: localectl")
from deckswitch.services import input as I

ausgabe = """   System Locale: LANG=de_DE.UTF-8
       VC Keymap: de-latin1-nodeadkeys
      X11 Layout: de
       X11 Model: pc105
     X11 Variant: nodeadkeys
"""
check("X11 Layout gewinnt gegen die Konsolenbelegung",
      I._parse_localectl(ausgabe) == ("de", "nodeadkeys"), str(I._parse_localectl(ausgabe)))
check("ohne X11-Angabe zählt die Konsolenbelegung bis zum Bindestrich",
      I._parse_localectl("VC Keymap: de-latin1\nX11 Layout: n/a\n") == ("de", ""))
check("ohne alles bleibt es bei us", I._parse_localectl("") == ("us", ""))

print("\nTastatur: Belegungswechsel")
erkannt = {"wert": ("de", "")}
gebaut = []


def bau(layout, variant=""):
    gebaut.append((layout, variant))
    return {"z": (21 if layout == "de" else 44, [])}


with (mock.patch.object(I, "_detect_layout", lambda: erkannt["wert"]),
      mock.patch.object(I, "_build_char_map", bau)):
    tastatur = I.InputService()
    tastatur._ensure_layout()
    tastatur._ensure_layout()
    check("innerhalb der Frist wird nicht neu gerechnet", len(gebaut) == 1, str(gebaut))
    erkannt["wert"] = ("us", "")
    tastatur._layout_checked_at -= I.LAYOUT_RECHECK_S + 1
    tastatur._ensure_layout()
    check("nach der Frist wird die neue Belegung übernommen",
          tastatur._layout == "us" and tastatur._chars["z"][0] == 44, tastatur._layout)
    tastatur._layout_checked_at -= I.LAYOUT_RECHECK_S + 1
    tastatur._ensure_layout()
    check("unverändert heißt: nicht neu rechnen", len(gebaut) == 2, str(gebaut))


# ==========================================================================
print("\nProgramme beenden")
from deckswitch.services import desktop as D

eltern = {100: 1, 101: 100, 102: 100, 103: 101, 200: 1, 201: 200}
with mock.patch.object(D, "_elternprozess", lambda pid: eltern.get(pid, 0)):
    check("Kindprozesse zählen nicht als eigene Programme",
          sorted(D._wurzeln(list(eltern))) == [100, 200], str(D._wurzeln(list(eltern))))

aufrufe = []


class Ergebnis:
    returncode = 1
    stdout = ""
    stderr = ""


with (mock.patch.object(D, "_run", lambda argv, **kw: aufrufe.append(argv) or Ergebnis()),
      mock.patch.object(D.shutil, "which", lambda name: "/usr/bin/" + name)):
    D.DesktopService.close_application("-xyz-muster")
check("das Muster steht hinter --", aufrufe and aufrufe[0][-2:] == ["--", "-xyz-muster"],
      str(aufrufe))

viele = list(range(1000, 1030))  # 30 Prozesse, aber nur ein Programm
mit_eltern = {1000: 1, **{pid: 1000 for pid in viele[1:]}}


class VieleTreffer:
    returncode = 0
    stdout = "\n".join(str(p) for p in viele)
    stderr = ""


getroffen = []
with (mock.patch.object(D, "_run", lambda argv, **kw: VieleTreffer()),
      mock.patch.object(D.shutil, "which", lambda name: "/usr/bin/" + name),
      mock.patch.object(D, "_elternprozess", lambda pid: mit_eltern.get(pid, 0)),
      mock.patch.object(D.os, "kill", lambda pid, sig: getroffen.append(pid))):
    anzahl = D.DesktopService.close_application("discord")
check("ein Programm mit 30 Prozessen wird beendet", anzahl == 30 and len(getroffen) == 30,
      f"{anzahl} beendet")


# ==========================================================================
print("\nMedien")
from deckswitch.services import media as M


async def medien():
    svc = M.MediaService()
    namen = [M.BUS_PREFIX + n for n in ("haengt", "pausiert", "spielt")]

    async def list_names():
        return namen

    async def get(dest, name, *, timeout=M.CALL_TIMEOUT_S):
        if dest.endswith("haengt"):
            await asyncio.sleep(timeout)
            return None
        return "Paused" if dest.endswith("pausiert") else "Playing"

    svc._list_names = list_names
    svc._get = get
    start = time.monotonic()
    wahl = await svc._pick()
    dauer = time.monotonic() - start
    check("der spielende Player gewinnt", wahl.endswith("spielt"), wahl)
    check("ein hängender Player kostet die Wartezeit nur einmal",
          dauer < M.PICK_TIMEOUT_S + 0.5, f"{dauer:.2f} s")

    threads = []

    class Tastatur:
        def send_combo(self, key):
            threads.append(threading.current_thread() is threading.main_thread())

    svc.bind_input(Tastatur())
    ok = await svc._fallback("play_pause")
    check("die Multimedia-Taste läuft nicht im Event-Loop",
          ok and threads == [False], str(threads))


asyncio.run(medien())


# ==========================================================================
print("\nSmart Profiles: gescheiterter Start")
from deckswitch.services import smartprofile as SP


class FalscherBus:
    offen = 0

    def __init__(self, *a, **k):
        pass

    async def connect(self):
        FalscherBus.offen += 1
        self.connected = True
        return self

    def export(self, *a):
        pass

    async def request_name(self, name):
        return 1

    async def call(self, msg):
        raise RuntimeError("kein KWin")

    def disconnect(self):
        FalscherBus.offen -= 1


class Laufzeit:
    class config:
        profiles = {"p": type("P", (), {"auto_apps": ["obs"], "id": "p"})()}

    decks = {}


async def smart():
    dienst = SP.SmartProfileService(Laufzeit())
    with mock.patch("dbus_next.aio.MessageBus", FalscherBus):
        for _ in range(3):
            await dienst.neu_bewerten()
    check("nicht verfügbar", not dienst.verfuegbar, dienst.grund)
    check("keine Verbindung bleibt offen", FalscherBus.offen == 0, f"{FalscherBus.offen} offen")


asyncio.run(smart())


# ==========================================================================
print("\nStore: Anmeldung nach HTTP-Status")
from deckswitch import texte
from deckswitch.services import store as S

S.schreib_token("abc")
texte.verbinde_sprache(lambda: "en")
try:
    with mock.patch.object(S, "_anfrage",
                           side_effect=S.StoreError("Token expired", status=401)):
        check("401 heißt abgemeldet, auch auf Englisch", S.wer_bin_ich() is None)
    check("und das alte Token ist weg", S.lies_token() == "")
    S.schreib_token("abc")
    with mock.patch.object(S, "_anfrage",
                           side_effect=S.StoreError("You lack the rights", status=403)):
        check("403 heißt: keine Prüfrechte", S.offene_pruefungen() is None)
    with mock.patch.object(S, "_anfrage",
                           side_effect=S.StoreError("Server kaputt", status=500)):
        try:
            S.offene_pruefungen()
            check("500 bleibt ein Fehler", False)
        except S.StoreError:
            check("500 bleibt ein Fehler", True)
finally:
    texte.verbinde_sprache(lambda: "de")
    S.schreib_token("")


# ==========================================================================
print("\nProfilimport: gleichnamige Bilder")
from deckswitch import paths
from deckswitch.config import Appearance, Background, ConfigStore, Page, Profile, Slot
from deckswitch.services import backup as B

paths.ensure_dirs()
store = ConfigStore()
store.load()
eigenes = paths.UPLOADS_DIR / "icon.png"
eigenes.write_bytes(b"\x89PNG eigenes")
gleiches = paths.UPLOADS_DIR / "gleich.png"
gleiches.write_bytes(b"\x89PNG gleich")

seite = Page(name="Fremd")
seite.keys[0] = Slot(plugin_id="audio", action_id="mic_mute",
                     appearance=Appearance(background=Background(kind="image", upload="icon.png")))
seite.keys[1] = Slot(plugin_id="audio", action_id="mic_mute",
                     appearance=Appearance(background=Background(kind="image", upload="gleich.png")))
fremd = Profile(name="Fremd", root_page_id=seite.id, pages={seite.id: seite})
puffer = io.BytesIO()
with zipfile.ZipFile(puffer, "w") as zf:
    zf.writestr("manifest.json", json.dumps({"kind": B.PROFILE_KIND, "format": 1}))
    zf.writestr("profile.json", json.dumps(fremd.model_dump(mode="json")))
    zf.writestr("uploads/icon.png", b"\x89PNG fremdes")
    zf.writestr("uploads/gleich.png", b"\x89PNG gleich")

neu = B.import_profile(puffer.getvalue(), store)
check("das eigene Bild bleibt unverändert", eigenes.read_bytes() == b"\x89PNG eigenes")
neue_seite = neu.pages[neu.root_page_id]
verweis = neue_seite.keys[0].appearance.background.upload
check("das fremde Bild bekommt einen eigenen Namen",
      verweis != "icon.png" and (paths.UPLOADS_DIR / verweis).read_bytes() == b"\x89PNG fremdes",
      verweis)
check("ein Bild mit gleichem Inhalt wird nicht verdoppelt",
      neue_seite.keys[1].appearance.background.upload == "gleich.png"
      and not (paths.UPLOADS_DIR / "gleich-2.png").exists())


# ==========================================================================
print("\nSymbole: Zwischenspeicher")
from deckswitch.services import icons as IC

speicher = {}
IC._ablegen(speicher, ("frames", "/a.gif", 1), "alt", 10)
IC._ablegen(speicher, ("scaled", "/a.gif", 1, 72), "alt", 10)
IC._ablegen(speicher, ("frames", "/b.gif", 5), "andere", 10)
IC._ablegen(speicher, ("frames", "/a.gif", 2), "neu", 10)
check("eine ersetzte Datei räumt ihre alten Einträge ab",
      set(speicher) == {("frames", "/b.gif", 5), ("frames", "/a.gif", 2)}, str(list(speicher)))
for i in range(20):
    IC._ablegen(speicher, ("set", f"/{i}.svg", 72, None), i, 10)
check("die Grenze hält", len(speicher) == 10, str(len(speicher)))


print()
if FAILS:
    print(f"FEHLGESCHLAGEN ({len(FAILS)}): " + ", ".join(FAILS))
    sys.exit(1)
print("Alle Prüfungen bestanden.")
