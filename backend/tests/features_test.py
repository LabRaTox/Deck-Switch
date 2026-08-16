"""Prüft die Funktionen, die mit Elgatos Umfang gleichziehen sollten.

Abgedeckt sind die Dinge, die man von Hand nur mühsam nachstellt:
Tastenlogik (Druck, Doppeldruck, Halten), Multi-Aktionen samt Umschalter
und Schleife, der Dial-Stack, mehrere Decks nebeneinander sowie die
Erweiterungen am Aussehen (Schriftschnitt, Hintergrundbild, Animation).

Aufruf (mit eigener Config, damit die echte unangetastet bleibt):

    cd backend
    env XDG_CONFIG_HOME=/tmp/sd-test XDG_DATA_HOME=/tmp/sd-test \\
        ../.venv/bin/python tests/features_test.py

Beendet sich mit Exit-Code 1, sobald eine Prüfung fehlschlägt.
"""
import _wache  # bricht ab, statt in die echte Config zu schreiben
_wache.sichere_umgebung()
import asyncio
import sys
from pathlib import Path

from PIL import Image

from deckswitch.config import Appearance, Background, DeckBinding, IconRef, Page, Slot, Step
from deckswitch.plugins.base import ActionPlugin, Manifest
from deckswitch.plugins.loader import LoadedPlugin
from deckswitch.runtime import Runtime

FAILS = []


def check(name, condition, detail=""):
    mark = "✔" if condition else "✘"
    print(f"  {mark} {name}" + (f"  ({detail})" if detail else ""))
    if not condition:
        FAILS.append(name)


class Recorder:
    events = []


MANIFEST = Manifest.model_validate(
    {
        "id": "probe",
        "name": "Probe",
        "type": "action",
        "entry": "x.py",
        "class": "P",
        "actions": [
            {"id": "a", "name": "A", "inputs": ["key", "dial"]},
            {"id": "b", "name": "B", "inputs": ["key", "dial"]},
            {"id": "c", "name": "C", "inputs": ["key", "dial"]},
        ],
    }
)


class Probe(ActionPlugin):
    def on_key_down(self, action_id, settings, ctx):
        Recorder.events.append(("down", action_id, settings.get("mark", "")))

    def on_key_up(self, action_id, settings, ctx):
        Recorder.events.append(("up", action_id, settings.get("mark", "")))

    def on_dial_push(self, action_id, settings, ctx):
        Recorder.events.append(("push", action_id, settings.get("mark", "")))

    def on_dial_rotate(self, action_id, settings, delta, ctx):
        Recorder.events.append(("rotate", action_id, delta))


def slot(action="a", **kwargs):
    settings = kwargs.pop("settings", {})
    return Slot(
        plugin_id="probe",
        action_id=action,
        settings=settings,
        appearance=kwargs.pop("appearance", Appearance()),
        **kwargs,
    )


def step(action="a", mark="", **kwargs):
    return Step(kind="action", plugin_id="probe", action_id=action,
                settings={"mark": mark}, **kwargs)


def fake_device(deck):
    """Tut so, als hinge ein Gerät dran — ohne Hardware."""
    deck.device.deck = object()
    deck.device.info.connected = True
    deck.device.info.key_count = 8
    deck.device.info.dial_count = 4
    deck.device.set_key_image = lambda index, image: None
    deck.device.set_touchscreen_image = lambda image, x=0, y=0: None
    deck.device.set_brightness = lambda value: None


