"""Macht die Bilder für die Detailansicht — mit dem echten Zeichencode.

Zwölf der vierzehn Aktionen zeigen Symbol und Beschriftung, zwei zeichnen
selbst: Streamstatus und Follower. Ein Blatt, das für diese beiden ein
Symbol malt, behauptete eine Darstellung, die es nicht gibt. Also wird das
Plugin geladen und jede Kachel wirklich von ihm gezeichnet.

**Auf diesen Bildern steht keine einzige Zahl von Twitch.** Ohne Anmeldung
gibt es keine Zuschauer und keine Follower, und ausgedacht wird hier nichts.
Die beiden Anzeigen zeigen deshalb den Zustand, den auch jeder frisch
Installierte sieht: „nicht verbunden". Alles andere — Namen, Symbole,
Beschriftungen — kommt aus dem Manifest.

Gerufen wird das von ``scripts/make-plugin-screenshots.py``.
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
    """Lädt das Plugin so, wie die App es lädt."""
    sys.path.insert(0, str(ORDNER.parent.parent / "backend"))
    sys.path.insert(0, str(ORDNER))

    from deckswitch.config import default_config
    from deckswitch.plugins.base import Manifest, Services
    from deckswitch.services.icons import IconService
    from deckswitch.services.render import RenderService

    manifest_dict = json.loads((ORDNER / "manifest.json").read_text(encoding="utf-8"))
    # Als Paket laden, genau wie die App: Sonst greifen die relativen
    # Importe der Nachbardateien nicht.
    spec = importlib.util.spec_from_file_location(
        "twitch_bilder", ORDNER / "plugin.py",
        submodule_search_locations=[str(ORDNER)],
    )
    modul = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = modul
    spec.loader.exec_module(modul)

    class KeineLaufzeit:
        def request_redraw(self, ctx=None):
            pass

        def notify(self, *a, **k):
            pass

    # Ohne Registry findet der IconService kein Iconset, und jede Kachel
    # bekäme den Platzhalter statt ihres Symbols. Gebraucht werden davon
    # nur zwei Angaben — dafür die ganze Ladeschicht hochzufahren wäre
    # unverhältnismäßig.
    class NurDasIconset:
        def __init__(self, ordner: Path) -> None:
            self.id = "iconset-tabler"
            self.is_iconset = True
            self.icons_path = ordner

    class MiniRegistry:
        def __init__(self, ordner: Path) -> None:
            self._eintrag = NurDasIconset(ordner)

        def get(self, plugin_id: str):
            return self._eintrag if plugin_id == self._eintrag.id else None

        @property
        def iconsets(self):
            return [self._eintrag]

    iconset = ORDNER.parent.parent / "backend" / "plugins" / "iconset-tabler" / "icons"
    icons = IconService(MiniRegistry(iconset))
    config = default_config()
    dienste = Services(
        audio=None, icons=icons, render=RenderService(icons), runtime=KeineLaufzeit(),
        config=config, plugin_dir=ORDNER,
    )
    manifest = Manifest.model_validate(manifest_dict)
    klasse = getattr(modul, manifest_dict["class"])
    return klasse(manifest, dienste), dienste, manifest_dict


def _text(wert) -> str:
    if isinstance(wert, dict):
        return wert.get("de") or wert.get("en") or ""
    return str(wert or "")


def _blatt(werkzeug, zeilen: int):
    from PIL import Image

    breite = werkzeug.RAND * 2 + werkzeug._breite()
    hoehe = werkzeug.RAND * 2 + zeilen * (werkzeug.TASTE + ZEILE) + \
        (zeilen - 1) * werkzeug.LUECKE
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
        zeichner.text(
            (x + (werkzeug.TASTE - (kasten[2] - kasten[0])) // 2, y + werkzeug.TASTE + 7),
            text, font=schrift, fill=(190, 190, 200),
        )


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

    plugin, dienste, manifest_dict = _plugin()
    zaehler = [0]

    def ctx(aktion: dict, art="key"):
        zaehler[0] += 1
        werte = {
            feld["key"]: feld["default"]
            for feld in aktion.get("settings_schema") or []
            if feld.get("default") is not None
        }
        aussehen = Appearance()
        aussehen.label_text = _text(aktion.get("default_label"))
        # Dieselbe Vorbelegung wie beim Ablegen auf eine Taste.
        if aktion.get("default_icon"):
            from deckswitch.config import IconRef

            aussehen.icon_by_state = {
                "default": IconRef(kind="iconset", set_id="iconset-tabler",
                                   name=aktion["default_icon"])
            }
        slot = Slot(plugin_id="twitch", action_id=aktion["id"], settings=werte,
                    appearance=aussehen)
        return SlotContext(
            action_id=aktion["id"], settings=werte, appearance=aussehen,
            input_type=art, index=zaehler[0], page_id="bilder", profile_id="bilder",
            size=(120, 120) if art == "key" else (200, 100),
            services=dienste, slot=slot,
        )

    aktionen = manifest_dict["actions"]
    gebaut: list[str] = []

    # -- Alle Aktionen, wie sie frisch abgelegt aussehen -------------------
    spalten = werkzeug.SPALTEN
    zeilen = -(-len(aktionen) // spalten)
    blatt = _blatt(werkzeug, zeilen)
    for i in range(zeilen * spalten):
        spalte, zeile = i % spalten, i // spalten
        if i >= len(aktionen):
            _setze(werkzeug, blatt, _leer(werkzeug), spalte, zeile, "")
            continue
        aktion = aktionen[i]
        c = ctx(aktion)
        _setze(werkzeug, blatt, plugin.render(aktion["id"], c.settings, c),
               spalte, zeile, _text(aktion.get("name")))
    blatt.save(ziel / "aktionen.png")
    gebaut.append(f"{ziel.name}/aktionen.png")

    # -- Die Zustände, die das Manifest nennt ------------------------------
    mit_zustaenden = [a for a in aktionen if len(a.get("states") or []) > 1]
    kacheln = []
    for aktion in mit_zustaenden:
        for zustand in aktion["states"]:
            from deckswitch.config import IconRef

            c = ctx(aktion)
            symbol = zustand.get("default_icon") or aktion.get("default_icon")
            if symbol:
                c.appearance.icon_by_state = {
                    "default": IconRef(kind="iconset", set_id="iconset-tabler",
                                       name=symbol)
                }
            kacheln.append((
                f"{_text(aktion.get('name'))}: {_text(zustand.get('name'))}",
                plugin.render(aktion["id"], c.settings, c),
            ))

    zeilen = -(-len(kacheln) // spalten)
    blatt = _blatt(werkzeug, zeilen)
    for i in range(zeilen * spalten):
        spalte, zeile = i % spalten, i // spalten
        if i >= len(kacheln):
            _setze(werkzeug, blatt, _leer(werkzeug), spalte, zeile, "")
            continue
        beschriftung, kachel = kacheln[i]
        _setze(werkzeug, blatt, kachel, spalte, zeile, beschriftung)
    blatt.save(ziel / "zustaende.png")
    gebaut.append(f"{ziel.name}/zustaende.png")

    # -- Die beiden Anzeigen auf dem Touchstrip ----------------------------
    from PIL import Image, ImageDraw

    anzeigen = [a for a in aktionen if "dial" in (a.get("inputs") or [])]
    breite = werkzeug.RAND * 2 + werkzeug._breite()
    hoehe_streifen = werkzeug._strip_hoehe()
    blatt = Image.new("RGB", (breite, werkzeug.RAND * 2 + hoehe_streifen + ZEILE),
                      werkzeug.HINTERGRUND)
    streifen = Image.new("RGBA", (800, 100), (0, 0, 0, 255))
    for i, aktion in enumerate(anzeigen[:4]):
        c = ctx(aktion, art="dial")
        streifen.alpha_composite(
            plugin.render(aktion["id"], c.settings, c).convert("RGBA"), (i * 200, 0))
    blatt.paste(
        streifen.convert("RGB").resize((werkzeug._breite(), hoehe_streifen),
                                       Image.LANCZOS),
        (werkzeug.RAND, werkzeug.RAND))
    zeichner = ImageDraw.Draw(blatt)
    schrift = werkzeug._schrift(15)
    text = "Auf den Dials — hier ohne Verbindung zu Twitch"
    kasten = zeichner.textbbox((0, 0), text, font=schrift)
    zeichner.text(((breite - (kasten[2] - kasten[0])) // 2,
                   werkzeug.RAND + hoehe_streifen + 8),
                  text, font=schrift, fill=(190, 190, 200))
    blatt.save(ziel / "dials.png")
    gebaut.append(f"{ziel.name}/dials.png")

    await plugin.teardown()
    return gebaut
