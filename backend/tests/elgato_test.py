"""Prüft die Brücke zu Elgato-Plugins an einem echten Plugin-Prozess.

Keine Attrappe: Es läuft ein Node-Prozess, der das Elgato-Protokoll spricht,
und es wird geprüft, was zwischen ihm und uns tatsächlich über den Draht
geht. Ohne node überspringt sich die Suite.

Das Prüf-Plugin liegt in ``tests/daten/elgato-pruef`` und ist nach Elgatos
Bauart gebaut: Manifest mit UUID und Actions, ``CodePath`` auf eine
JS-Datei, Anmeldung über die Startargumente.

Aufruf:

    cd backend
    d=$(mktemp -d); env XDG_CONFIG_HOME=$d XDG_DATA_HOME=$d \\
        ../.venv/bin/python tests/elgato_test.py
"""
import _wache  # bricht ab, statt in die echte Config zu schreiben
_wache.sichere_umgebung()

import asyncio
import json
import pathlib
import shutil
import sys
import tempfile
import zipfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from deckswitch.config import Appearance, Slot, default_config  # noqa: E402
from deckswitch.plugins import elgato  # noqa: E402
from deckswitch.plugins.base import Manifest, Services, SlotContext  # noqa: E402
from deckswitch.services.icons import IconService  # noqa: E402
from deckswitch.services.render import RenderService  # noqa: E402

QUELLE = pathlib.Path(__file__).resolve().parent / "daten" / "elgato-pruef"

FAILS = []


def check(name, bedingung, detail=""):
    print(("  ✔ " if bedingung else "  ✘ ") + name + (f"  ({detail})" if detail else ""))
    if not bedingung:
        FAILS.append(name)


class FakeRuntime:
    registry = None
    _loop = None

    def __init__(self):
        self.neuzeichnungen = 0
        self.gespeichert = 0

    def request_redraw(self, ctx=None):
        self.neuzeichnungen += 1

    def save_config(self):
        self.gespeichert += 1

    def notify(self, *a, **k):
        pass


def archiv(ziel: pathlib.Path) -> bytes:
    """Packt das Prüf-Plugin so, wie Elgato es ausliefert."""
    datei = ziel / "pruef.streamDeckPlugin"
    with zipfile.ZipFile(datei, "w", zipfile.ZIP_DEFLATED) as z:
        for pfad in sorted(QUELLE.rglob("*")):
            if pfad.is_file():
                z.write(pfad, f"de.labratox.pruef.sdPlugin/{pfad.relative_to(QUELLE)}")
    return datei.read_bytes()


