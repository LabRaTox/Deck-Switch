"""Findet die App ihr Mitgeliefertes — im Checkout *und* installiert?

Plugins, Overlay-QML und die gebaute Oberfläche liegen im Repo in drei
verschiedenen Ordnern, als Paket dagegen gemeinsam unter
``/usr/share/deckswitch/``. Vor dem 2026-08-19 rechnete jede der vier
Fundstellen den Pfad selbst aus, jede mit einem eigenen ``parents[…]`` —
installiert zeigte davon keine mehr irgendwohin.

Der Installationsfall wird über ``DECKSWITCH_SHARE_DIR`` nachgestellt: Ein
Testlauf, der erst ein Paket bauen und einspielen muss, wird nie gemacht.

Aufruf (der zweite Teil startet ein eigenes Python, damit ``paths`` mit
gesetzter Variable frisch importiert wird):

    cd backend
    ../.venv/bin/python tests/paths_test.py
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

FAILS = []
WURZEL = Path(__file__).resolve().parents[2]


def check(name, condition, detail=""):
    mark = "✔" if condition else "✘"
    print(f"  {mark} {name}" + (f"  ({detail})" if detail else ""))
    if not condition:
        FAILS.append(name)


def im_unterprozess(share_dir: str | None) -> dict[str, str]:
    """Fragt ein frisches Python nach den aufgelösten Pfaden.

    Nötig, weil ``paths`` die Betriebsart beim Import einmal festlegt —
    innerhalb eines Prozesses lässt sie sich nicht mehr umstellen.
    """
    code = textwrap.dedent(
        """
        import json
        from deckswitch import paths
        print(json.dumps({
            "repo_root": str(paths.REPO_ROOT) if paths.REPO_ROOT else "",
            "plugins": str(paths.BUILTIN_PLUGINS_DIR),
            "overlay": str(paths.OVERLAY_QML),
            "gui": str(paths.GUI_DIST),
        }))
        """
    )
    umgebung = {"PATH": "/usr/bin:/bin", "HOME": str(Path.home())}
    if share_dir is not None:
        umgebung["DECKSWITCH_SHARE_DIR"] = share_dir
    ergebnis = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        cwd=str(WURZEL / "backend"),
        env=umgebung,
        check=True,
    )
    import json

    return json.loads(ergebnis.stdout)


def main() -> None:
    print("\nAus dem Checkout heraus")
    repo = im_unterprozess(None)
    check("das Repo wird erkannt", repo["repo_root"] == str(WURZEL), repo["repo_root"])
    check("die Plugins liegen im Repo",
          repo["plugins"] == str(WURZEL / "backend" / "plugins"))
    check("und sind auch wirklich da",
          (WURZEL / "backend" / "plugins" / "system" / "manifest.json").is_file())
    check("das Overlay-QML liegt im Repo",
          repo["overlay"] == str(WURZEL / "packaging" / "overlay" / "deck-overlay.qml"))
    check("und ist auch wirklich da", Path(repo["overlay"]).is_file())
    check("die Oberfläche liegt im Repo",
          repo["gui"] == str(WURZEL / "gui" / "dist"))

    print("\nAls Paket installiert (nachgestellt)")
    inst = im_unterprozess("/usr/share/deckswitch")
    check("kein Repo mehr", inst["repo_root"] == "", inst["repo_root"])
    check("Plugins unter /usr/share", inst["plugins"] == "/usr/share/deckswitch/plugins")
    check("Overlay unter /usr/share",
          inst["overlay"] == "/usr/share/deckswitch/overlay/deck-overlay.qml")
    check("Oberfläche unter /usr/share", inst["gui"] == "/usr/share/deckswitch/gui")

    print("\nNiemand rechnet mehr selbst")
    # Die vier Fundstellen von früher. Wer wieder eine einbaut, hebelt die
    # Installation aus, ohne dass es im Checkout auffiele.
    treffer = subprocess.run(
        ["grep", "-rn", "parents\\[", "--include=*.py", "deckswitch/"],
        capture_output=True, text=True, cwd=str(WURZEL / "backend"), check=False,
    ).stdout.strip().splitlines()
    erlaubt = [z for z in treffer if z.startswith("deckswitch/paths.py:")]
    check("'parents[…]' steht nur noch in paths.py",
          len(treffer) == len(erlaubt),
          "; ".join(z.split(":")[0] for z in treffer if z not in erlaubt) or "keine")

    print()
    if FAILS:
        print(f"FEHLGESCHLAGEN ({len(FAILS)}): " + ", ".join(FAILS))
        sys.exit(1)
    print("Alle Prüfungen bestanden.")


main()
