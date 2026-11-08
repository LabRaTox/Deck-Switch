"""Prüft, was das System-Plugin aus der Ausgabe fremder Programme liest.

``ddcutil``, ``nvidia-smi`` und ``pgrep`` laufen hier nicht: An ihrer Stelle
steht eine Attrappe mit Ausgaben, wie sie die echten Programme liefern. So
bleiben Monitorhelligkeit und Prozesse unberührt, und Fälle wie ein
ungültiger Monitor oder ein ``[N/A]`` lassen sich gezielt nachstellen.

Aufruf:

    cd backend
    d=$(mktemp -d)
    env XDG_CONFIG_HOME=$d XDG_DATA_HOME=$d ../.venv/bin/python tests/system_plugin_test.py
"""
import _wache  # bricht ab, statt in die echte Config zu schreiben
_wache.sichere_umgebung()

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins"))

from system import ddc, sysinfo  # noqa: E402
from system import plugin as system_plugin  # noqa: E402

FAILS = []


def check(n, c, d=""):
    print(("  ✔ " if c else "  ✘ ") + n + (f"  ({d})" if d else ""))
    if not c:
        FAILS.append(n)


def antwort(stdout="", returncode=0, stderr=""):
    return SimpleNamespace(stdout=stdout, stderr=stderr, returncode=returncode)


# ==========================================================================
print("ddcutil detect")
MIT_UNGUELTIGEM = """Invalid display
   I2C bus:          /dev/i2c-1
   DRM connector:    card0-eDP-1
   Monitor:          BOE:0x0BCA:

Display 1
   I2C bus:          /dev/i2c-3
   DRM connector:    card1-HDMI-A-1
   Monitor:          HKC:24E4:0000000000001

Display 2
   I2C bus:          /dev/i2c-6
   DRM connector:    card1-DP-3
   Monitor:          PHL:27M2N3200:UK02438038402
"""
monitore = ddc.parse_detect(MIT_UNGUELTIGEM)
check("nur gültige Monitore zählen", [m.number for m in monitore] == [1, 2], str(monitore))
check("die Namen rutschen nicht", [m.label for m in monitore] == ["24E4", "27M2N3200"],
      str([m.label for m in monitore]))

OHNE_NAMEN = """Display 1
   I2C bus:          /dev/i2c-3

Display 3
   I2C bus:          /dev/i2c-5
   Monitor:          DEL:U2720Q:ABC
"""
monitore = ddc.parse_detect(OHNE_NAMEN)
check("ein Block ohne Monitor-Zeile bekommt einen Ersatznamen",
      [(m.number, m.label) for m in monitore] == [(1, "Monitor 1"), (3, "U2720Q")], str(monitore))
check("leere Ausgabe ergibt keine Monitore", ddc.parse_detect("") == [])

regler = ddc.DdcController()
regler._available = True
with mock.patch.object(ddc.subprocess, "run", return_value=antwort(MIT_UNGUELTIGEM)):
    gefunden = regler.displays(refresh=True)
check("displays() nutzt dieselbe Auswertung", [m.label for m in gefunden] == ["24E4", "27M2N3200"])

print("\nddcutil getvcp")
for ausgabe, erwartet in (
    ("VCP 10 C 50 100", 50),
    ("VCP 10 ERR", None),
    ("VCP 10 SNC x80", None),
    ("", None),
):
    regler = ddc.DdcController()
    regler._available = True
    with mock.patch.object(ddc.subprocess, "run", return_value=antwort(ausgabe)):
        wert = regler.read_brightness(1)
    check(f"{ausgabe or 'leer'!r} ergibt {erwartet}", wert == erwartet, str(wert))
    if erwartet is None:
        check("  mit Fehlermeldung", bool(regler.last_error), str(regler.last_error))

# ==========================================================================
print("\nnvidia-smi")
uhr = [1000.0]
zeit = mock.patch.object(sysinfo.time, "monotonic", lambda: uhr[0])
zeit.start()

info = sysinfo.SystemInfo()
with mock.patch.object(sysinfo.subprocess, "run",
                       side_effect=subprocess.TimeoutExpired("nvidia-smi", 4)):
    check("eine Zeitüberschreitung zeigt ---", info.gpu("temperature").text == "---")
aufrufe = []


def gut(*_a, **_k):
    aufrufe.append(1)
    return antwort("11, 50, 1741, 16376\n")


