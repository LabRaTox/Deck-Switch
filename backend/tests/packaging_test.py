"""Hält das AUR-Paket am Projekt fest.

Ein `PKGBUILD` fällt erst beim Bauen auf die Nase, und gebaut wird selten.
Die häufigsten Fehler lassen sich aber ohne Bau finden: eine Datei wurde
umbenannt und die Rezeptzeile zeigt ins Leere, die Version steht nicht mehr
auf dem Stand des Programms, oder die beiden systemd-Units sind
auseinandergelaufen.

Aufruf (braucht keine Konfiguration, schreibt nichts):

    cd backend
    ../.venv/bin/python tests/packaging_test.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from deckswitch import __version__  # noqa: E402

WURZEL = Path(__file__).resolve().parents[2]
PKGBUILD = WURZEL / "packaging" / "aur" / "PKGBUILD"
FAILS = []


def check(name, condition, detail=""):
    mark = "✔" if condition else "✘"
    print(f"  {mark} {name}" + (f"  ({detail})" if detail else ""))
    if not condition:
        FAILS.append(name)


def feld(text: str, name: str) -> str:
    treffer = re.search(rf"^{name}=(.+)$", text, re.MULTILINE)
    return treffer.group(1).strip() if treffer else ""


def main() -> None:
    text = PKGBUILD.read_text(encoding="utf-8")

    print("\nVersion")
    check("pkgver stimmt mit __version__ überein",
          feld(text, "pkgver") == __version__,
          f"PKGBUILD: {feld(text, 'pkgver')}, Programm: {__version__}")
    check("das Paket zieht den passenden Tag",
          "refs/tags/v$pkgver.tar.gz" in text)

    print("\n.SRCINFO ist auf demselben Stand")
    # Das AUR liest die .SRCINFO, nicht das PKGBUILD. Wer nur das Rezept
    # anfasst und `makepkg --printsrcinfo` vergisst, veröffentlicht die
    # alte Version — ohne dass lokal etwas auffiele.
    srcinfo_datei = PKGBUILD.with_name(".SRCINFO")
    if not srcinfo_datei.is_file():
        check(".SRCINFO liegt neben dem PKGBUILD", False, "fehlt")
    else:
        srcinfo = srcinfo_datei.read_text(encoding="utf-8")
        check("pkgver stimmt", f"pkgver = {__version__}" in srcinfo)
        check("die Prüfsumme ist eingetragen",
              "sha256sums = SKIP" not in srcinfo,
              "steht noch auf SKIP" if "sha256sums = SKIP" in srcinfo else "")
        summe = feld(text, "sha256sums").strip("()'\"")
        check("und stimmt mit dem PKGBUILD überein", f"sha256sums = {summe}" in srcinfo)

    print("\nAlle verpackten Dateien gibt es auch")
    # Jede Datei, die das Rezept aus dem Quellbaum einsammelt. Kommentare
    # fliegen vorher raus, sonst prüfte man Fließtext; gesucht wird dann
    # stumpf nach allem, was wie ein Pfad im Projekt aussieht — auch auf
    # Fortsetzungszeilen, wo ein Ausdruck rund um `install` nichts findet.
    ohne_kommentare = "\n".join(
        z for z in text.splitlines() if not z.lstrip().startswith("#")
    )
    pfade = {
        p
        for p in re.findall(
            r"(?:backend|gui|packaging|docs)/[A-Za-z0-9._/-]+", ohne_kommentare
        )
        # `backend/dist` entsteht erst beim Bauen, `gui/src-tauri/target`
        # ebenso — beide gibt es im Quellbaum zu Recht nicht.
        if not p.startswith(("backend/dist", "gui/src-tauri/target"))
    }
    check("überhaupt Pfade gefunden", len(pfade) >= 8, f"{len(pfade)} Stück")
    for pfad in sorted(pfade):
        ziel = WURZEL / pfad
        check(f"{pfad}", ziel.exists())
    for extra in ("LICENSE", "README.md", "README.de.md", "docs"):
        check(f"{extra}", (WURZEL / extra).exists())

    print("\nDie beiden systemd-Units passen zusammen")
    checkout = (WURZEL / "packaging" / "deckswitch.service").read_text(encoding="utf-8")
    paket = (WURZEL / "packaging" / "deckswitch-system.service").read_text(encoding="utf-8")
    for zeile in ("After=", "PartOf=", "Restart=", "WantedBy="):
        a = [z for z in checkout.splitlines() if z.startswith(zeile)]
        b = [z for z in paket.splitlines() if z.startswith(zeile)]
        check(f"'{zeile}' ist in beiden gleich", a == b, f"{a} vs. {b}")
    check("die Paket-Unit ruft das installierte Programm",
          "ExecStart=/usr/bin/deckswitch" in paket)
    check("und schleppt keinen Repo-Platzhalter mit",
          "__REPO__" not in paket)

    print("\nDie Pfade des Pakets stimmen mit paths.py überein")
    # Was das Rezept ablegt, muss dort liegen, wo die App ohne Checkout sucht.
    for ordner in ("plugins", "gui", "overlay"):
        check(f"/usr/share/deckswitch/{ordner} wird gefüllt",
              f'"$pkgdir/usr/share/$pkgname/{ordner}' in text
              or f'"$pkgdir/usr/share/$pkgname"' in text and ordner == "plugins")
    check("die Unit landet dort, wo autostart.py sie erwartet",
          '"$pkgdir/usr/lib/systemd/user/deckswitch.service"' in text)

    print()
    if FAILS:
        print(f"FEHLGESCHLAGEN ({len(FAILS)}): " + ", ".join(FAILS))
        sys.exit(1)
    print("Alle Prüfungen bestanden.")


main()
