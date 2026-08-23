"""Zugang zu Govee — wahlweise über die alte oder die neue Schnittstelle.

Govee betreibt zwei APIs nebeneinander, und welche bei welchem Gerät
funktioniert, lässt sich von außen nicht vorhersagen. Deshalb steht das
hier zur Wahl und wird nicht geraten:

``alt``
    ``developer-api.govee.com/v1``. Schlank, erprobt, kennt ``turn``,
    ``brightness``, ``color`` und ``colorTem``. Keine Szenen.
``neu``
    ``openapi.api.govee.com``. Kennt zusätzlich Szenen.
``beide``
    Erst die neue, dann die alte hinterher. Für Geräte, bei denen die neue
    Befehle mit ``success`` quittiert, ohne sie auszuführen.

**Warum das nötig ist.** Gemessen am 2026-08-24 an einem H615C: Die neue
Schnittstelle meldete die Helligkeit als 154 und wies genau diesen Wert
beim Setzen als „out of range" ab. Sie hielt das Gerät zeitweise für
offline, während die alte es einwandfrei schaltete. Und sie antwortete auf
Farbbefehle mit ``success``, ohne dass sich etwas änderte. Die alte tat in
denselben Minuten, was man ihr sagte — aber nicht durchgängig, und
verlässlich wiederholen ließ sich keins von beidem, weil Govee den Zustand
drei bis sechs Sekunden verzögert meldet.

Aus einer Messung, die man nicht wiederholen kann, folgt keine
Automatik — sondern ein Schalter.

Angemeldet wird sich mit einem persönlichen Schlüssel im Kopf jeder
Anfrage; derselbe gilt für beide Schnittstellen. Die Aufrufe sind
blockierend (``urllib``); der Aufrufer führt sie in einem Thread aus.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)

NEU_BASIS = "https://openapi.api.govee.com/router/api/v1"
ALT_BASIS = "https://developer-api.govee.com/v1"
USER_AGENT = "DeckSwitch/1.0"
ZEITLIMIT_S = 12

#: Die Vorgabe. Die alte Schnittstelle ist die erprobte; wer Szenen
#: braucht, stellt um.
STANDARD_MODUS = "alt"
MODI = ("alt", "neu", "beide")

#: So lange gilt ein abgefragter Zustand als frisch. Die neue Schnittstelle
#: erlaubt dreißig Abfragen je Minute und Gerät, die alte ist großzügiger —
#: es gilt die knappere Grenze, damit ein Wechsel nichts kaputt macht.
ZUSTAND_FRISCH_S = 20.0
LISTE_FRISCH_S = 600.0

#: Woran sich erkennen lässt, dass die neue Schnittstelle das Gerät nicht
#: erreicht. Dann lohnt der zweite Weg.
OFFLINE_HINWEIS = "offline"

#: Befehle, wie die alte Schnittstelle sie nennt. Die neue benennt dieselben
#: Dinge mit einem Typ *und* einem Namen; die Zuordnung steht in NEU_NAMEN.
AN_AUS = "turn"
HELLIGKEIT = "brightness"
FARBE = "color"
FARBTEMPERATUR = "colorTem"

NEU_NAMEN = {
    AN_AUS: ("devices.capabilities.on_off", "powerSwitch"),
    HELLIGKEIT: ("devices.capabilities.range", "brightness"),
    FARBE: ("devices.capabilities.color_setting", "colorRgb"),
    FARBTEMPERATUR: ("devices.capabilities.color_setting", "colorTemperatureK"),
}


def rgb_zu_zahl(rot: int, gruen: int, blau: int) -> int:
    return (max(0, min(255, rot)) << 16) + (max(0, min(255, gruen)) << 8) + max(0, min(255, blau))


def zahl_zu_rgb(wert: int) -> tuple[int, int, int]:
    wert = max(0, min(0xFFFFFF, int(wert)))
    return (wert >> 16) & 0xFF, (wert >> 8) & 0xFF, wert & 0xFF


def hex_zu_zahl(farbe: str) -> int:
    """``"#ff8800"`` → eine Zahl. Die Kurzform ``#f80`` geht auch."""
    roh = str(farbe or "").strip().lstrip("#")
    if len(roh) == 3:
        roh = "".join(z * 2 for z in roh)
    if len(roh) != 6:
        raise GoveeError(f"'{farbe}' ist keine Farbe der Form #rrggbb")
    try:
        return int(roh, 16)
    except ValueError as exc:
        raise GoveeError(f"'{farbe}' ist keine Farbe der Form #rrggbb") from exc


