"""Zugang zu YouTube: Anmeldung über Gerätecode und die Data API v3.

**Warum hier jeder seine eigenen Zugangsdaten braucht.** YouTubes Kontingent
gilt pro Google-Cloud-Projekt, nicht pro Benutzer: zehntausend Einheiten am
Tag, geteilt von allen, die dieselbe Kennung benutzen. Eine mitgelieferte
Client-ID wäre nach ein paar Dutzend Installationen erschöpft — und dann
funktioniert das Plugin für niemanden mehr. Bei Twitch zählt das Limit je
Benutzer, dort geht eine App für alle; hier nicht.

**Wie die Anmeldung läuft.** Über denselben Gerätecode-Weg wie bei Twitch,
mit zwei Unterschieden: Google verlangt dabei ein Client-Secret, und es
erlaubt nur einen kleinen Satz Berechtigungen — ``youtube`` und
``youtube.readonly``, aber nicht ``youtube.force-ssl``. Für alles, was
dieses Plugin tut, reicht ``youtube``.

Das Secret liegt damit auf dem Rechner des Benutzers. Google nennt es bei
installierten Anwendungen ausdrücklich nicht geheim — es identifiziert die
Anwendung, es autorisiert nichts. Trotzdem steht es in einem Passwortfeld
und nicht offen im Formular.

**Womit hier gerechnet wird: mit Einheiten.** Lesen kostet eine, Schreiben
fünfzig. Eine Zuschauerzahl, die alle dreißig Sekunden nachsieht, verbraucht
am Tag knapp dreitausend — vertretbar. Alle fünf Sekunden wären es
siebzehntausend, und damit wäre das Konto vor dem Abendessen leer. Deshalb
wird gebündelt gefragt und zwischengespeichert.

Die Aufrufe sind blockierend (``urllib``); der Aufrufer führt sie in einem
Thread aus.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

log = logging.getLogger(__name__)

API = "https://www.googleapis.com/youtube/v3"
GERAET_URL = "https://oauth2.googleapis.com/device/code"
TOKEN_URL = "https://oauth2.googleapis.com/token"
WIDERRUF_URL = "https://oauth2.googleapis.com/revoke"
USER_AGENT = "DeckSwitch/1.0"
ZEITLIMIT_S = 15

#: Was das Plugin können muss. ``youtube`` deckt Lesen und Schreiben ab und
#: ist einer der wenigen Bereiche, die Googles Gerätecode-Weg zulässt.
SCOPES = ["https://www.googleapis.com/auth/youtube"]

#: Wie lange abgefragte Zahlen als frisch gelten. Siehe Kontingent oben.
FRISCH_S = 30.0
#: Der laufende Broadcast wechselt selten; ihn öfter zu suchen wäre
#: verschwendete Einheiten.
BROADCAST_FRISCH_S = 60.0

#: Adresse des Studio-Dashboards zu einem Broadcast.
DASHBOARD = "https://studio.youtube.com/video/{id}/livestreaming"
#: Fällt keine Sendung an, wenigstens die Übersicht.
DASHBOARD_ALLGEMEIN = "https://studio.youtube.com/channel/UC/livestreaming"


class YouTubeError(RuntimeError):
    """Mit dem Text, den Google geschickt hat — oder warum keiner kam."""


class NichtAngemeldet(YouTubeError):
    pass


class KeineZugangsdaten(YouTubeError):
    pass


class NochNichtBestaetigt(YouTubeError):
    """Der Benutzer hat den Code noch nicht eingegeben.

    Kein Fehler, sondern der normale Zustand zwischen „Code anzeigen" und
    „Code bestätigt". Google beantwortet das mit **428 Precondition
    Required** und ``error: authorization_pending`` — und die Beschreibung
    lautet dann wörtlich „Precondition Required". Wer auf diesen Text
    prüft, statt auf die Kennung, hält das Warten für einen Abbruch. Genau
    so passiert am 2026-08-24.
    """


@dataclass
class Anmeldung:
    access_token: str = ""
    refresh_token: str = ""
    #: Ablauf als Unix-Zeit. Fünf Minuten vorher wird erneuert.
    laeuft_ab: float = 0.0
    kanal: str = ""
    kanal_id: str = ""

    def als_dict(self) -> dict[str, Any]:
        return {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "laeuft_ab": self.laeuft_ab,
            "kanal": self.kanal,
            "kanal_id": self.kanal_id,
        }

    @classmethod
    def aus_dict(cls, daten: dict[str, Any]) -> "Anmeldung":
        return cls(
            access_token=str(daten.get("access_token") or ""),
            refresh_token=str(daten.get("refresh_token") or ""),
            laeuft_ab=float(daten.get("laeuft_ab") or 0.0),
            kanal=str(daten.get("kanal") or ""),
            kanal_id=str(daten.get("kanal_id") or ""),
        )


@dataclass
class Sendung:
    """Ein Livestream, so wie YouTube ihn beschreibt."""

    id: str = ""
    titel: str = ""
    chat_id: str = ""
    #: ``ready``, ``testing``, ``live`` oder ``complete``.
    status: str = ""
    #: Nur gefüllt, solange die Sendung läuft.
    zuschauer: int | None = None

    @property
    def laeuft(self) -> bool:
        return self.status in ("live", "testing")


#: Kennungen, mit denen Google „noch nicht, frag später" ausdrückt.
WARTEN = ("authorization_pending", "slow_down")


def _kennung(exc: urllib.error.HTTPError, roh: bytes) -> str:
    """Googles Fehlerkennung — die kurze, maschinenlesbare."""
    try:
        daten = json.loads(roh.decode("utf-8"))
    except Exception:  # noqa: BLE001
        return ""
    fehler = daten.get("error")
    if isinstance(fehler, str):
        return fehler
    if isinstance(fehler, dict):
        gruende = fehler.get("errors") or []
        if isinstance(gruende, list) and gruende:
            return str((gruende[0] or {}).get("reason") or "")
    return ""


def _fehlertext(exc: urllib.error.HTTPError) -> str:
    """Wie :func:`_fehlertext_aus`, liest den Rumpf aber selbst."""
    try:
        return _fehlertext_aus(exc, exc.read())
    except Exception:  # noqa: BLE001
        return f"YouTube antwortet mit {exc.code}"


def _fehlertext_aus(exc: urllib.error.HTTPError, roh: bytes) -> str:
    """Googles Begründung, wenn eine mitkommt.

    Google verpackt sie zweifach — einmal als ``error.message`` im
    JSON-Fehler, einmal als ``error_description`` bei OAuth. Beides ist
    aussagekräftiger als der Statuscode: „The user is not enabled for live
    streaming." sagt einem Benutzer mehr als „403".
    """
    try:
        daten = json.loads(roh.decode("utf-8"))
    except Exception:  # noqa: BLE001 — dann eben ohne Begründung
        daten = {}

    # Der häufigste Stolperstein beim ersten Anmelden hat einen eigenen
    # Text: Google lässt eine App, die die Überprüfung nicht durchlaufen
    # hat, nur von eingetragenen Testnutzern benutzen — auch nicht von der
    # Person, die sie angelegt hat. „access_denied" allein sagt das nicht,
    # und man sucht den Fehler dann im Plugin statt in der Console.
    roh_fehler = daten.get("error")
    kennung = roh_fehler if isinstance(roh_fehler, str) else ""
    if kennung == "access_denied" or "has not completed the Google verification" in str(
        daten.get("error_description") or ""
    ):
        return (
            "Google lässt diese App nur von eingetragenen Testnutzern benutzen, "
            "solange sie nicht überprüft ist. Trag dich selbst ein: Cloud "
            "Console → APIs & Dienste → OAuth-Zustimmungsbildschirm → "
            "Zielgruppe → Testnutzer."
        )

    fehler = daten.get("error")
    if isinstance(fehler, dict):
        text = str(fehler.get("message") or "").strip()
        gruende = fehler.get("errors") or []
        if isinstance(gruende, list) and gruende:
            grund = str((gruende[0] or {}).get("reason") or "").strip()
            if grund and grund not in text:
                text = f"{text} ({grund})" if text else grund
        if text:
            return text
    beschreibung = str(daten.get("error_description") or "").strip()
    if beschreibung:
        return beschreibung
    if isinstance(fehler, str) and fehler:
        return fehler
    if exc.code == 403:
        return ("YouTube lehnt ab (403). Häufigster Grund: Das Kontingent des "
                "Google-Projekts ist für heute verbraucht, oder der Kanal ist "
                "nicht für Livestreams freigeschaltet.")
    if exc.code == 404:
        # Hier kommt oft nichts zurück — dann ist der Statuscode alles, was
        # es gibt, und „404" allein hilft niemandem weiter.
        return ("YouTube findet das nicht (404). Bei Chatnachrichten heißt das "
                "meist: Die Sendung läuft noch nicht, der Chat ist also noch "
                "nicht offen.")
    return f"YouTube antwortet mit {exc.code}"


class YouTubeApi:
    def __init__(self, client_id: str = "", client_secret: str = "") -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.anmeldung = Anmeldung()
        #: Wird gerufen, sobald sich die Anmeldung geändert hat. Google
        #: schickt beim Erneuern zwar meist kein neues Refresh-Token, aber
        #: den Ablauf und das Zugriffstoken — und die gehören mit auf die
        #: Platte, sonst wird bei jedem Start unnötig erneuert.
        self.beim_aendern = None
        self._sendung: Sendung | None = None
        self._sendung_geholt = 0.0
        self._zuschauer_geholt = 0.0

    @property
    def angemeldet(self) -> bool:
        return bool(self.anmeldung.access_token)

    # -- Anmeldung ---------------------------------------------------------

    def _oauth(self, url: str, felder: dict[str, str]) -> dict[str, Any]:
        rumpf = urllib.parse.urlencode(felder).encode("utf-8")
        anfrage = urllib.request.Request(url, data=rumpf, method="POST", headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        })
        try:
            with urllib.request.urlopen(anfrage, timeout=ZEITLIMIT_S) as antwort:
                roh = antwort.read(1024 * 1024)
        except urllib.error.HTTPError as exc:
            # Der Rumpf lässt sich nur einmal lesen — also einmal lesen und
            # daraus beides gewinnen: die Kennung fürs Verhalten, den Text
            # für den Menschen.
            fehler_rumpf = exc.read()
            kennung = _kennung(exc, fehler_rumpf)
            if kennung in WARTEN:
                raise NochNichtBestaetigt(kennung) from exc
            raise YouTubeError(_fehlertext_aus(exc, fehler_rumpf)) from exc
        except urllib.error.URLError as exc:
            raise YouTubeError(f"Google ist nicht erreichbar: {exc.reason}") from exc
        return json.loads(roh.decode("utf-8")) if roh else {}

    def _pruefe_zugangsdaten(self) -> None:
        if not self.client_id or not self.client_secret:
            raise KeineZugangsdaten(
                "Es fehlen Client-ID und Client-Secret. Beide kommen aus einem "
                "eigenen Google-Cloud-Projekt — siehe Hilfe in den "
                "Plugin-Einstellungen."
            )

    def geraetecode(self) -> dict[str, Any]:
        """Startet die Anmeldung. Zurück kommt der Code für den Benutzer."""
        self._pruefe_zugangsdaten()
        return self._oauth(GERAET_URL, {
            "client_id": self.client_id,
            "scope": " ".join(SCOPES),
        })

    def code_einloesen(self, device_code: str) -> Anmeldung:
        """Fragt nach, ob der Benutzer den Code eingegeben hat.

        Solange nicht, antwortet Google mit ``authorization_pending``. Das
        ist kein Fehler, sondern „warte noch" — der Aufrufer erkennt es am
        leeren Ergebnis.
        """
        self._pruefe_zugangsdaten()
        try:
            daten = self._oauth(TOKEN_URL, {
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "device_code": device_code,
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            })
        except NochNichtBestaetigt:
            # Noch nicht bestätigt — das ist der Normalfall, solange der
            # Code auf dem Bildschirm steht.
            return Anmeldung()
        return self._uebernimm(daten)

    def erneuere(self) -> None:
        if not self.anmeldung.refresh_token:
            raise NichtAngemeldet("Keine Anmeldung, die sich erneuern ließe")
        self._pruefe_zugangsdaten()
        daten = self._oauth(TOKEN_URL, {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "refresh_token": self.anmeldung.refresh_token,
            "grant_type": "refresh_token",
        })
        self._uebernimm(daten, behalte_refresh=True)
        self._melde_aenderung()

    def _melde_aenderung(self) -> None:
        if self.beim_aendern is None:
            return
        try:
            self.beim_aendern(self.anmeldung)
        except Exception:  # noqa: BLE001 — ein Token gilt auch unnotiert
            log.exception("YouTube: Anmeldung konnte nicht gespeichert werden")

    def abmelden(self) -> None:
        if self.anmeldung.refresh_token or self.anmeldung.access_token:
            try:
                self._oauth(WIDERRUF_URL, {
                    "token": self.anmeldung.refresh_token or self.anmeldung.access_token,
                })
            except YouTubeError as exc:
                log.debug("YouTube: Zurückziehen fehlgeschlagen: %s", exc)
        self.anmeldung = Anmeldung()
        self.vergiss()

    def _uebernimm(self, daten: dict[str, Any], *, behalte_refresh: bool = False) -> Anmeldung:
        zugriff = str(daten.get("access_token") or "")
        if not zugriff:
            return Anmeldung()
        self.anmeldung.access_token = zugriff
        neuer_refresh = str(daten.get("refresh_token") or "")
        if neuer_refresh or not behalte_refresh:
            self.anmeldung.refresh_token = neuer_refresh or self.anmeldung.refresh_token
        self.anmeldung.laeuft_ab = time.time() + float(daten.get("expires_in") or 0)
        self._wer_bin_ich()
        return self.anmeldung

    def _wer_bin_ich(self) -> None:
        """Den eigenen Kanal nachschlagen — kostet eine Einheit."""
        daten = self.ruf("/channels", {"part": "snippet", "mine": "true"})
        eintraege = daten.get("items") or []
        if not eintraege:
            raise YouTubeError(
                "Zu diesem Google-Konto gibt es keinen YouTube-Kanal."
            )
        self.anmeldung.kanal_id = str(eintraege[0].get("id") or "")
        self.anmeldung.kanal = str(
            (eintraege[0].get("snippet") or {}).get("title") or ""
        )

    # -- Die eigentlichen Aufrufe -----------------------------------------

    def ruf(self, pfad: str, abfrage: dict[str, Any] | None = None, *,
            methode: str = "GET", rumpf: dict[str, Any] | None = None,
            erneut: bool = True) -> dict[str, Any]:
        if not self.anmeldung.access_token:
            raise NichtAngemeldet("Für YouTube ist noch niemand angemeldet")

        # Fünf Minuten Vorlauf: Ein Token, das während des Aufrufs abläuft,
        # kostet einen unnötigen Fehlversuch — und der zählt aufs Kontingent.
        if self.anmeldung.laeuft_ab and time.time() > self.anmeldung.laeuft_ab - 300:
            if self.anmeldung.refresh_token:
                self.erneuere()

        adresse = API + pfad
        if abfrage:
            adresse += "?" + urllib.parse.urlencode(
                {k: v for k, v in abfrage.items() if v not in (None, "")}, doseq=True
            )
        kopf = {
            "Authorization": f"Bearer {self.anmeldung.access_token}",
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
                roh = antwort.read(4 * 1024 * 1024)
        except urllib.error.HTTPError as exc:
            if exc.code == 401 and erneut and self.anmeldung.refresh_token:
                self.erneuere()
                return self.ruf(pfad, abfrage, methode=methode, rumpf=rumpf, erneut=False)
            raise YouTubeError(_fehlertext(exc)) from exc
        except urllib.error.URLError as exc:
            raise YouTubeError(f"YouTube ist nicht erreichbar: {exc.reason}") from exc
        except (TimeoutError, OSError) as exc:
            raise YouTubeError(f"Verbindung abgebrochen: {exc}") from exc

        if not roh:
            return {}
        try:
            return json.loads(roh.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise YouTubeError("YouTube hat etwas Unlesbares geschickt") from exc

    # -- Was das Plugin braucht -------------------------------------------

    def sendung(self, *, erneut: bool = False) -> Sendung | None:
        """Die laufende oder nächste Sendung — ``None``, wenn keine da ist.

        Gesucht wird erst nach einer laufenden; gibt es keine, nach einer
        vorbereiteten. Beides kostet je eine Einheit, deshalb wird das
        Ergebnis eine Minute festgehalten.
        """
        if not erneut and self._sendung is not None and \
                time.monotonic() - self._sendung_geholt < BROADCAST_FRISCH_S:
            return self._sendung

        gefunden: Sendung | None = None
        for status in ("active", "upcoming"):
            daten = self.ruf("/liveBroadcasts", {
                "part": "id,snippet,status",
                "broadcastStatus": status,
                "broadcastType": "all",
                "maxResults": 1,
            })
            eintraege = daten.get("items") or []
            if eintraege:
                gefunden = _als_sendung(eintraege[0])
                break

        self._sendung = gefunden
        self._sendung_geholt = time.monotonic()
        self._zuschauer_geholt = 0.0
        return gefunden

    def zuschauer(self) -> int | None:
        """Wie viele gerade zusehen — ``None``, wenn nichts läuft.

        Die Zahl steht nicht am Broadcast, sondern am Video: ``videos.list``
        mit ``liveStreamingDetails``. Eine Einheit je Abruf.
        """
        laufend = self.sendung()
        if laufend is None or not laufend.laeuft:
            return None
        if laufend.zuschauer is not None and \
                time.monotonic() - self._zuschauer_geholt < FRISCH_S:
            return laufend.zuschauer

        daten = self.ruf("/videos", {"part": "liveStreamingDetails", "id": laufend.id})
        eintraege = daten.get("items") or []
        wert = None
        if eintraege:
            details = eintraege[0].get("liveStreamingDetails") or {}
            roh = details.get("concurrentViewers")
            wert = int(roh) if roh is not None else None
        laufend.zuschauer = wert
        self._zuschauer_geholt = time.monotonic()
        return wert

    def schicke_chat(self, text: str) -> None:
        """Eine Nachricht in den Live-Chat — fünfzig Einheiten.

        Geprüft wird vorher, ob die Sendung überhaupt läuft. Eine
        vorbereitete Sendung *hat* schon eine Chat-Kennung, aber der Chat
        nimmt noch nichts an: YouTube antwortet dann mit 404 und einem
        leeren Rumpf — ohne ein Wort dazu, was fehlt. Gemessen am
        2026-08-24 an einer Sendung im Zustand ``ready``.
        """
        laufend = self.sendung()
        if laufend is None:
            raise YouTubeError("Es läuft keine Sendung, in deren Chat man schreiben könnte")
        if not laufend.laeuft:
            raise YouTubeError(
                "Der Live-Chat ist erst offen, wenn die Sendung läuft. "
                f"'{laufend.titel}' steht gerade auf '{laufend.status}' "
                "— erst starten."
            )
        if not laufend.chat_id:
            raise YouTubeError(
                "Diese Sendung hat keinen Live-Chat (bei Streams für Kinder "
                "oder mit abgeschaltetem Chat)."
            )
        self.ruf("/liveChatMessages", {"part": "snippet"}, methode="POST", rumpf={
            "snippet": {
                "liveChatId": laufend.chat_id,
                "type": "textMessageEvent",
                "textMessageDetails": {"messageText": text[:200]},
            },
        })

    def werbung(self, dauer_s: int = 30) -> None:
        """Einen Werbeblock einschieben.

        YouTube verspricht dabei nichts: Ausgespielt wird, wem gerade Werbung
        zusteht — die übrigen sehen den Stream weiter. Das ist keine
        Einschränkung dieser Umsetzung, sondern steht so in der API.
        """
        laufend = self.sendung()
        if laufend is None or not laufend.laeuft:
            raise YouTubeError("Werbung geht nur, solange die Sendung läuft")
        self.ruf("/liveBroadcasts/cuepoint", {"id": laufend.id}, methode="POST", rumpf={
            "cueType": "cueTypeAd",
            "durationSecs": max(1, int(dauer_s)),
        })

    def wechsle(self, nach: str) -> Sendung | None:
        """Die Sendung in einen anderen Zustand bringen — fünfzig Einheiten.

        ``live`` startet, ``complete`` beendet. YouTube nimmt das nur an,
        wenn der Zustand davor passt: Eine vorbereitete Sendung lässt sich
        starten, eine laufende beenden, aber nicht umgekehrt.
        """
        laufend = self.sendung(erneut=True)
        if laufend is None:
            raise YouTubeError(
                "Es gibt keine Sendung. Eine muss in YouTube Studio angelegt "
                "sein, bevor sie sich von hier starten lässt."
            )
        daten = self.ruf("/liveBroadcasts/transition", {
            "part": "id,snippet,status",
            "broadcastStatus": nach,
            "id": laufend.id,
        }, methode="POST")
        neu = _als_sendung(daten) if daten.get("id") else None
        self._sendung = neu
        self._sendung_geholt = time.monotonic()
        return neu

    def dashboard_adresse(self) -> str:
        laufend = self._sendung
        if laufend and laufend.id:
            return DASHBOARD.format(id=laufend.id)
        if self.anmeldung.kanal_id:
            return (f"https://studio.youtube.com/channel/"
                    f"{self.anmeldung.kanal_id}/livestreaming")
        return DASHBOARD_ALLGEMEIN

    def vergiss(self) -> None:
        self._sendung = None
        self._sendung_geholt = 0.0
        self._zuschauer_geholt = 0.0


def _als_sendung(eintrag: dict[str, Any]) -> Sendung:
    schnipsel = eintrag.get("snippet") or {}
    zustand = eintrag.get("status") or {}
    return Sendung(
        id=str(eintrag.get("id") or ""),
        titel=str(schnipsel.get("title") or ""),
        chat_id=str(schnipsel.get("liveChatId") or ""),
        status=str(zustand.get("lifeCycleStatus") or ""),
    )
