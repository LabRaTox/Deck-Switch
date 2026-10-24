"""Prüft das Uhren-Plugin: Zeiten, Zifferblätter, Editor, Countdown.

Gezeichnet wird wirklich, mit festen Uhrzeiten wo es auf die Stellung
ankommt: Um drei Uhr muss rechts von der Mitte ein Zeiger liegen, um neun
links davon. Der Countdown läuft wirklich ab, nur ohne Minuten. Attrappiert
sind allein das Abspielen und das Speichern der Konfiguration.

Aufruf:

    cd backend
    d=$(mktemp -d); env XDG_CONFIG_HOME=$d XDG_DATA_HOME=$d \\
        ../.venv/bin/python tests/clocks_test.py
"""
import _wache  # bricht ab, statt in die echte Config zu schreiben
_wache.sichere_umgebung()

import asyncio
import json
import pathlib
import sys
from datetime import datetime, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

PLUGIN_DIR = pathlib.Path(__file__).resolve().parents[2] / "plugin-sources" / "clocks"

from PIL import Image  # noqa: E402

from deckswitch import texte  # noqa: E402
from deckswitch.config import Appearance, Slot, default_config  # noqa: E402
from deckswitch.plugins.base import Manifest, Services, SlotContext  # noqa: E402
from deckswitch.services.icons import IconService  # noqa: E402
from deckswitch.services.render import RenderService  # noqa: E402

from _pluginlader import lade, nachbar  # noqa: E402

uhrmod = lade(PLUGIN_DIR)
z = nachbar(uhrmod, "zeit")
zb = nachbar(uhrmod, "zifferblatt")

FAILS = []


def check(name, bedingung, detail=""):
    print(("  ✔ " if bedingung else "  ✘ ") + name + (f"  ({detail})" if detail else ""))
    if not bedingung:
        FAILS.append(name)


class FakeRuntime:
    def __init__(self):
        self.redraws = 0
        self.gespeichert = 0

    def request_redraw(self, ctx=None):
        self.redraws += 1

    def save_config(self):
        self.gespeichert += 1

    def notify(self, *a, **k):
        pass


class FakeSound:
    def __init__(self):
        self.gespielt = []
        self.gestoppt = []

    def play(self, pfad, *, owner, sink="", volume=100, loop=False):
        self.gespielt.append(pfad)

    def stop(self, owner):
        self.gestoppt.append(owner)


manifest_dict = json.loads((PLUGIN_DIR / "manifest.json").read_text())
manifest = Manifest.model_validate(manifest_dict)
config = default_config()
icons = IconService()
services = Services(
    audio=None, icons=icons, render=RenderService(icons), runtime=FakeRuntime(),
    config=config, plugin_dir=PLUGIN_DIR, sound=FakeSound(),
)


def vorgaben(action):
    """Die Einstellungen, die eine frisch abgelegte Taste bekommt."""
    beschreibung = manifest.action(action)
    return {f.key: f.default for f in beschreibung.settings_schema if f.default is not None}


def ctx_for(action, settings, *, input_type="key", index=0):
    slot = Slot(plugin_id="clocks", action_id=action, settings=settings, appearance=Appearance())
    return SlotContext(
        action_id=action, settings=settings, appearance=slot.appearance,
        input_type=input_type, index=index, page_id="p", profile_id="pr",
        size=(120, 120) if input_type == "key" else (200, 100),
        services=services, slot=slot,
    )


def um(stunde, minute, sekunde=0):
    return datetime(2026, 10, 11, stunde, minute, sekunde, tzinfo=timezone.utc)


def in_worten(zeit, sprache):
    """Die Uhrzeit in Worten, in der angegebenen Sprache."""
    texte.verbinde_sprache(lambda: sprache)
    try:
        return z.in_worten(zeit)
    finally:
        texte.verbinde_sprache(lambda: texte.VORGABE)


def pixel(bild, x, y):
    return bild.getpixel((round(x), round(y)))


