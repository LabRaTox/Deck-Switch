"""Prüft das Timer-Plugin: Zeiten lesen, ablaufen, klingeln, zeichnen.

Keine Attrappe für den Ablauf selbst — der Countdown läuft hier wirklich
gegen die Uhr, nur eben mit einer Sekunde statt fünf Minuten. Attrappiert
ist allein das Abspielen, denn eine Prüfsuite soll nicht klingeln.

Aufruf:

    cd backend
    d=$(mktemp -d); env XDG_CONFIG_HOME=$d XDG_DATA_HOME=$d \\
        ../.venv/bin/python tests/timer_test.py
"""
import _wache  # bricht ab, statt in die echte Config zu schreiben
_wache.sichere_umgebung()

import asyncio
import json
import pathlib
import sys
from datetime import datetime, timedelta

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

PLUGIN_DIR = pathlib.Path(__file__).resolve().parents[2] / "plugin-sources" / "timer"
sys.path.insert(0, str(PLUGIN_DIR))

from deckswitch.config import Appearance, Slot, default_config  # noqa: E402
from deckswitch.plugins.base import Manifest, Services, SlotContext  # noqa: E402
from deckswitch.services.icons import IconService  # noqa: E402
from deckswitch.services.render import RenderService  # noqa: E402

import plugin as timermod  # noqa: E402

FAILS = []


def check(name, bedingung, detail=""):
    print(("  ✔ " if bedingung else "  ✘ ") + name + (f"  ({detail})" if detail else ""))
    if not bedingung:
        FAILS.append(name)


class FakeRuntime:
    def __init__(self):
        self.redraws = 0

    def request_redraw(self, ctx=None):
        self.redraws += 1

    def notify(self, *a, **k):
        pass


class FakeSound:
    """Merkt sich, was geklungen hätte."""

    def __init__(self):
        self.gespielt = []
        self.gestoppt = []

    def play(self, pfad, *, owner, sink="", volume=100, loop=False):
        self.gespielt.append({"pfad": pfad, "owner": owner, "volume": volume,
                              "loop": loop})

    def stop(self, owner):
        self.gestoppt.append(owner)


manifest = Manifest.model_validate(json.loads((PLUGIN_DIR / "manifest.json").read_text()))
config = default_config()
icons = IconService()
services = Services(
    audio=None, icons=icons, render=RenderService(icons), runtime=FakeRuntime(),
    config=config, plugin_dir=PLUGIN_DIR, sound=FakeSound(),
)


def ctx_for(action, settings, *, index=0, input_type="key"):
    slot = Slot(plugin_id="timer", action_id=action, settings=settings,
                appearance=Appearance())
    return SlotContext(
        action_id=action, settings=settings, appearance=slot.appearance,
        input_type=input_type, index=index, page_id="p", profile_id="pr",
        size=(120, 120) if input_type == "key" else (200, 100),
        services=services, slot=slot,
    )


def main() -> int:
    print("== Zeiten lesen ==")
    faelle = [
        ("5:00", 300), ("05:00", 300), ("1:30:00", 5400), ("0:45", 45),
        ("90", 90), ("5m", 300), ("1h30m", 5400), ("90s", 90), ("2h", 7200),
        ("", 300), ("Quatsch", 300), (None, 300), (120, 120),
    ]
    for eingabe, erwartet in faelle:
        ergebnis = timermod.zu_sekunden(eingabe, 300)
        check(f"{eingabe!r} → {erwartet} s", ergebnis == erwartet, str(ergebnis))

    print("\n== Zeiten schreiben ==")
    for sekunden, erwartet in ((0, "00:00"), (59, "00:59"), (60, "01:00"),
                               (3599, "59:59"), (3600, "1:00:00"), (5445, "1:30:45")):
        check(f"{sekunden} s → {erwartet}", timermod.als_text(sekunden) == erwartet,
              timermod.als_text(sekunden))
    check("die laufende Sekunde wird aufgerundet", timermod.als_text(0.2) == "00:01",
          timermod.als_text(0.2))
    check("die Stoppuhr rundet ab", timermod.als_text(0.9, aufrunden=False) == "00:00")

    print("\n== Uhrzeiten ==")
    for eingabe, erwartet in (("07:30", 450), ("7:30", 450), ("0730", 450),
                              ("23:59", 1439), ("25:00", 420), ("", 420)):
        check(f"{eingabe!r} → {erwartet}", timermod.uhrzeit_zu_minuten(eingabe) == erwartet,
              str(timermod.uhrzeit_zu_minuten(eingabe)))
    check("450 → 07:30", timermod.minuten_als_uhrzeit(450) == "07:30")

    return asyncio.run(laufzeit())


