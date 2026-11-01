"""Prüft die Pegelanzeige: Skala, Trägheit, Ablauf der Messung und das Bild."""
import _wache
_wache.sichere_umgebung()

import struct, sys, threading, time
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image

from deckswitch.services import pegel as pg
from deckswitch.services.render import RenderService

FAILS = []
def check(name, ok, detail=""):
    print(f"  {'✔' if ok else '✘'} {name}" + (f"  ({detail})" if detail else ""))
    if not ok: FAILS.append(name)

print("Skala")
check("Vollaussteuerung ist 0 dB", pg.db(1.0) == 0.0)
check("halbe Amplitude sind rund -6 dB", abs(pg.db(0.5) + 6.02) < 0.01, f"{pg.db(0.5):.2f}")
check("Stille landet an der Untergrenze", pg.db(0.0) == pg.UNTERGRENZE_DB)
check("0 dB füllt die Anzeige", pg.anzeige_wert(0.0) == 1.0)
check("die Untergrenze lässt sie leer", pg.anzeige_wert(pg.UNTERGRENZE_DB) == 0.0)
check("-12 dB ist die gelbe Grenze", abs(pg.anzeige_wert(-12) - 0.8) < 1e-9)

print("\nTrägheit")
t = pg.Traegheit()
t.weiter(-6.0, 0.05, 10.0)
check("steigt sofort", t.pegel_db == -6.0)
t.weiter(pg.UNTERGRENZE_DB, 0.1, 10.1)
check("fällt gebremst", t.pegel_db == -9.0, str(t.pegel_db))
check("die Spitze bleibt stehen", t.spitze_db == -6.0)
t.weiter(pg.UNTERGRENZE_DB, 0.1, 10.0 + pg.SPITZE_HALTEN_S + 0.2)
check("nach der Haltezeit fällt sie mit", t.spitze_db < -6.0, str(t.spitze_db))

print("\nMessung gegen ein nachgestelltes parec")
class Parec:
    """Liefert laute Blöcke, bis es beendet wird."""
    gestartet = []
    def __init__(self, befehl, **_):
        Parec.gestartet.append(befehl)
        self.laeuft = True
        self.stdout = self
    def read(self, n):
        time.sleep(pg.FENSTER_S)
        return struct.pack("f", 0.5) * (n // 4) if self.laeuft else b""
    def terminate(self):
        self.laeuft = False
    def wait(self, timeout=None):
        return 0
    def close(self):
        pass

zeichnen = []
kachel = SimpleNamespace(key="seite:dial:0")
with mock.patch.object(pg.subprocess, "Popen", Parec), \
     mock.patch.object(pg.shutil, "which", return_value="/usr/bin/parec"), \
     mock.patch.object(pg, "MELDUNG_GILT_S", 0.5), mock.patch.object(pg, "NEUSTART_S", 0.05):
    m = pg.Pegelmesser(lambda: "ausgang", zeichnen.append)
    m.lesen("@DEFAULT_AUDIO_SINK@", True, kachel)
    time.sleep(0.25)
    wert, spitze = m.lesen("@DEFAULT_AUDIO_SINK@", True, kachel)
    check("das Signal kommt an", abs(wert - pg.anzeige_wert(pg.db(0.5))) < 1e-6, f"{wert:.3f}")
    check("die Kachel wird neu gezeichnet", kachel in zeichnen, str(len(zeichnen)))
    bilder = len(zeichnen)
    check("gemessen wird der Monitor des Standardausgangs", "ausgang.monitor" in Parec.gestartet[0])
    check("ohne den Ausgang wach zu halten", "--property=node.passive=true" in Parec.gestartet[0])
    check("nur einmal gestartet, auch bei zwei Lesern", len(Parec.gestartet) == 1)
    time.sleep(0.9)
    check("ohne Meldung endet die Messung", not m._messungen, str(list(m._messungen)))
    check("und der Prozess ist weg", not any(t.name.startswith("pegel-") for t in threading.enumerate()))
    check("gleichbleibender Pegel zeichnet nichts neu", len(zeichnen) == bilder, f"{bilder} → {len(zeichnen)}")

    m.lesen("beamer", False, kachel)
    time.sleep(0.1)
    check("ein festes Gerät wird direkt gemessen", any("beamer.monitor" in b for b in Parec.gestartet))
    m.stoppen()
    check("nach dem Stopp beginnt nichts Neues", m.lesen("beamer", False, kachel) == (0.0, 0.0) and not m._messungen)

print("\nFehlendes parec")
with mock.patch.object(pg.shutil, "which", return_value=None):
    ohne = pg.Pegelmesser(lambda: "x", lambda c: None)
check("dann wird die Anzeige nicht angeboten", ohne.verfuegbar is False)

print("\nBild")
r = RenderService.__new__(RenderService)
def bild(pegel, spitze, aktiv=True):
    b = Image.new("RGBA", (100, 10), (0, 0, 0, 255))
    r.draw_meter(b, pegel, spitze, box=(0, 0, 99, 9), aktiv=aktiv)
    return b
b = bild(1.0, 0.0)
check("links grün", b.getpixel((40, 5))[:3] == (34, 197, 94))
check("dann gelb", b.getpixel((88, 5))[:3] == (234, 179, 8))
check("rechts rot", b.getpixel((97, 5))[:3] == (239, 68, 68))
b = bild(0.5, 0.75)
check("über dem Pegel bleibt es dunkel", b.getpixel((60, 5))[:3] == (39, 39, 42))
check("die Spitze ist eine weiße Marke", b.getpixel((74, 5))[:3] == (255, 255, 255))
check("stumm bleibt alles dunkel", bild(1.0, 1.0, aktiv=False).getpixel((40, 5))[:3] == (39, 39, 42))

print()
if FAILS:
    print("FEHLGESCHLAGEN: " + ", ".join(FAILS)); sys.exit(1)
print("Alle Prüfungen bestanden.")
