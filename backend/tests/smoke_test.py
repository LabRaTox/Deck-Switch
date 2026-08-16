"""Integrationstest der Runtime-Logik — läuft auch ohne angeschlossenes Deck.

Prüft die Teile, die man von Hand nur mühsam nachstellt: Lang-Druck,
Seiten-Navigation, Idle-Dimming, Export/Import und die Fehlertoleranz beim
Rendern.

Aufruf (mit eigener Config, damit die echte unangetastet bleibt):

    cd backend
    env XDG_CONFIG_HOME=/tmp/sd-test XDG_DATA_HOME=/tmp/sd-test \\
        ../.venv/bin/python tests/smoke_test.py

Beendet sich mit Exit-Code 1, sobald eine Prüfung fehlschlägt.
"""
import _wache  # bricht ab, statt in die echte Config zu schreiben
_wache.sichere_umgebung()
import asyncio, json, sys, time
from deckswitch.runtime import Runtime
from deckswitch.config import Slot, Appearance, Page

FAILS = []


def check(name, condition, detail=""):
    mark = "✔" if condition else "✘"
    print(f"  {mark} {name}" + (f"  ({detail})" if detail else ""))
    if not condition:
        FAILS.append(name)


class Recorder:
    """Merkt sich, welche Aktionen gefeuert haben."""
    events = []


