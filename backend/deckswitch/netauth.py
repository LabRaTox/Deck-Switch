"""Passwörter und Sitzungen für Netz-Decks.

Bewusst ein eigenes Modul: Alles, was über den Zugang entscheidet, steht an
einer Stelle und ist damit am Stück prüfbar. Der Rest der Anwendung fragt
nur ``pruefe_token`` und bekommt ein Deck oder nichts.

Drei Dinge halten Unbefugte draußen:

1. **Das Passwort verlässt den Rechner nie.** Gespeichert wird ein
   abgeleiteter Schlüssel (PBKDF2-HMAC-SHA256), aus dem sich das Passwort
   nicht zurückrechnen lässt. Wer die Konfigurationsdatei liest, hat noch
   nichts.
2. **Nach dem Anmelden zählt nur ein Token.** Es gilt befristet und für
   genau ein Deck. Das Passwort muss also nicht bei jedem Tastendruck
   mitwandern, wo es in Logs und Verläufen landen könnte.
3. **Raten wird teuer.** Nach einigen Fehlversuchen ist die Adresse für eine
   Weile gesperrt, und jeder Fehlversuch kostet ohnehin eine Wartezeit.

Was das *nicht* leistet: Die Verbindung ist unverschlüsselt. Im eigenen
Netz ist das vertretbar — über fremde Netze gehört ein Netz-Deck nicht.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import secrets
import time

log = logging.getLogger(__name__)

#: Rechenaufwand je Anmeldeversuch. Hoch genug, dass Durchprobieren nicht
#: lohnt, niedrig genug, dass eine Anmeldung nicht spürbar hängt.
ITERATIONEN = 210_000
SALT_BYTES = 16

#: Wie lange eine Sitzung gilt. Ein Stream dauert selten länger; danach
#: meldet sich der Client von selbst neu an.
TOKEN_GUELTIG_S = 12 * 3600

#: So viele Fehlversuche je Adresse, dann ist für ``SPERRE_S`` Schluss.
MAX_FEHLVERSUCHE = 5
FEHLER_FENSTER_S = 300
SPERRE_S = 300

#: Wartezeit nach einem falschen Passwort. Bremst Durchprobieren zusätzlich
#: und macht nebenbei Laufzeitunterschiede unauffällig.
STRAFE_S = 0.5


# ---------------------------------------------------------------------------
# Passwort
# ---------------------------------------------------------------------------


def hash_passwort(passwort: str) -> str:
    """Leitet aus dem Passwort einen Speicherwert ab.

    Format: ``pbkdf2_sha256$<runden>$<salz>$<schlüssel>``. Die Runden stehen
    mit drin, damit sich der Aufwand später erhöhen lässt, ohne dass alte
    Passwörter ungültig werden.
    """
    if not passwort:
        raise ValueError("Leeres Passwort")
    salz = secrets.token_bytes(SALT_BYTES)
    schluessel = hashlib.pbkdf2_hmac("sha256", passwort.encode("utf-8"), salz, ITERATIONEN)
    return "$".join((
        "pbkdf2_sha256",
        str(ITERATIONEN),
        base64.b64encode(salz).decode("ascii"),
        base64.b64encode(schluessel).decode("ascii"),
    ))


def pruefe_passwort(passwort: str, gespeichert: str) -> bool:
    """Vergleicht in konstanter Zeit — die Dauer verrät sonst Teiltreffer."""
    if not passwort or not gespeichert:
        return False
    try:
        art, runden, salz_b64, schluessel_b64 = gespeichert.split("$")
        if art != "pbkdf2_sha256":
            return False
        salz = base64.b64decode(salz_b64)
        erwartet = base64.b64decode(schluessel_b64)
    except (ValueError, TypeError):
        log.warning("Gespeichertes Passwort ist unlesbar — Zugang bleibt zu")
        return False

    versuch = hashlib.pbkdf2_hmac("sha256", passwort.encode("utf-8"), salz, int(runden))
    return hmac.compare_digest(versuch, erwartet)


# ---------------------------------------------------------------------------
# Sitzungen
# ---------------------------------------------------------------------------


class Sitzungen:
    """Vergibt Token und merkt sich Fehlversuche je Adresse.

    Alles nur im Speicher: Nach einem Neustart des Backends meldet sich
    jeder neu an. Das ist gewollt — ein Token, das einen Neustart überlebt,
    müsste auf die Platte, und dort hat es nichts zu suchen.
    """

    def __init__(self) -> None:
        self._token: dict[str, tuple[str, float]] = {}
        self._fehlversuche: dict[str, list[float]] = {}

    # -- Anmelden ----------------------------------------------------------

    def gesperrt_bis(self, adresse: str) -> float:
        """Bis wann diese Adresse gesperrt ist (0 = nicht gesperrt)."""
        versuche = self._aktuelle_fehlversuche(adresse)
        if len(versuche) < MAX_FEHLVERSUCHE:
            return 0.0
        return versuche[-1] + SPERRE_S

    def melde_fehlversuch(self, adresse: str) -> None:
        self._fehlversuche.setdefault(adresse, []).append(time.monotonic())

    def melde_erfolg(self, adresse: str) -> None:
        self._fehlversuche.pop(adresse, None)

    def _aktuelle_fehlversuche(self, adresse: str) -> list[float]:
        jetzt = time.monotonic()
        versuche = [t for t in self._fehlversuche.get(adresse, []) if jetzt - t < FEHLER_FENSTER_S]
        if versuche:
            self._fehlversuche[adresse] = versuche
        else:
            self._fehlversuche.pop(adresse, None)
        return versuche

    # -- Token -------------------------------------------------------------

    def neues_token(self, deck_key: str) -> tuple[str, int]:
        """Legt eine Sitzung an. Liefert Token und Gültigkeit in Sekunden."""
        self._aufraeumen()
        token = secrets.token_urlsafe(32)
        self._token[token] = (deck_key, time.monotonic() + TOKEN_GUELTIG_S)
        return token, TOKEN_GUELTIG_S

    def pruefe_token(self, token: str) -> str | None:
        """Liefert das Deck zum Token — oder ``None``."""
        if not token:
            return None
        eintrag = self._token.get(token)
        if eintrag is None:
            return None
        deck_key, ablauf = eintrag
        if time.monotonic() > ablauf:
            self._token.pop(token, None)
            return None
        return deck_key

    def verwerfen(self, token: str) -> None:
        self._token.pop(token, None)

    def alle_verwerfen(self, deck_key: str) -> int:
        """Wirft jede Sitzung eines Decks raus — etwa nach neuem Passwort.

        Sonst käme jemand mit einem alten Token weiter herein, obwohl das
        Passwort gerade gewechselt wurde. Genau dann wechselt man es aber.
        """
        betroffen = [t for t, (key, _) in self._token.items() if key == deck_key]
        for token in betroffen:
            self._token.pop(token, None)
        return len(betroffen)

    def _aufraeumen(self) -> None:
        jetzt = time.monotonic()
        for token in [t for t, (_, ablauf) in self._token.items() if jetzt > ablauf]:
            self._token.pop(token, None)