async def laufzeit() -> int:
    plugin = timermod.TimerPlugin(manifest, services)
    await plugin.setup()
    klang: FakeSound = services.sound
    try:
        print("\n== Ein Countdown läuft wirklich ab ==")
        einstellungen = {"duration": "0:01", "sound": "bell", "volume": 70}
        ctx = ctx_for("countdown", einstellungen)

        check("vor dem Start ist er bereit",
              plugin.get_state("countdown", einstellungen, ctx) == "bereit",
              plugin.get_state("countdown", einstellungen, ctx))
        check("und zeigt die eingestellte Dauer",
              plugin._anzeige("countdown", einstellungen, plugin._hole(
                  "countdown", einstellungen, ctx)) == "00:01")

        plugin.on_key_down("countdown", einstellungen, ctx)
        check("nach dem Druck läuft er",
              plugin.get_state("countdown", einstellungen, ctx) == "laeuft")

        await asyncio.sleep(1.4)
        check("er hat von selbst geklingelt", len(klang.gespielt) == 1,
              json.dumps(klang.gespielt))
        if klang.gespielt:
            gespielt = klang.gespielt[0]
            check("mit der mitgelieferten Datei",
                  gespielt["pfad"].endswith("sounds/klingel.wav"), gespielt["pfad"])
            check("die es auch gibt", pathlib.Path(gespielt["pfad"]).is_file())
            check("und der eingestellten Lautstärke", gespielt["volume"] == 70,
                  str(gespielt["volume"]))
            check("ein Countdown klingelt einmal", gespielt["loop"] is False)
        check("er steht jetzt auf abgelaufen",
              plugin.get_state("countdown", einstellungen, ctx) == "abgelaufen",
              plugin.get_state("countdown", einstellungen, ctx))

        plugin.on_key_down("countdown", einstellungen, ctx)
        check("ein Druck stellt ihn ab",
              plugin.get_state("countdown", einstellungen, ctx) == "bereit")
        check("und beendet den Klang", ctx.key in klang.gestoppt)

        print("\n== Pause und Zurücksetzen ==")
        einstellungen = {"duration": "10:00"}
        ctx = ctx_for("countdown", einstellungen, index=1)
        plugin.on_key_down("countdown", einstellungen, ctx)
        await asyncio.sleep(0.3)
        plugin.on_key_down("countdown", einstellungen, ctx)
        lauf = plugin._hole("countdown", einstellungen, ctx)
        pausiert_bei = lauf.verstrichen()
        check("ein zweiter Druck pausiert",
              plugin.get_state("countdown", einstellungen, ctx) == "pausiert")
        await asyncio.sleep(0.3)
        check("in der Pause steht die Uhr still",
              abs(lauf.verstrichen() - pausiert_bei) < 0.02,
              f"{pausiert_bei:.3f} → {lauf.verstrichen():.3f}")

        zurueck = dict(einstellungen, on_press="reset")
        plugin.on_key_down("countdown", zurueck, ctx)
        check("„setzt zurück“ tut das auch",
              plugin.get_state("countdown", zurueck, ctx) == "bereit")

        print("\n== Zwei Belegungen stören sich nicht ==")
        a = ctx_for("countdown", {"duration": "10:00"}, index=2)
        b = ctx_for("countdown", {"duration": "10:00"}, index=3)
        plugin.on_key_down("countdown", a.settings, a)
        check("die eine läuft", plugin.get_state("countdown", a.settings, a) == "laeuft")
        check("die andere nicht",
              plugin.get_state("countdown", b.settings, b) == "bereit")

        print("\n== Am Dial lässt sich die Zeit stellen ==")
        einstellungen = {"duration": "5:00", "step": 30}
        ctx = ctx_for("countdown", einstellungen, index=0, input_type="dial")
        lauf = plugin._hole("countdown", einstellungen, ctx)
        plugin.on_dial_rotate("countdown", einstellungen, 2, ctx)
        check("zwei Rasten nach rechts sind eine Minute mehr",
              plugin._anzeige("countdown", einstellungen, lauf) == "06:00",
              plugin._anzeige("countdown", einstellungen, lauf))
        plugin.on_dial_rotate("countdown", einstellungen, -20, ctx)
        check("unter null geht es nicht",
              plugin._anzeige("countdown", einstellungen, lauf) == "00:00",
              plugin._anzeige("countdown", einstellungen, lauf))

        print("\n== Die Stoppuhr zählt hoch ==")
        einstellungen = {}
        ctx = ctx_for("stopwatch", einstellungen, index=4)
        plugin.on_key_down("stopwatch", einstellungen, ctx)
        await asyncio.sleep(1.1)
        lauf = plugin._hole("stopwatch", einstellungen, ctx)
        check("nach gut einer Sekunde steht 00:01",
              plugin._anzeige("stopwatch", einstellungen, lauf) == "00:01",
              plugin._anzeige("stopwatch", einstellungen, lauf))
        plugin.on_key_down("stopwatch", einstellungen, ctx)
        check("ein Druck hält sie an",
              plugin.get_state("stopwatch", einstellungen, ctx) == "pausiert")
        check("und sie klingelt nicht", len(klang.gespielt) == 1, str(len(klang.gespielt)))

        print("\n== Der Wecker ==")
        gleich = (datetime.now() + timedelta(minutes=1)).strftime("%H:%M")
        jetzt = datetime.now().strftime("%H:%M")
        ctx = ctx_for("alarm", {"time": gleich, "days": "daily", "armed": True}, index=5)
        lauf = plugin._hole("alarm", ctx.settings, ctx)
        check("eine Minute vor der Zeit klingelt er nicht",
              not plugin._wecker_faellig(lauf, ctx.settings))

        faellig = {"time": jetzt, "days": "daily", "armed": True}
        check("zur eingestellten Minute schon",
              plugin._wecker_faellig(lauf, faellig))
        check("aber nicht zweimal in derselben Minute",
              (lauf.__setattr__("zuletzt_geklingelt",
                                datetime.now().strftime("%Y-%m-%d %H:%M")),
               not plugin._wecker_faellig(lauf, faellig))[1])
        lauf.zuletzt_geklingelt = ""

        heute_wochentag = datetime.now().weekday() < 5
        check("Montag bis Freitag gilt nur werktags",
              plugin._wecker_faellig(lauf, dict(faellig, days="weekdays"))
              == heute_wochentag,
              "heute ist " + ("ein Werktag" if heute_wochentag else "Wochenende"))
        check("ein ausgeschalteter Wecker klingelt nie",
              not plugin._wecker_faellig(lauf, dict(faellig, armed=False)))

        plugin.on_key_down("alarm", ctx.settings, ctx)
        check("der Druck schaltet ihn aus",
              plugin.get_state("alarm", ctx.settings, ctx) == "aus",
              plugin.get_state("alarm", ctx.settings, ctx))
        plugin.on_key_down("alarm", ctx.settings, ctx)
        check("und wieder scharf",
              plugin.get_state("alarm", ctx.settings, ctx) == "scharf")

        # Am Dial: eine eigene Belegung mit eigener Uhr — dieselbe Aktion auf
        # Taste und Dial teilt sich nichts, und das ist Absicht.
        dial = ctx_for("alarm", dict(ctx.settings), index=5, input_type="dial")
        plugin.on_dial_rotate("alarm", dial.settings, 3, dial)
        dial_lauf = plugin._hole("alarm", dial.settings, dial)
        erwartet = timermod.minuten_als_uhrzeit(
            timermod.uhrzeit_zu_minuten(gleich) + 15)
        check("am Dial geht die Weckzeit in Fünf-Minuten-Schritten",
              plugin._anzeige("alarm", dial.settings, dial_lauf) == erwartet,
              f"{plugin._anzeige('alarm', dial.settings, dial_lauf)} statt {erwartet}")
        check("die Uhr der Taste bleibt davon unberührt",
              plugin._anzeige("alarm", ctx.settings, lauf) == gleich,
              plugin._anzeige("alarm", ctx.settings, lauf))

        print("\n== Wann der Wecker das nächste Mal klingelt ==")
        # Feste Zeitpunkte statt „jetzt": Sonst hinge das Ergebnis davon ab,
        # an welchem Wochentag die Suite läuft — und genau die Wochentage
        # sind hier der Punkt.
        SAMSTAG = datetime(2026, 8, 22, 20, 0)   # Samstagabend
        DIENSTAG = datetime(2026, 8, 18, 6, 0)   # Dienstagmorgen

        wecker_ctx = ctx_for("alarm", {"time": "07:00"}, index=10)
        lauf = plugin._hole("alarm", wecker_ctx.settings, wecker_ctx)

        def termin(tage, jetzt, zeit="07:00"):
            return plugin._naechster_termin(lauf, {"time": zeit, "days": tage,
                                                   "armed": True}, jetzt)

        check("täglich: heute Abend heißt morgen früh",
              termin("daily", SAMSTAG) == datetime(2026, 8, 23, 7, 0),
              str(termin("daily", SAMSTAG)))
        check("täglich: morgens vor der Zeit heißt noch heute",
              termin("daily", DIENSTAG) == datetime(2026, 8, 18, 7, 0),
              str(termin("daily", DIENSTAG)))
        check("Mo–Fr: am Samstagabend erst am Montag",
              termin("weekdays", SAMSTAG) == datetime(2026, 8, 24, 7, 0),
              str(termin("weekdays", SAMSTAG)))
        check("Wochenende: am Dienstagmorgen erst am Samstag",
              termin("weekend", DIENSTAG) == datetime(2026, 8, 22, 7, 0),
              str(termin("weekend", DIENSTAG)))

        check("und die Anzeige nennt die Tage dazwischen",
              plugin._restzeit(datetime(2026, 8, 24, 7, 0) - SAMSTAG) == "in 1 Tag 11 h",
              plugin._restzeit(datetime(2026, 8, 24, 7, 0) - SAMSTAG))
        check("Mehrzahl, wenn es mehrere sind",
              plugin._restzeit(datetime(2026, 8, 22, 7, 0) - DIENSTAG) == "in 4 Tagen 1 h",
              plugin._restzeit(datetime(2026, 8, 22, 7, 0) - DIENSTAG))
        check("unter einem Tag stehen Stunden und Minuten",
              plugin._restzeit(timedelta(hours=3, minutes=5)) == "in 3 h 05 min",
              plugin._restzeit(timedelta(hours=3, minutes=5)))
        check("unter einer Stunde nur Minuten",
              plugin._restzeit(timedelta(minutes=42)) == "in 42 min",
              plugin._restzeit(timedelta(minutes=42)))
        check("und in der letzten Minute steht „jetzt“",
              plugin._restzeit(timedelta(seconds=20)) == "jetzt",
              plugin._restzeit(timedelta(seconds=20)))

        print("\n== Ein einmaliger Wecker ist danach vorbei ==")
        einmal = ctx_for("alarm", {"time": datetime.now().strftime("%H:%M"),
                                   "days": "once", "armed": True, "sound": "none"},
                         index=11)
        lauf_einmal = plugin._hole("alarm", einmal.settings, einmal)
        plugin._runde()
        check("er klingelt einmal", lauf_einmal.fertig)
        plugin.on_key_down("alarm", einmal.settings, einmal)
        check("der Druck stellt ihn ab", not lauf_einmal.fertig)
        check("und er bleibt aufgebraucht", lauf_einmal.verbraucht,
              str(lauf_einmal.verbraucht))
        check("dann steht keine Restzeit mehr da",
              plugin._zusatz("alarm", einmal.settings, lauf_einmal) == "",
              plugin._zusatz("alarm", einmal.settings, lauf_einmal))
        check("und es gibt keinen Termin mehr",
              plugin._naechster_termin(lauf_einmal, einmal.settings) is None)
        check("auch der Balken bleibt weg",
              plugin._fortschritt("alarm", einmal.settings, lauf_einmal) is None)
        plugin.on_key_down("alarm", einmal.settings, einmal)
        check("ein Druck macht ihn wieder scharf",
              not lauf_einmal.verbraucht
              and plugin._naechster_termin(lauf_einmal, einmal.settings) is not None)

        print("\n== Der Wecker klingelt, bis jemand drückt ==")
        wecker = ctx_for("alarm", {"time": datetime.now().strftime("%H:%M"),
                                   "days": "daily", "armed": True, "volume": 60},
                         index=9)
        plugin._hole("alarm", wecker.settings, wecker)
        vorher = len(klang.gespielt)
        plugin._runde()
        check("er klingelt", len(klang.gespielt) == vorher + 1,
              str(len(klang.gespielt) - vorher))
        if len(klang.gespielt) > vorher:
            check("und zwar in Schleife", klang.gespielt[-1]["loop"] is True,
                  json.dumps(klang.gespielt[-1]))
        check("die Kachel zeigt es an",
              plugin.get_state("alarm", wecker.settings, wecker) == "klingelt",
              plugin.get_state("alarm", wecker.settings, wecker))

        plugin._runde()
        check("er fängt nicht immer wieder von vorn an",
              len(klang.gespielt) == vorher + 1, str(len(klang.gespielt) - vorher))

        plugin.on_key_down("alarm", wecker.settings, wecker)
        check("der Druck beendet ihn", wecker.key in klang.gestoppt)
        check("und die Kachel ist wieder ruhig",
              plugin.get_state("alarm", wecker.settings, wecker) != "klingelt",
              plugin.get_state("alarm", wecker.settings, wecker))

        einmal = dict(wecker.settings, repeat=False)
        lauf_wecker = plugin._hole("alarm", einmal, wecker)
        lauf_wecker.zuletzt_geklingelt = ""
        plugin._runde()
        check("abgeschaltet klingelt er nur einmal",
              klang.gespielt[-1]["loop"] is False, json.dumps(klang.gespielt[-1]))
        plugin.on_key_down("alarm", einmal, wecker)

        print("\n== Der Rahmen der Stoppuhr ==")
        # Gemessen wird am Bild, nicht am Zustand: Der Rahmen ist genau dann
        # etwas wert, wenn er auch wirklich gemalt wird.
        def randfarbe(bild):
            """Die auffälligste Farbe auf dem Rand der Kachel."""
            breite, hoehe = bild.size
            punkte = [bild.getpixel((breite // 2, 1)), bild.getpixel((breite // 2, hoehe - 2)),
                      bild.getpixel((1, hoehe // 2)), bild.getpixel((breite - 2, hoehe // 2))]
            return max(punkte, key=lambda p: p[0] + p[1] + p[2])

        def nah(farbe, hex_wert, toleranz=40):
            soll = tuple(int(hex_wert[i:i + 2], 16) for i in (1, 3, 5))
            return all(abs(a - b) <= toleranz for a, b in zip(farbe[:3], soll))

        ctx = ctx_for("stopwatch", {}, index=7)
        ruhe = randfarbe(plugin.render("stopwatch", ctx.settings, ctx))
        check("im Ruhezustand ist der Rand unauffällig",
              not nah(ruhe, timermod.RAHMEN_LAEUFT) and not nah(ruhe, timermod.RAHMEN_PAUSE),
              str(ruhe))

        plugin.on_key_down("stopwatch", ctx.settings, ctx)
        laufend = randfarbe(plugin.render("stopwatch", ctx.settings, ctx))
        check("laufend ist er grün", nah(laufend, timermod.RAHMEN_LAEUFT),
              f"{laufend} statt {timermod.RAHMEN_LAEUFT}")

        plugin.on_key_down("stopwatch", ctx.settings, ctx)
        stehend = randfarbe(plugin.render("stopwatch", ctx.settings, ctx))
        check("angehalten ist er bernstein", nah(stehend, timermod.RAHMEN_PAUSE),
              f"{stehend} statt {timermod.RAHMEN_PAUSE}")

        dial = ctx_for("stopwatch", {}, index=7, input_type="dial")
        plugin.on_dial_push("stopwatch", dial.settings, dial)
        check("am Dial genauso",
              nah(randfarbe(plugin.render("stopwatch", dial.settings, dial)),
                  timermod.RAHMEN_LAEUFT))

        laufender_countdown = ctx_for("countdown", {"duration": "5:00"}, index=8)
        plugin.on_key_down("countdown", laufender_countdown.settings, laufender_countdown)
        rand = randfarbe(plugin.render("countdown", laufender_countdown.settings,
                                       laufender_countdown))
        check("der Countdown bekommt keinen — er hat seinen Balken",
              not nah(rand, timermod.RAHMEN_LAEUFT), str(rand))

        print("\n== Gezeichnet wird auch ==")
        for aktion in ("countdown", "stopwatch", "alarm"):
            for art, groesse in (("key", (120, 120)), ("dial", (200, 100))):
                c = ctx_for(aktion, {"duration": "5:00", "time": "07:30"},
                            index=6, input_type=art)
                bild = plugin.render(aktion, c.settings, c)
                check(f"{aktion} als {art}", bild.size == groesse, str(bild.size))
    finally:
        await plugin.teardown()

    print()
    if FAILS:
        print(f"FEHLGESCHLAGEN: {len(FAILS)} — {', '.join(FAILS)}")
        return 1
    print("Alle Prüfungen bestanden.")
    return 0


sys.exit(main())
