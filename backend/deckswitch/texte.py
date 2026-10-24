"""Texte für die Oberfläche, in der eingestellten Sprache.

Alles, was das Backend an die Oberfläche schickt (Fehlermeldungen, Hinweise,
Begründungen), steht nicht im Code, sondern in ``locales/de.json`` und
``locales/en.json``. Im Code steht nur ein Schlüssel::

    raise DesktopError(t("desktop.programm_fehlt", programm=argv[0]))

``t`` liefert eine gewöhnliche Zeichenkette. Sie trägt ihren Schlüssel als
``code`` mit, damit die Oberfläche auf einen Fehler reagieren kann, ohne
seinen Wortlaut zu vergleichen.

Die Sprache kommt aus der Konfiguration (``app.language``). Die Runtime
meldet sie über :func:`verbinde_sprache` an. Ohne Runtime, etwa in Tests,
gilt Deutsch.

Fehlt ein Text in der gewünschten Sprache, kommt der englische, dann der
deutsche, zuletzt der Schlüssel selbst. Eine Lücke in einer Übersetzung
führt so nie zu einem Absturz.

Log-Zeilen bleiben Deutsch und stehen weiter direkt im Code. Sie erscheinen
nur im Journal und dienen der Fehlersuche.

Plugins übersetzen mit demselben Verfahren über ``self.t`` aus
:class:`deckswitch.plugins.base.ActionPlugin`, mit eigenen Sprachdateien im
Plugin-Ordner.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from pathlib import Path

log = logging.getLogger(__name__)

SPRACHEN = ("de", "en")
VORGABE = "de"

#: Reihenfolge, in der nach einem Text gesucht wird, wenn er in der
#: gewünschten Sprache fehlt.
ERSATZ = ("en", "de")

ORDNER = Path(__file__).resolve().parent / "locales"


class Text(str):
    """Eine übersetzte Zeichenkette, die ihren Schlüssel und ihre Werte kennt.

    Die Werte braucht :func:`aktuell`, um einen gespeicherten Text nach einem
    Sprachwechsel neu zu erzeugen.
    """

    code: str
    werte: dict

    def __new__(cls, inhalt: str, code: str, werte: dict | None = None) -> "Text":
        neu = super().__new__(cls, inhalt)
        neu.code = code
        neu.werte = dict(werte or {})
        return neu


def _vorgabe() -> str:
    return VORGABE


_sprache_holen: Callable[[], str] = _vorgabe
_kataloge: dict[Path, dict[str, dict[str, str]]] = {}


def verbinde_sprache(holen: Callable[[], str]) -> None:
    """Sagt, woher die aktuelle Sprache kommt. Die Runtime ruft das beim Start."""
    global _sprache_holen
    _sprache_holen = holen


def sprache() -> str:
    try:
        wert = _sprache_holen()
    except Exception:  # noqa: BLE001 - ohne Sprache gilt die Vorgabe
        wert = VORGABE
    return wert if wert in SPRACHEN else VORGABE


def lade(ordner: Path) -> dict[str, dict[str, str]]:
    """Die Sprachdateien eines Ordners, einmal gelesen und dann behalten."""
    ordner = Path(ordner)
    if ordner not in _kataloge:
        kataloge: dict[str, dict[str, str]] = {}
        for code in SPRACHEN:
            datei = ordner / f"{code}.json"
            try:
                kataloge[code] = json.loads(datei.read_text(encoding="utf-8"))
            except FileNotFoundError:
                kataloge[code] = {}
            except (OSError, ValueError) as exc:
                log.warning("Sprachdatei %s unlesbar: %s", datei, exc)
                kataloge[code] = {}
        _kataloge[ordner] = kataloge
    return _kataloge[ordner]


def vergiss(ordner: Path) -> None:
    """Vergisst die Sprachdateien eines Ordners, etwa nach einem Plugin-Update."""
    _kataloge.pop(Path(ordner), None)


class _Werte(dict):
    """Lässt einen fehlenden Platzhalter stehen, statt abzubrechen."""

    def __missing__(self, schluessel: str) -> str:
        return "{" + schluessel + "}"


def uebersetze(
    kataloge: dict[str, dict[str, str]], schluessel: str, ziel: str, werte: dict
) -> str | None:
    """Der Text zu ``schluessel`` in ``ziel`` oder einer Ersatzsprache, sonst ``None``."""
    for code in (ziel, *ERSATZ):
        vorlage = kataloge.get(code, {}).get(schluessel)
        if vorlage is not None:
            return vorlage.format_map(_Werte(werte))
    return None


def t(schluessel: str, **werte) -> Text:
    """Der Text zu ``schluessel`` in der eingestellten Sprache."""
    inhalt = uebersetze(lade(ORDNER), schluessel, sprache(), werte)
    if inhalt is None:
        log.warning("Kein Text für '%s'", schluessel)
        inhalt = schluessel
    return Text(inhalt, schluessel, werte)


def aktuell(wert):
    """Ein gespeicherter Text in der Sprache, die jetzt gilt.

    Für Texte, die einmal entstehen und später ausgeliefert werden, etwa die
    Begründung, warum eine Fähigkeit fehlt. Alles andere kommt unverändert
    zurück, auch Texte von Plugins: Die kennen ihre Sprachdateien selbst.
    """
    if isinstance(wert, Text) and "." in wert.code and wert.code.split(".", 1)[0] in _kern_module():
        werte = {k: aktuell(v) for k, v in wert.werte.items()}
        return t(wert.code, **werte)
    return wert


_kern_cache: tuple[dict, frozenset[str]] | None = None


def _kern_module() -> frozenset[str]:
    """Die Präfixe der Kern-Schlüssel. Einmal je Katalog berechnet."""
    global _kern_cache
    katalog = lade(ORDNER).get(VORGABE, {})
    if _kern_cache is None or _kern_cache[0] is not katalog:
        _kern_cache = (katalog, frozenset(s.split(".", 1)[0] for s in katalog))
    return _kern_cache[1]


def code_von(fehler: BaseException | str | None) -> str | None:
    """Der Schlüssel einer Meldung, auch wenn sie in einem Fehler steckt."""
    if isinstance(fehler, Text):
        return fehler.code
    if isinstance(fehler, BaseException):
        for teil in (*fehler.args, fehler.__cause__):
            if isinstance(teil, Text):
                return teil.code
            if isinstance(teil, BaseException) and teil is not fehler:
                code = code_von(teil)
                if code:
                    return code
    return None
