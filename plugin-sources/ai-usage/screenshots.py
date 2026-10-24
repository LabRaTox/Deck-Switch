"""Macht die Bilder für die Detailansicht, mit dem echten Zeichencode.

Jede Kachel hat das Plugin selbst gezeichnet, und zwar mit dem Stand, den
der CodexBar-Dienst auf diesem Rechner beim Lauf des Skripts liefert. Ist
CodexBar nicht erreichbar, bricht das Skript ab, statt Werte zu erfinden.
Der Plan des Kontos wird vor dem Zeichnen entfernt, damit er nicht auf den
Bildern steht.

Für die Zustände Warnung und kritisch werden die Schwellen auf der Taste
gesenkt, für „veraltet“ wird der Stand gealtert und für „Fehler“ ein
Abruf an einen Port geschickt, auf dem nichts läuft. Unter jeder Kachel
steht, was dafür eingestellt ist.

Gerufen wird das von ``scripts/make-plugin-screenshots.py``. Ins Paket
gehört diese Datei nicht, ``package_plugins.py`` lässt sie draußen.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

ORDNER = Path(__file__).resolve().parent

#: Höhe der erklärenden Zeile unter einer Kachel.
ZEILE = 30

#: Ein Port, auf dem kein Dienst läuft, für den Fehlerzustand.
TOTER_PORT = "http://127.0.0.1:9"


def _plugin():
    sys.path.insert(0, str(ORDNER.parent.parent / "backend"))

    from deckswitch import paths
    from deckswitch.config import default_config
    from deckswitch.plugins.base import Manifest, Services
    from deckswitch.plugins.loader import PluginRegistry
    from deckswitch.services.icons import IconService
    from deckswitch.services.render import RenderService

    manifest_dict = json.loads((ORDNER / "manifest.json").read_text(encoding="utf-8"))
    spec = importlib.util.spec_from_file_location(
        "ai_usage_bilder", ORDNER / "plugin.py", submodule_search_locations=[str(ORDNER)],
    )
    modul = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = modul
    spec.loader.exec_module(modul)

    class KeineLaufzeit:
        _loop = None
        registry = None

        def request_redraw(self, ctx=None):
            pass

        def save_config(self):
            pass

        def notify(self, *a, **k):
            pass

        def publish_plugin_status(self, plugin_id):
            pass

    icons = IconService()
    laufzeit = KeineLaufzeit()
    dienste = Services(
        audio=None, icons=icons, render=RenderService(icons), runtime=laufzeit,
        config=default_config(), plugin_dir=ORDNER,
    )
    # Ohne Registry kennt der IconService die eingebauten Symbole nicht.
    registry = PluginRegistry()
    registry.discover(lambda _ordner: dienste,
                      search_paths=[(paths.BUILTIN_PLUGINS_DIR, True), (ORDNER.parent, False)])
    icons.bind_registry(registry)
    laufzeit.registry = registry

    manifest = Manifest.model_validate(manifest_dict)
    return modul, modul.AIUsagePlugin(manifest, dienste), dienste, manifest_dict


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
    schrift = werkzeug._schrift(14)
    kasten = zeichner.textbbox((0, 0), text, font=schrift)
    zeichner.text((mitte_x - (kasten[2] - kasten[0]) // 2, y), text, font=schrift,
                  fill=(190, 190, 200))


def _setze(werkzeug, blatt, kachel, spalte: int, zeile: int, text: str) -> None:
    x = werkzeug.RAND + spalte * (werkzeug.TASTE + werkzeug.LUECKE)
    y = werkzeug.RAND + zeile * (werkzeug.TASTE + ZEILE + werkzeug.LUECKE)
    kachel = kachel.convert("RGBA")
    blatt.paste(kachel, (x, y), kachel)
    _beschrifte(werkzeug, blatt, text, x + werkzeug.TASTE // 2, y + werkzeug.TASTE + 7)


def _setze_streifen(werkzeug, blatt, segmente, zeilen_davor: int, texte: list[str]) -> None:
    from PIL import Image

    streifen = Image.new("RGBA", (800, 100), (0, 0, 0, 255))
    for i, segment in enumerate(segmente):
        streifen.alpha_composite(segment.convert("RGBA"), (i * 200, 0))
    y = werkzeug.RAND + zeilen_davor * (werkzeug.TASTE + ZEILE + werkzeug.LUECKE)
    blatt.paste(streifen.convert("RGB").resize((werkzeug._breite(), werkzeug._strip_hoehe()),
                                               Image.LANCZOS), (werkzeug.RAND, y))
    viertel = werkzeug._breite() / 4
    for i, text in enumerate(texte):
        _beschrifte(werkzeug, blatt, text, round(werkzeug.RAND + viertel * (i + 0.5)),
                    y + werkzeug._strip_hoehe() + 8)


def erzeuge(ziel: Path, werkzeug) -> list[str]:
    return asyncio.run(_erzeuge(ziel, werkzeug))


async def _erzeuge(ziel: Path, werkzeug) -> list[str]:
    from deckswitch.config import Appearance, Slot
    from deckswitch.plugins.base import SlotContext

    modul, plugin, dienste, manifest_dict = _plugin()
    # PollSettings über das Plugin-Modul, nicht über sys.modules: Die Registry
    # oben räumt beim Laden alle Module aus diesem Ordner dort weg.
    pl = modul

    # Echter Stand vom CodexBar-Dienst, mit den Vorgaben aus dem Manifest.
    poller = plugin.poller
    poller.poll(pl.PollSettings.from_config({}))
    if poller.snapshot is None or poller.snapshot.source != "codexbar":
        raise SystemExit(f"CodexBar nicht erreichbar ({poller.codexbar_error}), keine Bilder")
    poller.snapshot = replace(
        poller.snapshot,
        providers=[replace(p, plan=None) for p in poller.snapshot.providers],
    )
    mit_werten = [p for p in poller.snapshot.providers if p.windows and not p.error]
    ohne_login = [p for p in poller.snapshot.providers if p.error_kind == "login_missing"]
    if not mit_werten:
        raise SystemExit("CodexBar liefert keinen Anbieter mit Werten, keine Bilder")
    erster = mit_werten[0].id
    gross = (werkzeug.TASTE, werkzeug.TASTE)
    zaehler = [0]

    def ctx(action_id, einstellungen=None, *, art="key"):
        zaehler[0] += 1
        werte = dict(_vorgaben(manifest_dict, action_id))
        werte.update(einstellungen or {})
        aussehen = Appearance(label_text="KI-Nutzung" if action_id == "overview" else "")
        slot = Slot(plugin_id="ai-usage", action_id=action_id, settings=werte, appearance=aussehen)
        return SlotContext(
            action_id=action_id, settings=werte, appearance=aussehen, input_type=art,
            index=zaehler[0], page_id="bilder", profile_id="bilder",
            size=gross if art == "key" else (200, 100), services=dienste, slot=slot,
        )

    def male(c):
        return plugin.render(c.action_id, c.settings, c)

    gebaut: list[str] = []

    # -- Tasten ------------------------------------------------------------
    blatt = _blatt(werkzeug, 2)
    zeile_eins = [
        (ctx("provider", {"provider": erster}), "Anbieter, Ring"),
        (ctx("provider", {"provider": erster, "window": "weekly", "style": "bar"}),
         "Anbieter, Balken"),
        (ctx("highest"), "Höchste Auslastung"),
        (ctx("credits", {"provider": erster, "show": "cost_30d"}), "Guthaben/Kosten"),
    ]
    zeile_zwei = [
        (ctx("provider", {"provider": erster, "style": "icon"}), "Symbol je Zustand"),
        (ctx("provider", {"provider": erster, "display": "remaining"}), "Anzeige „übrig“"),
    ]
    if ohne_login:
        zeile_zwei.append((ctx("provider", {"provider": ohne_login[0].id}), "Anmeldung fehlt"))
    zeile_zwei.append((ctx("overview"), "Übersicht öffnen"))
    for spalte, (c, text) in enumerate(zeile_eins):
        _setze(werkzeug, blatt, male(c), spalte, 0, text)
    for spalte, (c, text) in enumerate(zeile_zwei):
        _setze(werkzeug, blatt, male(c), spalte, 1, text)
    blatt.save(ziel / "tasten.png")
    gebaut.append("screenshots/tasten.png")

    # -- Touchstrip --------------------------------------------------------
    blatt = _blatt(werkzeug, 0, streifen=True)
    normal = ctx("dial", {"provider": erster}, art="dial")
    detail = ctx("dial", {"provider": erster}, art="dial")
    await plugin.on_touch("dial", detail.settings, 10, 10, detail)
    uebrig = ctx("dial", {"provider": erster}, art="dial")
    await plugin.on_dial_push("dial", uebrig.settings, uebrig)
    segmente = [male(normal), male(detail), male(uebrig)]
    texte = ["Anbieter-Dial", "nach Tippen", "nach Drücken"]
    if ohne_login:
        segmente.append(male(ctx("dial", {"provider": ohne_login[0].id}, art="dial")))
        texte.append("Anmeldung fehlt")
    _setze_streifen(werkzeug, blatt, segmente, 0, texte)
    blatt.save(ziel / "touchstrip.png")
    gebaut.append("screenshots/touchstrip.png")

    # -- Zustände ----------------------------------------------------------
    peak = mit_werten[0].window("session") or mit_werten[0].peak()
    # Abgerundet, damit der echte Wert die gesenkte Schwelle sicher erreicht.
    wert = int(peak.used_pct or 0)
    blatt = _blatt(werkzeug, 2)
    zustaende = [
        (ctx("provider", {"provider": erster}), "normal"),
        (ctx("provider", {"provider": erster, "warn_pct": max(1, wert)}),
         f"Warnung ab {max(1, wert)} %"),
        (ctx("provider", {"provider": erster, "warn_pct": max(1, wert),
                          "crit_pct": max(1, wert)}), f"kritisch ab {max(1, wert)} %"),
    ]
    for spalte, (c, text) in enumerate(zustaende):
        _setze(werkzeug, blatt, male(c), spalte, 0, text)

    echt = poller.snapshot
    poller.snapshot = replace(echt, generated_at=echt.generated_at - timedelta(minutes=10))
    _setze(werkzeug, blatt, male(ctx("provider", {"provider": erster})), 3, 0,
           "Stand 10 Min. alt")
    poller.snapshot = echt

    spalte = 0
    if ohne_login:
        _setze(werkzeug, blatt, male(ctx("provider", {"provider": ohne_login[0].id})), 0, 1,
               "Anmeldung fehlt")
        spalte = 1
    tot = modul.AIUsagePlugin(plugin.manifest, dienste)
    tot.poller.poll(pl.PollSettings(url=TOTER_PORT, claude_fallback=False))
    _setze(werkzeug, blatt, tot.render("provider", {"provider": erster},
                                       ctx("provider", {"provider": erster})),
           spalte, 1, "CodexBar aus")
    blatt.save(ziel / "zustaende.png")
    gebaut.append("screenshots/zustaende.png")

    return gebaut
