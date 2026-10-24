"""Macht die Bilder für die Detailansicht — mit dem echten Zeichencode.

Jede Kachel auf diesen Bildern hat das Plugin selbst gemalt. Die Uhren
zeigen die Zeit, zu der dieses Skript lief; die Zonen der Weltuhr sind die
Vorgaben aus dem Manifest, also das, was eine frisch abgelegte Taste zeigt.
Editor und Countdown auf dem Touchstrip sind über dieselben Dial-Eingaben
hergestellt, die auch am Gerät ankommen.

Gerufen wird das von ``scripts/make-plugin-screenshots.py``. Ins Paket
gehört diese Datei nicht — ``package_plugins.py`` lässt sie draußen.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
from pathlib import Path

ORDNER = Path(__file__).resolve().parent

#: Höhe der erklärenden Zeile unter einer Kachel.
ZEILE = 30


def _plugin():
    sys.path.insert(0, str(ORDNER.parent.parent / "backend"))

    from deckswitch.config import default_config
    from deckswitch.plugins.base import Manifest, Services
    from deckswitch.services.icons import IconService
    from deckswitch.services.render import RenderService

    manifest_dict = json.loads((ORDNER / "manifest.json").read_text(encoding="utf-8"))
    spec = importlib.util.spec_from_file_location(
        "clocks_bilder", ORDNER / "plugin.py", submodule_search_locations=[str(ORDNER)],
    )
    modul = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = modul
    spec.loader.exec_module(modul)

    class Still:
        def play(self, *a, **k):
            pass

        def stop(self, *a, **k):
            pass

    class KeineLaufzeit:
        def request_redraw(self, ctx=None):
            pass

        def save_config(self):
            pass

        def notify(self, *a, **k):
            pass

    icons = IconService()
    dienste = Services(
        audio=None, icons=icons, render=RenderService(icons), runtime=KeineLaufzeit(),
        config=default_config(), plugin_dir=ORDNER, sound=Still(),
    )
    manifest = Manifest.model_validate(manifest_dict)
    return modul, modul.ClocksPlugin(manifest, dienste), dienste, manifest_dict


def _vorgaben(manifest_dict: dict, action_id: str) -> dict:
    aktion = next(a for a in manifest_dict["actions"] if a["id"] == action_id)
    return {f["key"]: f["default"] for f in aktion.get("settings_schema") or []
            if f.get("default") is not None}


def _blatt(werkzeug, zeilen: int, streifen: bool = False):
    from PIL import Image

    breite = werkzeug.RAND * 2 + werkzeug._breite()
    hoehe = werkzeug.RAND * 2 + zeilen * (werkzeug.TASTE + ZEILE) + (zeilen - 1) * werkzeug.LUECKE
    if streifen:
        hoehe += werkzeug._strip_hoehe() + ZEILE + werkzeug.LUECKE
    return Image.new("RGB", (breite, hoehe), werkzeug.HINTERGRUND)


def _beschrifte(werkzeug, blatt, text, mitte_x, y):
    from PIL import ImageDraw

    zeichner = ImageDraw.Draw(blatt)
    schrift = werkzeug._schrift(15)
    kasten = zeichner.textbbox((0, 0), text, font=schrift)
    zeichner.text((mitte_x - (kasten[2] - kasten[0]) // 2, y), text, font=schrift,
                  fill=(190, 190, 200))


def _setze(werkzeug, blatt, kachel, spalte: int, zeile: int, text: str) -> None:
    x = werkzeug.RAND + spalte * (werkzeug.TASTE + werkzeug.LUECKE)
    y = werkzeug.RAND + zeile * (werkzeug.TASTE + ZEILE + werkzeug.LUECKE)
    kachel = kachel.convert("RGBA").resize((werkzeug.TASTE, werkzeug.TASTE))
    blatt.paste(kachel, (x, y), kachel)
    _beschrifte(werkzeug, blatt, text, x + werkzeug.TASTE // 2, y + werkzeug.TASTE + 7)


def _setze_streifen(werkzeug, blatt, segmente, zeilen_davor: int, text: str) -> None:
    from PIL import Image

    streifen = Image.new("RGBA", (800, 100), (0, 0, 0, 255))
    for i, segment in enumerate(segmente):
        streifen.alpha_composite(segment.convert("RGBA"), (i * 200, 0))
    y = werkzeug.RAND + zeilen_davor * (werkzeug.TASTE + ZEILE + werkzeug.LUECKE)
    blatt.paste(streifen.convert("RGB").resize((werkzeug._breite(), werkzeug._strip_hoehe()),
                                               Image.LANCZOS), (werkzeug.RAND, y))
    _beschrifte(werkzeug, blatt, text, blatt.width // 2, y + werkzeug._strip_hoehe() + 8)


def erzeuge(ziel: Path, werkzeug) -> list[str]:
    return asyncio.run(_erzeuge(ziel, werkzeug))


async def _erzeuge(ziel: Path, werkzeug) -> list[str]:
    from deckswitch.config import Appearance, Slot
    from deckswitch.plugins.base import SlotContext

    modul, plugin, dienste, manifest_dict = _plugin()
    zb = sys.modules["clocks_bilder.zifferblatt"]
    zaehler = [0]

    def ctx(action_id, einstellungen=None, *, art="key"):
        zaehler[0] += 1
        werte = dict(_vorgaben(manifest_dict, action_id))
        werte.update(einstellungen or {})
        aussehen = Appearance()
        slot = Slot(plugin_id="clocks", action_id=action_id, settings=werte, appearance=aussehen)
        return SlotContext(
            action_id=action_id, settings=werte, appearance=aussehen, input_type=art,
            index=zaehler[0], page_id="bilder", profile_id="bilder",
            size=(120, 120) if art == "key" else (200, 100), services=dienste, slot=slot,
        )

    def male(c):
        return plugin.render(c.action_id, c.settings, c)

    def name(tabelle, schluessel):
        eintrag = tabelle[schluessel]
        return plugin.t(eintrag if isinstance(eintrag, str) else eintrag[0])

    gebaut: list[str] = []

    # -- Zifferblätter: je vier analoge und digitale -----------------------
    blatt = _blatt(werkzeug, 2)
    analog = [("classic", "night"), ("railway", "light"), ("chrono", "amber"), ("ring", "ocean")]
    for spalte, (blattname, schema) in enumerate(analog):
        c = ctx("my_clock", {"display": "analog", "face_analog": blattname, "scheme": schema,
                             "seconds": True})
        _setze(werkzeug, blatt, male(c), spalte, 0,
               f"{name(zb.ANALOG, blattname)} · {name(zb.SCHEMATA, schema)}")
    digital = [("classic", "night"), ("segment", "red"), ("flip", "light"), ("words", "violet")]
    for spalte, (blattname, schema) in enumerate(digital):
        c = ctx("my_clock", {"display": "digital", "face_digital": blattname, "scheme": schema,
                             "date": "weekday"})
        _setze(werkzeug, blatt, male(c), spalte, 1,
               f"{name(zb.DIGITAL, blattname)} · {name(zb.SCHEMATA, schema)}")
    blatt.save(ziel / "uhren.png")
    gebaut.append(f"{ziel.name}/uhren.png")

    # -- Weltuhr und Dials ---------------------------------------------------
    blatt = _blatt(werkzeug, 1, streifen=True)
    _setze(werkzeug, blatt, male(ctx("my_clock", {"date": "both"})), 0, 0, "Meine Uhr")
    for spalte in range(1, 4):
        welt = ctx("world_clock")
        for _ in range(spalte - 1):
            await plugin.on_key_down("world_clock", welt.settings, welt)
        _setze(werkzeug, blatt, male(welt), spalte, 0,
               f"Weltuhr · {plugin._weltzone(welt.settings, welt).rsplit('/', 1)[-1].replace('_', ' ')}")

    meine = ctx("my_clock", {"date": "both"}, art="dial")
    welt = ctx("world_clock", {"display": "analog"}, art="dial")
    editor = ctx("my_clock", art="dial")
    await plugin.on_dial_push("my_clock", editor.settings, editor)
    await plugin.on_dial_push("my_clock", editor.settings, editor)
    countdown = ctx("my_clock", art="dial")
    felder = plugin._felder("my_clock")
    await plugin.on_dial_push("my_clock", countdown.settings, countdown)
    while felder[countdown.scratch["editor"]] != "countdown":
        await plugin.on_dial_push("my_clock", countdown.settings, countdown)
    await plugin.on_dial_rotate("my_clock", countdown.settings, 5, countdown)
    await plugin.on_dial_push("my_clock", countdown.settings, countdown)
    await asyncio.sleep(1.2)
    _setze_streifen(werkzeug, blatt, [male(c) for c in (meine, welt, editor, countdown)], 1,
                    "Dials: Uhr, Weltuhr, Editor beim Zifferblatt, laufender Countdown")
    blatt.save(ziel / "dials.png")
    gebaut.append(f"{ziel.name}/dials.png")

    await plugin.teardown()
    return gebaut