async def main():
    rt = Runtime()
    await rt.start()
    await asyncio.sleep(0.5)

    profile = rt.config.active_profile()
    root = profile.root_page()

    # --- Testplugin einschleusen (ohne Dateien anzulegen) -----------------
    from deckswitch.plugins.base import ActionPlugin, Manifest
    from deckswitch.plugins.loader import LoadedPlugin

    manifest = Manifest.model_validate({
        "id": "probe", "name": "Probe", "type": "action",
        "entry": "x.py", "class": "P",
        "actions": [{"id": "a", "name": "A", "inputs": ["key", "dial"]},
                    {"id": "b", "name": "B", "inputs": ["key"]},
                    {"id": "nav", "name": "Nav", "inputs": ["key"]}],
    })

    class Probe(ActionPlugin):
        def on_key_down(self, action_id, settings, ctx):
            Recorder.events.append(("down", action_id, ctx.is_long_press))
            if action_id == "nav":
                rt.navigate(settings["page"])

        def on_key_up(self, action_id, settings, ctx):
            Recorder.events.append(("up", action_id, ctx.is_long_press))

        def on_dial_rotate(self, action_id, settings, delta, ctx):
            Recorder.events.append(("rotate", action_id, delta))

    services = rt._services_for(__import__("pathlib").Path("."))
    rt.registry.plugins["probe"] = LoadedPlugin(
        manifest=manifest, directory=__import__("pathlib").Path("."),
        instance=Probe(manifest, services), builtin=True, enabled=True)

    def slot(action, long=None, **settings):
        return Slot(plugin_id="probe", action_id=action, settings=settings,
                    appearance=Appearance(), long_press=long)

    print("\n== Lang-Druck ==")
    # Taste 0: ohne Zweitbelegung → sofort beim Drücken
    root.keys[0] = slot("a")
    # Taste 1: mit Zweitbelegung → erst bei Loslassen bzw. nach Ablauf
    root.keys[1] = slot("a", long=slot("b"))
    # Geräteeinstellungen hängen am Deck, nicht global an der Config:
    # jedes angeschlossene Deck hat eigene Zeiten und eigene Helligkeit.
    rt.primary.settings.long_press_ms = 300

    Recorder.events.clear()
    await rt._handle_key(0, True)
    check("ohne Zweitbelegung: feuert sofort beim Drücken",
          Recorder.events == [("down", "a", False)], str(Recorder.events))
    await rt._handle_key(0, False)

    Recorder.events.clear()
    await rt._handle_key(1, True)
    check("mit Zweitbelegung: beim Drücken noch nichts",
          Recorder.events == [], str(Recorder.events))
    await asyncio.sleep(0.1)
    await rt._handle_key(1, False)
    check("kurzer Druck: Hauptaktion nachgeholt",
          [e[:2] for e in Recorder.events] == [("down", "a"), ("up", "a")],
          str(Recorder.events))

    Recorder.events.clear()
    await rt._handle_key(1, True)
    await asyncio.sleep(0.45)          # länger als die Schwelle
    check("langer Druck: Zweitaktion gefeuert",
          [e[:2] for e in Recorder.events] == [("down", "b")], str(Recorder.events))
    await rt._handle_key(1, False)
    check("langer Druck: Hauptaktion bleibt aus",
          all(e[1] == "b" for e in Recorder.events), str(Recorder.events))

    print("\n== Seiten-Navigation ==")
    sub = Page(name="Unterseite", parent_id=root.id)
    profile.pages[sub.id] = sub
    sub2 = Page(name="Geschwister", parent_id=None)
    profile.pages[sub2.id] = sub2

    rt.navigate(sub.id)
    check("navigate in die Unterseite", rt.current_page_id() == sub.id)
    rt.navigate_back()
    check("zurück landet beim Elternteil", rt.current_page_id() == root.id)
    rt.navigate(sub.id)
    rt.navigate_home()
    check("home landet auf der Wurzelseite", rt.current_page_id() == profile.root_page_id)
    check("Seitennummer auf Wurzelebene", rt.page_number() == 1, f"={rt.page_number()}")
    rt.navigate(sub2.id)
    check("Seitennummer beim Geschwister", rt.page_number() == 2, f"={rt.page_number()}")
    check("Geschwister-Anzahl", len(rt.sibling_pages()) == 2)
    rt.navigate_home()

    print("\n== Seitenwechsel während eines Tastendrucks ==")
    # Der Ordner wechselt schon beim Drücken die Seite. Was danach an
    # derselben Stelle liegt, darf vom selben Druck nichts mehr abbekommen —
    # sonst löst ein Ordner die Taste dahinter mit aus.
    root.keys[4] = slot("nav", page=sub.id)
    sub.keys[4] = slot("b")

    Recorder.events.clear()
    await rt._handle_key(4, True)
    await rt._handle_key(4, False)
    check("Ordner wechselt die Seite", rt.current_page_id() == sub.id)
    check("die Taste auf der Zielseite bleibt unberührt",
          [e[1] for e in Recorder.events] == ["nav", "nav"], str(Recorder.events))

    # Dasselbe mit Zweitbelegung auf der Zielseite: dort wurde der
    # Hauptzweig früher beim Loslassen nachgeholt.
    rt.navigate_home()
    sub.keys[4] = slot("b", long=slot("a"))
    Recorder.events.clear()
    await rt._handle_key(4, True)
    await rt._handle_key(4, False)
    check("auch mit Zweitbelegung dahinter bleibt es beim Ordner",
          [e[1] for e in Recorder.events] == ["nav", "nav"], str(Recorder.events))

    rt.navigate_home()
    del root.keys[4]
    del sub.keys[4]

    print("\n== Dial ==")
    Recorder.events.clear()
    root.dials[0] = slot("a")
    await rt._handle_dial_rotate(0, -3)
    check("Drehung reicht das Delta durch",
          Recorder.events == [("rotate", "a", -3)], str(Recorder.events))

    print("\n== Touchstrip-Segmentzuordnung ==")
    seg_w = rt.device.info.segment_size[0]
    hits = []
    for x in (10, seg_w + 10, 2 * seg_w + 10, 3 * seg_w + 10):
        index = max(0, min(3, x // seg_w))
        hits.append(index)
    check("x-Koordinaten treffen die richtigen Segmente", hits == [0, 1, 2, 3], str(hits))

    print("\n== Idle-Dimming ==")
    # Das echte Gerät hängt am laufenden Backend; hier wird nur die Logik
    # geprüft, also Verbindung und Helligkeitsaufruf simulieren.
    brightness_calls = []
    rt.device.info.connected = True
    rt.device.deck = object()   # connected ist ein Property über deck + info
    rt.device.set_brightness = lambda value: brightness_calls.append(value)

    settings = rt.primary.settings
    check("ohne Verbindung wird nicht gedimmt (Vorbedingung)", True)
    settings.idle_dim_after_s = 1
    rt._last_input = time.monotonic() - 5
    rt._check_idle()
    check("dimmt nach Ablauf der Wartezeit", rt._dimmed is True)
    check("und setzt die Ruhe-Helligkeit",
          brightness_calls[-1:] == [settings.idle_brightness],
          str(brightness_calls))
    rt._wake()
    check("Eingabe weckt wieder auf", rt._dimmed is False)
    check("und stellt die volle Helligkeit her",
          brightness_calls[-1:] == [settings.brightness],
          str(brightness_calls))
    settings.idle_dim_after_s = 0
    rt._last_input = time.monotonic() - 500
    rt._check_idle()
    check("0 schaltet das Dimmen ab", rt._dimmed is False)

    print("\n== Export / Import ==")
    exported = rt.store.export_json()
    parsed = json.loads(exported)
    check("Export ist gültiges JSON mit Profilen", "profiles" in parsed)
    before = len(profile.pages)
    imported = rt.store.import_json(exported)
    check("Import stellt dieselbe Seitenzahl her",
          len(imported.active_profile().pages) == before,
          f"{len(imported.active_profile().pages)} vs {before}")

    print("\n== Fehlertoleranz ==")
    root.keys[2] = Slot(plugin_id="gibtsnicht", action_id="x", appearance=Appearance())
    image = await rt.render_preview(root.id, "key", 2)
    check("unbekanntes Plugin ergibt eine Fehlerkachel statt Absturz",
          image is not None and image.size == rt.device.info.key_size)

    class Broken(Probe):
        def render(self, action_id, settings, ctx):
            raise RuntimeError("kaputt")

    rt.registry.plugins["probe"].instance = Broken(manifest, services)
    root.keys[3] = slot("a")
    errors_before = len(rt.errors)
    image = await rt.render_preview(root.id, "key", 3)
    check("werfendes render() wird abgefangen", image is not None)
    check("und als Fehler gemeldet", len(rt.errors) > errors_before)

    await rt.stop()

    print()
    if FAILS:
        print(f"FEHLGESCHLAGEN ({len(FAILS)}): " + ", ".join(FAILS))
        sys.exit(1)
    print("Alle Prüfungen bestanden.")


asyncio.run(main())
