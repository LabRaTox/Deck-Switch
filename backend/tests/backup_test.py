"""Sicherung, Zeitreise und Profilaustausch — hält ein Paket, was es verspricht?

Geprüft wird gegen ein eigenes ``XDG_CONFIG_HOME``/``XDG_DATA_HOME`` in einem
Wegwerfordner. Ohne das schriebe der Test in die echte Konfiguration des
Benutzers — bei einem Test, dessen Zweck das Zurückspielen ganzer Zustände
ist, wäre das besonders unangenehm.

Aufruf:

    cd backend
    ../.venv/bin/python tests/backup_test.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import zipfile
from pathlib import Path

FAILS = []


def check(name, condition, detail=""):
    mark = "✔" if condition else "✘"
    print(f"  {mark} {name}" + (f"  ({detail})" if detail else ""))
    if not condition:
        FAILS.append(name)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="deckswitch-backup-test-") as tmp:
        wurzel = Path(tmp)
        os.environ["XDG_CONFIG_HOME"] = str(wurzel / "config")
        os.environ["XDG_DATA_HOME"] = str(wurzel / "data")

        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from deckswitch import paths  # noqa: E402  (erst nach den Variablen)
        from deckswitch.config import (  # noqa: E402
            Appearance,
            Background,
            ConfigStore,
            Page,
            Profile,
            Slot,
        )
        from deckswitch.services import backup  # noqa: E402

        paths.ensure_dirs()
        store = ConfigStore()
        store.load()

        # -- Ausgangslage: ein Profil mit einem Bild darin ------------------
        print("\nAusgangslage")
        bild = paths.UPLOADS_DIR / "logo-abcd1234.png"
        bild.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 64)
        streifen = paths.WALLPAPERS_DIR / "strip-99887766.png"
        streifen.write_bytes(b"\x89PNG\r\n\x1a\n" + b"1" * 64)

        # Eine Taste, deren Hintergrund auf das hochgeladene Bild zeigt —
        # genau die Verbindung, an der ein reiner JSON-Export scheitert.
        seite = Page(name="Start")
        seite.keys[0] = Slot(
            plugin_id="audio",
            action_id="mic_mute",
            appearance=Appearance(
                background=Background(kind="image", upload=bild.name)
            ),
        )
        profil = Profile(name="Streaming", root_page_id=seite.id,
                         pages={seite.id: seite})
        store.config.profiles[profil.id] = profil
        store.save()
        check("Profil mit Bildverweis angelegt", bild.name in json.dumps(
            profil.model_dump(mode="json")))

        # -- Sicherungspaket ------------------------------------------------
        print("\nSicherungspaket")
        paket = backup.make_archive(store)
        with zipfile.ZipFile(__import__("io").BytesIO(paket)) as zf:
            namen = set(zf.namelist())
        check("enthält die Konfiguration", "config.json" in namen)
        check("enthält ein Manifest", "manifest.json" in namen)
        check("enthält das hochgeladene Bild", f"uploads/{bild.name}" in namen)
        check("enthält den Streifen", f"wallpapers/{streifen.name}" in namen)
        check("enthält keine Plugins", not any(n.startswith("plugins/") for n in namen),
              "so entschieden: Plugins kommen über den Store zurück")

        # -- Wiederherstellen nach Verlust ----------------------------------
        print("\nWiederherstellen")
        bild.unlink()
        streifen.unlink()
        store.config.profiles.pop(profil.id)
        store.save()
        check("Ausgangslage zerstört", not bild.exists()
              and profil.id not in store.config.profiles)

        backup.restore_archive(paket, store)
        check("Bild ist zurück", bild.is_file())
        check("Streifen ist zurück", streifen.is_file())
        check("Profil ist zurück", profil.id in store.config.profiles)

        # -- Ein Paket, das ausbrechen will ---------------------------------
        print("\nEin Paket, das ausbrechen will")
        boese = wurzel / "boese.zip"
        with zipfile.ZipFile(boese, "w") as zf:
            zf.writestr("manifest.json", json.dumps(
                {"kind": backup.ARCHIVE_KIND, "format": 1}))
            zf.writestr("config.json", store.export_json())
            zf.writestr("uploads/../../../entkommen.png", b"\x89PNG\r\n\x1a\n")
            zf.writestr("uploads/harmlos.png", b"\x89PNG\r\n\x1a\n")
        backup.restore_archive(boese.read_bytes(), store)
        entkommen = wurzel / "entkommen.png"
        check("Pfad mit ../ landet nicht außerhalb", not entkommen.exists())
        check("und auch sonst nirgends oberhalb",
              not (wurzel.parent / "entkommen.png").exists())
        check("der harmlose Eintrag kam an", (paths.UPLOADS_DIR / "harmlos.png").is_file())
        check("der Ausbrecher liegt höchstens brav im Zielordner",
              not any(p.name == "entkommen.png" for p in wurzel.rglob("entkommen.png")
                      if paths.UPLOADS_DIR not in p.parents))

        # -- Fremde Pakete werden abgelehnt ---------------------------------
        print("\nFremde Pakete")
        for name, inhalt, erwartet in [
            ("keine ZIP-Datei", b"nur text", "keine lesbare ZIP"),
            ("ZIP ohne Manifest", None, "Kein Manifest"),
        ]:
            if inhalt is None:
                puffer = __import__("io").BytesIO()
                with zipfile.ZipFile(puffer, "w") as zf:
                    zf.writestr("irgendwas.txt", "hallo")
                inhalt = puffer.getvalue()
            try:
                backup.restore_archive(inhalt, store)
                check(f"{name} wird abgelehnt", False, "wurde angenommen")
            except backup.BackupError as exc:
                check(f"{name} wird abgelehnt", True, str(exc)[:40])

        # -- Aufräumen des Verlaufs -----------------------------------------
        print("\nAufräumen des Verlaufs")
        from deckswitch.config import (  # noqa: E402
            BACKUP_FULL_HOURS,
            BACKUP_MAX_AGE_DAYS,
        )

        # Ein Verlauf, wie er über Wochen entsteht: alle zwei Stunden ein
        # Stand, zwei Wochen weit zurück.
        paths.BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        for datei in paths.BACKUP_DIR.glob("config-*.json"):
            datei.unlink()
        jetzt = time.time()
        gebaut = 0
        for stunden in range(0, 14 * 24, 2):
            stempel = time.strftime("%Y%m%d-%H", time.localtime(jetzt - stunden * 3600))
            ziel = paths.BACKUP_DIR / f"config-{stempel}.json"
            if not ziel.exists():
                ziel.write_text(store.export_json(), encoding="utf-8")
                gebaut += 1
        check("Verlauf über zwei Wochen angelegt", gebaut > 100, f"{gebaut} Stände")

        ConfigStore._prune_backups()
        uebrig = sorted(paths.BACKUP_DIR.glob("config-*.json"))
        alter_tage = [
            (jetzt - time.mktime(time.strptime(d.stem.removeprefix("config-"), "%Y%m%d-%H")))
            / 86400
            for d in uebrig
        ]
        check("nichts älter als die Aufbewahrungsfrist",
              all(a <= BACKUP_MAX_AGE_DAYS + 0.05 for a in alter_tage),
              f"ältester {max(alter_tage):.1f} Tage")
        check("deutlich weniger Dateien als vorher",
              len(uebrig) < gebaut / 3, f"{gebaut} → {len(uebrig)}")

        frisch = [a for a in alter_tage if a * 24 <= BACKUP_FULL_HOURS]
        check("der letzte Tag bleibt feinstufig", len(frisch) >= 10,
              f"{len(frisch)} Stände in {BACKUP_FULL_HOURS} h")

        je_tag: dict[str, int] = {}
        for datei in uebrig:
            tag = datei.stem.removeprefix("config-").split("-")[0]
            je_tag[tag] = je_tag.get(tag, 0) + 1
        aeltere_tage = sorted(je_tag.items())[:-2]
        check("ältere Tage sind auf einen Stand ausgedünnt",
              all(anzahl == 1 for _, anzahl in aeltere_tage),
              ", ".join(f"{t}:{n}" for t, n in aeltere_tage) or "keine")

        # -- Zeitreise ------------------------------------------------------
        print("\nZeitreise")
        staende = backup.snapshots()
        check("es gibt automatische Stände", len(staende) >= 1, f"{len(staende)} Stück")
        if staende:
            zurueck = backup.restore_snapshot(staende[0].name, store)
            check("ein Stand lässt sich zurückspielen", zurueck is not None)
        for boeser_name in ("../config.json", "/etc/passwd", "beliebig.txt"):
            try:
                backup.restore_snapshot(boeser_name, store)
                check(f"'{boeser_name}' wird abgelehnt", False, "wurde angenommen")
            except backup.BackupError:
                check(f"'{boeser_name}' wird abgelehnt", True)

        # -- Profil weitergeben ---------------------------------------------
        # Die Zeitreise eben hat die Konfiguration auf einen Stand gesetzt,
        # in dem es das Profil noch nicht gab — also erst wieder vorwärts.
        # Nebenbei zeigt das, dass nach einem Rücksprung nichts klemmt.
        print("\nProfil weitergeben")
        backup.restore_archive(paket, store)
        check("nach der Zeitreise wieder vorwärts", profil.id in store.config.profiles)
        profilpaket = backup.export_profile(store, profil.id)
        with zipfile.ZipFile(__import__("io").BytesIO(profilpaket)) as zf:
            namen = set(zf.namelist())
        check("Profilpaket enthält das Profil", "profile.json" in namen)
        check("und das darin benutzte Bild", f"uploads/{bild.name}" in namen)
        check("aber nicht die ganze Konfiguration", "config.json" not in namen)
        check("und nicht den unbeteiligten Streifen",
              f"wallpapers/{streifen.name}" not in namen)

        vorher = len(store.config.profiles)
        neu = backup.import_profile(profilpaket, store)
        check("Import legt ein zusätzliches Profil an",
              len(store.config.profiles) == vorher + 1)
        check("mit neuer Kennung", neu.id != profil.id)
        check("und unterscheidbarem Namen", neu.name != profil.name,
              f"'{profil.name}' → '{neu.name}'")
        check("das Original bleibt unangetastet",
              store.config.profiles[profil.id].name == profil.name)

        try:
            backup.import_profile(backup.make_archive(store), store)
            check("eine Sicherung wird nicht als Profil angenommen", False)
        except backup.BackupError:
            check("eine Sicherung wird nicht als Profil angenommen", True)

    print()
    if FAILS:
        print(f"FEHLGESCHLAGEN ({len(FAILS)}): " + ", ".join(FAILS))
        return 1
    print("Alle Prüfungen bestanden.")
    return 0


sys.exit(main())
