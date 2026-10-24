"""Zeitzonen, Formate und die wenigen Wörter, die auf einer Uhr stehen.

Zeitzonen kommen aus der IANA-Datenbank, die jedes Linux unter
``/usr/share/zoneinfo`` mitbringt — dieselbe, aus der auch die Systemuhr
liest. Ein eigenes Verzeichnis von Städten und Abständen wäre nach der
nächsten Sommerzeitreform irgendwo falsch; die Datenbank wird mit dem
System aktualisiert.

Die Wörter stehen in ``locales/de.json`` und ``locales/en.json``. Übersetzt
wird dort, statt ``locale.setlocale`` zu rufen: Das wirkt prozessweit und
würde die Formatierung in allen anderen Plugins verändern.
"""

from __future__ import annotations

import zoneinfo
from datetime import datetime, timedelta, tzinfo
from functools import lru_cache
from pathlib import Path
from typing import Any

from deckswitch.plugins.base import plugin_text

#: Schlüssel der Wochentage und Monate in den Sprachdateien.
WOCHENTAGE = ("tag_mo", "tag_di", "tag_mi", "tag_do", "tag_fr", "tag_sa", "tag_so")
MONATE = ("monat_01", "monat_02", "monat_03", "monat_04", "monat_05", "monat_06",
          "monat_07", "monat_08", "monat_09", "monat_10", "monat_11", "monat_12")


def _t(schluessel: str, **werte: Any) -> str:
    """Text aus den Sprachdateien dieses Plugins."""
    return plugin_text(Path(__file__).resolve().parent, "clocks", schluessel, werte)


#: Zonen, durch die das Dial blättert. Am Dial durch alle knapp 600 zu
#: drehen wäre eine Strafarbeit; die volle Liste steht im Formular. Je
#: Abstand zur UTC eine bekannte Stadt, dazu die Zonen mit halben und
#: Dreiviertelstunden.
DIAL_ZONEN = [
    "Pacific/Honolulu", "America/Anchorage", "America/Los_Angeles",
    "America/Denver", "America/Chicago", "America/New_York",
    "America/Sao_Paulo", "Atlantic/Reykjavik", "Europe/London",
    "Europe/Berlin", "Europe/Athens", "Europe/Istanbul", "Europe/Moscow",
    "Asia/Dubai", "Asia/Karachi", "Asia/Kolkata", "Asia/Kathmandu",
    "Asia/Bangkok", "Asia/Shanghai", "Asia/Singapore", "Asia/Tokyo",
    "Australia/Adelaide", "Australia/Sydney", "Pacific/Auckland",
]


@lru_cache(maxsize=1)
def alle_zonen() -> list[str]:
    """Alle Zonen der Datenbank, ohne die Altlasten.

    ``Etc/GMT+5`` meint UTC−5 (das Vorzeichen ist absichtlich verdreht),
    ``US/Eastern`` und Konsorten sind Aliasse. Beides stiftet in einer
    Auswahlliste nur Verwirrung.
    """
    zonen = []
    for name in zoneinfo.available_timezones():
        if "/" not in name or name.startswith(("Etc/", "SystemV/", "US/", "posix/", "right/")):
            continue
        zonen.append(name)
    return sorted(zonen)


def zone(name: str | None) -> tzinfo | None:
    """Die Zone zu einem Namen; ``None`` heißt Systemzeit."""
    name = (name or "").strip()
    if not name:
        return None
    try:
        return zoneinfo.ZoneInfo(name)
    except (zoneinfo.ZoneInfoNotFoundError, ValueError):
        return None


def jetzt(name: str | None, referenz: datetime | None = None) -> datetime:
    """Die aktuelle Zeit in einer Zone, oder lokal ohne Zone.

    ``referenz`` ist ein fester Zeitpunkt für Prüfungen und Bilder; sie muss
    zeitzonenbewusst sein.
    """
    basis = referenz or datetime.now().astimezone()
    ziel = zone(name)
    return basis.astimezone(ziel) if ziel else basis.astimezone()