def main() -> int:
    print("== Zeit in Worten ==")
    for (h, m), de, en in (
        ((15, 0), "drei Uhr", "three o'clock"),
        ((13, 0), "ein Uhr", "one o'clock"),
        ((13, 5), "fünf nach eins", "five past one"),
        ((17, 23), "fünf vor halb sechs", "twenty-five past five"),
        ((17, 30), "halb sechs", "half past five"),
        ((11, 45), "viertel vor zwölf", "quarter to twelve"),
        ((23, 58), "zwölf Uhr", "twelve o'clock"),
    ):
        check(f"{h:02d}:{m:02d} → {de!r}", in_worten(um(h, m), "de") == de,
              in_worten(um(h, m), "de"))
        check(f"{h:02d}:{m:02d} → {en!r}", in_worten(um(h, m), "en") == en,
              in_worten(um(h, m), "en"))

    print("\n== Uhrzeit und Abstand ==")
    for zeit, erwartet in ((um(0, 5), ("12:05", "AM")), (um(12, 0), ("12:00", "PM")),
                           (um(13, 7), ("1:07", "PM"))):
        check(f"{zeit:%H:%M} im 12-Stunden-Format", z.uhrzeit(zeit, format24=False,
              sekunden=False) == erwartet, str(z.uhrzeit(zeit, format24=False, sekunden=False)))
    check("24 Stunden mit Sekunden",
          z.uhrzeit(um(9, 4, 7), format24=True, sekunden=True) == ("09:04:07", ""))
    from datetime import timedelta
    for minuten, erwartet in ((330, "+5:30"), (-210, "−3:30"), (345, "+5:45"), (0, "+0"),
                              (-300, "−5")):
        check(f"{minuten} min → {erwartet}", z.abstand(timedelta(minutes=minuten)) == erwartet,
              z.abstand(timedelta(minutes=minuten)))
    check("Stadt aus der Zone", z.stadt("America/Argentina/Buenos_Aires") == "Buenos Aires")
    zonen = z.alle_zonen()
    check("die Zonenliste ist gefüllt", "Europe/Berlin" in zonen and len(zonen) > 300, str(len(zonen)))
    check("ohne Aliasse und Etc", not any(n.startswith(("Etc/", "US/")) for n in zonen))
    check("jede Zone am Dial gibt es", all(z.zone(n) for n in z.DIAL_ZONEN),
          str([n for n in z.DIAL_ZONEN if not z.zone(n)]))
    referenz = datetime(2026, 1, 15, 23, 30, tzinfo=timezone.utc)
    tokio = z.jetzt("Asia/Tokyo", referenz)
    check("Tokio um 23:30 UTC ist 8:30 am Folgetag",
          (tokio.hour, tokio.minute, tokio.day) == (8, 30, 16), str(tokio))

    print("\n== Zeiger zeigen in die richtige Richtung ==")
    schema = zb.SCHEMATA["night"][1]
    for blatt in zb.ANALOG:
        if blatt == "ring":
            continue  # dort zeigt ein Punkt am Rand die Minuten, kein Zeiger
        drei, neun = (Image.new("RGBA", (120, 120), (0, 0, 0, 255)) for _ in range(2))
        uhr = zb.Uhr(art="analog", blatt=blatt, schema=schema)
        zb.zeichne(drei, (0, 0, 120, 120), um(3, 0), uhr)
        zb.zeichne(neun, (0, 0, 120, 120), um(9, 0), uhr)
        # 25 px rechts bzw. links der Mitte liegt der Stundenzeiger.
        rechts_hell = sum(pixel(drei, 85, 60)[:3]) > 500
        links_hell = sum(pixel(neun, 35, 60)[:3]) > 500
        check(f"„{blatt}“: 3 Uhr rechts, 9 Uhr links", rechts_hell and links_hell,
              f"{pixel(drei, 85, 60)} {pixel(neun, 35, 60)}")

    print("\n== Jedes Blatt zeichnet etwas ==")
    leer = Image.new("RGBA", (120, 120), (0, 0, 0, 255))
    for art, tabelle in (("analog", zb.ANALOG), ("digital", zb.DIGITAL)):
        for blatt in tabelle:
            for format24, sekunden in ((True, False), (False, True)):
                bild = leer.copy()
                zb.zeichne(bild, (0, 0, 120, 120), um(17, 23, 29),
                           zb.Uhr(art=art, blatt=blatt, schema=zb.SCHEMATA["none"][1],
                                  format24=format24, sekunden=sekunden, unten="So 11. Okt"))
                geaendert = bild.tobytes() != leer.tobytes()
                check(f"{art}/{blatt} {'24' if format24 else '12'} h", geaendert)

    print("\n== Manifest und Zeichencode passen zusammen ==")
    schema_felder = {f.key: f for f in manifest.action("my_clock").settings_schema}
    check("alle analogen Blätter wählbar",
          {o["value"] for o in schema_felder["face_analog"].options} == set(zb.ANALOG))
    check("alle digitalen Blätter wählbar",
          {o["value"] for o in schema_felder["face_digital"].options} == set(zb.DIGITAL))
    check("alle Farbschemata wählbar",
          {o["value"] for o in schema_felder["scheme"].options} == set(zb.SCHEMATA))
    anzahl = len(zb.ANALOG) + len(zb.DIGITAL)
    check(f"die Beschreibung nennt {anzahl} Blätter und {len(zb.SCHEMATA)} Schemata",
          f"{anzahl} Zifferblätter" in manifest_dict["description"]["de"]
          and f"{len(zb.SCHEMATA)} Farbschemata" in manifest_dict["description"]["de"]
          and f"{anzahl} clock faces" in manifest_dict["description"]["en"])
    check("der Klang liegt bei", (PLUGIN_DIR / "sounds" / "gong.wav").is_file())

    return asyncio.run(laufzeit())


