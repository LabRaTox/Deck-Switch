"""Twitch auf dem Deck: Stream steuern, Chat moderieren, zuschauen lassen.

Vierzehn Aktionen um eine Idee herum: Was man während eines Streams tut,
soll ein Tastendruck sein und kein Fensterwechsel. Titel umstellen, Werbung
schalten, einen Clip schneiden, den Chat langsamer machen — dafür will
niemand aus dem Spiel heraus.

**Wie die Anmeldung läuft.** Twitch verlangt zu jedem Aufruf eine
Client-ID; die gehört zu einer registrierten App und wird mitgeliefert —
einzurichten gibt es nichts. Ein Geheimnis kommt nicht vor, denn was auf
fremden Rechnern liegt, ist keins mehr. Stattdessen der Gerätecode-Weg: Das
Plugin holt einen Code, der Benutzer tippt ihn auf ``twitch.tv/activate``
ein, fertig. Das Token liegt danach unter
``~/.config/deckswitch/twitch-token.json``, nur für den Benutzer lesbar.

**Was hier nie passiert: im Zeichnen warten.** ``render`` greift
ausschließlich auf gespiegelte Werte zu. Geholt werden sie im Hintergrund;
steht dort noch nichts, zeigt die Kachel das ehrlich an, statt die Anzeige
für eine Netzrunde anzuhalten.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import time
from typing import Any

from deckswitch import paths
from deckswitch.plugins.base import ActionPlugin

from .twitch_api import Anmeldung, NichtAngemeldet, TwitchApi, TwitchError

log = logging.getLogger(__name__)

ACCENT = "#9146ff"

#: Hier liegt das Token. Neben der Konfiguration und nicht im Cache: Ohne
#: die Datei muss man sich neu anmelden, und das ist keine Kleinigkeit.
TOKEN_DATEI = paths.CONFIG_DIR / "twitch-token.json"

#: Die App, die dieses Plugin bei Twitch vertritt. Öffentlich und ohne
#: Geheimnis — genau dafür ist der Gerätecode-Weg gedacht: Sie steht offen
#: im Quelltext, und das ist kein Versehen, sondern der Sinn der Sache. Ein
#: Eingabefeld dafür gibt es nicht; niemand soll erst eine eigene App
#: registrieren müssen, um einen Streamtitel zu ändern.
EINGEBAUTE_CLIENT_ID = "qvmv6inuv0jgrbzz0ljf0dvb38gkwk"

#: Wie oft der Hintergrund nachsieht, solange etwas angezeigt wird.
AUFFRISCHEN_S = 20.0

#: Nach einem Raid-Start bleibt der Countdown so lange sichtbar. Twitch
#: nennt keine Restzeit; 90 Sekunden sind die Vorgabe der Oberfläche.
RAID_COUNTDOWN_S = 90.0

FARBE_LIVE = "#22c55e"
FARBE_OFFLINE = "#6b7280"

#: Die paar Wörter auf den Kacheln, in beiden Sprachen der Oberfläche.
WOERTER = {
    "de": {"offline": "offline", "live": "live", "viewers": "Zuschauer",
           "followers": "Follower", "uptime": "Laufzeit", "no_login": "nicht verbunden",
           "loading": "…", "running": "läuft", "locked": "gesperrt", "none": "keine"},
    "en": {"offline": "offline", "live": "live", "viewers": "viewers",
           "followers": "followers", "uptime": "uptime", "no_login": "not connected",
           "loading": "…", "running": "running", "locked": "locked", "none": "none"},
}


def _lade_token() -> dict[str, Any]:
    try:
        return json.loads(TOKEN_DATEI.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _schreib_token(daten: dict[str, Any]) -> None:
    TOKEN_DATEI.parent.mkdir(parents=True, exist_ok=True)
    # Erst schreiben, dann die Rechte setzen, dann tauschen: Zwischen
    # Anlegen und chmod stünde die Datei sonst kurz für alle offen.
    vorlaeufig = TOKEN_DATEI.with_suffix(".neu")
    vorlaeufig.write_text(json.dumps(daten, indent=2) + "\n", encoding="utf-8")
    os.chmod(vorlaeufig, 0o600)
    vorlaeufig.replace(TOKEN_DATEI)


def _loesche_token() -> None:
    TOKEN_DATEI.unlink(missing_ok=True)


def _dauer(sekunden: float) -> str:
    """Laufzeit als ``2:14`` bzw. ``12:03:07``."""
    gesamt = max(0, int(sekunden))
    stunden, rest = divmod(gesamt, 3600)
    minuten, sek = divmod(rest, 60)
    if stunden:
        return f"{stunden}:{minuten:02d}:{sek:02d}"
    return f"{minuten}:{sek:02d}"


def _zahl(wert: int) -> str:
    """Große Zahlen kurz: 1234 → 1,2k. Auf einer Taste ist wenig Platz."""
    if wert < 1000:
        return str(wert)
    if wert < 1_000_000:
        knapp = wert / 1000
        return f"{knapp:.1f}k".replace(".", ",") if knapp < 10 else f"{round(knapp)}k"
    return f"{wert / 1_000_000:.1f}M".replace(".", ",")


def _oeffne(adresse: str) -> None:
    """Eine Adresse im Browser — abgekoppelt, damit sie uns nicht anhängt."""
    subprocess.Popen(
        ["xdg-open", adresse],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL, start_new_session=True,
    )


def _teile(text: str) -> list[str]:
    """``"Ja | Nein"`` → ``["Ja", "Nein"]``."""
    return [t.strip() for t in str(text or "").split("|") if t.strip()]


class TwitchPlugin(ActionPlugin):
    def __init__(self, manifest, services) -> None:
        super().__init__(manifest, services)
        self.api = TwitchApi()
        self.fehler = ""

        # Gespiegelter Zustand — nur daraus zeichnet render().
        self.stream: dict[str, Any] | None = None
        self.follower = 0
        self.kanal: dict[str, Any] = {}
        self.chat: dict[str, Any] = {}
        self.umfrage: dict[str, Any] | None = None
        self.vorhersage: dict[str, Any] | None = None
        self.stand_geholt = 0.0

        self._raid_bis = 0.0
        self._rueckfrage: dict[str, float] = {}
        self._laufende_anmeldung: dict[str, Any] = {}
        self._auffrischer: asyncio.Task | None = None
        self._holt = asyncio.Lock()

    # -- Lebenszyklus ------------------------------------------------------

    async def setup(self) -> None:
        self._uebernimm_konfiguration()
        gespeichert = _lade_token()
        if gespeichert:
            self.api.anmeldung = Anmeldung.aus_dict(gespeichert)
        self._auffrischer = asyncio.create_task(self._schleife(), name="twitch-auffrischen")

    async def teardown(self) -> None:
        if self._auffrischer is not None:
            self._auffrischer.cancel()
            try:
                await self._auffrischer
            except asyncio.CancelledError:
                pass
            self._auffrischer = None

    def on_plugin_config_changed(self, config: dict[str, Any]) -> None:
        self._uebernimm_konfiguration()

    def _uebernimm_konfiguration(self) -> None:
        self.api.client_id = EINGEBAUTE_CLIENT_ID
        # Kann nur passieren, wenn jemand das Plugin ohne Kennung baut —
        # dann aber sofort und mit klarer Ansage, statt beim ersten
        # Tastendruck.
        self.fehler = "" if self.api.client_id else (
            "Diesem Plugin fehlt die Client-ID der Twitch-App. So gebaut "
            "kann es sich nicht anmelden."
        )

    def get_status(self) -> dict[str, Any] | None:
        if self.fehler:
            return {"connected": False, "detail": self.fehler}
        if not self.api.angemeldet:
            return {"connected": False, "detail": "nicht mit Twitch verbunden"}
        name = self.api.anmeldung.anzeigename or self.api.anmeldung.login
        if self.stream:
            zuschauer = int(self.stream.get("viewer_count") or 0)
            return {"connected": True, "detail": f"{name} — live, {zuschauer} Zuschauer"}
        return {"connected": True, "detail": f"{name} — offline"}

    # -- Der Hintergrund ---------------------------------------------------

    async def _schleife(self) -> None:
        """Hält den Spiegel aktuell, solange jemand hinsieht."""
        while True:
            await asyncio.sleep(AUFFRISCHEN_S)
            if not self.api.angemeldet:
                continue
            try:
                await self._hole_stand()
            except Exception as exc:  # noqa: BLE001 — die Schleife darf nie sterben
                log.debug("Twitch: Auffrischen fehlgeschlagen: %s", exc)

    async def _hole_stand(self) -> None:
        """Alles, was die Anzeigen brauchen — in einem Rutsch, im Thread."""
        if self._holt.locked():
            return
        async with self._holt:
            def arbeit():
                ergebnis: dict[str, Any] = {}
                ergebnis["stream"] = self.api.stream()
                ergebnis["kanal"] = self.api.kanal()
                ergebnis["follower"] = self.api.follower()
                ergebnis["chat"] = self.api.chat_einstellungen()
                ergebnis["umfrage"] = self._aktive_umfrage()
                ergebnis["vorhersage"] = self._aktive_vorhersage()
                return ergebnis

            try:
                stand = await asyncio.to_thread(arbeit)
            except NichtAngemeldet:
                return
            except TwitchError as exc:
                self.notify_error(f"Twitch: {exc}")
                return

            self.stream = stand["stream"]
            self.kanal = stand["kanal"]
            self.follower = stand["follower"]
            self.chat = stand["chat"]
            self.umfrage = stand["umfrage"]
            self.vorhersage = stand["vorhersage"]
            self.stand_geholt = time.monotonic()
            self.services.runtime.request_redraw()

    def _aktive_umfrage(self) -> dict[str, Any] | None:
        daten = self.api.helix("GET", "/polls", abfrage={
            "broadcaster_id": self.api.anmeldung.benutzer_id, "first": 1,
        })
        eintraege = daten.get("data") or []
        if eintraege and str(eintraege[0].get("status")) == "ACTIVE":
            return eintraege[0]
        return None

    def _aktive_vorhersage(self) -> dict[str, Any] | None:
        daten = self.api.helix("GET", "/predictions", abfrage={
            "broadcaster_id": self.api.anmeldung.benutzer_id, "first": 1,
        })
        eintraege = daten.get("data") or []
        if eintraege and str(eintraege[0].get("status")) in ("ACTIVE", "LOCKED"):
            return eintraege[0]
        return None

    # -- Anmeldung über die GUI -------------------------------------------

    async def gui_command(self, command: str, payload: dict[str, Any]) -> dict[str, Any]:
        if command == "status":
            return {
                "angemeldet": self.api.angemeldet,
                "konto": self.api.anmeldung.anzeigename or self.api.anmeldung.login,
                "fehler": self.fehler,
            }
        if command == "verbinden":
            return await self._verbinden()
        if command == "nachfragen":
            return await self._nachfragen()
        if command == "abmelden":
            await asyncio.to_thread(self.api.abmelden)
            _loesche_token()
            self._leere_spiegel()
            return {"angemeldet": False}
        raise NotImplementedError(f"Twitch kennt kein Kommando '{command}'")

    async def _verbinden(self) -> dict[str, Any]:
        daten = await asyncio.to_thread(self.api.geraetecode)
        self._laufende_anmeldung = {
            "device_code": str(daten.get("device_code") or ""),
            "interval": float(daten.get("interval") or 5),
            "endet": time.monotonic() + float(daten.get("expires_in") or 1800),
        }
        return {
            "code": daten.get("user_code"),
            "url": daten.get("verification_uri") or "https://www.twitch.tv/activate",
            "interval": self._laufende_anmeldung["interval"],
        }

    async def _nachfragen(self) -> dict[str, Any]:
        laufend = self._laufende_anmeldung
        if not laufend:
            return {"angemeldet": self.api.angemeldet, "wartet": False}
        if time.monotonic() > laufend["endet"]:
            self._laufende_anmeldung = {}
            raise TwitchError("Der Code ist abgelaufen — bitte neu anfangen")

        anmeldung = await asyncio.to_thread(
            self.api.code_einloesen, laufend["device_code"]
        )
        if not anmeldung.access_token:
            return {"angemeldet": False, "wartet": True}

        self._laufende_anmeldung = {}
        _schreib_token(anmeldung.als_dict())
        await self._hole_stand()
        return {
            "angemeldet": True,
            "wartet": False,
            "konto": anmeldung.anzeigename or anmeldung.login,
        }

    def _leere_spiegel(self) -> None:
        self.stream = None
        self.kanal = {}
        self.chat = {}
        self.follower = 0
        self.umfrage = None
        self.vorhersage = None
        self.services.runtime.request_redraw()

    # -- Auswahllisten -----------------------------------------------------

    def get_dynamic_options(self, source, context=None):
        context = context or {}
        suche = str(context.get("search") or "").strip()
        if not suche or not self.api.angemeldet:
            return []
        try:
            if source == "kategorien":
                return [
                    {"value": eintrag["name"], "label": eintrag["name"]}
                    for eintrag in self.api.kategorien(suche)
                ]
            if source == "kanaele":
                return [
                    {"value": eintrag["broadcaster_login"],
                     "label": eintrag.get("display_name") or eintrag["broadcaster_login"]}
                    for eintrag in self.api.kanal_suchen(suche)
                ]
        except TwitchError as exc:
            self.notify_error(f"Twitch: {exc}")
        return []

    # -- Die Aktionen ------------------------------------------------------

    async def on_key_down(self, action_id, settings, ctx):
        await self._ausfuehren(action_id, settings, ctx)

    async def on_dial_push(self, action_id, settings, ctx):
        await self._ausfuehren(action_id, settings, ctx)

    async def _ausfuehren(self, action_id, settings, ctx) -> None:
        if self.fehler:
            self.notify_error(self.fehler)
            return
        if not self.api.angemeldet:
            self.notify_error("Für Twitch ist niemand verbunden — Plugin-Einstellungen")
            return

        # Was sich nicht zurücknehmen lässt, fragt einmal nach: Der erste
        # Druck bewaffnet, der zweite löst aus. Ohne Antwort verfällt es.
        if settings.get("confirm") and not self._bestaetigt(ctx.key):
            self.notify_info("Noch einmal drücken zum Auslösen")
            ctx.request_redraw()
            return

        try:
            await asyncio.to_thread(self._arbeit, action_id, dict(settings), ctx.key)
        except TwitchError as exc:
            self.notify_error(f"{action_id}: {exc}")
        else:
            await self._hole_stand()
        ctx.request_redraw()

    def _bestaetigt(self, schluessel: str) -> bool:
        bis = self._rueckfrage.get(schluessel, 0.0)
        if time.monotonic() < bis:
            self._rueckfrage.pop(schluessel, None)
            return True
        self._rueckfrage[schluessel] = time.monotonic() + 5.0
        return False

    def _arbeit(self, action_id: str, settings: dict[str, Any], schluessel: str) -> None:
        """Alles, was mit Twitch spricht — läuft in einem Thread."""
        ich = self.api.anmeldung.benutzer_id

        if action_id == "title":
            rumpf: dict[str, Any] = {}
            titel = str(settings.get("title") or "").strip()
            if titel:
                rumpf["title"] = titel
            kategorie = str(settings.get("category") or "").strip()
            if kategorie:
                rumpf["game_id"] = self._kategorie_id(kategorie)
            if not rumpf:
                raise TwitchError("Für diese Taste ist kein Titel eingetragen")
            self.api.helix("PATCH", "/channels", abfrage={"broadcaster_id": ich},
                           rumpf=rumpf)
            self.api.vergiss("kanal")

        elif action_id == "category":
            name = str(settings.get("category") or "").strip()
            if not name:
                raise TwitchError("Für diese Taste ist keine Kategorie eingetragen")
            self.api.helix("PATCH", "/channels", abfrage={"broadcaster_id": ich},
                           rumpf={"game_id": self._kategorie_id(name)})
            self.api.vergiss("kanal")

        elif action_id == "commercial":
            self.api.helix("POST", "/channels/commercial", rumpf={
                "broadcaster_id": ich,
                "length": int(settings.get("length") or 60),
            })

        elif action_id == "marker":
            rumpf = {"user_id": ich}
            text = str(settings.get("description") or "").strip()
            if text:
                rumpf["description"] = text[:140]
            self.api.helix("POST", "/streams/markers", rumpf=rumpf)

        elif action_id == "clip":
            antwort = self.api.helix("POST", "/clips", abfrage={
                "broadcaster_id": ich,
                "has_delay": "true" if settings.get("delay") else "false",
            })
            eintraege = antwort.get("data") or []
            if eintraege and settings.get("open_editor"):
                adresse = str(eintraege[0].get("edit_url") or "")
                # Nur https, und die Adresse kommt von Twitch selbst — aber
                # geprüft wird sie trotzdem, bevor sie an den Browser geht.
                if adresse.startswith("https://"):
                    _oeffne(adresse)

        elif action_id == "raid":
            if time.monotonic() < self._raid_bis:
                self.api.helix("DELETE", "/raids", abfrage={"broadcaster_id": ich})
                self._raid_bis = 0.0
            else:
                ziel = str(settings.get("channel") or "").strip()
                if not ziel:
                    raise TwitchError("Für diese Taste ist kein Kanal eingetragen")
                self.api.helix("POST", "/raids", abfrage={
                    "from_broadcaster_id": ich,
                    "to_broadcaster_id": self.api.benutzer_id(ziel),
                })
                self._raid_bis = time.monotonic() + RAID_COUNTDOWN_S

        elif action_id == "chat":
            text = str(settings.get("message") or "").strip()
            if not text:
                raise TwitchError("Für diese Taste ist keine Nachricht eingetragen")
            self.api.helix("POST", "/chat/messages", rumpf={
                "broadcaster_id": ich, "sender_id": ich, "message": text[:500],
            })

        elif action_id == "chat_mode":
            self._chatmodus(settings, ich)

        elif action_id == "clear_chat":
            self.api.helix("DELETE", "/moderation/chat", abfrage={
                "broadcaster_id": ich, "moderator_id": ich,
            })

        elif action_id == "shoutout":
            ziel = str(settings.get("channel") or "").strip()
            if not ziel:
                raise TwitchError("Für diese Taste ist kein Kanal eingetragen")
            self.api.helix("POST", "/chat/shoutouts", abfrage={
                "from_broadcaster_id": ich,
                "to_broadcaster_id": self.api.benutzer_id(ziel),
                "moderator_id": ich,
            })

        elif action_id == "poll":
            self._umfrage(settings, ich)

        elif action_id == "prediction":
            self._vorhersage(settings, ich)

        elif action_id in ("status", "followers"):
            # Diese beiden zeigen nur an. Ein Druck holt frische Zahlen,
            # statt bis zum nächsten Durchlauf zu warten.
            self.api.vergiss()

    def _kategorie_id(self, name: str) -> str:
        treffer = self.api.kategorien(name)
        genau = next((t for t in treffer if t["name"].lower() == name.lower()), None)
        gewaehlt = genau or (treffer[0] if treffer else None)
        if gewaehlt is None:
            raise TwitchError(f"Kategorie '{name}' gibt es bei Twitch nicht")
        return str(gewaehlt["id"])

    def _chatmodus(self, settings: dict[str, Any], ich: str) -> None:
        modus = str(settings.get("mode") or "subscriber")
        jetzt = self.api.chat_einstellungen()
        felder = {
            "subscriber": "subscriber_mode",
            "follower": "follower_mode",
            "emote": "emote_mode",
            "slow": "slow_mode",
            "unique": "unique_chat_mode",
        }
        feld = felder[modus]
        an = not bool(jetzt.get(feld))
        rumpf: dict[str, Any] = {feld: an}
        if an and modus == "slow":
            rumpf["slow_mode_wait_time"] = int(settings.get("seconds") or 30)
        if an and modus == "follower":
            rumpf["follower_mode_duration"] = int(settings.get("minutes") or 0)
        self.api.helix("PATCH", "/chat/settings", abfrage={
            "broadcaster_id": ich, "moderator_id": ich,
        }, rumpf=rumpf)
        self.api.vergiss("chat")

    def _umfrage(self, settings: dict[str, Any], ich: str) -> None:
        if self.umfrage:
            self.api.helix("PATCH", "/polls", rumpf={
                "broadcaster_id": ich,
                "id": self.umfrage["id"],
                "status": "TERMINATED",
            })
            return
        frage = str(settings.get("question") or "").strip()
        antworten = _teile(settings.get("choices"))
        if not frage or len(antworten) < 2:
            raise TwitchError("Es braucht eine Frage und mindestens zwei Antworten")
        self.api.helix("POST", "/polls", rumpf={
            "broadcaster_id": ich,
            "title": frage[:60],
            "choices": [{"title": a[:25]} for a in antworten[:5]],
            "duration": int(settings.get("duration") or 120),
        })

    def _vorhersage(self, settings: dict[str, Any], ich: str) -> None:
        laufend = self.vorhersage
        if laufend and str(laufend.get("status")) == "ACTIVE":
            self.api.helix("PATCH", "/predictions", rumpf={
                "broadcaster_id": ich, "id": laufend["id"], "status": "LOCKED",
            })
            return
        if laufend and str(laufend.get("status")) == "LOCKED":
            ergebnisse = laufend.get("outcomes") or []
            nummer = max(1, int(settings.get("winner") or 1))
            if nummer > len(ergebnisse):
                raise TwitchError(
                    f"Diese Vorhersage hat nur {len(ergebnisse)} Antworten"
                )
            self.api.helix("PATCH", "/predictions", rumpf={
                "broadcaster_id": ich, "id": laufend["id"], "status": "RESOLVED",
                "winning_outcome_id": ergebnisse[nummer - 1]["id"],
            })
            return

        frage = str(settings.get("question") or "").strip()
        antworten = _teile(settings.get("choices"))
        if not frage or len(antworten) < 2:
            raise TwitchError("Es braucht eine Frage und mindestens zwei Antworten")
        self.api.helix("POST", "/predictions", rumpf={
            "broadcaster_id": ich,
            "title": frage[:45],
            "outcomes": [{"title": a[:25]} for a in antworten[:10]],
            "prediction_window": int(settings.get("duration") or 120),
        })

    # -- Anzeige -----------------------------------------------------------

    async def on_tick(self, action_id, settings, ctx):
        """Sichtbare Anzeigen halten den Spiegel frisch."""
        if action_id not in ("status", "followers", "poll", "prediction", "chat_mode"):
            return
        if not self.api.angemeldet:
            return
        if time.monotonic() - self.stand_geholt >= AUFFRISCHEN_S:
            await self._hole_stand()

    def _wort(self, name: str) -> str:
        try:
            sprache = self.services.config.app.language
        except AttributeError:
            sprache = "de"
        return WOERTER.get(sprache, WOERTER["de"]).get(name, name)

    def get_state(self, action_id, settings, ctx):
        if action_id == "status":
            return "live" if self.stream else "offline"
        if action_id == "chat_mode":
            felder = {
                "subscriber": "subscriber_mode", "follower": "follower_mode",
                "emote": "emote_mode", "slow": "slow_mode",
                "unique": "unique_chat_mode",
            }
            feld = felder.get(str(settings.get("mode") or "subscriber"), "subscriber_mode")
            return "an" if self.chat.get(feld) else "aus"
        if action_id == "poll":
            return "laeuft" if self.umfrage else "aus"
        if action_id == "prediction":
            if not self.vorhersage:
                return "aus"
            return "offen" if str(self.vorhersage.get("status")) == "ACTIVE" else "gesperrt"
        if action_id == "raid":
            return "laeuft" if time.monotonic() < self._raid_bis else "default"
        if action_id == "title":
            eigener = str(settings.get("title") or "").strip()
            return "aktiv" if eigener and eigener == str(self.kanal.get("title") or "") \
                else "default"
        if action_id == "category":
            eigene = str(settings.get("category") or "").strip()
            return "aktiv" if eigene and eigene == str(self.kanal.get("game_name") or "") \
                else "default"
        return None

    def _laufzeit(self) -> float:
        """Sekunden seit Streambeginn — 0, wenn keiner läuft."""
        if not self.stream:
            return 0.0
        from datetime import datetime, timezone

        roh = str(self.stream.get("started_at") or "")
        if not roh:
            return 0.0
        try:
            start = datetime.fromisoformat(roh.replace("Z", "+00:00"))
        except ValueError:
            return 0.0
        return (datetime.now(timezone.utc) - start).total_seconds()

    def render(self, action_id, settings, ctx):
        if action_id not in ("status", "followers"):
            return super().render(action_id, settings, ctx)

        render = self.services.render
        live = bool(self.stream)
        farbe = FARBE_LIVE if live else FARBE_OFFLINE
        bild = render.background(ctx.size, ctx.appearance, accent=ACCENT,
                                 frame_time=ctx.frame_time)
        breite, hoehe = ctx.size

        if not self.api.angemeldet:
            gross, klein = "—", self._wort("no_login")
        elif action_id == "followers":
            gross, klein = _zahl(self.follower), self._wort("followers")
        elif not live:
            gross, klein = self._wort("offline"), ""
        else:
            was = str(settings.get("show") or "viewers")
            if was == "uptime":
                gross, klein = _dauer(self._laufzeit()), self._wort("uptime")
            elif was == "followers":
                gross, klein = _zahl(self.follower), self._wort("followers")
            else:
                gross = _zahl(int(self.stream.get("viewer_count") or 0))
                klein = self._wort("viewers")

        beschriftung = ctx.appearance.label_text or ""
        if ctx.input_type == "dial":
            render.draw_text_at(bild, beschriftung or "Twitch", x=10, y=8, size=13,
                                color="#c7c7d1", max_width=breite - 70)
            if self.api.angemeldet:
                render.draw_text_at(bild, self._wort("live") if live else self._wort("offline"),
                                    x=breite - 10, y=8, size=13, color=farbe, align="right")
            render.draw_text_at(bild, gross, x=10, y=30, size=38, bold=True,
                                color=ctx.appearance.label_color)
            if klein:
                render.draw_text_at(bild, klein, x=breite - 10, y=52, size=13,
                                    color="#9ca3af", align="right")
            return bild

        groesse = 30 if len(gross) <= 5 else 24
        render.draw_text(bild, gross, y=hoehe // 2 - groesse // 2 - 6, size=groesse,
                         bold=True, color=ctx.appearance.label_color)
        if klein:
            render.draw_text(bild, klein, y=hoehe // 2 + groesse // 2 - 2, size=12,
                             color="#c7c7d1")
        if beschriftung:
            render.draw_text(bild, beschriftung, y=8, size=12, color="#9ca3af")
        # Ein schmaler Streifen unten sagt live oder nicht — Farbe liest man
        # schneller als ein Wort.
        if self.api.angemeldet:
            render.draw_bar(bild, 1.0 if live else 0.0, color=farbe,
                            box=(12, hoehe - 14, breite - 12, hoehe - 9))
        return bild