def stadt(name: str | None) -> str:
    """„America/Argentina/Buenos_Aires“ → „Buenos Aires“."""
    name = (name or "").strip()
    if not name:
        return ""
    return name.rsplit("/", 1)[-1].replace("_", " ")


def abstand(dauer: timedelta | None) -> str:
    """Ein Abstand zur UTC oder zur Ortszeit: ``+2``, ``−5:30``, ``+5:45``."""
    if dauer is None:
        return ""
    minuten = round(dauer.total_seconds() / 60)
    zeichen = "+" if minuten >= 0 else "−"
    stunden, rest = divmod(abs(minuten), 60)
    return f"{zeichen}{stunden}" + (f":{rest:02d}" if rest else "")


def utc_label(name: str) -> str:
    """Bezeichnung für die Auswahlliste: „Europe/Berlin · UTC+2“."""
    ziel = zone(name)
    if ziel is None:
        return name
    return f"{name} · UTC{abstand(datetime.now(ziel).utcoffset())}"


def unterschied(name: str | None, referenz: datetime | None = None) -> str:
    """Wie weit eine Zone von der Ortszeit weg ist, samt Tageswechsel."""
    lokal = jetzt(None, referenz)
    dort = jetzt(name, referenz)
    delta = (dort.utcoffset() or timedelta()) - (lokal.utcoffset() or timedelta())
    if not delta:
        text = _t("gleiche_zeit")
    else:
        text = f"{abstand(delta)} h"
    tage = (dort.date() - lokal.date()).days
    if tage > 0:
        text += f" · {_t('morgen')}"
    elif tage < 0:
        text += f" · {_t('gestern')}"
    return text


def uhrzeit(zeit: datetime, *, format24: bool, sekunden: bool) -> tuple[str, str]:
    """Uhrzeit als Text und, im 12-Stunden-Format, „AM“ oder „PM“."""
    if format24:
        text = f"{zeit.hour:02d}:{zeit.minute:02d}"
        tageszeit = ""
    else:
        stunde = zeit.hour % 12 or 12
        text = f"{stunde}:{zeit.minute:02d}"
        tageszeit = "AM" if zeit.hour < 12 else "PM"
    if sekunden:
        text += f":{zeit.second:02d}"
    return text, tageszeit


def ziffern(zeit: datetime, *, format24: bool, sekunden: bool) -> str:
    """Nur die Ziffern, immer zweistellig — für Segment, Matrix und Klappen."""
    stunde = zeit.hour if format24 else (zeit.hour % 12 or 12)
    text = f"{stunde:02d}{zeit.minute:02d}"
    if sekunden:
        text += f"{zeit.second:02d}"
    return text


def datum(zeit: datetime, modus: str) -> str:
    """Datum und Wochentag, je nach Einstellung."""
    tag = _t(WOCHENTAGE[zeit.weekday()])
    kalender = _t("datum_kalender", tag=zeit.day, monat=_t(MONATE[zeit.month - 1]))
    if modus == "date":
        return kalender
    if modus == "weekday":
        return tag
    if modus == "both":
        return f"{tag} {kalender}"
    return ""


# --------------------------------------------------------------------------
# Uhrzeit in Worten
# --------------------------------------------------------------------------

def in_worten(zeit: datetime) -> str:
    """Die Uhrzeit, wie man sie sagt, auf fünf Minuten gerundet.

    Ab welcher Minute die kommende Stunde genannt wird („halb sechs“ gegen
    „half past five“), steht als ``worte_naechste_ab`` in der Sprachdatei.
    """
    gesamt = zeit.hour * 60 + zeit.minute
    gerundet = (gesamt + 2) // 5 * 5
    stunde, minute = divmod(gerundet % (24 * 60), 60)
    try:
        naechste_ab = int(_t("worte_naechste_ab"))
    except ValueError:
        naechste_ab = 35
    if minute >= naechste_ab:
        stunde += 1
    if minute == 0 and stunde % 12 == 1:
        # „ein Uhr“, aber „fünf nach eins“.
        name = _t("stunde_1_voll")
    else:
        name = _t(f"stunde_{stunde % 12:02d}")
    return _t(f"worte_{minute:02d}", stunde=name)
