"""Prüft die Kette App → Store → App an einem echten Dienst.

Kein Attrappen-Store: Hier läuft der richtige, auf einem eigenen Port, gegen
die Entwicklungsdatenbank aus dem DevServer. Nur so lässt sich prüfen, was
zwischen den beiden Programmen wirklich passiert — die Prüfsumme, das Token,
die Mehrteil-Nachricht beim Hochladen.

Alles, was dieser Lauf anlegt, trägt einen eigenen Präfix und wird am Ende
wieder entfernt: Die Datenbank teilen wir uns mit den anderen Projekten.

Steht der Store nicht neben der App, überspringt sich die Suite mit einem
Hinweis. Ein Test, der bei einem fehlenden Nachbarprojekt rot wird, wird nach
dem dritten Mal ignoriert.

Aufruf (mit eigener Config, damit die echte unangetastet bleibt):

    cd backend
    d=$(mktemp -d); env XDG_CONFIG_HOME=$d XDG_DATA_HOME=$d \\
        ../.venv/bin/python tests/store_test.py
"""
import _wache  # bricht ab, statt in die echte Config zu schreiben
_wache.sichere_umgebung()

import base64
import hashlib
import json
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORE_PROJEKT = Path(__file__).resolve().parents[3] / "PlugInStore"

#: Alles, was dieser Lauf anlegt, beginnt damit.
PRAEFIX = "pruef-" + secrets.token_hex(3)

FAILS: list[str] = []


def check(name: str, bedingung: bool, detail: str = "") -> None:
    zeichen = "✔" if bedingung else "✘"
    print(f"  {zeichen} {name}" + (f"  ({detail})" if detail else ""))
    if not bedingung:
        FAILS.append(name)


def freier_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def warte_auf(url: str, sekunden: float = 60) -> bool:
    ende = time.monotonic() + sekunden
    while time.monotonic() < ende:
        try:
            with urllib.request.urlopen(url, timeout=2) as antwort:
                if antwort.status == 200:
                    return True
        except (urllib.error.URLError, OSError):
            time.sleep(0.3)
    return False


def store_umgebung() -> dict[str, str]:
    """Die Umgebung des Stores — DATABASE_URL aus seiner .env.local."""
    werte = dict(os.environ)
    datei = STORE_PROJEKT / ".env.local"
    for zeile in datei.read_text(encoding="utf-8").splitlines():
        zeile = zeile.strip()
        if not zeile or zeile.startswith("#") or "=" not in zeile:
            continue
        name, wert = zeile.split("=", 1)
        werte[name.strip()] = wert.strip().strip('"').strip("'")
    return werte


def node(skript: str, *argumente: str, umgebung: dict[str, str]) -> str:
    """Ein Hilfsskript des Stores ausführen und die Ausgabe zurückgeben."""
    lauf = subprocess.run(
        ["node", f"scripts/{skript}", *argumente],
        cwd=STORE_PROJEKT, env=umgebung, capture_output=True, text=True,
    )
    if lauf.returncode != 0:
        raise RuntimeError(f"{skript} fehlgeschlagen: {lauf.stderr.strip()}")
    return lauf.stdout.strip()


#: Ein gültiges 1×1-PNG — klein genug, um es hier stehen zu lassen.
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def baue_plugin(wurzel: Path, slug: str, version: str = "1.0.0") -> Path:
    ordner = wurzel / slug
    ordner.mkdir(parents=True, exist_ok=True)
    (ordner / "manifest.json").write_text(
        json.dumps({
            "id": slug,
            "name": slug.title(),
            "version": version,
            "type": "action",
            "entry": "plugin.py",
            "class": "TestPlugin",
            "description": "Nur zum Prüfen",
            "icon": "icon.png",
            # Zwei Einträge, von denen einer keiner ist: Der Katalog soll
            # das SVG aussortieren, nicht die App damit umgehen müssen.
            "screenshots": ["screenshots/deck.png", "boese.svg"],
        }),
        encoding="utf-8",
    )
    (ordner / "icon.png").write_bytes(PNG)
    (ordner / "screenshots").mkdir(exist_ok=True)
    (ordner / "screenshots" / "deck.png").write_bytes(PNG)
    (ordner / "boese.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
        encoding="utf-8",
    )
    (ordner / "plugin.py").write_text(
        "from deckswitch.plugins.base import ActionPlugin\n\n\n"
        "class TestPlugin(ActionPlugin):\n    pass\n",
        encoding="utf-8",
    )
    (ordner / "__pycache__").mkdir(exist_ok=True)
    (ordner / "__pycache__" / "alt.pyc").write_bytes(b"\x00")
    return ordner