async def main() -> int:
    if not shutil.which("node"):
        print("ÜBERSPRUNGEN: node ist nicht installiert")
        return 0
    if not QUELLE.is_dir():
        print(f"ÜBERSPRUNGEN: Prüfplugin fehlt ({QUELLE})")
        return 0

    with tempfile.TemporaryDirectory(prefix="elgato-test-") as tmp:
        arbeit = pathlib.Path(tmp)
        daten = archiv(arbeit)

        print("== Erkennen ==")
        check("ein Elgato-Archiv wird erkannt", elgato.ist_elgato_archiv(daten))
        check("am Dateinamen ebenso",
              elgato.ist_elgato_archiv(b"kein zip", "irgendwas.streamDeckPlugin"))
        check("ein gewöhnliches ZIP nicht",
              not elgato.ist_elgato_archiv(_leeres_zip()))

        print("\n== Einlesen ==")
        ordner = arbeit / "installiert"
        manifest_dict = elgato.lies_ein(daten, ordner)
        check("unser Manifest entsteht", (ordner / "manifest.json").is_file())
        check("der fremde Ordner liegt daneben",
              (ordner / "sdPlugin" / "plugin.js").is_file())
        check("die Zwischenebene ist abgeschnitten",
              not (ordner / "sdPlugin" / "de.labratox.pruef.sdPlugin").exists())
        check("Kennung übernommen", manifest_dict["id"] == "de.labratox.pruef",
              manifest_dict["id"])
        check("Name übernommen", manifest_dict["name"] == "Prüfzähler")
        check("Autor übernommen", manifest_dict["author"] == "LabRaTox")
        check("eine Aktion", len(manifest_dict["actions"]) == 1)

        aktion = manifest_dict["actions"][0]
        check("Aktion trägt ihre UUID", aktion["id"] == "de.labratox.pruef.zaehler")
        check("Keypad und Encoder werden zu key und dial",
              sorted(aktion["inputs"]) == ["dial", "key"], str(aktion["inputs"]))
        check("zwei Zustände", len(aktion["states"]) == 2)
        check("das Symbol zeigt auf eine wirklich vorhandene Datei",
              manifest_dict["icon"] and (ordner / manifest_dict["icon"]).is_file(),
              str(manifest_dict["icon"]))

        print("\n== Ein echter Plugin-Prozess ==")
        manifest = Manifest.model_validate(manifest_dict)
        icons = IconService()
        runtime = FakeRuntime()
        dienste = Services(
            audio=None, icons=icons, render=RenderService(icons), runtime=runtime,
            config=default_config(), plugin_dir=ordner,
        )
        plugin = elgato.ElgatoPlugin(manifest, dienste)

        await plugin.setup()
        try:
            await asyncio.wait_for(plugin.bruecke.bereit.wait(), timeout=20)
            angemeldet = True
        except asyncio.TimeoutError:
            angemeldet = False
        check("das Plugin meldet sich an", angemeldet, plugin.fehler or "")
        if not angemeldet:
            await plugin.teardown()
            return 1

        check("der Status meldet verbunden",
              (plugin.get_status() or {}).get("connected") is True,
              json.dumps(plugin.get_status()))

        st = {}
        ap = Appearance()
        slot = Slot(plugin_id=manifest.id, action_id=aktion["id"], settings=st, appearance=ap)
        ctx = SlotContext(
            action_id=aktion["id"], settings=st, appearance=ap, input_type="key",
            index=0, page_id="p", profile_id="pr", size=(120, 120),
            services=dienste, slot=slot,
        )

        # willAppear kommt beim ersten Tick, danach beantwortet das Plugin es
        # mit einem Titel.
        await plugin.on_tick(aktion["id"], st, ctx)
        await _warte_auf(lambda: plugin._titel.get(ctx.key) == "bereit")
        check("willAppear kommt an und wird beantwortet",
              plugin._titel.get(ctx.key) == "bereit", str(plugin._titel))

        print("\n== Tastendruck ==")
        await plugin.on_key_down(aktion["id"], st, ctx)
        await _warte_auf(lambda: plugin._titel.get(ctx.key) == "1")
        check("setTitle landet als Beschriftung",
              plugin.get_label(aktion["id"], st, ctx) == "1",
              str(plugin.get_label(aktion["id"], st, ctx)))
        check("setImage wird zu einem Bild",
              plugin._bilder.get(ctx.key) is not None
              and plugin._bilder[ctx.key].size == (2, 2),
              str(plugin._bilder.get(ctx.key)))
        check("setState merkt sich den Zustand", plugin._zustaende.get(ctx.key) == 1)
        check("setSettings landet in der Belegung",
              slot.settings.get("elgato") == {"drucke": 1}, json.dumps(slot.settings))
        check("showOk hinterlässt eine Rückmeldung", ctx.key in plugin._meldungen)

        bild = plugin.render(aktion["id"], st, ctx)
        check("die Kachel wird gezeichnet", bild.size == (120, 120), str(bild.size))

        print("\n== Dial ==")
        dial_slot = Slot(plugin_id=manifest.id, action_id=aktion["id"], settings={}, appearance=ap)
        dial = SlotContext(
            action_id=aktion["id"], settings={}, appearance=ap, input_type="dial",
            index=1, page_id="p", profile_id="pr", size=(200, 100),
            services=dienste, slot=dial_slot,
        )
        await plugin.on_dial_rotate(aktion["id"], {}, 3, dial)
        await _warte_auf(lambda: (plugin._titel.get(dial.key) or "").startswith("Dial"))
        check("dialRotate reicht die Schritte weiter",
              plugin._titel.get(dial.key) == "Dial 3", str(plugin._titel.get(dial.key)))
        check("das Segment wird gezeichnet",
              plugin.render(aktion["id"], {}, dial).size == (200, 100))

        await _warte_auf(lambda: plugin._anzeige.get(dial.key))
        anzeige = plugin._anzeige.get(dial.key) or {}
        check("setFeedback kommt an",
              anzeige.get("value") == "3" and anzeige.get("title") == "Zähler",
              json.dumps(anzeige))
        layout = plugin._layout_fuer(aktion["id"], dial)
        check("das Layout des Plugins wird gelesen",
              layout is not None and layout.get("id") == "layouts/zaehler.json",
              str(layout and layout.get("id")))
        check("es hat drei Bestandteile", len((layout or {}).get("items") or []) == 3)

        segment = plugin.render(aktion["id"], {}, dial)
        check("die Anzeige wird gezeichnet", segment.size == (200, 100))
        # Der Balken steht bei 30 %: links gefüllt, rechts leer. Gemessen
        # statt geglaubt — sonst wäre nur bewiesen, dass etwas gemalt wurde.
        links = segment.convert("RGB").getpixel((25, 66))
        rechts = segment.convert("RGB").getpixel((175, 66))
        check("der Pegel steht bei 30 %", links != rechts and max(links) > max(rechts),
              f"links {links}, rechts {rechts}")

        await plugin.vom_plugin("setFeedbackLayout",
                                {"context": dial.key, "payload": {"layout": "$A0"}})
        check("das Plugin kann das Layout wechseln",
              (plugin._layout_fuer(aktion["id"], dial) or {}).get("items")
              == elgato.EINGEBAUTE_LAYOUTS["$A0"]["items"])

        # Elgatos Schema beschreibt jede der sechs Anordnungen in einem Satz.
        # Geprüft wird, dass unsere daraus gebaut sind — nicht die Pixel,
        # sondern was worin steht.
        soll = {
            "$X1": ["title:text", "icon:pixmap"],
            "$A0": ["title:text", "canvas:pixmap"],
            "$A1": ["title:text", "icon:pixmap", "value:text"],
            "$B1": ["title:text", "icon:pixmap", "value:text", "indicator:bar"],
            "$B2": ["title:text", "icon:pixmap", "value:text", "indicator:gbar"],
            "$C1": ["title:text", "icon1:pixmap", "indicator1:bar",
                    "icon2:pixmap", "indicator2:bar"],
        }
        for name, teile in soll.items():
            ist = [f"{i['key']}:{i['type']}" for i in elgato.EINGEBAUTE_LAYOUTS[name]["items"]]
            check(f"{name} ist gebaut wie beschrieben", ist == teile, str(ist))
        check("alle liegen im Raum eines Segments",
              all(0 <= i["rect"][0] and i["rect"][0] + i["rect"][2] <= 200
                  and 0 <= i["rect"][1] and i["rect"][1] + i["rect"][3] <= 100
                  for layout in elgato.EINGEBAUTE_LAYOUTS.values()
                  for i in layout["items"]))

        print("\n== Einstellungsseite ==")
        check("die Aktion nennt ihre Seite",
              aktion.get("property_inspector") == "ui/einstellungen.html",
              str(aktion.get("property_inspector")))

        anschluss = plugin.anschluss(ctx.key, aktion["id"])
        check("der Anschluss nennt den Port der Brücke",
              f'"port": {plugin.bruecke.port}' in anschluss, anschluss[:80])
        check("und die Belegung", f'"uuid": "{ctx.key}"' in anschluss)
        check("er versucht beide Namen der Funktion",
              "connectElgatoStreamDeckSocket" in anschluss and "connectSocket" in anschluss)

        import websockets
        async with websockets.connect(f"ws://127.0.0.1:{plugin.bruecke.port}") as seite:
            await seite.send(json.dumps({
                "event": "registerPropertyInspector", "uuid": ctx.key}))

            erste = json.loads(await asyncio.wait_for(seite.recv(), timeout=10))
            check("die Seite bekommt ungefragt den Stand",
                  erste.get("event") == "didReceiveSettings", json.dumps(erste)[:120])
            check("mit den gespeicherten Werten",
                  erste["payload"]["settings"] == {"drucke": 1},
                  json.dumps(erste["payload"]))

            await _warte_auf(lambda: plugin._titel.get(ctx.key) == "PI offen")
            check("das Plugin erfährt vom Öffnen",
                  plugin._titel.get(ctx.key) == "PI offen", str(plugin._titel.get(ctx.key)))

            await seite.send(json.dumps({
                "event": "setSettings", "context": ctx.key, "payload": {"ton": 42}}))
            antwort = json.loads(await asyncio.wait_for(seite.recv(), timeout=10))
            check("Speichern wird der Seite bestätigt",
                  antwort.get("event") == "didReceiveSettings"
                  and antwort["payload"]["settings"] == {"ton": 42},
                  json.dumps(antwort)[:140])
            check("und landet in der Belegung",
                  slot.settings.get("elgato") == {"ton": 42}, json.dumps(slot.settings))
            check("die Konfiguration wird geschrieben", runtime.gespeichert > 0,
                  str(runtime.gespeichert))
            await _warte_auf(lambda: (plugin._titel.get(ctx.key) or "").startswith("S:"))
            check("auch das Plugin erfährt davon",
                  plugin._titel.get(ctx.key) == 'S:{"ton":42}',
                  str(plugin._titel.get(ctx.key)))

            await seite.send(json.dumps({
                "event": "sendToPlugin", "context": ctx.key, "payload": {"frage": "wer"}}))
            echo = json.loads(await asyncio.wait_for(seite.recv(), timeout=10))
            check("die Seite kann mit dem Plugin reden",
                  echo.get("event") == "sendToPropertyInspector"
                  and echo["payload"]["echo"] == {"frage": "wer"},
                  json.dumps(echo)[:140])

        await _warte_auf(lambda: ctx.key not in plugin.bruecke.inspektoren)
        check("beim Schließen wird die Seite vergessen",
              ctx.key not in plugin.bruecke.inspektoren)

        print("\n== Abbau ==")
        prozess = plugin.bruecke._prozess
        await plugin.teardown()
        check("der Prozess ist beendet", prozess is not None and prozess.returncode is not None,
              str(prozess.returncode if prozess else None))

        await _pruefe_html(arbeit)
        _pruefe_windows(arbeit)

    print()
    if FAILS:
        print(f"FEHLGESCHLAGEN: {len(FAILS)} — {', '.join(FAILS)}")
        return 1
    print("Alle Prüfungen bestanden.")
    return 0


