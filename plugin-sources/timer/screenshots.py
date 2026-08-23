"""Macht die Bilder für die Detailansicht — mit dem echten Zeichencode.

Der Timer zeichnet seine Kacheln selbst: Uhrzeit, Fortschrittsbalken,
farbiger Rahmen. Ein Blatt, das stattdessen Symbol und Aktionsname zeigt,
wäre eine Behauptung über eine Darstellung, die es nicht gibt. Also wird das
Plugin hier wirklich geladen, wirklich gestartet und wirklich gerendert —
jede Kachel auf diesen Bildern hat es selbst gemalt.

Damit steht auf den Bildern auch nichts Ausgedachtes: Die Dauer ist die
Vorgabe aus dem Manifest, die Weckzeit ebenso, die Beschriftung ist das
``default_label``, das eine frisch abgelegte Taste bekommt. Was die Uhren
zeigen, haben sie in den Sekunden dieses Laufs selbst gezählt.

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

#: Höhe der erklärenden Zeile unter einer Kachel. Sie steht auf dem Blatt
#: und nicht in der Kachel: Was das Deck zeigt, und was wir dazu sagen, soll
#: sich nicht vermischen.
ZEILE = 30


def _plugin():
    """Lädt das Plugin so, wie die App es lädt."""
    sys.path.insert(0, str(ORDNER.parent.parent / "backend"))

    from deckswitch.config import default_config
    from deckswitch.plugins.base import Manifest, Services
    from deckswitch.services.icons import IconService
    from deckswitch.services.render import RenderService

    manifest_dict = json.loads((ORDNER / "manifest.json").read_text(encoding="utf-8"))
    # Als Paket laden, genau wie die App: Sonst greifen die relativen
    # Importe der Nachbardateien nicht.
    spec = importlib.util.spec_from_file_location(
        "timer_bilder", ORDNER / "plugin.py",
        submodule_search_locations=[str(ORDNER)],
    )
    modul = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = modul
    spec.loader.exec_module(modul)

    class StummerKlang:
        """Beim Bildermachen soll nichts klingeln."""

        def play(self, *a, **k):
            pass

        def stop(self, *a, **k):
            pass

    class KeineLaufzeit:
        def request_redraw(self, ctx=None):
            pass

        def notify(self, *a, **k):
            pass

    icons = IconService()
    config = default_config()
    dienste = Services(
        audio=None, icons=icons, render=RenderService(icons), runtime=KeineLaufzeit(),
        config=config, plugin_dir=ORDNER, sound=StummerKlang(),
    )
    manifest = Manifest.model_validate(manifest_dict)
    klasse = getattr(modul, manifest_dict["class"])
    return modul, manifest, klasse(manifest, dienste), dienste, manifest_dict


def _vorgaben(manifest_dict: dict, action_id: str) -> dict:
    """Die Einstellungen, die eine frisch abgelegte Taste hätte."""
    aktion = next(a for a in manifest_dict["actions"] if a["id"] == action_id)
    return {
        feld["key"]: feld["default"]
        for feld in aktion.get("settings_schema") or []
        if feld.get("default") is not None
    }


def _label(manifest_dict: dict, action_id: str) -> str:
    aktion = next(a for a in manifest_dict["actions"] if a["id"] == action_id)
    wert = aktion.get("default_label") or ""
    return wert.get("de") or wert.get("en") or "" if isinstance(wert, dict) else str(wert)


def _blatt_mit_zeilen(werkzeug, zeilen: int, segmentzeile: bool = False):
    from PIL import Image

    breite = werkzeug.RAND * 2 + werkzeug._breite()
    hoehe = werkzeug.RAND * 2 + zeilen * (werkzeug.TASTE + ZEILE) + \
        (zeilen - 1) * werkzeug.LUECKE
    if segmentzeile:
        hoehe += werkzeug._strip_hoehe() + ZEILE + werkzeug.LUECKE
    return Image.new("RGB", (breite, hoehe), werkzeug.HINTERGRUND)


def _setze(werkzeug, blatt, kachel, spalte: int, zeile: int, text: str) -> None:
    from PIL import ImageDraw

    x = werkzeug.RAND + spalte * (werkzeug.TASTE + werkzeug.LUECKE)
    y = werkzeug.RAND + zeile * (werkzeug.TASTE + ZEILE + werkzeug.LUECKE)
    kachel = kachel.convert("RGBA").resize((werkzeug.TASTE, werkzeug.TASTE))
    blatt.paste(kachel, (x, y), kachel)
    if text:
        zeichner = ImageDraw.Draw(blatt)
        schrift = werkzeug._schrift(15)
        kasten = zeichner.textbbox((0, 0), text, font=schrift)
        zeichner.text((x + (werkzeug.TASTE - (kasten[2] - kasten[0])) // 2, y + werkzeug.TASTE + 7),
                      text, font=schrift, fill=(190, 190, 200))


def _leer(werkzeug):
    from PIL import Image, ImageDraw

    bild = Image.new("RGBA", (werkzeug.TASTE, werkzeug.TASTE), (0, 0, 0, 0))
    ImageDraw.Draw(bild).rounded_rectangle(
        (0, 0, werkzeug.TASTE - 1, werkzeug.TASTE - 1),
        radius=werkzeug.RADIUS, fill=(22, 22, 26, 255))
    return bild


def erzeuge(ziel: Path, werkzeug) -> list[str]:
    return asyncio.run(_erzeuge(ziel, werkzeug))


async def _erzeuge(ziel: Path, werkzeug) -> list[str]:
    from deckswitch.config import Appearance, Slot
    from deckswitch.plugins.base import SlotContext

    modul, manifest, plugin, dienste, manifest_dict = _plugin()
    await plugin.setup()

    zaehler = [0]

    def ctx(action_id, einstellungen=None, *, art="key"):
        """Jede Kachel eine eigene Belegung — sonst teilten sie sich eine Uhr."""
        zaehler[0] += 1
        werte = dict(_vorgaben(manifest_dict, action_id))
        werte.update(einstellungen or {})
        aussehen = Appearance()
        aussehen.label_text = _label(manifest_dict, action_id)
        slot = Slot(plugin_id="timer", action_id=action_id, settings=werte,
                    appearance=aussehen)
        return SlotContext(
            action_id=action_id, settings=werte, appearance=aussehen, input_type=art,
            index=zaehler[0], page_id="bilder", profile_id="bilder",
            size=(120, 120) if art == "key" else (200, 100),
            services=dienste, slot=slot,
        )

    def male(c):
        return plugin.render(c.action_id, c.settings, c)

    gebaut: list[str] = []

    # -- Die drei Aktionen, wie sie frisch abgelegt aussehen ---------------
    blatt = _blatt_mit_zeilen(werkzeug, 1)
    for spalte, (aktion, beschriftung) in enumerate((
        ("countdown", "Countdown"), ("stopwatch", "Stoppuhr"), ("alarm", "Wecker"),
    )):
        _setze(werkzeug, blatt, male(ctx(aktion)), spalte, 0, beschriftung)
    _setze(werkzeug, blatt, _leer(werkzeug), 3, 0, "")
    blatt.save(ziel / "aktionen.png")
    gebaut.append(f"{ziel.name}/aktionen.png")

    # -- Die Zustände, wirklich hergestellt --------------------------------
    blatt = _blatt_mit_zeilen(werkzeug, 3)

    bereit = ctx("countdown")
    _setze(werkzeug, blatt, male(bereit), 0, 0, "bereit")

    laufend = ctx("countdown")
    plugin.on_key_down("countdown", laufend.settings, laufend)

    pausiert = ctx("countdown")
    plugin.on_key_down("countdown", pausiert.settings, pausiert)

    abgelaufen = ctx("countdown", {"duration": "0:01"})
    plugin.on_key_down("countdown", abgelaufen.settings, abgelaufen)

    uhr_laeuft = ctx("stopwatch")
    plugin.on_key_down("stopwatch", uhr_laeuft.settings, uhr_laeuft)
    uhr_steht = ctx("stopwatch")
    plugin.on_key_down("stopwatch", uhr_steht.settings, uhr_steht)

    # Die Sekunden hier sind keine Kosmetik: Sie sind die Wartezeit, in der
    # die Uhren wirklich zählen und der kurze Countdown wirklich abläuft.
    await asyncio.sleep(1.3)
    plugin._runde()
    plugin.on_key_down("countdown", pausiert.settings, pausiert)
    plugin.on_key_down("stopwatch", uhr_steht.settings, uhr_steht)

    _setze(werkzeug, blatt, male(laufend), 1, 0, "läuft")
    _setze(werkzeug, blatt, male(pausiert), 2, 0, "pausiert")
    _setze(werkzeug, blatt, male(abgelaufen), 3, 0, "abgelaufen — es klingelt")

    _setze(werkzeug, blatt, male(ctx("stopwatch")), 0, 1, "Stoppuhr, bereit")
    _setze(werkzeug, blatt, male(uhr_laeuft), 1, 1, "läuft")
    _setze(werkzeug, blatt, male(uhr_steht), 2, 1, "angehalten")
    _setze(werkzeug, blatt, _leer(werkzeug), 3, 1, "")

    scharf = ctx("alarm")
    aus = ctx("alarm")
    plugin.on_key_down("alarm", aus.settings, aus)
    klingelt = ctx("alarm")
    lauf = plugin._hole("alarm", klingelt.settings, klingelt)
    lauf.fertig = True
    _setze(werkzeug, blatt, male(scharf), 0, 2, "Wecker, scharf")
    _setze(werkzeug, blatt, male(aus), 1, 2, "aus")
    _setze(werkzeug, blatt, male(klingelt), 2, 2, "klingelt")
    _setze(werkzeug, blatt, _leer(werkzeug), 3, 2, "")

    blatt.save(ziel / "zustaende.png")
    gebaut.append(f"{ziel.name}/zustaende.png")

    # -- Dieselben drei auf dem Touchstrip ---------------------------------
    from PIL import Image, ImageDraw

    breite = werkzeug.RAND * 2 + werkzeug._breite()
    streifen_hoehe = werkzeug._strip_hoehe()
    blatt = Image.new("RGB", (breite, werkzeug.RAND * 2 + streifen_hoehe + ZEILE),
                      werkzeug.HINTERGRUND)
    # Der echte Streifen ist ein Bild von 800×100, in vier Segmente geteilt.
    streifen = Image.new("RGBA", (800, 100), (0, 0, 0, 255))
    dial_countdown = ctx("countdown", art="dial")
    plugin.on_dial_push("countdown", dial_countdown.settings, dial_countdown)
    dial_uhr = ctx("stopwatch", art="dial")
    plugin.on_dial_push("stopwatch", dial_uhr.settings, dial_uhr)
    await asyncio.sleep(1.2)
    for i, c in enumerate((dial_countdown, dial_uhr, ctx("alarm", art="dial"))):
        streifen.alpha_composite(male(c).convert("RGBA"), (i * 200, 0))
    blatt.paste(streifen.convert("RGB").resize((werkzeug._breite(), streifen_hoehe),
                                               Image.LANCZOS),
                (werkzeug.RAND, werkzeug.RAND))
    zeichner = ImageDraw.Draw(blatt)
    schrift = werkzeug._schrift(15)
    text = "Dieselben drei Aktionen auf den Dials"
    kasten = zeichner.textbbox((0, 0), text, font=schrift)
    zeichner.text(((breite - (kasten[2] - kasten[0])) // 2,
                   werkzeug.RAND + streifen_hoehe + 8),
                  text, font=schrift, fill=(190, 190, 200))
    blatt.save(ziel / "dials.png")
    gebaut.append(f"{ziel.name}/dials.png")

    await plugin.teardown()
    return gebaut