def main() -> None:
    if not (STORE_PROJEKT / "src" / "app").is_dir():
        print(f"ÜBERSPRUNGEN: Der Store liegt nicht unter {STORE_PROJEKT}")
        return
    if not (STORE_PROJEKT / "node_modules").is_dir():
        print("ÜBERSPRUNGEN: Dem Store fehlen seine Pakete (npm install)")
        return
    if not (STORE_PROJEKT / ".env.local").is_file():
        print("ÜBERSPRUNGEN: Dem Store fehlt seine .env.local")
        return

    port = freier_port()
    umgebung = store_umgebung()

    with tempfile.TemporaryDirectory(prefix="store-e2e-") as tmp:
        umgebung["STORE_DATA_DIR"] = str(Path(tmp) / "storedaten")
        umgebung["STORE_BASE_URL"] = f"http://127.0.0.1:{port}"
        umgebung["NODE_ENV"] = "development"

        dienst = subprocess.Popen(
            ["npx", "next", "dev", "-p", str(port)],
            cwd=STORE_PROJEKT, env=umgebung,
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        )
        try:
            if not warte_auf(f"http://127.0.0.1:{port}/api/health"):
                fehler = (dienst.stderr.read() or b"").decode()[-2000:]
                print("ABBRUCH: Der Store ist nicht hochgekommen\n" + fehler)
                sys.exit(1)

            os.environ["DECKSWITCH_STORE_URL"] = f"http://127.0.0.1:{port}"
            from deckswitch.plugins import installer  # noqa: E402
            from deckswitch.services import store  # noqa: E402

            print("Ohne Anmeldung")
            check("niemand ist angemeldet", store.wer_bin_ich() is None)
            check("nichts wartet auf Prüfung", store.offene_pruefungen() is None)
            check("und Hochladen geht nicht",
                  _wirft(lambda: store.hochladen(b"x"), store.StoreError))

            autor = f"{PRAEFIX}-autor"
            token = node("test-account.mjs", autor, "member", umgebung=umgebung)
            store.schreib_token(token)

            print("\nAngemeldet")
            konto = store.wer_bin_ich()
            check("der Store kennt uns", konto and konto["handle"] == autor,
                  json.dumps(konto))
            check("das Token liegt nur für den Benutzer lesbar",
                  oct(store.TOKEN_DATEI.stat().st_mode)[-3:] == "600")
            check("ein gewöhnliches Konto sieht keine Warteschlange",
                  store.offene_pruefungen() is None)
            check("ein freier Name ist frei",
                  store.name_pruefen(f"{PRAEFIX}-neu")["frei"])
            check("ein reservierter nicht", not store.name_pruefen("system")["frei"])

            print("\nHochladen")
            slug = f"{PRAEFIX}-wetter"
            quelle = baue_plugin(Path(tmp) / "quelle", slug)
            archiv = store.packe(quelle)

            import io
            import zipfile
            namen = zipfile.ZipFile(io.BytesIO(archiv)).namelist()
            check("das Archiv trägt den Ordnernamen", f"{slug}/manifest.json" in namen)
            check("Übersetzungsreste bleiben draußen",
                  not any("__pycache__" in n for n in namen))

            antwort = store.hochladen(archiv, dateiname=f"{slug}.zip")
            check("angenommen", antwort["version"] == "1.0.0", json.dumps(antwort))
            check("und wartet auf Prüfung", antwort["status"] == "pending",
                  antwort["status"])
            check("dieselbe Fassung nicht zweimal",
                  _wirft(lambda: store.hochladen(archiv), store.StoreError))

            meine = store.meine_plugins()
            eigenes = next((p for p in meine["plugins"] if p["slug"] == slug), None)
            check("es steht in den eigenen Einreichungen", eigenes is not None)
            check("mit seinem Stand",
                  eigenes and eigenes["versions"][0]["status"] == "pending",
                  json.dumps(eigenes["versions"][0] if eigenes else None))
            check("und noch nicht im Katalog",
                  eigenes and eigenes["visibility"] == "draft")

            print("\nWer prüfen darf, erfährt davon")
            mod = f"{PRAEFIX}-mod"
            mod_token = node("test-account.mjs", mod, "moderator", umgebung=umgebung)
            store.schreib_token(mod_token)

            offen = store.offene_pruefungen()
            check("die Warteschlange wird gemeldet", offen is not None, json.dumps(offen))
            check("mit der Zahl der Einreichungen",
                  offen and offen["submissions"] >= 1, json.dumps(offen))
            check("und der Adresse der Verwaltung",
                  offen and offen["url"].endswith("/admin/queue"))

            print("\nInstallieren")
            # Von Hand freigeben — die Moderation über die Oberfläche zu
            # spielen ist Sache der Suiten im Store selbst.
            node("test-approve.mjs", slug, umgebung=umgebung)
            store.vergiss()

            katalog = store.katalog(q=slug)
            check("das Plugin steht im Katalog", katalog["count"] == 1,
                  str(katalog["count"]))

            eintrag = katalog["plugins"][0]
            check("und nennt die Adresse seines Symbols",
                  bool(eintrag["latest"].get("icon_url")),
                  str(eintrag["latest"].get("icon_url")))
            check("nur echte Bilder stehen als Screenshot dabei",
                  eintrag["latest"].get("screenshot_urls") == [
                      f"http://127.0.0.1:{port}/api/assets/{slug}/1.0.0/screenshots/deck.png"
                  ],
                  str(eintrag["latest"].get("screenshot_urls")))

            daten, typ = store.bild(slug, "1.0.0", "icon")
            check("das Symbol kommt als PNG herein", typ == "image/png", typ)
            check("und unverändert", daten == PNG)
            check("ein Screenshot ebenso",
                  store.bild(slug, "1.0.0", "screenshot", 0)[0] == PNG)
            check("nach einer Stelle, die es nicht gibt, wird nicht gefragt",
                  _wirft(lambda: store.bild(slug, "1.0.0", "screenshot", 7), store.StoreError))
            check("und keine Adresse außerhalb des Stores",
                  _wirft(lambda: store._hol_bild("http://fremde.example/icon.png"),
                         store.StoreError))

            ergebnis = store.installiere(slug)
            check("installiert", ergebnis["plugin_id"] == slug, json.dumps(ergebnis))
            from deckswitch import paths  # noqa: E402
            # Der Ordner heißt nach einer laufenden Nummer, nicht nach der
            # Kennung — gesucht wird deshalb über die Manifeste.
            gefunden = [
                ordner for ordner in paths.USER_PLUGINS_DIR.iterdir()
                if (ordner / "manifest.json").is_file()
                and json.loads((ordner / "manifest.json").read_text())["id"] == slug
            ]
            check("und liegt im Plugin-Verzeichnis", len(gefunden) == 1,
                  gefunden[0].name if gefunden else "nicht gefunden")
            check("die Prüfsumme stimmt mit der des Archivs überein",
                  ergebnis["sha256"] == hashlib.sha256(archiv).hexdigest())

            print("\nVersionen vergleichen")
            faelle = [
                ("1.0.1", "1.0.0", True), ("1.0.0", "1.0.1", False),
                ("1.0.0", "1.0.0", False),
                # Der Klassiker: zeichenweise wäre 1.10 kleiner als 1.9.
                ("1.10.0", "1.9.0", True), ("1.9.0", "1.10.0", False),
                ("1.1", "1.0.9", True), ("1.1", "1.1.0", False),
                ("2.0", "1.99.99", True),
                # Was keine Zahl ist, zählt als 0 — niemand soll aus Versehen
                # von einer Fassung auf eine Vorabfassung „aktualisieren".
                ("1.0.0-beta", "1.0.0", False),
            ]
            for neuer, alter, erwartet in faelle:
                check(f"{neuer} ist {'neuer' if erwartet else 'nicht neuer'} als {alter}",
                      store.neuer_als(neuer, alter) is erwartet,
                      str(store.neuer_als(neuer, alter)))
            check("1.10.2 wird zu (1, 10, 2)", store.als_zahlen("1.10.2") == (1, 10, 2),
                  str(store.als_zahlen("1.10.2")))

            print("\nBewerten")
            # Angemeldet ist gerade der Moderator; der Autor kommt gleich
            # als zweite Stimme dazu.
            leer = store.bewertung(slug)
            check("am Anfang hat niemand abgestimmt",
                  (leer["up"], leer["down"], leer["mine"]) == (0, 0, None),
                  json.dumps(leer))

            hoch = store.bewerte(slug, 1, "Läuft bei mir seit Tagen.")
            check("ein Daumen hoch zählt", hoch["up"] == 1, json.dumps(hoch))
            check("und gilt als die eigene Stimme", hoch["mine"] == 1)
            check("der Kommentar steht dabei",
                  hoch["comment"] == "Läuft bei mir seit Tagen.", str(hoch["comment"]))

            store.vergiss()
            im_katalog = store.katalog(q=slug)["plugins"][0]["rating"]
            check("der Katalog zeigt dieselbe Zahl", im_katalog["up"] == 1,
                  json.dumps(im_katalog))

            umentschieden = store.bewerte(slug, -1)
            check("eine zweite Stimme ersetzt die erste, statt sich zu addieren",
                  (umentschieden["up"], umentschieden["down"]) == (0, 1),
                  json.dumps(umentschieden))

            zurueckgezogen = store.bewertung_zuruecknehmen(slug)
            check("zurückziehen räumt sie weg",
                  (zurueckgezogen["up"], zurueckgezogen["down"], zurueckgezogen["mine"])
                  == (0, 0, None), json.dumps(zurueckgezogen))
            check("und ein zweites Mal ist kein Fehler",
                  store.bewertung_zuruecknehmen(slug)["mine"] is None)

            store.bewerte(slug, 1, "Von der Moderation.")
            store.schreib_token(token)
            zweite = store.bewerte(slug, 1, "Und vom Autor.")
            check("zwei Leute sind zwei Stimmen", zweite["up"] == 2, json.dumps(zweite))
            check("jeder sieht nur die eigene als seine", zweite["mine"] == 1)
            fremde = [k for k in zweite["comments"] if k["author"] != autor]
            check("der Kommentar des anderen ist zu lesen",
                  any(k["comment"] == "Von der Moderation." for k in fremde),
                  json.dumps(zweite["comments"]))

            check("etwas anderes als 1 oder -1 nimmt er nicht",
                  _wirft(lambda: store.bewerte(slug, 5), store.StoreError))

            store.schreib_token("")
            check("ohne Anmeldung lässt sich lesen",
                  store.bewertung(slug)["up"] == 2)
            check("aber nicht abstimmen",
                  _wirft(lambda: store.bewerte(slug, 1), store.StoreError))
            check("und die eigene Stimme ist dann keine",
                  store.bewertung(slug)["mine"] is None)
            store.schreib_token(mod_token)

            print("\nWenn unterwegs etwas ausgetauscht wird")
            # Die Datei im Store ersetzen, die Prüfsumme im Katalog stehen
            # lassen: genau der Fall, gegen den die Prüfung gedacht ist.
            abgelegt = Path(umgebung["STORE_DATA_DIR"]) / "plugins" / slug / "1.0.0.zip"
            abgelegt.write_bytes(archiv + b"\x00noch etwas")
            store.vergiss()
            check("die Installation bricht ab",
                  _wirft(lambda: store.installiere(slug), installer.ChecksumError))

            print("\nEine eigene Einreichung zurücknehmen")
            store.schreib_token(token)
            zurueck = store.zuruecknehmen(slug, "1.0.0")
            check("die freigegebene Fassung wird nur zurückgezogen",
                  zurueck["aktion"] == "zurueckgezogen", json.dumps(zurueck))
            store.vergiss()
            check("und fällt damit aus dem Katalog",
                  store.katalog(q=slug)["count"] == 0)
            check("ein zweites Mal geht nicht",
                  _wirft(lambda: store.zuruecknehmen(slug, "1.0.0"), store.StoreError))

            # Was noch niemand bekommen hat, verschwindet ganz — samt Nummer.
            # Genau das braucht, wer versehentlich einen halben Stand hochlädt.
            zweite = store.packe(baue_plugin(Path(tmp) / "zweite", slug, "1.1.0"))
            store.hochladen(zweite, dateiname=f"{slug}.zip")
            check("eine wartende Fassung verschwindet ganz",
                  store.zuruecknehmen(slug, "1.1.0")["aktion"] == "geloescht")
            check("und ihre Nummer ist wieder zu haben",
                  store.hochladen(zweite)["version"] == "1.1.0")

            store.schreib_token(mod_token)
            check("fremde Einreichungen gehen niemanden etwas an",
                  _wirft(lambda: store.zuruecknehmen(slug, "1.1.0"), store.StoreError))
            store.schreib_token(token)

            print("\nEine neue Fassung finden und einspielen")
            store.vergiss()
            check("mit der aktuellen Fassung gibt es nichts zu tun",
                  store.verfuegbare_updates({slug: "1.0.0"}) == [],
                  json.dumps(store.verfuegbare_updates({slug: "1.0.0"})))
            check("und für nicht installierte Plugins auch nicht",
                  store.verfuegbare_updates({}) == [])

            # Hochladen darf nur, wem das Plugin gehört — gerade ist die
            # Moderation angemeldet.
            zweite = baue_plugin(Path(tmp) / "zweite", slug, version="1.2.0")
            store.schreib_token(token)
            store.hochladen(store.packe(zweite), dateiname=f"{slug}.zip")
            store.schreib_token(mod_token)
            node("test-approve.mjs", slug, umgebung=umgebung)
            store.vergiss()

            gefunden = store.verfuegbare_updates({slug: "1.0.0"})
            check("die neue Fassung wird gefunden", len(gefunden) == 1,
                  json.dumps(gefunden))
            if gefunden:
                eintrag = gefunden[0]
                check("mit alter und neuer Nummer",
                      (eintrag["installed"], eintrag["available"]) == ("1.0.0", "1.2.0"),
                      json.dumps(eintrag))
                check("und sie lässt sich mit dieser App benutzen", eintrag["usable"])
            check("wer schon die neue hat, bekommt nichts angeboten",
                  store.verfuegbare_updates({slug: "1.2.0"}) == [])
            check("und wer eine noch neuere hat, erst recht nicht",
                  store.verfuegbare_updates({slug: "2.0.0"}) == [])

            ergebnis = store.installiere(slug)
            check("das Einspielen holt die neue Fassung",
                  ergebnis["version"] == "1.2.0", json.dumps(ergebnis))
            store.vergiss()
            check("danach ist nichts mehr offen",
                  store.verfuegbare_updates({slug: "1.2.0"}) == [])

            print("\nAbmelden")
            store.abmelden()
            check("das Token ist weg", store.lies_token() == "")
            check("und der Store hält uns für niemanden", store.wer_bin_ich() is None)

        finally:
            dienst.terminate()
            try:
                dienst.wait(timeout=15)
            except subprocess.TimeoutExpired:
                dienst.kill()
            try:
                print("\n" + node("test-cleanup.mjs", PRAEFIX, umgebung=umgebung))
            except Exception as exc:  # noqa: BLE001
                print(f"Aufräumen fehlgeschlagen: {exc}", file=sys.stderr)

    print()
    if FAILS:
        print(f"FEHLGESCHLAGEN ({len(FAILS)}): " + ", ".join(FAILS))
        sys.exit(1)
    print("Alle Prüfungen bestanden.")


def _wirft(arbeit, art: type[BaseException]) -> bool:
    try:
        arbeit()
    except art:
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"    (unerwartet: {type(exc).__name__}: {exc})")
        return False
    return False


main()