def zahl_zu_hex(wert: int) -> str:
    rot, gruen, blau = zahl_zu_rgb(wert)
    return f"#{rot:02x}{gruen:02x}{blau:02x}"


def als_prozent(wert: Any) -> int | None:
    """Eine gemeldete Helligkeit auf 1–100 bringen.

    Es gibt Geräte, die ihre Helligkeit in 0–255 melden, obwohl beim Setzen
    nur 1–100 erlaubt ist — ein H615C gab 154 zurück und lehnte denselben
    Wert als „out of range" ab. Über 100 wird deshalb als 0–255 gelesen; ein
    Gerät, das ehrlich in Prozent meldet, bleibt unberührt.
    """
    if wert is None:
        return None
    zahl = int(wert)
    if zahl > 100:
        return max(1, min(100, round(zahl / 255 * 100)))
    return max(0, min(100, zahl))


class GoveeError(RuntimeError):
    """Mit dem Text, den Govee geschickt hat — oder warum keiner kam."""


class KeinSchluessel(GoveeError):
    pass


@dataclass
class Geraet:
    """Ein Gerät — gleich beschrieben, egal aus welcher Quelle.

    Beide Schnittstellen nennen dasselbe unterschiedlich: ``model`` bzw.
    ``sku``, die Befehlsliste als Wörter bzw. als Typ-und-Name. Hier steht
    die gemeinsame Form, damit eine gespeicherte Belegung nach einem
    Wechsel der Schnittstelle weiterhin auf dasselbe Gerät zeigt.
    """

    model: str
    kennung: str
    name: str
    #: Was es kann, in der Sprache der alten Schnittstelle.
    kann: set[str] = field(default_factory=set)
    steuerbar: bool = True
    abfragbar: bool = True
    kelvin_min: int = 2000
    kelvin_max: int = 9000
    #: Szenen: Name → Wert. Nur die neue Schnittstelle kennt sie.
    szenen: dict[str, Any] = field(default_factory=dict)
    szenen_feld: tuple[str, str] | None = None

    @property
    def schluessel(self) -> str:
        return f"{self.model}:{self.kennung}"


@dataclass
class Zustand:
    an: bool | None = None
    helligkeit: int | None = None
    farbe: int | None = None
    temperatur: int | None = None
    erreichbar: bool = True


def _fehlertext(exc: urllib.error.HTTPError) -> str:
    if exc.code == 429:
        return "Zu viele Anfragen — Govee bremst. In einer Minute noch einmal."
    if exc.code in (401, 403):
        return "Govee nimmt den Schlüssel nicht an. Steht er richtig in den Einstellungen?"
    try:
        daten = json.loads(exc.read().decode("utf-8"))
        for feld in ("message", "msg", "errorMessage"):
            text = str(daten.get(feld) or "").strip()
            if text:
                return f"{text} ({exc.code})"
    except Exception:  # noqa: BLE001 — dann eben ohne Begründung
        pass
    return f"Govee antwortet mit {exc.code}"


