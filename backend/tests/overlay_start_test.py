"""Prüft den Start des Overlays: Wer gleich wieder stirbt, wird gemeldet."""
import _wache
_wache.sichere_umgebung()

import asyncio, sys
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from deckswitch.services import overlay as ov
from deckswitch.services import session as sess

FAILS = []
def check(name, ok, detail=""):
    print(f"  {'✔' if ok else '✘'} {name}" + (f"  ({detail})" if detail else ""))
    if not ok: FAILS.append(name)

class Prozess:
    def __init__(self, code=None):
        self.code = code
    def poll(self):
        return self.code
    def terminate(self):
        self.code = 0
    def wait(self, timeout=None):
        return 0

def dienst(anbieter):
    deck = SimpleNamespace(
        label="V", _mark_all_dirty=lambda: None,
        binding=SimpleNamespace(columns=4, rows=2, dials=0),
    )
    runtime = SimpleNamespace(
        decks={"v": deck},
        config=SimpleNamespace(app=SimpleNamespace(port=8770)),
        session=SimpleNamespace(caps={sess.OVERLAY: SimpleNamespace(available=True, provider=anbieter, reason="")}),
    )
    d = ov.OverlayService(runtime)
    d._position = mock.AsyncMock(return_value=(10, 20))
    return d

def starte(d, prozess):
    with mock.patch.object(ov.subprocess, "Popen", return_value=prozess) as popen, \
         mock.patch.object(ov.OVERLAY_QML.__class__, "is_file", lambda self: True):
        asyncio.run(d.show("v", at_cursor=False))
    return popen

print("Start")
d = dienst("layer-shell-qt")
popen = starte(d, Prozess())
befehl = popen.call_args.args[0]
check("Layer-Surface nimmt die Startdatei mit dem Modul", befehl[1].endswith("deck-overlay.qml"), befehl[1])
check("ohne --x11", "--x11" not in befehl)
check("das Overlay gilt als sichtbar", d.is_visible("v"))

d = dienst("xwayland")
popen = starte(d, Prozess())
befehl = popen.call_args.args[0]
check("XWayland nimmt die Startdatei ohne das Modul", befehl[1].endswith("deck-overlay-x11.qml"), befehl[1])
check("mit --x11", "--x11" in befehl)
check("und erzwingt das X-Backend", popen.call_args.kwargs["env"].get("QT_QPA_PLATFORM") == "xcb")

print("\nSofortabbruch")
d = dienst("xwayland")
meldung = ""
try:
    starte(d, Prozess(code=1))
except RuntimeError as exc:
    meldung = str(exc)
check("stirbt das Programm, gibt es eine Meldung", "1" in meldung, meldung)
check("und es gilt nicht als sichtbar", not d.is_visible("v"))

print("\nVersteckt während des Anlaufs")
d = dienst("xwayland")
async def beides():
    with mock.patch.object(ov.subprocess, "Popen", return_value=Prozess()), \
         mock.patch.object(ov.OVERLAY_QML.__class__, "is_file", lambda self: True):
        start = asyncio.create_task(d.show("v", at_cursor=False))
        await asyncio.sleep(ov.ANLAUF_S / 2)
        d.hide("v")
        await start
try:
    asyncio.run(beides())
    check("das ist kein Fehler", True)
except Exception as exc:
    check("das ist kein Fehler", False, repr(exc))
check("und es bleibt versteckt", not d.is_visible("v"))

print()
if FAILS:
    print("FEHLGESCHLAGEN: " + ", ".join(FAILS)); sys.exit(1)
print("Alle Prüfungen bestanden.")
