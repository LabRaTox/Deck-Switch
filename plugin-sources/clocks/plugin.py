"""Uhren auf Tasten und Dials: die eigene Uhrzeit und eine Weltuhr.

Zwei Aktionen, ein Zeichner. **Meine Uhr** zeigt eine Zeitzone — die des
Systems oder eine gewählte —, **Weltuhr** blättert durch bis zu sechs.
Beide können analog oder digital, in elf Blättern je Art und neun
Farbschemata (siehe :mod:`.zifferblatt`).

**Am Dial gibt es einen eingebauten Editor.** Drücken öffnet ihn und geht
von Feld zu Feld, Drehen ändert den Wert, nach dem letzten Feld oder ein
paar Sekunden ohne Eingabe schließt er sich. Ohne offenen Editor wechselt
Drehen bei „Meine Uhr“ das Blatt und bei der Weltuhr die Zone. Das letzte
Feld von „Meine Uhr“ ist ein Countdown: Minuten eindrehen, drücken, er
läuft.

**Was am Dial geändert wird, bleibt.** Es landet in den Einstellungen der
Belegung und wird kurz danach gespeichert — ohne Pause, damit ein zügiger
Dreh nicht bei jeder Raste die Konfiguration schreibt. Das offene
Formular in der GUI sieht die Änderung erst nach dem nächsten Laden; wer
dort danach etwas ändert, schreibt seine Fassung zurück.

**Was einen Neustart nicht überlebt:** ein laufender Countdown und die
gerade gezeigte Zone der Weltuhr. Beides ist Moment, keine Einstellung.

Der Klang am Ende des Countdowns (``sounds/gong.wav``) ist erzeugt, nicht
aufgenommen: zwei abklingende Sinustöne, 880 und 660 Hz.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

from deckswitch.plugins.base import ActionPlugin

from . import zeit as z
from . import zifferblatt as zb

ACCENT = "#14b8a6"

#: So lange bleibt die Zusatzanzeige nach einem Tastendruck stehen.
DETAIL_S = 4.0

#: So lange bleibt der Editor ohne Eingabe offen.
EDITOR_S = 8.0

#: Pause, nach der am Dial Geändertes gespeichert wird.
SPEICHERN_S = 1.5

#: So lange blinkt ein abgelaufener Countdown, wenn niemand ihn wegdrückt.
FERTIG_S = 20.0

GONG = Path(__file__).resolve().parent / "sounds" / "gong.wav"

#: Minuten, die sich am Dial für den Countdown eindrehen lassen.
COUNTDOWN_MINUTEN = [0, 1, 2, 3, 5, 10, 15, 20, 25, 30, 45, 60, 90, 120]

#: Felder der Weltuhr. Leere bleiben ungenutzt.
WELTZONEN = [f"zone_{i}" for i in range(1, 7)]

#: Schlüssel der Feldnamen im Editor.
FELDNAMEN = {feld: f"feld_{feld}" for feld in (
    "display", "face", "scheme", "hour_format", "seconds", "date", "timezone",
    "show_difference", "countdown")}


class ClocksPlugin(ActionPlugin):
    def __init__(self, manifest, services):
        super().__init__(manifest, services)
        #: Laufende Countdowns je Belegung.
        self._countdowns: dict[str, asyncio.Task] = {}
        self._speichern: asyncio.TimerHandle | None = None

    async def teardown(self):
        for aufgabe in list(self._countdowns.values()):
            aufgabe.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await aufgabe
        self._countdowns.clear()
        if self._speichern is not None:
            # Was noch aussteht, nicht verlieren.
            self._speichern.cancel()
            self._speichern = None
            self.services.runtime.save_config()

    # ======================================================================
    # Einstellungen
    # ======================================================================

    @staticmethod
    def _art(settings) -> str:
        return "digital" if settings.get("display") == "digital" else "analog"

    def _blatt(self, settings) -> str:
        if self._art(settings) == "digital":
            blatt = settings.get("face_digital") or "classic"
            return blatt if blatt in zb.DIGITAL else "classic"
        blatt = settings.get("face_analog") or "classic"
        return blatt if blatt in zb.ANALOG else "classic"

    def _schema(self, settings) -> zb.Schema:
        schema = zb.SCHEMATA.get(settings.get("scheme") or "night", zb.SCHEMATA["night"])[1]
        if settings.get("custom_colors"):
            schema = zb.mit_farben(
                schema,
                blatt=(settings.get("color_face") or "").strip(),
                schrift=(settings.get("color_text") or "").strip(),
                akzent=(settings.get("color_accent") or "").strip(),
            )
        return schema

    def _uhr(self, settings, *, oben: str = "", unten: str = "") -> zb.Uhr:
        return zb.Uhr(
            art=self._art(settings),
            blatt=self._blatt(settings),
            schema=self._schema(settings),
            format24=str(settings.get("hour_format") or "24") != "12",
            sekunden=bool(settings.get("seconds")),
            oben=oben,
            unten=unten,
        )

    @staticmethod
    def _weltzonen(settings) -> list[str]:
        """Die eingetragenen Zonen der Weltuhr, ohne Lücken und Doppelte."""
        zonen = []
        for feld in WELTZONEN:
            name = (settings.get(feld) or "").strip()
            if name and name not in zonen and z.zone(name) is not None:
                zonen.append(name)
        return zonen

    def _weltzone(self, settings, ctx) -> str | None:
        zonen = self._weltzonen(settings)
        if not zonen:
            return None
        return zonen[int(ctx.scratch.get("zone", 0)) % len(zonen)]

    def _speichere_bald(self) -> None:
        """Speichert nach einer kurzen Pause — ein Dreh sind viele Rasten."""
        loop = asyncio.get_running_loop()
        if self._speichern is not None:
            self._speichern.cancel()

        def speichern():
            self._speichern = None
            self.services.runtime.save_config()

        self._speichern = loop.call_later(SPEICHERN_S, speichern)

    # ======================================================================
    # Der Editor am Dial
    # ======================================================================

    def _felder(self, action_id) -> list[str]:
        felder = ["display", "face", "scheme", "hour_format", "seconds", "date"]
        if action_id == "my_clock":
            return [*felder, "timezone", "countdown"]
        return [*felder, "show_difference"]

    def _werte(self, feld, settings) -> list[Any]:
        if feld == "display":
            return ["analog", "digital"]
        if feld == "face":
            return list(zb.DIGITAL if self._art(settings) == "digital" else zb.ANALOG)
        if feld == "scheme":
            return list(zb.SCHEMATA)
        if feld == "hour_format":
            return ["24", "12"]
        if feld in ("seconds", "show_difference"):
            return [False, True]
        if feld == "date":
            return ["none", "date", "weekday", "both"]
        if feld == "timezone":
            zonen = ["", *z.DIAL_ZONEN]
            aktuell = settings.get("timezone") or ""
            if aktuell not in zonen:
                zonen.insert(1, aktuell)
            return zonen
        return COUNTDOWN_MINUTEN

    def _schluessel(self, feld, settings) -> str:
        """Unter welchem Einstellungsnamen ein Editorfeld steht."""
        if feld == "face":
            return "face_digital" if self._art(settings) == "digital" else "face_analog"
        return feld

    def _wert(self, feld, settings, ctx) -> Any:
        if feld == "countdown":
            return int(ctx.scratch.get("countdown_minuten", 0))
        werte = self._werte(feld, settings)
        if feld == "face":
            return self._blatt(settings)
        wert = settings.get(self._schluessel(feld, settings))
        if feld == "show_difference":
            return wert is None or bool(wert)
        if feld == "seconds":
            return bool(wert)
        if feld == "hour_format":
            return "12" if str(wert) == "12" else "24"
        if wert is None and werte:
            return werte[0]
        return wert

    def _wert_text(self, feld, wert, settings) -> str:
        if feld == "display":
            return self.t("anzeige_analog") if wert == "analog" else self.t("anzeige_digital")
        if feld == "face":
            tabelle = zb.DIGITAL if self._art(settings) == "digital" else zb.ANALOG
            eintrag = tabelle.get(wert)
            if eintrag is None:
                return str(wert)
            return self.t(eintrag if isinstance(eintrag, str) else eintrag[0])
        if feld == "scheme":
            return self.t(zb.SCHEMATA.get(wert, zb.SCHEMATA["night"])[0])
        if feld == "hour_format":
            return "24 h" if wert == "24" else "12 h (AM/PM)"
        if feld in ("seconds", "show_difference"):
            return self.t("an" if wert else "aus")
        if feld == "date":
            schluessel = {"none": "datum_none", "date": "datum_date", "weekday": "datum_weekday",
                          "both": "datum_both"}.get(wert)
            return self.t(schluessel) if schluessel else str(wert)
        if feld == "timezone":
            return z.stadt(wert) or self.t("systemzeit")
        if feld == "countdown":
            return self.t("aus") if not wert else self.t("countdown_minuten", minuten=wert)
        return str(wert)

    def _drehe_feld(self, action_id, settings, ctx, delta: int) -> None:
        felder = self._felder(action_id)
        feld = felder[ctx.scratch["editor"]]
        werte = self._werte(feld, settings)
        aktuell = self._wert(feld, settings, ctx)
        try:
            index = werte.index(aktuell)
        except ValueError:
            index = 0
        if feld == "countdown":
            # Der Countdown läuft nicht im Kreis: Nach „aus“ kommen keine
            # zwei Stunden.
            neu = werte[max(0, min(len(werte) - 1, index + delta))]
            ctx.scratch["countdown_minuten"] = neu
            return
        neu = werte[(index + delta) % len(werte)]
        settings[self._schluessel(feld, settings)] = neu
        self._speichere_bald()

    # ======================================================================
    # Eingaben
    # ======================================================================

    async def on_key_down(self, action_id, settings, ctx):
        if action_id == "world_clock":
            ctx.scratch["zone"] = int(ctx.scratch.get("zone", 0)) + 1
        else:
            ctx.scratch["detail_bis"] = time.monotonic() + DETAIL_S
        ctx.request_redraw()

    async def on_dial_push(self, action_id, settings, ctx):
        jetzt = time.monotonic()

        # Ein laufender oder abgelaufener Countdown geht vor: Drücken hält
        # ihn an bzw. räumt ihn ab.
        if self._countdown_aus(ctx):
            ctx.request_redraw()
            return

        felder = self._felder(action_id)
        editor = ctx.scratch.get("editor")
        if editor is None:
            ctx.scratch["editor"] = 0
        else:
            if felder[editor] == "countdown" and int(ctx.scratch.get("countdown_minuten", 0)) > 0:
                ctx.scratch["editor"] = None
                self._countdown_start(ctx, int(ctx.scratch["countdown_minuten"]))
                ctx.request_redraw()
                return
            editor += 1
            ctx.scratch["editor"] = editor if editor < len(felder) else None
        ctx.scratch["editor_bis"] = jetzt + EDITOR_S
        ctx.request_redraw()

    async def on_dial_rotate(self, action_id, settings, delta, ctx):
        if ctx.scratch.get("editor") is not None:
            self._drehe_feld(action_id, settings, ctx, delta)
            ctx.scratch["editor_bis"] = time.monotonic() + EDITOR_S
        elif action_id == "world_clock":
            ctx.scratch["zone"] = int(ctx.scratch.get("zone", 0)) + delta
        else:
            # Ohne Editor blättert Drehen durch die Blätter der gewählten Art.
            werte = self._werte("face", settings)
            index = werte.index(self._blatt(settings)) if self._blatt(settings) in werte else 0
            settings[self._schluessel("face", settings)] = werte[(index + delta) % len(werte)]
            self._speichere_bald()
        ctx.request_redraw()

    async def on_touch(self, action_id, settings, x, y, ctx):
        if self._countdown_aus(ctx):
            pass
        elif action_id == "world_clock":
            ctx.scratch["zone"] = int(ctx.scratch.get("zone", 0)) + 1
        else:
            settings["display"] = "analog" if self._art(settings) == "digital" else "digital"
            self._speichere_bald()
        ctx.request_redraw()

    def on_tick(self, action_id, settings, ctx):
        jetzt = time.monotonic()
        neu = False

        if ctx.scratch.get("editor") is not None and ctx.scratch.get("editor_bis", 0) < jetzt:
            ctx.scratch["editor"] = None
            neu = True
        if ctx.scratch.get("detail_bis") and ctx.scratch["detail_bis"] < jetzt:
            ctx.scratch["detail_bis"] = 0
            neu = True

        # Neu zeichnen, sobald sich an der Anzeige etwas ändert: jede Sekunde
        # mit Sekunden oder Countdown, sonst zum Minutenwechsel.
        sekundengenau = (
            bool(settings.get("seconds"))
            or "countdown" in ctx.scratch
            or ctx.scratch.get("editor") is not None
        )
        stand = time.strftime("%Y%m%d%H%M%S" if sekundengenau else "%Y%m%d%H%M")
        if ctx.scratch.get("stand") != stand:
            ctx.scratch["stand"] = stand
            neu = True
        if neu:
            ctx.request_redraw()

    # ======================================================================
    # Countdown
    # ======================================================================

    def _countdown_start(self, ctx, minuten: int) -> None:
        self._countdown_beenden(ctx.key)
        dauer = minuten * 60
        ctx.scratch["countdown"] = {"ende": time.monotonic() + dauer, "dauer": dauer,
                                    "fertig": 0.0}
        self._countdowns[ctx.key] = asyncio.create_task(
            self._countdown_lauf(ctx), name=f"clocks-countdown-{ctx.key}"
        )

    async def _countdown_lauf(self, ctx) -> None:
        """Wartet auf das Ende, klingelt und räumt nach einer Weile ab.

        Eine eigene Aufgabe statt ``on_tick``: Der Tick erreicht nur die
        Seite, die gerade auf dem Gerät liegt. Ein Countdown, nach dessen
        Start man weiterblättert, würde sonst nie klingeln.
        """
        try:
            stand = ctx.scratch.get("countdown") or {}
            await asyncio.sleep(max(0.0, stand.get("ende", 0) - time.monotonic()))
            stand["fertig"] = time.monotonic()
            self._klingeln(ctx)
            ctx.request_redraw()
            await asyncio.sleep(FERTIG_S)
            ctx.scratch.pop("countdown", None)
            ctx.request_redraw()
        finally:
            self._countdowns.pop(ctx.key, None)

    def _klingeln(self, ctx) -> None:
        klang = self.services.sound
        if klang is None or not GONG.is_file():
            return
        try:
            klang.play(str(GONG), owner=f"clocks:{ctx.key}", volume=80)
        except Exception as exc:  # noqa: BLE001 — ein Klang darf die Uhr nicht stören
            self.log.warning("Countdown-Klang nicht abspielbar: %s", exc)

    def _countdown_beenden(self, schluessel: str) -> None:
        aufgabe = self._countdowns.pop(schluessel, None)
        if aufgabe is not None:
            aufgabe.cancel()

    def _countdown_aus(self, ctx) -> bool:
        """Hält einen laufenden Countdown an. Zurück kommt, ob einer lief."""
        if "countdown" not in ctx.scratch:
            return False
        self._countdown_beenden(ctx.key)
        ctx.scratch.pop("countdown", None)
        if self.services.sound is not None:
            with contextlib.suppress(Exception):
                self.services.sound.stop(f"clocks:{ctx.key}")
        return True

    # ======================================================================
    # Darstellung
    # ======================================================================

    def render(self, action_id, settings, ctx):
        image = self.services.render.background(ctx.size, ctx.appearance, accent=ACCENT)
        if ctx.input_type == "dial":
            if "countdown" in ctx.scratch:
                self._zeichne_countdown(image, settings, ctx)
            elif ctx.scratch.get("editor") is not None:
                self._zeichne_editor(image, action_id, settings, ctx)
            else:
                self._zeichne_segment(image, action_id, settings, ctx)
            return image
        self._zeichne_taste(image, action_id, settings, ctx)
        return image

    def _beschriftung(self, action_id, settings, ctx) -> tuple[str | None, str, str]:
        """Zone, obere und untere Zeile einer Uhr."""
        if action_id == "world_clock":
            zone = self._weltzone(settings, ctx)
            if zone is None:
                return None, "", ""
            oben = z.stadt(zone) if settings.get("show_city", True) else ""
            if settings.get("show_difference", True):
                unten = z.unterschied(zone)
            else:
                unten = z.datum(z.jetzt(zone), settings.get("date") or "none")
            return zone, oben, unten

        zone = (settings.get("timezone") or "").strip()
        jetzt = z.jetzt(zone)
        name = (settings.get("place_name") or "").strip()
        oben = name or z.stadt(zone)
        unten = z.datum(jetzt, settings.get("date") or "none")
        if ctx.scratch.get("detail_bis", 0) > time.monotonic():
            # Nach einem Druck: das volle Datum und wie weit die Zone von
            # UTC weg ist — auch wenn beides sonst ausgeblendet ist.
            unten = z.datum(jetzt, "both")
            oben = name or z.stadt(zone) or f"UTC{z.abstand(jetzt.utcoffset())}"
        return zone, oben, unten

    def _zeichne_taste(self, image, action_id, settings, ctx) -> None:
        zone, oben, unten = self._beschriftung(action_id, settings, ctx)
        if zone is None and action_id == "world_clock":
            self._keine_zone(image)
            return
        zb.zeichne(image, (0, 0, *ctx.size), z.jetzt(zone),
                   self._uhr(settings, oben=oben, unten=unten))

    def _zeichne_segment(self, image, action_id, settings, ctx) -> None:
        breite, hoehe = ctx.size
        zone, oben, unten = self._beschriftung(action_id, settings, ctx)
        if zone is None and action_id == "world_clock":
            self._keine_zone(image)
            return
        jetzt = z.jetzt(zone)
        uhr = self._uhr(settings)

        if uhr.art == "digital":
            zb.zeichne(image, (0, 0, breite, hoehe), jetzt,
                       self._uhr(settings, oben=oben, unten=unten))
            return

        # Analog: das Blatt links, rechts daneben in Worten, was es zeigt.
        zb.zeichne(image, (2, 2, hoehe - 2, hoehe - 2), jetzt, uhr)
        render = self.services.render
        links = hoehe + 6
        rechts_breite = breite - links - 6
        text, tageszeit = z.uhrzeit(jetzt, format24=uhr.format24, sekunden=False)
        farbe = ctx.appearance.label_color
        if oben:
            render.draw_text_at(image, oben, x=links, y=10, size=13, color="#c7c7d1",
                                max_width=rechts_breite)
        render.draw_text_at(image, f"{text} {tageszeit}".strip(), x=links, y=32, size=24,
                            color=farbe, bold=True, max_width=rechts_breite)
        if unten:
            render.draw_text_at(image, unten, x=links, y=hoehe - 26, size=12,
                                color="#9ca3af", max_width=rechts_breite)
        if action_id == "world_clock":
            self._punkte(image, settings, ctx)

    def _punkte(self, image, settings, ctx) -> None:
        """Kleine Punkte unten rechts: welche der Zonen gerade zu sehen ist."""
        zonen = self._weltzonen(settings)
        if len(zonen) < 2:
            return
        aktiv = int(ctx.scratch.get("zone", 0)) % len(zonen)
        draw = ImageDraw.Draw(image)
        x = image.width - 10 - (len(zonen) - 1) * 9
        y = image.height - 9
        for i in range(len(zonen)):
            farbe = (255, 255, 255, 230) if i == aktiv else (255, 255, 255, 70)
            draw.ellipse((x + i * 9 - 2.5, y - 2.5, x + i * 9 + 2.5, y + 2.5), fill=farbe)

    def _zeichne_editor(self, image, action_id, settings, ctx) -> None:
        """Links die Uhr, wie sie mit dem neuen Wert aussieht; rechts das Feld."""
        breite, hoehe = ctx.size
        felder = self._felder(action_id)
        index = min(ctx.scratch["editor"], len(felder) - 1)
        feld = felder[index]

        zone = self._weltzone(settings, ctx) if action_id == "world_clock" else (
            settings.get("timezone") or "")
        zb.zeichne(image, (2, 2, hoehe - 2, hoehe - 2), z.jetzt(zone), self._uhr(settings))

        render = self.services.render
        links = hoehe + 6
        platz = breite - links - 6
        render.draw_text_at(image, f"{self.t(FELDNAMEN[feld])}  {index + 1}/{len(felder)}",
                            x=links, y=8, size=11, color="#9ca3af", max_width=platz)
        wert = self._wert_text(feld, self._wert(feld, settings, ctx), settings)
        render.draw_text_at(image, wert, x=links, y=30, size=18,
                            color=ctx.appearance.label_color, bold=True, max_width=platz)
        start = feld == "countdown" and int(ctx.scratch.get("countdown_minuten", 0)) > 0
        hinweis = self.t("hinweis_starten" if start else "hinweis_weiter")
        render.draw_text_at(image, self.t("hinweis_drehen"), x=links, y=hoehe - 34, size=10,
                            color="#6b7280", max_width=platz)
        render.draw_text_at(image, hinweis, x=links, y=hoehe - 20, size=10,
                            color="#6b7280", max_width=platz)

    def _zeichne_countdown(self, image, settings, ctx) -> None:
        breite, hoehe = ctx.size
        stand = ctx.scratch["countdown"]
        render = self.services.render
        schema = self._schema(settings)
        akzent = "#{:02x}{:02x}{:02x}".format(*schema.akzent[:3])

        if stand.get("fertig"):
            # Blinken im Sekundentakt — aus der Ferne sichtbar.
            if int(time.monotonic() - stand["fertig"]) % 2 == 0:
                rot = Image.new("RGBA", ctx.size, (185, 28, 28, 255))
                image.alpha_composite(rot)
            render.draw_text_at(image, self.t("fertig"), x=breite // 2, y=hoehe // 2 - 18,
                                size=28, color="#ffffff", bold=True, align="center")
            render.draw_text_at(image, self.t("hinweis_stoppen"), x=breite // 2, y=hoehe - 18,
                                size=10, color="#e5e7eb", align="center")
            return

        rest = max(0.0, stand["ende"] - time.monotonic())
        # Aufrunden: 4:59,3 ist noch „05:00“ — sonst stünde direkt nach dem
        # Start schon eine Sekunde weniger da, als eingestellt war.
        sekunden = int(rest) + (1 if rest % 1 else 0)
        stunden, rest_s = divmod(sekunden, 3600)
        minuten, sek = divmod(rest_s, 60)
        text = f"{stunden}:{minuten:02d}:{sek:02d}" if stunden else f"{minuten:02d}:{sek:02d}"

        render.draw_text_at(image, self.t("countdown"), x=10, y=8, size=11,
                            color="#9ca3af")
        uhrzeit, tageszeit = z.uhrzeit(z.jetzt(settings.get("timezone") or ""),
                                       format24=str(settings.get("hour_format") or "24") != "12",
                                       sekunden=False)
        render.draw_text_at(image, f"{uhrzeit} {tageszeit}".strip(), x=breite - 10, y=8,
                            size=11, color="#9ca3af", align="right")
        render.draw_text_at(image, text, x=breite // 2, y=hoehe // 2 - 20, size=32,
                            color=ctx.appearance.label_color, bold=True, align="center")

        # Fortschrittsbalken: wie viel schon vorbei ist.
        draw = ImageDraw.Draw(image)
        anteil = 1 - rest / stand["dauer"] if stand["dauer"] else 1
        draw.rounded_rectangle((10, hoehe - 16, breite - 10, hoehe - 10), radius=3,
                               fill=(255, 255, 255, 40))
        if anteil > 0:
            draw.rounded_rectangle((10, hoehe - 16, 10 + (breite - 20) * anteil, hoehe - 10),
                                   radius=3, fill=akzent)

    def _keine_zone(self, image) -> None:
        render = self.services.render
        render.draw_text(image, self.t("keine_zone"),
                         y=image.height // 2 - 8, size=13, color="#9ca3af")

    # ======================================================================
    # GUI
    # ======================================================================

    def get_dynamic_options(self, source, context=None):
        if source not in ("zones", "zones_world"):
            return []
        leer = self.t("systemzeit") if source == "zones" else "---"
        return [{"value": "", "label": leer}] + [
            {"value": name, "label": z.utc_label(name)} for name in z.alle_zonen()
        ]