async def _pruefe_html(arbeit: pathlib.Path) -> None:
    """Dieselbe Brücke, aber das Plugin ist eine Seite im Browser.

    Übersprungen, wenn kein Chromium da ist — auf einem Rechner ohne Browser
    ist das kein Fehler, sondern eine fehlende Zutat.
    """
    from deckswitch.plugins.elgato import _browser

    print("\n== Ein Plugin, das im Browser läuft ==")
    if _browser() is None:
        print("  – übersprungen: kein Chromium gefunden")
        return

    quelle = pathlib.Path(__file__).resolve().parent / "daten" / "elgato-html"
    archiv_datei = arbeit / "html.streamDeckPlugin"
    with zipfile.ZipFile(archiv_datei, "w", zipfile.ZIP_DEFLATED) as z:
        for pfad in sorted(quelle.rglob("*")):
            if pfad.is_file():
                z.write(pfad, f"de.labratox.pruefseite.sdPlugin/{pfad.relative_to(quelle)}")

    ordner = arbeit / "html-installiert"
    manifest_dict = elgato.lies_ein(archiv_datei.read_bytes(), ordner)
    check("die Kennung kommt aus dem Ordnernamen",
          manifest_dict["id"] == "de.labratox.pruefseite", manifest_dict["id"])
    check("die Art ist erkannt",
          elgato.art_des_plugins(json.loads(
              (ordner / "sdPlugin" / "manifest.json").read_text())) == "html")

    icons = IconService()
    runtime = FakeRuntime()
    dienste = Services(audio=None, icons=icons, render=RenderService(icons), runtime=runtime,
                       config=default_config(), plugin_dir=ordner)
    plugin = elgato.ElgatoPlugin(Manifest.model_validate(manifest_dict), dienste)
    await plugin.setup()
    try:
        try:
            await asyncio.wait_for(plugin.bruecke.bereit.wait(), timeout=45)
            angemeldet = True
        except asyncio.TimeoutError:
            angemeldet = False
        check("die Seite meldet sich an", angemeldet, plugin.fehler or "")
        if not angemeldet:
            return

        check("sie bekam ein eigenes Browserprofil",
              plugin.bruecke._profil is not None and plugin.bruecke._profil.is_dir())

        aktion = manifest_dict["actions"][0]
        st, ap = {}, Appearance()
        slot = Slot(plugin_id=manifest_dict["id"], action_id=aktion["id"],
                    settings=st, appearance=ap)
        ctx = SlotContext(action_id=aktion["id"], settings=st, appearance=ap, input_type="key",
                          index=0, page_id="p", profile_id="pr", size=(120, 120),
                          services=dienste, slot=slot)
        await plugin.on_tick(aktion["id"], st, ctx)
        await _warte_auf(lambda: plugin._titel.get(ctx.key) == "aus dem Browser", timeout=20)
        check("willAppear erreicht die Seite",
              plugin._titel.get(ctx.key) == "aus dem Browser", str(plugin._titel))

        await plugin.on_key_down(aktion["id"], st, ctx)
        await _warte_auf(lambda: plugin._bilder.get(ctx.key) is not None, timeout=20)
        bild = plugin._bilder.get(ctx.key)
        check("die Seite malt ein Bild und schickt es", bild is not None and bild.size == (72, 72),
              str(bild))
        if bild is not None:
            check("es ist wirklich ihr Bild", bild.convert("RGB").getpixel((36, 36)) == (255, 255, 255)
                  and bild.convert("RGB").getpixel((4, 4)) == (29, 78, 216),
                  f"Mitte {bild.convert('RGB').getpixel((36, 36))}, Ecke {bild.convert('RGB').getpixel((4, 4))}")
    finally:
        profil = plugin.bruecke._profil
        await plugin.teardown()
        check("das Browserprofil wird wieder abgeräumt",
              profil is None or not profil.exists(), str(profil))


