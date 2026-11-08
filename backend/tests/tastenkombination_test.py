"""Prüft, wie Tastenkombinationen gelesen werden: Zeichen der Belegung.

Eine Kombination nennt das Zeichen, das die Taste auf der eingestellten
Belegung schreibt. „ctrl+z" auf einer deutschen Tastatur ist die Taste, die
dort ein Z schreibt, also die Position, die auf einer amerikanischen ein Y
wäre. Senden (uinput), Empfangen (kglobalaccel) und das Portal müssen das
gleich lesen.

Nichts hier sendet eine Taste oder meldet einen Kurzbefehl an. Die
Belegung wird mit libxkbcommon nur ausgerechnet.

Aufruf:

    cd backend
    d=$(mktemp -d)
    env XDG_CONFIG_HOME=$d XDG_DATA_HOME=$d ../.venv/bin/python tests/tastenkombination_test.py
"""
import _wache  # bricht ab, statt in die echte Config zu schreiben
_wache.sichere_umgebung()

import asyncio
import sys
from types import SimpleNamespace
from unittest import mock

from deckswitch.services import input as inp
from deckswitch.services import portal
from deckswitch.services import shortcuts as sc

FAILS = []


def check(n, c, d=""):
    print(("  ✔ " if c else "  ✘ ") + n + (f"  ({d})" if d else ""))
    if not c:
        FAILS.append(n)


print("Kombinationen zerlegen")
check("ctrl+shift+f5", inp.parse_combo("ctrl+shift+f5") == (["ctrl", "shift"], "f5"))
check("ctrl++ ist Strg und die Plus-Taste", inp.parse_combo("ctrl++") == (["ctrl"], "+"),
      str(inp.parse_combo("ctrl++")))
check("ctrl+plus ebenso", inp.parse_combo("ctrl+plus") == (["ctrl"], "+"))
check("strg + + mit Leerzeichen", inp.parse_combo("strg + +") == (["ctrl"], "+"))
check("ein Plus allein", inp.parse_combo("+") == ([], "+"))
check("ctrl+minus ist das Minus", inp.parse_combo("ctrl+minus") == (["ctrl"], "-"))
check("ctrl+- bleibt das Minus", inp.parse_combo("ctrl+-") == (["ctrl"], "-"))
check("ctrl+ ist unfertig, ohne Taste", inp.parse_combo("ctrl+") == (["ctrl"], ""))
check("ctrl+shift+plus", inp.parse_combo("ctrl+shift+plus") == (["ctrl", "shift"], "+"))

print("\nZeichen auf der deutschen Belegung")
try:
    de = inp._build_char_map("de", "")
    us = inp._build_char_map("us", "")
except Exception as exc:  # libxkbcommon fehlt
    de = us = None
    print(f"  (übersprungen: xkbcommon nicht nutzbar: {exc})")
if de is not None:
    # Kernel-Tastencodes: KEY_Y = 21, KEY_Z = 44.
    check("z liegt auf de dort, wo us ein Y hat", de["z"][0] == 21 and us["y"][0] == 21,
          f"de z={de['z']}, us y={us['y']}")
    check("y liegt auf de dort, wo us ein Z hat", de["y"][0] == 44)
    check("Plus ist auf de eine eigene Taste", de["+"] == (27, []), str(de["+"]))
    check("ß hat auf de eine Taste", de["ß"][0] == 12)

    dienst = inp.InputService()
    dienst._chars = de
    dienst._detected = ("de", "")
    dienst._layout_checked_at = 1e18
    code, mods = dienst._resolve_key("z")
    check("ctrl+z trifft auf de die Z-Taste", code == 21 and mods == [], f"{code} {mods}")
    code, mods = dienst._resolve_key(inp.parse_combo("ctrl++")[1])
    check("ctrl++ trifft auf de die Plus-Taste", code == 27, f"{code} {mods}")
    code, mods = dienst._resolve_key(inp.parse_combo("ctrl+plus")[1])
    check("ctrl+plus ebenso", code == 27)

print("\nKurzbefehle für Plasma (Qt-Tastencodes)")
check("ctrl+z ist Key_Z", sc.qt_keycode("ctrl+z") == 0x04000000 | 0x5A)
check("ctrl+ß ist Key_ssharp, kein Absturz", sc.qt_keycode("ctrl+ß") == 0x04000000 | 0xDF,
      hex(sc.qt_keycode("ctrl+ß")))
check("ctrl++ ist Key_Plus", sc.qt_keycode("ctrl++") == 0x04000000 | 0x2B)
check("ctrl+ö ist Key_Odiaeresis", sc.qt_keycode("ctrl+ö") == 0x04000000 | 0xD6)
try:
    sc.qt_keycode("ctrl+€")
    check("ein Zeichen ohne Qt-Code meldet sich verständlich", False)
except sc.ShortcutError:
    check("ein Zeichen ohne Qt-Code meldet sich verständlich", True)

print("\nPortal")
check("ctrl++ wird zu CTRL+plus", portal.trigger_aus_combo("ctrl++") == "CTRL+plus",
      portal.trigger_aus_combo("ctrl++"))
check("ctrl+z bleibt CTRL+z", portal.trigger_aus_combo("ctrl+z") == "CTRL+z")

print("\nEin Deck mit kaputter Kombination hält die anderen nicht auf")


class Deck(SimpleNamespace):
    pass


def deck(key, hotkey):
    return Deck(key=key, label=key,
                binding=SimpleNamespace(is_overlay=True, overlay_hotkey=hotkey))


async def lauf():
    runtime = SimpleNamespace(
        decks={"a": deck("a", "ctrl+alt+a"), "b": deck("b", "ctrl+alt+b"),
               "c": deck("c", "ctrl+alt+c")},
        session=None,
    )
    dienst = sc.ShortcutService(runtime)
    angemeldet = []

    async def anmelden(key, combo, name):
        if key == "b":
            raise TypeError("kaputt")
        angemeldet.append(key)
        dienst._angemeldet[key] = (combo, name)

    with mock.patch.object(dienst, "_connect", mock.AsyncMock(return_value=object())), \
         mock.patch.object(dienst, "_anmelden", anmelden):
        await dienst.sync()
    return dienst, angemeldet

dienst, angemeldet = asyncio.run(lauf())
check("die Decks nach dem kaputten werden angemeldet", angemeldet == ["a", "c"], str(angemeldet))
check("das kaputte hat einen Grund", "kaputt" in dienst.reason("b"), dienst.reason("b"))

print()
if FAILS:
    print(f"FEHLGESCHLAGEN ({len(FAILS)}): " + ", ".join(FAILS))
    sys.exit(1)
print("Alle Prüfungen bestanden.")