async def laufzeit() -> int:
    plugin = uhrmod.ClocksPlugin(manifest, services)
    runtime: FakeRuntime = services.runtime
    klang: FakeSound = services.sound
    uhrmod.SPEICHERN_S = 0.05
    uhrmod.FERTIG_S = 0.2

    print("\n== Beide Aktionen auf Taste und Dial ==")
    for action in ("my_clock", "world_clock"):
        for eingabe in ("key", "dial"):
            for anzeige in ("analog", "digital"):
                einstellungen = vorgaben(action) | {"display": anzeige, "date": "both"}
                ctx = ctx_for(action, einstellungen, input_type=eingabe)
                bild = plugin.render(action, einstellungen, ctx)
                check(f"{action} / {eingabe} / {anzeige}", bild.size == ctx.size, str(bild.size))

    print("\n== Weltuhr ==")
    einstellungen = vorgaben("world_clock") | {"zone_4": "Asia/Tokyo", "zone_5": "Mars/Olymp"}
    check("Doppelte und Unbekannte fallen weg",
          plugin._weltzonen(einstellungen) == ["America/New_York", "Europe/London", "Asia/Tokyo"],
          str(plugin._weltzonen(einstellungen)))
    ctx = ctx_for("world_clock", einstellungen)
    vorher = plugin._weltzone(einstellungen, ctx)
    await plugin.on_key_down("world_clock", einstellungen, ctx)
    check("ein Druck zeigt die nächste Zone", plugin._weltzone(einstellungen, ctx) != vorher,
          f"{vorher} → {plugin._weltzone(einstellungen, ctx)}")
    leer = {k: v for k, v in vorgaben("world_clock").items() if not k.startswith("zone_")}
    bild = plugin.render("world_clock", leer, ctx_for("world_clock", leer))
    check("ohne Zone zeichnet sie trotzdem", bild.size == (120, 120))

    print("\n== Der Editor am Dial ==")
    einstellungen = vorgaben("my_clock")
    ctx = ctx_for("my_clock", einstellungen, input_type="dial")
    await plugin.on_dial_push("my_clock", einstellungen, ctx)
    check("Drücken öffnet den Editor beim ersten Feld", ctx.scratch.get("editor") == 0)
    await plugin.on_dial_rotate("my_clock", einstellungen, 1, ctx)
    check("Drehen schaltet auf digital", einstellungen["display"] == "digital",
          str(einstellungen.get("display")))
    bild = plugin.render("my_clock", einstellungen, ctx)
    check("der Editor zeichnet sich", bild.size == (200, 100))
    await asyncio.sleep(0.15)
    check("die Änderung wird gespeichert", runtime.gespeichert >= 1, str(runtime.gespeichert))

    await plugin.on_dial_push("my_clock", einstellungen, ctx)
    await plugin.on_dial_rotate("my_clock", einstellungen, 2, ctx)
    check("im zweiten Feld wechselt das digitale Blatt",
          einstellungen.get("face_digital") == list(zb.DIGITAL)[2],
          str(einstellungen.get("face_digital")))
    felder = plugin._felder("my_clock")
    while felder[ctx.scratch["editor"]] != "countdown":
        await plugin.on_dial_push("my_clock", einstellungen, ctx)
    await plugin.on_dial_rotate("my_clock", einstellungen, -3, ctx)
    check("der Countdown läuft nicht unter null", ctx.scratch.get("countdown_minuten") == 0)
    await plugin.on_dial_rotate("my_clock", einstellungen, 4, ctx)
    check("vier Rasten sind fünf Minuten", ctx.scratch.get("countdown_minuten") == 5,
          str(ctx.scratch.get("countdown_minuten")))
    await plugin.on_dial_push("my_clock", einstellungen, ctx)
    check("Drücken startet ihn und schließt den Editor",
          "countdown" in ctx.scratch and ctx.scratch.get("editor") is None)
    bild = plugin.render("my_clock", einstellungen, ctx)
    check("der laufende Countdown zeichnet sich", bild.size == (200, 100))
    await plugin.on_dial_push("my_clock", einstellungen, ctx)
    check("noch einmal Drücken hält ihn an", "countdown" not in ctx.scratch
          and not plugin._countdowns)

    print("\n== Ein Countdown läuft ab ==")
    ctx = ctx_for("my_clock", einstellungen, input_type="dial", index=1)
    plugin._countdown_start(ctx, 0)
    await asyncio.sleep(0.05)
    check("am Ende klingelt es", klang.gespielt and klang.gespielt[-1].endswith("gong.wav"),
          str(klang.gespielt))
    check("die Anzeige steht auf fertig", bool(ctx.scratch["countdown"]["fertig"]))
    bild = plugin.render("my_clock", einstellungen, ctx)
    check("„fertig“ zeichnet sich", bild.size == (200, 100))
    await asyncio.sleep(0.3)
    check("nach einer Weile räumt er sich ab", "countdown" not in ctx.scratch)

    print("\n== Neu gezeichnet wird, wenn sich etwas ändert ==")
    ctx = ctx_for("my_clock", vorgaben("my_clock"))
    plugin.on_tick("my_clock", ctx.settings, ctx)
    vorher = runtime.redraws
    plugin.on_tick("my_clock", ctx.settings, ctx)
    check("in derselben Minute nicht noch einmal", runtime.redraws == vorher)
    ctx.scratch["stand"] = "alt"
    plugin.on_tick("my_clock", ctx.settings, ctx)
    check("zum Minutenwechsel schon", runtime.redraws == vorher + 1)

    print("\n== Auswahl in der GUI ==")
    lokal = plugin.get_dynamic_options("zones")
    welt = plugin.get_dynamic_options("zones_world")
    check("„Systemzeit“ steht oben", lokal[0]["value"] == "" and lokal[0]["label"] == "Systemzeit",
          str(lokal[0]))
    check("die Weltuhr bietet „---“ für frei", welt[0] == {"value": "", "label": "---"})
    check("Berlin ist dabei, mit Abstand",
          any(o["value"] == "Europe/Berlin" and "UTC+" in o["label"] for o in lokal))

    await plugin.teardown()

    print()
    if FAILS:
        print(f"FEHLGESCHLAGEN ({len(FAILS)}): " + ", ".join(FAILS))
        return 1
    print("Alle Prüfungen bestanden.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