async def main():
    rt = Runtime()
    await rt.start()
    await asyncio.sleep(0.3)

    services = rt._services_for(Path("."))
    rt.registry.plugins["probe"] = LoadedPlugin(
        manifest=MANIFEST,
        directory=Path("."),
        instance=Probe(MANIFEST, services),
        builtin=True,
        enabled=True,
    )

    deck = rt.primary
    fake_device(deck)
    profile = deck.profile
    root = profile.root_page()
    deck.settings.long_press_ms = 200
    deck.settings.double_press_ms = 200

    # ==================================================================
    print("\n== Tastenlogik: Druck, Doppeldruck, Halten ==")
    # ==================================================================
    root.keys[0] = slot("a", double_press=slot("b"), long_press=slot("c"))

    Recorder.events.clear()
    await deck.handle_key(0, True)
    await deck.handle_key(0, False)
    check("einfacher Druck wartet auf das Doppeldruck-Fenster",
          Recorder.events == [], str(Recorder.events))
    await asyncio.sleep(0.3)
    check("und löst danach die Hauptaktion aus",
          [e[1] for e in Recorder.events] == ["a", "a"], str(Recorder.events))

    Recorder.events.clear()
    await deck.handle_key(0, True)
    await deck.handle_key(0, False)
    await asyncio.sleep(0.05)
    await deck.handle_key(0, True)
    await deck.handle_key(0, False)
    await asyncio.sleep(0.3)
    check("zweiter Druck im Fenster löst den Doppeldruck aus",
          [e[1] for e in Recorder.events] == ["b", "b"], str(Recorder.events))

    Recorder.events.clear()
    await deck.handle_key(0, True)
    await asyncio.sleep(0.3)
    check("Halten löst den dritten Zweig aus",
          [e[1] for e in Recorder.events] == ["c"], str(Recorder.events))
    await deck.handle_key(0, False)
    check("und der Hauptzweig bleibt dabei aus",
          all(e[1] == "c" for e in Recorder.events), str(Recorder.events))

    # Ohne Zweitbelegung darf es keine Verzögerung geben — das ist der
    # Grund, warum die Wartezeit überhaupt an die Belegung geknüpft ist.
    root.keys[1] = slot("a")
    Recorder.events.clear()
    await deck.handle_key(1, True)
    check("eine Taste ohne Zweig löst weiterhin sofort aus",
          [e[1] for e in Recorder.events] == ["a"], str(Recorder.events))
    await deck.handle_key(1, False)

    # ==================================================================
    print("\n== Multi-Aktion ==")
    # ==================================================================
    chain = slot("a")
    chain.plugin_id = "multi"
    chain.action_id = "chain"
    chain.steps = [
        step("a", "eins"),
        Step(kind="delay", delay_ms=60),
        step("b", "zwei"),
        step("c", "drei", enabled=False),
    ]
    root.keys[2] = chain

    Recorder.events.clear()
    ctx = deck.context("key", 2, chain)
    await deck.run_steps(chain.steps, ctx)
    await asyncio.sleep(0.25)
    marks = [e[2] for e in Recorder.events if e[0] == "down"]
    check("die Kette läuft der Reihe nach", marks == ["eins", "zwei"], str(marks))
    check("abgeschaltete Schritte bleiben aus", "drei" not in marks, str(marks))

    Recorder.events.clear()
    await deck.run_steps([step("a", "loop"), Step(kind="delay", delay_ms=40)],
                         ctx, repeat=True)
    await asyncio.sleep(0.25)
    running = deck.steps_running(ctx)
    count_while_running = len([e for e in Recorder.events if e[0] == "down"])
    check("die Schleife läuft weiter", running and count_while_running >= 2,
          f"{count_while_running} Durchläufe")
    deck.stop_steps(ctx)
    await asyncio.sleep(0.15)
    stopped_at = len([e for e in Recorder.events if e[0] == "down"])
    await asyncio.sleep(0.2)
    check("und lässt sich anhalten",
          len([e for e in Recorder.events if e[0] == "down"]) == stopped_at,
          f"{stopped_at} Durchläufe")

    # Eine Kette in der Kette wäre eine Endlosschleife.
    Recorder.events.clear()
    nested = Step(kind="action", plugin_id="multi", action_id="chain")
    await deck.run_steps([nested], ctx)
    await asyncio.sleep(0.1)
    check("verschachtelte Multi-Aktionen werden abgelehnt",
          Recorder.events == [], str(Recorder.events))

    # ==================================================================
    print("\n== Umschalter ==")
    # ==================================================================
    switch = Slot(plugin_id="multi", action_id="switch", appearance=Appearance())
    switch.steps = [step("a", "an")]
    switch.steps_off = [step("b", "aus")]
    root.keys[3] = switch

    multi_plugin = rt.registry.instance("multi")
    check("das Multi-Plugin ist geladen", multi_plugin is not None)

    if multi_plugin is not None:
        Recorder.events.clear()
        switch_ctx = deck.context("key", 3, switch)
        await multi_plugin.on_key_down("switch", switch.settings, switch_ctx)
        await asyncio.sleep(0.15)
        check("erster Druck schaltet an und läuft die erste Kette",
              switch.toggled and [e[2] for e in Recorder.events if e[0] == "down"] == ["an"],
              str(Recorder.events))
        check("und der Zustand steht auf 'an'",
              multi_plugin.get_state("switch", switch.settings, switch_ctx) == "on")

        Recorder.events.clear()
        await multi_plugin.on_key_down("switch", switch.settings, switch_ctx)
        await asyncio.sleep(0.15)
        check("zweiter Druck schaltet zurück und läuft die zweite Kette",
              not switch.toggled
              and [e[2] for e in Recorder.events if e[0] == "down"] == ["aus"],
              str(Recorder.events))

    # ==================================================================
    print("\n== Dial-Stack ==")
    # ==================================================================
    stacked = slot("a", settings={"mark": "erster"})
    stacked.stack = [
        slot("b", settings={"mark": "zweiter"}),
        slot("c", settings={"mark": "dritter"}),
    ]
    root.dials[0] = stacked

    check("ohne Umschalten gilt der erste Eintrag",
          deck.slot_at("dial", 0).settings.get("mark") == "erster")
    deck.cycle_stack(0)
    check("Weiterschalten bringt den zweiten Eintrag nach oben",
          deck.slot_at("dial", 0).settings.get("mark") == "zweiter")
    deck.cycle_stack(0)
    deck.cycle_stack(0)
    check("nach dem letzten Eintrag geht es wieder von vorn los",
          deck.slot_at("dial", 0).settings.get("mark") == "erster")

    Recorder.events.clear()
    await deck.handle_dial_push(0, True)
    await asyncio.sleep(0.05)
    await deck.handle_dial_push(0, False)
    check("kurzer Druck löst weiterhin die Aktion aus",
          [e[0] for e in Recorder.events] == ["push"], str(Recorder.events))

    Recorder.events.clear()
    await deck.handle_dial_push(0, True)
    await asyncio.sleep(0.3)
    await deck.handle_dial_push(0, False)
    check("langes Drücken schaltet den Stack weiter statt auszulösen",
          Recorder.events == []
          and deck.slot_at("dial", 0).settings.get("mark") == "zweiter",
          str(Recorder.events))

    # Ein Dial ohne Stack darf keine Verzögerung bekommen.
    root.dials[1] = slot("a", settings={"mark": "einzeln"})
    Recorder.events.clear()
    await deck.handle_dial_push(1, True)
    check("ein Dial ohne Stack löst sofort beim Drücken aus",
          [e[0] for e in Recorder.events] == ["push"], str(Recorder.events))

    # ==================================================================
    print("\n== Drehrichtungen ==")
    # ==================================================================
    turner = slot("a", settings={"mark": "regeln"})
    turner.turn_right = slot("b", settings={"mark": "rechts"})
    turner.turn_every = 2
    root.dials[2] = turner

    Recorder.events.clear()
    await deck.handle_dial_rotate(2, 1)
    check("eine Raste löst noch nichts aus", Recorder.events == [], str(Recorder.events))
    await deck.handle_dial_rotate(2, 1)
    check("nach zwei Rasten feuert die Rechtsdrehung",
          [e[2] for e in Recorder.events if e[0] == "down"] == ["rechts"],
          str(Recorder.events))

    # Die unbelegte Richtung geht weiter an die Grundaktion.
    Recorder.events.clear()
    await deck.handle_dial_rotate(2, -1)
    check("links bleibt bei der Grundaktion",
          Recorder.events == [("rotate", "a", -1)], str(Recorder.events))

    # Richtungswechsel setzt den Zähler zurück.
    Recorder.events.clear()
    await deck.handle_dial_rotate(2, 1)
    await deck.handle_dial_rotate(2, -1)
    await deck.handle_dial_rotate(2, 1)
    check("Richtungswechsel setzt den Zähler zurück",
          [e for e in Recorder.events if e[0] == "down"] == [], str(Recorder.events))

    # Zügiger Dreh: sechs Rasten bei „alle 3" → genau zweimal.
    turner.turn_every = 3
    Recorder.events.clear()
    for _ in range(6):
        await deck.handle_dial_rotate(2, 1)
    check("sechs Rasten bei „alle 3“ lösen zweimal aus",
          len([e for e in Recorder.events if e[0] == "down"]) == 2,
          str([e[2] for e in Recorder.events if e[0] == "down"]))

    # Beide Richtungen belegt: die Grundaktion bekommt gar kein Delta mehr.
    turner.turn_left = slot("c", settings={"mark": "links"})
    turner.turn_every = 1
    Recorder.events.clear()
    await deck.handle_dial_rotate(2, -1)
    await deck.handle_dial_rotate(2, 1)
    check("beide Richtungen lösen ihre eigene Aktion aus",
          [e[2] for e in Recorder.events if e[0] == "down"] == ["links", "rechts"],
          str(Recorder.events))
    check("und die Grundaktion bekommt kein Delta mehr",
          not any(e[0] == "rotate" for e in Recorder.events), str(Recorder.events))

    # Ein Dial ohne Richtungsbelegung bleibt beim alten Verhalten.
    Recorder.events.clear()
    await deck.handle_dial_rotate(1, -4)
    check("ein Dial ohne Richtungen regelt weiterhin stufenlos",
          Recorder.events == [("rotate", "a", -4)], str(Recorder.events))

    # ==================================================================
    print("\n== Mehrere Decks ==")
    # ==================================================================
    second_profile = rt.config.new_profile_for_deck("Zweites Deck")
    rt.config.decks["FAKE-2"] = DeckBinding(
        serial="FAKE-2", name="Zweites Deck", profile_id=second_profile.id, order=1
    )
    rt._sync_decks()
    second = rt.decks["FAKE-2"]
    fake_device(second)
    second.start()

    check("beide Decks sind eingerichtet", len(rt.decks) == 2, str(list(rt.decks)))
    check("und haben getrennte Profile",
          second.profile.id != deck.profile.id)

    second_root = second.profile.root_page()
    second_root.keys[0] = slot("c", settings={"mark": "deck2"})

    Recorder.events.clear()
    await second.handle_key(0, True)
    await second.handle_key(0, False)
    check("ein Druck auf dem zweiten Deck trifft dessen Belegung",
          [e[2] for e in Recorder.events] == ["deck2", "deck2"], str(Recorder.events))

    # Navigation muss beim auslösenden Deck bleiben.
    extra = Page(name="Zweite Seite", parent_id=None)
    second.profile.pages[extra.id] = extra
    second.navigate(extra.id)
    check("Navigation wirkt nur auf dem eigenen Deck",
          second.current_page_id() == extra.id
          and deck.current_page_id() == root.id,
          f"{second.current_page_id()} / {deck.current_page_id()}")

    # Die Sicht, die Plugins bekommen, muss auf dasselbe Deck zeigen.
    view_ctx = second.context("key", 0, second_root.keys[0])
    check("ctx trägt die Kennung seines Decks", view_ctx.deck_serial == "FAKE-2",
          view_ctx.deck_serial)
    check("und die Runtime-Sicht darin navigiert dieses Deck",
          view_ctx.services.runtime.current_page_id() == extra.id)
    second.navigate_home()

    # Einstellungen sind je Deck getrennt.
    deck.settings.brightness = 42
    second.settings.brightness = 77
    check("Helligkeit ist je Deck getrennt",
          deck.settings.brightness == 42 and second.settings.brightness == 77)

    # ==================================================================
    print("\n== Virtuelles Deck ==")
    # ==================================================================
    virtuell = rt.create_virtual_deck("Overlay", columns=3, rows=2, dials=2)
    check("es ist angelegt und gilt als verbunden", virtuell.connected)
    check("mit eigenem Profil", virtuell.profile.id != deck.profile.id)
    info = virtuell.device.info
    check("Geometrie folgt dem Raster",
          info.key_count == 6 and info.dial_count == 2 and info.key_columns == 3,
          f"{info.key_columns}x{info.key_rows}, {info.dial_count} Dials")

    vroot = virtuell.profile.root_page()
    vroot.keys[0] = slot("a", settings={"mark": "overlay"})
    virtuell._mark_all_dirty()
    await asyncio.sleep(0.4)

    bild = virtuell.device.image("key", 0)
    check("die Kachel wird gerendert und liegt als PNG bereit",
          bild is not None and bild[:4] == b"\x89PNG", f"{len(bild or b'')} Bytes")
    check("und hat eine Fassung, an der Änderungen erkennbar sind",
          virtuell.device.versions().get("key:0", 0) > 0)

    Recorder.events.clear()
    virtuell.device.press("key", 0, True)
    virtuell.device.press("key", 0, False)
    await asyncio.sleep(0.3)
    check("ein Klick aus dem Overlay löst die Aktion aus",
          [e[2] for e in Recorder.events if e[0] == "down"] == ["overlay"],
          str(Recorder.events))

    vroot.dials[0] = slot("b", settings={"mark": "rad"})
    Recorder.events.clear()
    virtuell.device.rotate(0, -2)
    await asyncio.sleep(0.3)
    check("das Mausrad dreht den Dial",
          Recorder.events == [("rotate", "b", -2)], str(Recorder.events))

    # Alles, was am echten Deck gilt, gilt hier auch.
    vroot.keys[1] = slot("a", settings={"mark": "kurz"}, long_press=slot("c", settings={"mark": "lang"}))
    virtuell.settings.long_press_ms = 150
    Recorder.events.clear()
    await virtuell.handle_key(1, True)
    await asyncio.sleep(0.3)
    check("auch die Tastenlogik gilt im Overlay",
          [e[2] for e in Recorder.events if e[0] == "down"] == ["lang"],
          str(Recorder.events))
    await virtuell.handle_key(1, False)

    # Ein virtuelles Deck gilt immer als verbunden — es darf der Hardware
    # trotzdem nie das Hauptdeck wegnehmen, sonst zeigt alles ohne
    # ausdrückliches Deck stillschweigend woanders hin.
    check("die Hardware bleibt Hauptdeck, auch neben einem virtuellen",
          rt.primary is deck, rt.primary.label)
    # Selbst wenn *keine* Hardware verbunden ist: Ein Overlay gilt immer als
    # verbunden und würde sonst alles an sich reißen, was ohne
    # ausdrückliches Deck angesprochen wird.
    for hardware in rt.decks.values():
        if not hardware.binding.is_virtual:
            hardware.device.info.connected = False
    check("und auch dann, wenn gar keine Hardware verbunden ist",
          not rt.primary.binding.is_virtual, rt.primary.label)
    for hardware in rt.decks.values():
        if not hardware.binding.is_virtual:
            hardware.device.info.connected = True

    check("die Schalter fürs Overlay sind einstellbar",
          virtuell.binding.overlay_transparent is False
          and virtuell.binding.hide_empty is False)

    # Ein Deck ganz ohne Drehregler: Der Ersatzwert „dann eben vier" ließ die
    # Renderschleife vier Segmente der Größe 0×0 zeichnen und daran sterben —
    # das trifft ein Stream Deck MK.2 genauso wie ein Overlay ohne Regler.
    ohne = rt.create_virtual_deck("Ohne Regler", columns=2, rows=1, dials=0)
    check("ein Deck ohne Regler meldet auch keine",
          ohne.device.info.dial_count == 0 and ohne.device.info.segment_size[1] == 0,
          f"{ohne.device.info.dial_count} Dials, Segment {ohne.device.info.segment_size}")
    check("und die Renderschleife lässt die Segmente aus",
          [z for z in ohne._all_targets() if z[0] == "dial"] == [],
          str(ohne._all_targets()))
    ohne.profile.root_page().keys[0] = slot("a", settings={"mark": "ohne"})
    ohne._mark_all_dirty()
    await asyncio.sleep(0.4)
    check("die Tasten werden trotzdem gezeichnet",
          (ohne.device.image("key", 0) or b"")[:4] == b"\x89PNG")
    rt.forget_deck(ohne.key)

    check("ein virtuelles Deck lässt sich wieder entfernen",
          rt.forget_deck(virtuell.key) and virtuell.key not in rt.decks)

    # ==================================================================
    print("\n== Aussehen ==")
    # ==================================================================
    from deckswitch.services.render import list_font_families, load_font

    families = list_font_families()
    check("Schriftfamilien werden gefunden", len(families) > 5, f"{len(families)} Familien")
    fett = load_font(20, bold=True, family=families[0] if families else "")
    check("eine Schrift lässt sich mit Schnitt laden", fett is not None)

    styled = Appearance(
        label_text="Test",
        label_bold=True,
        label_italic=True,
        label_underline=True,
        label_align="left",
        label_size=18,
    )
    root.keys[4] = slot("a", appearance=styled)
    image = await deck.render_preview(root.id, "key", 4)
    check("eine Kachel mit Schriftschnitt wird gezeichnet",
          image is not None and image.size == deck.device.info.key_size)

    # Hintergrundbild mit Deckkraft: Ein Bild anlegen und einsetzen.
    from deckswitch import paths as app_paths

    app_paths.UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    sample = app_paths.UPLOADS_DIR / "test-hintergrund.png"
    Image.new("RGBA", (200, 200), (255, 0, 0, 255)).save(sample)

    bg = Appearance(background=Background(kind="image", upload=sample.name, opacity=50))
    root.keys[5] = slot("a", appearance=bg)
    image = await deck.render_preview(root.id, "key", 5)
    middle = image.convert("RGBA").getpixel((image.width // 2, image.height // 2))
    check("ein Hintergrundbild wird eingesetzt und die Deckkraft wirkt",
          image is not None and 100 < middle[0] < 200 and middle[3] == 255,
          str(middle))

    # Animation: mehrbildriges GIF anlegen und erkennen lassen.
    animated = app_paths.UPLOADS_DIR / "test-animation.gif"
    frames = [Image.new("RGB", (60, 60), colour) for colour in ("red", "blue", "green")]
    frames[0].save(animated, save_all=True, append_images=frames[1:], duration=100, loop=0)

    check("eine animierte Datei wird als solche erkannt",
          rt.icons.is_animated_upload(animated.name))
    check("ein Standbild dagegen nicht",
          not rt.icons.is_animated_upload(sample.name))

    moving = Appearance(
        icon_by_state={"default": IconRef(kind="upload", upload=animated.name)}
    )
    root.keys[6] = slot("a", appearance=moving)
    check("die Animationsschleife findet die bewegte Kachel",
          ("key", 6) in deck._animated_targets(), str(deck._animated_targets()))

    first = rt.icons.resolve(moving.icon_by_state["default"], size=60, frame_time=0.0)
    later = rt.icons.resolve(moving.icon_by_state["default"], size=60, frame_time=0.15)
    check("und liefert zu verschiedenen Zeiten verschiedene Einzelbilder",
          first.getpixel((30, 30)) != later.getpixel((30, 30)),
          f"{first.getpixel((30, 30))} vs {later.getpixel((30, 30))}")

    # ==================================================================
    print("\n== Tastenkombinationen ==")
    # ==================================================================
    from deckswitch.services.input import parse_combo

    check("eine Kombination wird zerlegt",
          parse_combo("Strg+Shift+F5") == (["ctrl", "shift"], "F5"),
          str(parse_combo("Strg+Shift+F5")))
    check("deutsche wie englische Schreibweise gehen",
          parse_combo("ctrl+alt+entf")[0] == ["ctrl", "alt"])

    available, reason = rt.input.available()
    check("die virtuelle Tastatur ist nutzbar", available, reason)
    if available:
        code, mods = rt.input._resolve_key("z")
        # Auf einer deutschen Belegung liegt das Z auf der Taste, die eine
        # amerikanische Y nennt (Tastencode 21).
        check("Zeichen werden über die aktive Belegung aufgelöst",
              isinstance(code, int) and code > 0, f"z → {code} {mods}")

    await rt.stop()

    print()
    if FAILS:
        print(f"FEHLGESCHLAGEN ({len(FAILS)}): " + ", ".join(FAILS))
        sys.exit(1)
    print("Alle Prüfungen bestanden.")


asyncio.run(main())
