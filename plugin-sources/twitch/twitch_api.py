"""Zugang zu Twitch: Anmeldung über Gerätecode und die Helix-API.

**Warum Gerätecode.** Twitch verlangt zu jedem Aufruf eine Client-ID, und
die gibt es nur zu einer registrierten Anwendung. Ein Programm auf dem
Rechner des Benutzers kann kein Geheimnis hüten — was mitgeliefert wird,
liegt offen. Der Gerätecode-Weg ist genau dafür gedacht: Er kommt ohne
Secret aus. Das Plugin fragt einen Code an, der Benutzer tippt ihn auf
``twitch.tv/activate`` ein, und danach hat das Plugin ein Token.

Derselbe Weg, den die App für die Anmeldung am eigenen Store benutzt — wer
das einmal gemacht hat, kennt es wieder.

**Was hier nicht passiert: raten.** Jeder Aufruf steht mit seiner Adresse
und seinen Berechtigungen in :data:`AUFRUFE` bzw. bei der Aktion. Fehlt eine
Berechtigung, sagt Twitch das mit 401, und die Meldung wird durchgereicht
statt in ein allgemeines „hat nicht geklappt" übersetzt.

Die Aufrufe sind blockierend (``urllib``); der Aufrufer führt sie in einem
Thread aus, damit die Schleife der App nicht wartet.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)

HELIX = "https://api.twitch.tv/helix"
ID_BASIS = "https://id.twitch.tv/oauth2"
USER_AGENT = "DeckSwitch/1.0 (+https://github.com/LabRaTox/Deck-Switch)"

ZEITLIMIT_S = 12

#: Wie lange abgerufene Zahlen als frisch gelten. Acht Kacheln sollen nicht
#: acht Abfragen auslösen, und Twitch zählt mit: 800 Punkte je Minute.
FRISCH_S = 30
#: Der Kanal (Name, Kennung) ändert sich praktisch nie.
KANAL_FRISCH_S = 3600

#: Alles, was dieses Plugin können soll — in einer Liste, damit die
#: Anmeldung genau danach fragt und nicht nach mehr. Wer nur Titel setzen
#: will, gibt trotzdem alles frei; das ist der Preis für eine Anmeldung
#: statt vier. Was womit gebraucht wird, steht in der Doku.
SCOPES = [
    "channel:manage:broadcast",     # Titel, Kategorie, Stream-Marker
    "channel:edit:commercial",      # Werbung
    "clips:edit",                   # Clip erstellen
    "channel:manage:raids",         # Raid starten und abbrechen
    "user:write:chat",              # Nachricht in den Chat
    "user:bot",                     # … dasselbe, aus Sicht des Kontos
    "channel:bot",
    "moderator:manage:chat_settings",   # Slow-, Sub-, Emote-, Follower-Modus
    "moderator:manage:chat_messages",   # Chat leeren
    "moderator:manage:shoutouts",       # Shoutout
    "moderator:read:followers",         # Followerzahl
    "channel:manage:polls",
    "channel:manage:predictions",
]


class TwitchError(RuntimeError):
    """Etwas ist schiefgegangen — mit dem Text, den Twitch geschickt hat."""


class NichtAngemeldet(TwitchError):
    pass


class NochNichtBestaetigt(TwitchError):
    """Der Benutzer hat den Code noch nicht eingegeben.

    Der Normalzustand zwischen „Code anzeigen" und „Code bestätigt".
    Erkannt wird er an Twitchs Kennung ``authorization_pending`` — und
    nicht daran, dass irgendwo eine 400 im Text steht: So galt jede
    Ablehnung als Warten, und eine falsche Client-ID hätte den Dialog bis
    zum Ablauf des Codes „wartend" stehen lassen.
    """


@dataclass
class Anmeldung:
    """Was nach der Anmeldung übrig bleibt."""

    access_token: str = ""
    refresh_token: str = ""
    #: Ablauf als Unix-Zeit. Zehn Minuten vorher wird erneuert.
    laeuft_ab: float = 0.0
    login: str = ""
    anzeigename: str = ""
    benutzer_id: str = ""

    def als_dict(self) -> dict[str, Any]:
        return {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "laeuft_ab": self.laeuft_ab,
            "login": self.login,
            "anzeigename": self.anzeigename,
            "benutzer_id": self.benutzer_id,
        }

    @classmethod
    def aus_dict(cls, daten: dict[str, Any]) -> "Anmeldung":
        return cls(
            access_token=str(daten.get("access_token") or ""),
            refresh_token=str(daten.get("refresh_token") or ""),
            laeuft_ab=float(daten.get("laeuft_ab") or 0.0),
            login=str(daten.get("login") or ""),
            anzeigename=str(daten.get("anzeigename") or ""),
            benutzer_id=str(daten.get("benutzer_id") or ""),
        )


@dataclass
class Zwischenspeicher:
    werte: dict[str, tuple[float, Any]] = field(default_factory=dict)

    def hol(self, schluessel: str, dauer: float) -> Any | None:
        eintrag = self.werte.get(schluessel)
        if eintrag is None:
            return None
        zeit, wert = eintrag
        if time.monotonic() - zeit > dauer:
            return None
        return wert

    def leg_ab(self, schluessel: str, wert: Any) -> None:
        self.werte[schluessel] = (time.monotonic(), wert)

    def vergiss(self, praefix: str = "") -> None:
        if not praefix:
            self.werte.clear()
            return
        for schluessel in [k for k in self.werte if k.startswith(praefix)]:
            self.werte.pop(schluessel, None)


def _lies(antwort) -> Any:
    roh = antwort.read(4 * 1024 * 1024)
    if not roh:
        return None
    try:
        return json.loads(roh.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TwitchError("Twitch hat etwas Unlesbares geschickt") from exc


#: Womit Twitch „noch nicht, frag später" ausdrückt.
WARTEN = ("authorization_pending", "slow_down")


def _fehlertext(exc: urllib.error.HTTPError) -> str:
    """Wie :func:`_fehlertext_aus`, liest den Rumpf aber selbst."""
    try:
        return _fehlertext_aus(exc, exc.read())
    except Exception:  # noqa: BLE001
        return f"Twitch antwortet mit {exc.code}"


def _fehlertext_aus(exc: urllib.error.HTTPError, roh: bytes) -> str:
    """Die Begründung von Twitch, wenn eine mitkommt.

    Twitch schickt bei Fehlern JSON mit ``message`` — das ist fast immer
    aussagekräftiger als der Statuscode („The ID in broadcaster_id must
    match the user ID found in the request's OAuth token.").
    """
    try:
        daten = json.loads(roh.decode("utf-8"))
        text = str(daten.get("message") or "").strip()
        if text:
            return f"{text} ({exc.code})"
    except Exception:  # noqa: BLE001 — dann eben ohne Begründung
        pass
    return f"Twitch antwortet mit {exc.code}"


def _kennung(roh: bytes) -> str:
    """Twitchs kurze, maschinenlesbare Angabe — sie steht in ``message``."""
    try:
        return str(json.loads(roh.decode("utf-8")).get("message") or "")
    except Exception:  # noqa: BLE001
        return ""


class TwitchApi:
    """Ein Zugang je Plugin — hält Token, Zwischenspeicher und Client-ID."""

    def __init__(self, client_id: str = "") -> None:
        self.client_id = client_id
        self.anmeldung = Anmeldung()
        self._cache = Zwischenspeicher()
        #: Wird gerufen, sobald sich die Anmeldung geändert hat. Muss gesetzt
        #: werden, sonst geht ein erneuertes Token beim nächsten Start
        #: verloren — siehe :meth:`erneuere`.
        self.beim_aendern = None

    # -- Anmeldung ---------------------------------------------------------

    def geraetecode(self) -> dict[str, Any]:
        """Startet die Anmeldung. Zurück kommt der Code für den Benutzer."""
        if not self.client_id:
            raise TwitchError(
                "Es fehlt die Client-ID. Sie steht in den Plugin-Einstellungen "
                "und stammt aus einer App auf dev.twitch.tv."
            )
        return self._id_aufruf("/device", {
            "client_id": self.client_id,
            "scopes": " ".join(SCOPES),
        })

    def code_einloesen(self, device_code: str) -> Anmeldung:
        """Fragt nach, ob der Benutzer den Code schon eingegeben hat.

        Solange nicht, antwortet Twitch mit ``authorization_pending`` — das
        ist kein Fehler, sondern „warte noch". Der Aufrufer erkennt das am
        leeren Ergebnis.
        """
        try:
            daten = self._id_aufruf("/token", {
                "client_id": self.client_id,
                "device_code": device_code,
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            })
        except NochNichtBestaetigt:
            # Noch nicht bestätigt — der Normalfall, solange der Code auf
            # dem Bildschirm steht.
            return Anmeldung()
        return self._uebernimm(daten)

    def erneuere(self) -> None:
        """Holt ein frisches Zugriffstoken, solange das Refresh-Token gilt.

        **Und speichert es sofort.** Twitch tauscht dabei auch das
        Refresh-Token aus und macht das alte ungültig. Wer das neue nicht
        ablegt, hat auf der Platte eine verbrannte Anmeldung: Solange das
        Backend läuft, merkt man nichts — beim nächsten Start kommt
        „Invalid refresh token". Genau so passiert am 2026-08-24.
        """
        if not self.anmeldung.refresh_token:
            raise NichtAngemeldet("Keine Anmeldung, die sich erneuern ließe")
        daten = self._id_aufruf("/token", {
            "client_id": self.client_id,
            "refresh_token": self.anmeldung.refresh_token,
            "grant_type": "refresh_token",
        })
        self._uebernimm(daten)
        self._melde_aenderung()

    def _melde_aenderung(self) -> None:
        if self.beim_aendern is None:
            return
        try:
            self.beim_aendern(self.anmeldung)
        except Exception:  # noqa: BLE001 — ein Token gilt auch unnotiert
            log.exception("Twitch: Anmeldung konnte nicht gespeichert werden")

    def abmelden(self) -> None:
        """Zieht das Token bei Twitch zurück und wirft es weg."""
        if self.anmeldung.access_token:
            try:
                self._id_aufruf("/revoke", {
                    "client_id": self.client_id,
                    "token": self.anmeldung.access_token,
                })
            except TwitchError as exc:
                log.debug("Twitch: Zurückziehen fehlgeschlagen: %s", exc)
        self.anmeldung = Anmeldung()
        self._cache.vergiss()

    def _uebernimm(self, daten: dict[str, Any]) -> Anmeldung:
        zugriff = str(daten.get("access_token") or "")
        if not zugriff:
            return Anmeldung()
        self.anmeldung.access_token = zugriff
        self.anmeldung.refresh_token = str(
            daten.get("refresh_token") or self.anmeldung.refresh_token
        )
        self.anmeldung.laeuft_ab = time.time() + float(daten.get("expires_in") or 0)
        self._cache.vergiss()
        self._wer_bin_ich()
        return self.anmeldung

    def _wer_bin_ich(self) -> None:
        daten = self.helix("GET", "/users")
        eintraege = daten.get("data") or []
        if not eintraege:
            raise TwitchError("Twitch nennt kein Konto zu diesem Token")
        konto = eintraege[0]
        self.anmeldung.login = str(konto.get("login") or "")
        self.anmeldung.anzeigename = str(konto.get("display_name") or "")
        self.anmeldung.benutzer_id = str(konto.get("id") or "")

    @property
    def angemeldet(self) -> bool:
        return bool(self.anmeldung.access_token and self.anmeldung.benutzer_id)

    # -- Die eigentlichen Aufrufe -----------------------------------------

    def helix(
        self,
        methode: str,
        pfad: str,
        *,
        abfrage: dict[str, Any] | None = None,
        rumpf: dict[str, Any] | None = None,
        erneut: bool = True,
    ) -> dict[str, Any]:
        """Ein Aufruf gegen Helix. Antwort als Dict, ``{}`` bei 204."""
        if not self.anmeldung.access_token:
            raise NichtAngemeldet("Für Twitch ist noch niemand angemeldet")

        # Zehn Minuten Vorlauf: Ein Token, das während des Aufrufs abläuft,
        # kostet einen unnötigen Fehlversuch.
        if self.anmeldung.laeuft_ab and time.time() > self.anmeldung.laeuft_ab - 600:
            if self.anmeldung.refresh_token:
                self.erneuere()

        adresse = HELIX + pfad
        if abfrage:
            adresse += "?" + urllib.parse.urlencode(
                {k: v for k, v in abfrage.items() if v not in (None, "")}, doseq=True
            )
        kopf = {
            "Client-Id": self.client_id,
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
                if antwort.status == 204:
                    return {}
                return _lies(antwort) or {}
        except urllib.error.HTTPError as exc:
            # Ein abgelaufenes Token merkt man erst hier, wenn die Uhr des
            # Rechners falsch geht. Einmal erneuern und noch einmal fragen.
            if exc.code == 401 and erneut and self.anmeldung.refresh_token:
                self.erneuere()
                return self.helix(methode, pfad, abfrage=abfrage, rumpf=rumpf,
                                  erneut=False)
            raise TwitchError(_fehlertext(exc)) from exc
        except urllib.error.URLError as exc:
            raise TwitchError(f"Twitch ist nicht erreichbar: {exc.reason}") from exc
        except (TimeoutError, OSError) as exc:
            raise TwitchError(f"Verbindung abgebrochen: {exc}") from exc

    def _id_aufruf(self, pfad: str, felder: dict[str, str]) -> dict[str, Any]:
        rumpf = urllib.parse.urlencode(felder).encode("utf-8")
        anfrage = urllib.request.Request(
            ID_BASIS + pfad, data=rumpf, method="POST",
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
                "User-Agent": USER_AGENT,
            },
        )
        try:
            with urllib.request.urlopen(anfrage, timeout=ZEITLIMIT_S) as antwort:
                return _lies(antwort) or {}
        except urllib.error.HTTPError as exc:
            # Der Rumpf lässt sich nur einmal lesen: einmal lesen, daraus die
            # Kennung fürs Verhalten und den Text für den Menschen.
            roh = exc.read()
            if _kennung(roh) in WARTEN:
                raise NochNichtBestaetigt(_kennung(roh)) from exc
            raise TwitchError(_fehlertext_aus(exc, roh)) from exc
        except urllib.error.URLError as exc:
            raise TwitchError(f"Twitch ist nicht erreichbar: {exc.reason}") from exc

    # -- Was das Plugin abfragt -------------------------------------------

    def kanal(self) -> dict[str, Any]:
        """Titel, Kategorie und Sprache des eigenen Kanals."""
        zwischen = self._cache.hol("kanal", KANAL_FRISCH_S)
        if zwischen is not None:
            return zwischen
        daten = self.helix("GET", "/channels",
                           abfrage={"broadcaster_id": self.anmeldung.benutzer_id})
        eintrag = (daten.get("data") or [{}])[0]
        self._cache.leg_ab("kanal", eintrag)
        return eintrag

    def stream(self) -> dict[str, Any] | None:
        """Der laufende Stream — ``None``, wenn gerade keiner läuft."""
        zwischen = self._cache.hol("stream", FRISCH_S)
        if zwischen is not None:
            return zwischen or None
        daten = self.helix("GET", "/streams",
                           abfrage={"user_id": self.anmeldung.benutzer_id})
        eintraege = daten.get("data") or []
        eintrag = eintraege[0] if eintraege else {}
        self._cache.leg_ab("stream", eintrag)
        return eintrag or None

    def follower(self) -> int:
        zwischen = self._cache.hol("follower", FRISCH_S)
        if zwischen is not None:
            return zwischen
        daten = self.helix("GET", "/channels/followers", abfrage={
            "broadcaster_id": self.anmeldung.benutzer_id, "first": 1,
        })
        anzahl = int(daten.get("total") or 0)
        self._cache.leg_ab("follower", anzahl)
        return anzahl

    def chat_einstellungen(self) -> dict[str, Any]:
        zwischen = self._cache.hol("chat", FRISCH_S)
        if zwischen is not None:
            return zwischen
        daten = self.helix("GET", "/chat/settings", abfrage={
            "broadcaster_id": self.anmeldung.benutzer_id,
            "moderator_id": self.anmeldung.benutzer_id,
        })
        eintrag = (daten.get("data") or [{}])[0]
        self._cache.leg_ab("chat", eintrag)
        return eintrag

    def kategorien(self, suche: str) -> list[dict[str, Any]]:
        """Kategorien zu einem Suchbegriff — für die Auswahlliste."""
        if not suche.strip():
            return []
        daten = self.helix("GET", "/search/categories",
                           abfrage={"query": suche.strip(), "first": 20})
        return daten.get("data") or []

    def kanal_suchen(self, suche: str) -> list[dict[str, Any]]:
        """Kanäle zu einem Suchbegriff — für Raid und Shoutout."""
        if not suche.strip():
            return []
        daten = self.helix("GET", "/search/channels",
                           abfrage={"query": suche.strip(), "first": 20})
        return daten.get("data") or []

    def benutzer_id(self, login: str) -> str:
        """Die Kennung zu einem Kanalnamen."""
        name = login.strip().lstrip("@").lower()
        if not name:
            raise TwitchError("Kein Kanal angegeben")
        schluessel = f"id:{name}"
        zwischen = self._cache.hol(schluessel, KANAL_FRISCH_S)
        if zwischen is not None:
            return zwischen
        daten = self.helix("GET", "/users", abfrage={"login": name})
        eintraege = daten.get("data") or []
        if not eintraege:
            raise TwitchError(f"Kanal '{name}' gibt es nicht")
        kennung = str(eintraege[0].get("id") or "")
        self._cache.leg_ab(schluessel, kennung)
        return kennung

    def vergiss(self, praefix: str = "") -> None:
        """Nach einer Änderung: beim nächsten Zeichnen neu fragen."""
        self._cache.vergiss(praefix)