def _pruefe_windows(arbeit: pathlib.Path) -> None:
    """Der Weg für Windows-Binärdateien.

    Ein echtes .NET-Plugin läuft hier nicht mit: Es bräuchte eine
    Windows-Laufzeit im Wine-Prefix, und die lädt keine Prüfsuite herunter.
    Geprüft wird deshalb, was ohne sie prüfbar ist — der Startbefehl und die
    Umgebung. Beides ist genau das, woran es zweimal gescheitert war.
    """
    print("\n== Ein Plugin für Windows ==")
    elgato_manifest = {
        "Name": "Windows-Plugin", "Version": "1.0", "CodePath": "plugin.exe",
        "OS": [{"Platform": "windows", "MinimumVersion": "10"}],
        "Actions": [{"Name": "A", "UUID": "de.labratox.win.a"}],
    }
    check("die Art wird erkannt", elgato.art_des_plugins(elgato_manifest) == "windows")

    ordner = arbeit / "win"
    (ordner).mkdir(exist_ok=True)
    (ordner / "plugin.exe").write_bytes(b"MZ")
    if not shutil.which("wine"):
        print("  – Rest übersprungen: wine ist nicht installiert")
        return

    befehl = elgato.startbefehl(ordner, elgato_manifest)
    check("gestartet wird über wine", befehl[0].endswith("wine"), befehl[0])
    check("mit der Datei aus dem Plugin", befehl[-1].endswith("plugin.exe"), befehl[-1])

    class Leer:
        pass

    bruecke = elgato.Bruecke(Leer(), ordner, elgato_manifest, kennung="de.labratox.win")
    umgebung = bruecke._umgebung("windows")
    check("die Windows-Umgebung liegt bei uns",
          umgebung.get("WINEPREFIX", "").endswith("/deckswitch/wine"),
          umgebung.get("WINEPREFIX", ""))
    check("und .NET rechnet mit NLS statt ICU",
          umgebung.get("DOTNET_SYSTEM_GLOBALIZATION_USENLS") == "1")
    check("die gemeldete Plattform ist windows", bruecke._plattform() == "windows")
    check("und steht auch in den Anmeldedaten",
          bruecke._info()["application"]["platform"] == "windows")
    check("ein Plugin für den Mac bekommt mac genannt",
          elgato.Bruecke(Leer(), ordner, {"CodePath": "x.js", "Nodejs": {},
                                          "OS": [{"Platform": "mac"}]})._plattform() == "mac")


def _leeres_zip() -> bytes:
    import io
    puffer = io.BytesIO()
    with zipfile.ZipFile(puffer, "w") as z:
        z.writestr("manifest.json", "{}")
    return puffer.getvalue()


async def _warte_auf(bedingung, timeout: float = 10.0) -> None:
    """Wartet, bis eine Antwort des Plugins da ist — es antwortet nebenläufig."""
    ende = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < ende:
        if bedingung():
            return
        await asyncio.sleep(0.05)


sys.exit(asyncio.run(main()))