with mock.patch.object(sysinfo.subprocess, "run", side_effect=gut):
    uhr[0] += 2
    check("kurz danach wird nicht gleich wieder gefragt",
          info.gpu("temperature").text == "---" and not aufrufe, str(len(aufrufe)))
    uhr[0] += sysinfo.GPU_RETRY_S
    check("nach der Pause kommt der Wert wieder", info.gpu("temperature").text == "50 °C",
          info.gpu("temperature").text)
    check("Auslastung", info.gpu("utilization").text == "11 %")
    check("Speicher", info.gpu("memory").text == "1.7 GB", info.gpu("memory").text)

info = sysinfo.SystemInfo()
with mock.patch.object(sysinfo.subprocess, "run", return_value=antwort("[N/A], 45, 300, 4096")):
    check("ein [N/A] lässt die anderen Felder stehen", info.gpu("temperature").text == "45 °C",
          info.gpu("temperature").text)
    check("das [N/A]-Feld selbst zeigt ---", info.gpu("utilization").text == "---")
check("parse_gpu_line überspringt Unlesbares",
      sysinfo.parse_gpu_line(["a", "b", "c"], "1, [Not Supported], 3") == {"a": 1.0, "c": 3.0})

info = sysinfo.SystemInfo()
with mock.patch.object(sysinfo.subprocess, "run", return_value=antwort("", returncode=9)):
    check("ein Fehlercode zeigt ---", info.gpu("temperature").text == "---")
with mock.patch.object(sysinfo.subprocess, "run", return_value=antwort("1, 60, 1, 2")):
    uhr[0] += sysinfo.GPU_RETRY_S + 1
    check("und erholt sich danach", info.gpu("temperature").text == "60 °C")

info = sysinfo.SystemInfo()
with mock.patch.object(sysinfo.subprocess, "run", side_effect=FileNotFoundError("nvidia-smi")):
    info.gpu("temperature")
check("ohne nvidia-smi gilt die lange Pause",
      info._gpu_retry_at - uhr[0] >= sysinfo.GPU_RETRY_MAX_S, str(info._gpu_retry_at - uhr[0]))

print("\nDatenträger")
info = sysinfo.SystemInfo()
with mock.patch("shutil.disk_usage", return_value=SimpleNamespace(total=0, used=0, free=0)):
    try:
        lesung = info.disk_usage("/proc")
        check("Größe null ergibt --- statt Absturz", lesung.text == "---" and not lesung.available)
    except ZeroDivisionError:
        check("Größe null ergibt --- statt Absturz", False, "ZeroDivisionError")

print("\nTemperaturfühler")
info = sysinfo.SystemInfo()
with mock.patch.object(sysinfo.glob, "glob", return_value=[]):
    check("ohne Fühler ---", info.nvme_temp().text == "---")
gesucht = []


def glob_mit_fuehler(muster):
    gesucht.append(muster)
    return []


with mock.patch.object(sysinfo.glob, "glob", side_effect=glob_mit_fuehler):
    uhr[0] += 1
    info.nvme_temp()
    check("kurz danach wird nicht neu gesucht", not gesucht)
    uhr[0] += sysinfo.TEMP_REPROBE_S
    info.nvme_temp()
    check("nach einer Weile wird neu gesucht", bool(gesucht))

zeit.stop()

# ==========================================================================
print("\npgrep")
befehle = []


def pgrep(befehl, **_k):
    befehle.append(befehl)
    return antwort("", returncode=0)


with mock.patch.object(system_plugin.shutil, "which", return_value="/usr/bin/pgrep"), \
     mock.patch.object(system_plugin.subprocess, "run", side_effect=pgrep):
    system_plugin._is_running("signal-desktop-beta")
    system_plugin._is_running("c++filt")
check("lange Namen werden auf 15 Zeichen gekürzt", befehle[0][-1] == "signal-desktop-",
      str(befehle[0]))
check("Sonderzeichen werden wörtlich gesucht", befehle[1][-1] == r"c\+\+filt", str(befehle[1]))
check("weiter mit -x", all("-x" in b for b in befehle))

print()
if FAILS:
    print(f"FEHLGESCHLAGEN ({len(FAILS)}): " + ", ".join(FAILS))
    sys.exit(1)
print("Alle Prüfungen bestanden.")