class GoveeApi:
    def __init__(self, schluessel: str = "", modus: str = STANDARD_MODUS) -> None:
        self.schluessel = schluessel
        self.modus = modus if modus in MODI else STANDARD_MODUS
        self._geraete: list[Geraet] = []
        self._geraete_geholt = 0.0
        self._zustand: dict[str, tuple[float, Zustand]] = {}

    @property
    def nutzt_neue(self) -> bool:
        return self.modus in ("neu", "beide")

    # -- Der Draht ---------------------------------------------------------

    def _ruf(self, basis: str, pfad: str, *, methode: str = "GET",
             rumpf: dict[str, Any] | None = None,
             abfrage: dict[str, str] | None = None) -> dict[str, Any]:
        if not self.schluessel:
            raise KeinSchluessel(
                "Es fehlt der Govee-Schlüssel. Er steht in den Plugin-Einstellungen "
                "und kommt aus der Govee-Home-App."
            )
        adresse = basis + pfad
        if abfrage:
            adresse += "?" + urllib.parse.urlencode(abfrage)
        kopf = {
            "Govee-API-Key": self.schluessel,
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        }
        daten = None
        if rumpf is not None:
            daten = json.dumps(rumpf).encode("utf-8")
            kopf["Content-Type"] = "application/json"

        anfrage = urllib.request.Request(adresse, data=daten, headers=kopf, method=methode)
        try:
            with urllib.request.urlopen(anfrage, timeout=ZEITLIMIT_S) as antwort:
                roh = antwort.read(2 * 1024 * 1024)
        except urllib.error.HTTPError as exc:
            raise GoveeError(_fehlertext(exc)) from exc
        except urllib.error.URLError as exc:
            raise GoveeError(f"Govee ist nicht erreichbar: {exc.reason}") from exc
        except (TimeoutError, OSError) as exc:
            raise GoveeError(f"Verbindung abgebrochen: {exc}") from exc

        if not roh:
            return {}
        try:
            antwort_daten = json.loads(roh.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise GoveeError("Govee hat etwas Unlesbares geschickt") from exc

        # Beide Schnittstellen antworten auch bei Fehlern mit 200 und einem
        # Code im Rumpf. Die Begründung steht je nach Aufruf anderswo.
        code = antwort_daten.get("code")
        if code not in (None, 200, 0):
            grund = ""
            for feld in ("message", "msg", "errorMessage"):
                if str(antwort_daten.get(feld) or "").strip():
                    grund = str(antwort_daten[feld]).strip()
                    break
            if not grund:
                grund = f"Code {code}, Antwort: {json.dumps(antwort_daten)[:300]}"
            log.warning("Govee lehnt ab: %s — geschickt wurde: %s",
                        grund, json.dumps(rumpf)[:400])
            raise GoveeError(f"{grund} (geschickt: {json.dumps(rumpf)[:200]})"
                             if rumpf else grund)
        return antwort_daten

    # -- Geräte ------------------------------------------------------------

    def geraete(self, *, erneut: bool = False) -> list[Geraet]:
        if not erneut and self._geraete and \
                time.monotonic() - self._geraete_geholt < LISTE_FRISCH_S:
            return self._geraete

        gefunden = self._neue_liste() if self.nutzt_neue else self._alte_liste()
        # Im Modus „beide" kommt die Befehlsliste der alten dazu: Ohne sie
        # wüsste der zweite Weg nicht, was er schicken darf.
        if self.modus == "beide":
            try:
                nach_schluessel = {g.schluessel: g for g in self._alte_liste()}
            except GoveeError as exc:
                log.debug("Govee: alte Geräteliste nicht abrufbar: %s", exc)
            else:
                for geraet in gefunden:
                    passend = nach_schluessel.get(geraet.schluessel)
                    if passend:
                        geraet.kann |= passend.kann

        self._geraete = gefunden
        self._geraete_geholt = time.monotonic()
        return gefunden

    def _alte_liste(self) -> list[Geraet]:
        antwort = self._ruf(ALT_BASIS, "/devices")
        gefunden: list[Geraet] = []
        for eintrag in (antwort.get("data") or {}).get("devices") or []:
            geraet = Geraet(
                model=str(eintrag.get("model") or ""),
                kennung=str(eintrag.get("device") or ""),
                name=str(eintrag.get("deviceName") or eintrag.get("model") or "Gerät"),
                kann=set(eintrag.get("supportCmds") or []),
                steuerbar=bool(eintrag.get("controllable", True)),
                abfragbar=bool(eintrag.get("retrievable", True)),
            )
            bereich = (eintrag.get("properties") or {}).get("colorTem", {}).get("range") or {}
            if bereich.get("min"):
                geraet.kelvin_min = int(bereich["min"])
            if bereich.get("max"):
                geraet.kelvin_max = int(bereich["max"])
            if geraet.kennung:
                gefunden.append(geraet)
        return gefunden

    def _neue_liste(self) -> list[Geraet]:
        antwort = self._ruf(NEU_BASIS, "/user/devices")
        # Die neue nennt die Fähigkeiten als Typ und Name — übersetzt in die
        # Wörter der alten, damit der Rest des Plugins nur eine Sprache
        # kennen muss.
        rueck = {paar: kurz for kurz, paar in NEU_NAMEN.items()}
        gefunden: list[Geraet] = []
        for eintrag in antwort.get("data") or []:
            geraet = Geraet(
                model=str(eintrag.get("sku") or ""),
                kennung=str(eintrag.get("device") or ""),
                name=str(eintrag.get("deviceName") or eintrag.get("sku") or "Gerät"),
            )
            for faehigkeit in eintrag.get("capabilities") or []:
                typ = str(faehigkeit.get("type") or "")
                name = str(faehigkeit.get("instance") or "")
                kurz = rueck.get((typ, name))
                if kurz:
                    geraet.kann.add(kurz)
                bereich = (faehigkeit.get("parameters") or {}).get("range") or {}
                if name == "colorTemperatureK" and bereich:
                    geraet.kelvin_min = int(bereich.get("min") or 2000)
                    geraet.kelvin_max = int(bereich.get("max") or 9000)
                if typ == "devices.capabilities.dynamic_scene" or name.endswith("Scene"):
                    geraet.szenen_feld = (typ, name)
                    for option in (faehigkeit.get("parameters") or {}).get("options") or []:
                        geraet.szenen[str(option.get("name") or "")] = option.get("value")
            if geraet.kennung:
                gefunden.append(geraet)
        return gefunden

    def geraet(self, schluessel: str) -> Geraet | None:
        for eintrag in self.geraete():
            if eintrag.schluessel == schluessel:
                return eintrag
        return None

    # -- Zustand -----------------------------------------------------------

    def zustand(self, geraet: Geraet, *, erneut: bool = False) -> Zustand:
        gemerkt = self._zustand.get(geraet.schluessel)
        if not erneut and gemerkt and time.monotonic() - gemerkt[0] < ZUSTAND_FRISCH_S:
            return gemerkt[1]
        if not geraet.abfragbar:
            # Manche Geräte lassen sich steuern, aber nicht auslesen. Dann
            # bleibt der zuletzt selbst gesetzte Stand stehen.
            return gemerkt[1] if gemerkt else Zustand()

        if self.nutzt_neue:
            try:
                stand = self._neuer_zustand(geraet)
            except GoveeError as exc:
                # Im Modus „beide" ist die alte Schnittstelle die zweite
                # Chance — auch beim Lesen. Im Modus „neu" bleibt es beim
                # Fehler; wer nur die neue will, soll nicht heimlich die
                # andere befragen.
                if self.modus != "beide" or OFFLINE_HINWEIS not in str(exc).lower():
                    raise
                stand = self._alter_zustand(geraet)
        else:
            stand = self._alter_zustand(geraet)
        self._zustand[geraet.schluessel] = (time.monotonic(), stand)
        return stand

    def _alter_zustand(self, geraet: Geraet) -> Zustand:
        antwort = self._ruf(ALT_BASIS, "/devices/state",
                            abfrage={"device": geraet.kennung, "model": geraet.model})
        # Die alte meldet Eigenschaften als Liste einzelner Wörterbücher.
        flach: dict[str, Any] = {}
        for eintrag in (antwort.get("data") or {}).get("properties") or []:
            if isinstance(eintrag, dict):
                flach.update(eintrag)

        stand = Zustand()
        if "powerState" in flach:
            stand.an = str(flach["powerState"]).lower() == "on"
        if flach.get("brightness") is not None:
            stand.helligkeit = als_prozent(flach["brightness"])
        farbe = flach.get("color")
        if isinstance(farbe, dict):
            stand.farbe = rgb_zu_zahl(int(farbe.get("r", 0)), int(farbe.get("g", 0)),
                                      int(farbe.get("b", 0)))
        temperatur = flach.get("colorTem")
        if temperatur and int(temperatur) >= 1000:
            stand.temperatur = int(temperatur)
        if "online" in flach:
            stand.erreichbar = bool(flach["online"])
        return stand

    def _neuer_zustand(self, geraet: Geraet) -> Zustand:
        antwort = self._ruf(NEU_BASIS, "/device/state", methode="POST", rumpf={
            "requestId": str(uuid.uuid4()),
            "payload": {"sku": geraet.model, "device": geraet.kennung},
        })
        stand = Zustand()
        for faehigkeit in (antwort.get("payload") or {}).get("capabilities") or []:
            name = str(faehigkeit.get("instance") or "")
            wert = (faehigkeit.get("state") or {}).get("value")
            if name == "powerSwitch":
                stand.an = bool(wert)
            elif name == "brightness" and wert is not None:
                stand.helligkeit = als_prozent(wert)
            elif name == "colorRgb" and wert is not None:
                stand.farbe = int(wert)
            elif name == "colorTemperatureK" and wert is not None:
                # 0 heißt „gerade keine Weißeinstellung", nicht null Kelvin.
                stand.temperatur = int(wert) if int(wert) >= 1000 else None
            elif name == "online":
                stand.erreichbar = bool(wert)
        return stand

    def merke(self, geraet: Geraet, **werte: Any) -> None:
        """Einen Befehl sofort im Zwischenspeicher nachziehen.

        Govee meldet eine Änderung erst nach drei bis sechs Sekunden. Ohne
        das zeigte die Kachel so lange den alten Stand — und wer nicht
        wartet, drückt noch einmal und schaltet zurück.
        """
        gemerkt = self._zustand.get(geraet.schluessel)
        stand = gemerkt[1] if gemerkt else Zustand()
        for name, wert in werte.items():
            setattr(stand, name, wert)
        self._zustand[geraet.schluessel] = (time.monotonic(), stand)

    # -- Befehle -----------------------------------------------------------

    def steuere(self, geraet: Geraet, befehl: str, alt_wert: Any, neu_wert: Any) -> None:
        """Einen Befehl schicken — über den eingestellten Weg.

        ``alt_wert`` und ``neu_wert`` sind derselbe Befehl in zwei Sprachen:
        Die alte Schnittstelle will Farben als ``{r,g,b}``, die neue als
        eine einzige Zahl.
        """
        if befehl not in geraet.kann:
            raise GoveeError(
                f"'{geraet.name}' kann das nicht — Govee nennt für dieses Gerät "
                f"nur {', '.join(sorted(geraet.kann)) or 'gar nichts'}."
            )
        if not geraet.steuerbar:
            raise GoveeError(f"'{geraet.name}' lässt sich über die API nicht steuern")

        if self.modus == "alt":
            self._alt_befehl(geraet, befehl, alt_wert)
            return

        fehler: GoveeError | None = None
        try:
            self._neu_befehl(geraet, befehl, neu_wert)
        except GoveeError as exc:
            fehler = exc
            # Im Modus „neu" bleibt es dabei — außer das Gerät gilt als
            # offline; dann ist der andere Weg die einzige Chance.
            if self.modus == "neu" and OFFLINE_HINWEIS not in str(exc).lower():
                raise

        if self.modus == "beide" or fehler is not None:
            try:
                self._alt_befehl(geraet, befehl, alt_wert)
                return
            except GoveeError as exc:
                fehler = fehler or exc
        if fehler is not None:
            raise fehler

    def _alt_befehl(self, geraet: Geraet, name: str, wert: Any) -> None:
        self._ruf(ALT_BASIS, "/devices/control", methode="PUT", rumpf={
            "device": geraet.kennung,
            "model": geraet.model,
            "cmd": {"name": name, "value": wert},
        })

    def _neu_befehl(self, geraet: Geraet, befehl: str, wert: Any) -> None:
        typ, name = NEU_NAMEN[befehl]
        self._ruf(NEU_BASIS, "/device/control", methode="POST", rumpf={
            "requestId": str(uuid.uuid4()),
            "payload": {
                "sku": geraet.model,
                "device": geraet.kennung,
                "capability": {"type": typ, "instance": name, "value": wert},
            },
        })

    def schalte(self, geraet: Geraet, an: bool) -> None:
        self.steuere(geraet, AN_AUS, "on" if an else "off", 1 if an else 0)
        self.merke(geraet, an=an)

    def helligkeit(self, geraet: Geraet, prozent: int) -> None:
        prozent = max(1, min(100, int(prozent)))
        self.steuere(geraet, HELLIGKEIT, prozent, prozent)
        # Wer die Helligkeit stellt, will Licht — Govee schaltet dabei ein.
        self.merke(geraet, helligkeit=prozent, an=True)

    def farbe(self, geraet: Geraet, wert: int) -> None:
        rot, gruen, blau = zahl_zu_rgb(int(wert))
        self.steuere(geraet, FARBE, {"r": rot, "g": gruen, "b": blau}, int(wert))
        # Farbe und Weiß schließen sich aus — das eine löscht das andere.
        self.merke(geraet, farbe=int(wert), temperatur=None, an=True)

    def temperatur(self, geraet: Geraet, kelvin: int) -> None:
        kelvin = max(geraet.kelvin_min, min(geraet.kelvin_max, int(kelvin)))
        self.steuere(geraet, FARBTEMPERATUR, kelvin, kelvin)
        self.merke(geraet, temperatur=kelvin, farbe=None, an=True)

    def szene(self, geraet: Geraet, name: str) -> None:
        """Szenen kennt nur die neue Schnittstelle."""
        if not self.nutzt_neue:
            raise GoveeError(
                "Szenen gibt es nur über die neue Schnittstelle — umstellen "
                "in den Plugin-Einstellungen unter „Schnittstelle“."
            )
        if not geraet.szenen_feld:
            raise GoveeError(f"'{geraet.name}' kennt keine Szenen")
        if name not in geraet.szenen:
            raise GoveeError(f"'{geraet.name}' kennt die Szene '{name}' nicht")
        typ, feld = geraet.szenen_feld
        self._ruf(NEU_BASIS, "/device/control", methode="POST", rumpf={
            "requestId": str(uuid.uuid4()),
            "payload": {
                "sku": geraet.model, "device": geraet.kennung,
                "capability": {"type": typ, "instance": feld,
                               "value": geraet.szenen[name]},
            },
        })
        self.merke(geraet, an=True)

    def vergiss(self) -> None:
        self._zustand.clear()
        self._geraete_geholt = 0.0
