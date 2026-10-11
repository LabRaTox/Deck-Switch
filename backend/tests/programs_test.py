"""Die Programmliste für die Profil-Automatik.

Gewählt wird aus der Liste der Name, den die Automatik mit der Fensterklasse
vergleicht — als Teilzeichenkette. Ein falscher Name ist deshalb schlimmer
als keiner: Aus scrcpy wurde bis zum 2026-10-11 ``sh``, und ``sh`` trifft
fast jedes Fenster. Alle Steam-Spiele hießen ``steam``, ein Flatpak
``flatpak``.

Aufruf (liest nur die Menüeinträge, die die Suite selbst anlegt):

    cd backend
    ../.venv/bin/python tests/programs_test.py
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from deckswitch.services import programs  # noqa: E402

FAILS = []


def check(name, condition, detail=""):
    mark = "✔" if condition else "✘"
    print(f"  {mark} {name}" + (f"  ({detail})" if detail else ""))
    if not condition:
        FAILS.append(name)


def eintrag(ordner: Path, datei: str, **felder: str) -> None:
    ordner.mkdir(parents=True, exist_ok=True)
    zeilen = ["[Desktop Entry]", "Type=Application"]
    zeilen += [f"{schluessel}={wert}" for schluessel, wert in felder.items()]
    (ordner / datei).write_text("\n".join(zeilen) + "\n", encoding="utf-8")


def main() -> int:
    print("\nProgrammname aus Exec=")
    faelle = [
        ("code %F", "code"),
        ("/usr/bin/obs", "obs"),
        ("env GDK_BACKEND=x11 /opt/foo/bar --flag", "bar"),
        ("/usr/bin/env -u FOO baz", "baz"),
        ("steam steam://rungameid/1669000", "steam_app_1669000"),
        ("/usr/bin/flatpak run --branch=stable --arch=x86_64 --command=LOOT "
         "io.github.loot.loot", "io.github.loot.loot"),
        ("/bin/sh -c \"\\$SHELL -i -c scrcpy\"", ""),
        ("bash /home/x/start.sh", ""),
        ("\"/opt/Mein Programm/prog\" %U", "prog"),
    ]
    for zeile, erwartet in faelle:
        ergebnis = programs._programm(zeile)
        check(f"{zeile!r} → {erwartet!r}", ergebnis == erwartet, repr(ergebnis))

    print("\nListe aus den Datenverzeichnissen")
    with tempfile.TemporaryDirectory() as tmp:
        heim = Path(tmp) / "home" / "applications"
        system = Path(tmp) / "usr" / "applications"
        eintrag(system, "code.desktop", Name="Visual Studio Code", Exec="code %F",
                StartupWMClass="com.example.Code")
        eintrag(system, "scrcpy.desktop", Name="scrcpy",
                Exec="/bin/sh -c \"\\$SHELL -i -c scrcpy\"")
        eintrag(system, "versteckt.desktop", Name="Versteckt", Exec="geheim")
        eintrag(heim, "versteckt.desktop", Name="Versteckt", Exec="geheim",
                NoDisplay="true")
        eintrag(heim, "Anno 1800.desktop", Name="Anno 1800",
                Exec="steam steam://rungameid/916440")
        eintrag(heim, "Age.desktop", Name="Age of Wonders 4",
                Exec="steam steam://rungameid/1669000")

        alt = {k: os.environ.get(k) for k in ("XDG_DATA_HOME", "XDG_DATA_DIRS")}
        os.environ["XDG_DATA_HOME"] = str(heim.parent)
        os.environ["XDG_DATA_DIRS"] = str(system.parent)
        try:
            liste = programs.list_applications()
        finally:
            for k, v in alt.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    namen = {e["name"]: e["exec"] for e in liste}
    check("StartupWMClass geht vor dem Befehl",
          namen.get("Visual Studio Code") == "com.example.Code", str(namen))
    check("ein Eintrag mit sh -c fällt weg", "scrcpy" not in namen, str(namen))
    check("die Benutzerdatei versteckt die gleichnamige Systemdatei",
          "Versteckt" not in namen, str(namen))
    check("zwei Steam-Spiele bleiben zwei verschiedene Namen",
          namen.get("Anno 1800") == "steam_app_916440"
          and namen.get("Age of Wonders 4") == "steam_app_1669000", str(namen))

    print()
    if FAILS:
        print(f"{len(FAILS)} Prüfung(en) fehlgeschlagen.")
        return 1
    print("Alle Prüfungen bestanden.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
