"""Zifferblätter und Farbschemata — alles, was eine Uhr auf eine Kachel malt.

Analoge Blätter werden vierfach so groß gezeichnet und dann verkleinert:
Pillow glättet Linien und Polygone nicht, und ein Zeiger mit Treppenkante
fällt auf 120 Pixeln sofort auf. Text braucht das nicht, FreeType glättet
selbst.

Schema und Blatt sind getrennt. Das Blatt bestimmt die Form (Striche,
Zahlen, Zeiger), das Schema die Farben. So ergibt jede Kombination eine
brauchbare Uhr, ohne dass jede einzeln gezeichnet werden muss.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from datetime import datetime

from PIL import Image, ImageDraw

from deckswitch.services.backgrounds import parse_color
from deckswitch.services.render import load_font

from . import zeit as z

#: Überabtastung für alles, was keine Schrift ist.
FAKTOR = 4

Farbe = tuple[int, int, int, int]


def _farbe(text: str) -> Farbe:
    return parse_color(text, (255, 255, 255, 255))


@dataclass(frozen=True)
class Schema:
    """Die Farben einer Uhr."""

    #: Fläche des Zifferblatts. ``None`` heißt: kein Blatt, die Uhr steht
    #: direkt auf dem Hintergrund der Taste.
    blatt: Farbe | None
    schrift: Farbe
    zeiger: Farbe
    akzent: Farbe
    gedimmt: Farbe


def _schema(blatt: str | None, schrift: str, zeiger: str, akzent: str, gedimmt: str) -> Schema:
    return Schema(
        blatt=_farbe(blatt) if blatt else None,
        schrift=_farbe(schrift),
        zeiger=_farbe(zeiger),
        akzent=_farbe(akzent),
        gedimmt=_farbe(gedimmt),
    )


#: Farbschemata: Schlüssel des Namens in den Sprachdateien und die Farben.
SCHEMATA: dict[str, tuple[str, Schema]] = {
    "night": ("schema_night",
              _schema("#111827", "#f9fafb", "#f9fafb", "#ef4444", "#4b5563")),
    "light": ("schema_light",
              _schema("#f8fafc", "#0f172a", "#0f172a", "#dc2626", "#94a3b8")),
    "ocean": ("schema_ocean",
              _schema("#0c4a6e", "#e0f2fe", "#e0f2fe", "#38bdf8", "#0369a1")),
    "forest": ("schema_forest",
               _schema("#14532d", "#dcfce7", "#dcfce7", "#4ade80", "#166534")),
    "amber": ("schema_amber",
              _schema("#1c1917", "#fbbf24", "#fbbf24", "#f97316", "#57534e")),
    "red": ("schema_red",
            _schema("#0a0a0a", "#dc2626", "#dc2626", "#f87171", "#450a0a")),
    "violet": ("schema_violet",
               _schema("#2e1065", "#ede9fe", "#ede9fe", "#c084fc", "#5b21b6")),
    "teal": ("schema_teal",
             _schema("#134e4a", "#ccfbf1", "#ccfbf1", "#2dd4bf", "#0f766e")),
    "none": ("schema_none",
             _schema(None, "#ffffff", "#ffffff", "#ef4444", "#6b7280")),
}


@dataclass(frozen=True)
class Analog:
    #: ``hm`` Stunden und Minuten, ``h`` Stunden, ``q`` Viertel, ``dots``
    #: Punkte, ``bars`` kräftige Balken (Bahnhof), ``none`` nichts.
    striche: str = "hm"
    #: ``12`` alle Zahlen, ``4`` nur 12/3/6/9, ``roman`` römisch 12/3/6/9.
    zahlen: str = ""
    #: ``taper`` spitz zulaufend, ``bar`` gerade Balken, ``thin`` dünn,
    #: ``rail`` Bahnhof mit roter Kelle.
    zeiger: str = "taper"
    #: Minuten als Bogen um das Blatt.
    bogen: bool = False
    #: Fenster mit dem Tag bei drei Uhr.
    datumsfenster: bool = False
    #: Dünner Ring am Rand.
    rand: bool = False


#: Analoge Blätter: Schlüssel des Namens und die Gestaltung.
ANALOG: dict[str, tuple[str, Analog]] = {
    "classic": ("analog_classic", Analog(rand=True)),
    "numbers": ("analog_numbers", Analog(striche="m", zahlen="12")),
    "roman": ("analog_roman",
              Analog(striche="h", zahlen="roman", zeiger="thin", rand=True)),
    "minimal": ("analog_minimal", Analog(striche="q", zeiger="thin")),
    "dots": ("analog_dots", Analog(striche="dots", zeiger="bar")),
    "railway": ("analog_railway", Analog(striche="bars", zeiger="rail")),
    "bauhaus": ("analog_bauhaus",
                Analog(striche="none", zahlen="4", zeiger="thin")),
    "ring": ("analog_ring", Analog(striche="none", zeiger="bar", bogen=True)),
    "modern": ("analog_modern", Analog(striche="h", zeiger="bar")),
    "chrono": ("analog_chrono",
               Analog(striche="hm", zahlen="4", datumsfenster=True)),
    "hands": ("analog_hands", Analog(striche="none")),
}

#: Digitale Blätter: Schlüssel des Namens.
DIGITAL: dict[str, str] = {
    "classic": "digital_classic",
    "light": "digital_light",
    "mono": "digital_mono",
    "serif": "digital_serif",
    "segment": "digital_segment",
    "matrix": "digital_matrix",
    "stacked": "digital_stacked",
    "flip": "digital_flip",
    "binary": "digital_binary",
    "dayarc": "digital_dayarc",
    "words": "digital_words",
}


@dataclass(frozen=True)
class Uhr:
    """Was gezeichnet werden soll — alles außer der Zeit selbst."""

    art: str = "analog"
    blatt: str = "classic"
    schema: Schema = SCHEMATA["night"][1]
    format24: bool = True
    sekunden: bool = False
    oben: str = ""
    unten: str = ""


def mit_farben(schema: Schema, blatt: str = "", schrift: str = "", akzent: str = "") -> Schema:
    """Eigene Farben über ein Schema legen. Leer heißt: wie im Schema."""
    neu = schema
    if blatt:
        neu = replace(neu, blatt=_farbe(blatt))
    if schrift:
        neu = replace(neu, schrift=_farbe(schrift), zeiger=_farbe(schrift))
    if akzent:
        neu = replace(neu, akzent=_farbe(akzent))
    return neu


def zeichne(bild: Image.Image, box: tuple[int, int, int, int], zeit: datetime, uhr: Uhr) -> None:
    """Malt die Uhr in den Kasten ``box`` (links, oben, rechts, unten)."""
    if uhr.art == "digital":
        _digital(bild, box, zeit, uhr)
    else:
        _analog(bild, box, zeit, uhr)


# ==========================================================================
# Analog
# ==========================================================================


def _punkt(cx: float, cy: float, laenge: float, winkel: float) -> tuple[float, float]:
    """Ein Punkt auf dem Blatt; Winkel 0 ist zwölf Uhr, im Uhrzeigersinn."""
    return cx + math.sin(winkel) * laenge, cy - math.cos(winkel) * laenge


def _zeiger(draw, cx, cy, winkel, laenge, breite, farbe, *, spitze=0.35, heck=0.0):
    """Ein Zeiger als Viereck: am Fuß ``breite``, an der Spitze schmaler."""
    quer = winkel + math.pi / 2
    fuss = _punkt(cx, cy, -heck, winkel)
    kopf = _punkt(cx, cy, laenge, winkel)
    b1, b2 = breite / 2, breite * spitze / 2
    punkte = [
        (fuss[0] + math.sin(quer) * b1, fuss[1] - math.cos(quer) * b1),
        (kopf[0] + math.sin(quer) * b2, kopf[1] - math.cos(quer) * b2),
        (kopf[0] - math.sin(quer) * b2, kopf[1] + math.cos(quer) * b2),
        (fuss[0] - math.sin(quer) * b1, fuss[1] + math.cos(quer) * b1),
    ]
    draw.polygon(punkte, fill=farbe)
    # Runde Enden: Ohne sie sehen dicke Zeiger abgehackt aus.
    if spitze >= 0.9:
        draw.ellipse((kopf[0] - b2, kopf[1] - b2, kopf[0] + b2, kopf[1] + b2), fill=farbe)
    draw.ellipse((fuss[0] - b1, fuss[1] - b1, fuss[0] + b1, fuss[1] + b1), fill=farbe)


def _analog(bild: Image.Image, box, zeit: datetime, uhr: Uhr) -> None:
    links, oben, rechts, unten = box
    breite, hoehe = rechts - links, unten - oben
    seite = min(breite, hoehe)
    stil = ANALOG.get(uhr.blatt, ANALOG["classic"])[1]
    schema = uhr.schema

    # Vierfach groß zeichnen, dann verkleinern.
    gross = seite * FAKTOR
    ebene = Image.new("RGBA", (gross, gross), (0, 0, 0, 0))
    draw = ImageDraw.Draw(ebene)
    cx = cy = gross / 2
    r = gross / 2 - 2 * FAKTOR

    if schema.blatt is not None:
        draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=schema.blatt)
    if stil.rand:
        draw.ellipse((cx - r, cy - r, cx + r, cy + r), outline=schema.gedimmt,
                     width=max(1, round(r * 0.025)))

    # Minutenbogen: der Teil der Stunde, der schon vorbei ist.
    if stil.bogen:
        dicke = r * 0.09
        kasten = (cx - r + dicke / 2, cy - r + dicke / 2, cx + r - dicke / 2, cy + r - dicke / 2)
        draw.arc(kasten, 0, 360, fill=schema.gedimmt, width=round(dicke))
        anteil = (zeit.minute + zeit.second / 60) / 60
        if anteil > 0:
            draw.arc(kasten, -90, -90 + 360 * anteil, fill=schema.akzent, width=round(dicke))

    _striche(draw, cx, cy, r, stil, schema)
    _zahlen(ebene, cx, cy, r, stil, schema)

    if stil.datumsfenster:
        _datumsfenster(ebene, cx, cy, r, zeit, schema)

    # Beschriftungen innen, oberhalb und unterhalb der Mitte. Sie kommen vor
    # den Zeigern, damit ein Zeiger darüber liegt und nicht darunter.
    # Bei Blättern mit Zahlen bleibt zwischen 9 und 3 weniger Platz.
    platz = r * (0.9 if stil.zahlen else 1.15)
    if uhr.oben:
        _text_mittig(ebene, uhr.oben, (cx, cy - r * 0.4), r * 0.2, platz, schema.schrift)
    if uhr.unten:
        _text_mittig(ebene, uhr.unten, (cx, cy + r * 0.4), r * 0.2, platz, schema.schrift)

    stunde = (zeit.hour % 12 + zeit.minute / 60) / 12 * 2 * math.pi
    minute = (zeit.minute + zeit.second / 60) / 60 * 2 * math.pi
    sekunde = zeit.second / 60 * 2 * math.pi

    if stil.zeiger == "rail":
        _zeiger(draw, cx, cy, stunde, r * 0.55, r * 0.11, schema.zeiger, spitze=0.8, heck=r * 0.18)
        _zeiger(draw, cx, cy, minute, r * 0.85, r * 0.08, schema.zeiger, spitze=0.75, heck=r * 0.18)
    elif stil.zeiger == "bar":
        _zeiger(draw, cx, cy, stunde, r * 0.5, r * 0.11, schema.zeiger, spitze=1.0)
        if stil.bogen:
            # Beim Ring zeigt der Bogen die Minuten; ein Punkt am Rand reicht.
            spitze = _punkt(cx, cy, r * 0.955, minute)
            d = r * 0.075
            draw.ellipse((spitze[0] - d, spitze[1] - d, spitze[0] + d, spitze[1] + d),
                         fill=schema.zeiger)
        else:
            _zeiger(draw, cx, cy, minute, r * 0.78, r * 0.075, schema.zeiger, spitze=1.0)
    elif stil.zeiger == "thin":
        _zeiger(draw, cx, cy, stunde, r * 0.5, r * 0.05, schema.zeiger, spitze=0.6)
        _zeiger(draw, cx, cy, minute, r * 0.8, r * 0.035, schema.zeiger, spitze=0.6)
    else:
        _zeiger(draw, cx, cy, stunde, r * 0.52, r * 0.09, schema.zeiger, heck=r * 0.08)
        _zeiger(draw, cx, cy, minute, r * 0.8, r * 0.065, schema.zeiger, heck=r * 0.1)

    if uhr.sekunden:
        if stil.zeiger == "rail":
            _zeiger(draw, cx, cy, sekunde, r * 0.62, r * 0.025, schema.akzent, spitze=1.0,
                    heck=r * 0.25)
            kelle = _punkt(cx, cy, r * 0.62, sekunde)
            d = r * 0.1
            draw.ellipse((kelle[0] - d, kelle[1] - d, kelle[0] + d, kelle[1] + d),
                         fill=schema.akzent)
        else:
            _zeiger(draw, cx, cy, sekunde, r * 0.88, r * 0.022, schema.akzent, spitze=1.0,
                    heck=r * 0.18)

    kappe = r * (0.06 if uhr.sekunden else 0.05)
    farbe = schema.akzent if uhr.sekunden else schema.zeiger
    draw.ellipse((cx - kappe, cy - kappe, cx + kappe, cy + kappe), fill=farbe)

    klein = ebene.resize((seite, seite), Image.Resampling.LANCZOS)
    bild.alpha_composite(klein, (links + (breite - seite) // 2, oben + (hoehe - seite) // 2))


def _striche(draw, cx, cy, r, stil: Analog, schema: Schema) -> None:
    if stil.striche in ("none", ""):
        return
    for i in range(60):
        winkel = i / 60 * 2 * math.pi
        voll = i % 5 == 0
        viertel = i % 15 == 0
        if stil.striche == "dots":
            if not voll:
                continue
            d = r * (0.06 if viertel else 0.035)
            p = _punkt(cx, cy, r * 0.86, winkel)
            draw.ellipse((p[0] - d, p[1] - d, p[0] + d, p[1] + d), fill=schema.schrift)
            continue
        if stil.striche == "q" and not viertel:
            continue
        if stil.striche == "h" and not voll:
            continue
        if stil.striche == "m" and voll:
            # Bei Blättern mit allen Zahlen stehen an den vollen Stunden die
            # Zahlen; ein Strich dazu wäre doppelt.
            continue
        if stil.striche == "bars":
            laenge, dicke = (r * 0.2, r * 0.07) if voll else (r * 0.06, r * 0.025)
        elif voll:
            laenge, dicke = r * (0.17 if viertel and stil.striche == "q" else 0.14), r * 0.035
        else:
            laenge, dicke = r * 0.06, r * 0.014
        farbe = schema.schrift if (voll or stil.striche == "bars") else schema.gedimmt
        aussen = _punkt(cx, cy, r * 0.94, winkel)
        innen = _punkt(cx, cy, r * 0.94 - laenge, winkel)
        draw.line([innen, aussen], fill=farbe, width=max(1, round(dicke)))


_ROEMISCH = {12: "XII", 3: "III", 6: "VI", 9: "IX"}


def _zahlen(ebene, cx, cy, r, stil: Analog, schema: Schema) -> None:
    if not stil.zahlen:
        return
    if stil.zahlen == "12":
        stunden, abstand, groesse = range(1, 13), 0.74, 0.24
    else:
        stunden, abstand, groesse = (12, 3, 6, 9), 0.72, 0.27
    # Mit Strichen am Rand rücken die Zahlen ein Stück nach innen.
    if stil.striche in ("hm", "h"):
        abstand -= 0.06
    for stunde in stunden:
        if stunde == 3 and stil.datumsfenster:
            continue  # dort sitzt das Datumsfenster, wie bei echten Chronographen
        text = _ROEMISCH[stunde] if stil.zahlen == "roman" else str(stunde)
        p = _punkt(cx, cy, r * abstand, stunde / 12 * 2 * math.pi)
        _text_mittig(ebene, text, p, r * groesse, r * 0.6, schema.schrift, bold=True)


def _datumsfenster(ebene, cx, cy, r, zeit: datetime, schema: Schema) -> None:
    draw = ImageDraw.Draw(ebene)
    mitte = (cx + r * 0.62, cy)
    b, h = r * 0.34, r * 0.25
    hell = schema.blatt is None or sum(schema.blatt[:3]) < 384
    grund = (245, 245, 245, 255) if hell else (20, 20, 20, 255)
    schrift = (20, 20, 20, 255) if hell else (245, 245, 245, 255)
    draw.rounded_rectangle((mitte[0] - b / 2, mitte[1] - h / 2, mitte[0] + b / 2, mitte[1] + h / 2),
                           radius=r * 0.03, fill=grund, outline=schema.gedimmt,
                           width=max(1, round(r * 0.012)))
    _text_mittig(ebene, str(zeit.day), mitte, h * 0.85, b * 0.9, schrift, bold=True)


# ==========================================================================
# Digital
# ==========================================================================


def _digital(bild: Image.Image, box, zeit: datetime, uhr: Uhr) -> None:
    links, oben, rechts, unten = box
    breite, hoehe = rechts - links, unten - oben
    schema = uhr.schema
    einheit = min(breite, hoehe) / 120

    if schema.blatt is not None:
        flaeche = Image.new("RGBA", bild.size, (0, 0, 0, 0))
        ImageDraw.Draw(flaeche).rounded_rectangle(
            (links + 3, oben + 3, rechts - 3, unten - 3), radius=round(14 * einheit),
            fill=schema.blatt,
        )
        bild.alpha_composite(flaeche)

    # Kopf- und Fußzeile nehmen sich ihren Platz, die Uhrzeit bekommt den Rest.
    zeile = round(15 * einheit)
    innen_oben = oben + (zeile + round(8 * einheit) if uhr.oben else round(8 * einheit))
    innen_unten = unten - (zeile + round(8 * einheit) if uhr.unten else round(8 * einheit))
    if uhr.oben:
        _text_mittig(bild, uhr.oben, ((links + rechts) / 2, oben + 6 * einheit + zeile / 2),
                     zeile, breite - 14 * einheit, schema.schrift)
    if uhr.unten:
        _text_mittig(bild, uhr.unten, ((links + rechts) / 2, unten - 6 * einheit - zeile / 2),
                     zeile, breite - 14 * einheit, schema.schrift)

    feld = (links + round(8 * einheit), innen_oben, rechts - round(8 * einheit), innen_unten)
    blatt = uhr.blatt if uhr.blatt in DIGITAL else "classic"
    zeichner = {
        "segment": _segment, "matrix": _matrix, "stacked": _gestapelt,
        "flip": _klappen, "binary": _binaer, "dayarc": _tagesbogen, "words": _worte,
    }.get(blatt, _schriftzeit)
    zeichner(bild, feld, zeit, uhr)


def _schriftzeit(bild, feld, zeit: datetime, uhr: Uhr) -> None:
    """Die Uhrzeit als Text, in der Schrift des Blatts."""
    familie, fett = {
        "light": ("", False), "mono": ("monospace", True), "serif": ("serif", True),
    }.get(uhr.blatt, ("", True))
    text, tageszeit = z.uhrzeit(zeit, format24=uhr.format24, sekunden=uhr.sekunden)
    links, oben, rechts, unten = feld
    mitte = ((links + rechts) / 2, (oben + unten) / 2)
    hoehe = unten - oben
    if tageszeit:
        groesse = _passend(text, rechts - links, hoehe * 0.62, fett, familie)
        _text_mittig(bild, text, (mitte[0], mitte[1] - hoehe * 0.1), groesse,
                     rechts - links, uhr.schema.schrift, bold=fett, family=familie)
        _text_mittig(bild, tageszeit, (mitte[0], unten - hoehe * 0.12), hoehe * 0.24,
                     rechts - links, uhr.schema.akzent, bold=True)
    else:
        groesse = _passend(text, rechts - links, hoehe * 0.7, fett, familie)
        _text_mittig(bild, text, mitte, groesse, rechts - links, uhr.schema.schrift,
                     bold=fett, family=familie)


def _gestapelt(bild, feld, zeit: datetime, uhr: Uhr) -> None:
    """Stunden über Minuten, groß; Sekunden und AM/PM klein daneben."""
    links, oben, rechts, unten = feld
    stunde = zeit.hour if uhr.format24 else (zeit.hour % 12 or 12)
    hoehe = unten - oben
    breite = rechts - links
    zeilen = [f"{stunde:02d}", f"{zeit.minute:02d}"]
    groesse = _passend("00", breite * 0.8, hoehe * 0.5, True, "")
    for i, text in enumerate(zeilen):
        y = oben + hoehe * (0.26 + 0.5 * i)
        farbe = uhr.schema.schrift if i == 0 else uhr.schema.akzent
        _text_mittig(bild, text, ((links + rechts) / 2, y), groesse, breite, farbe, bold=True)
    zusatz = []
    if uhr.sekunden:
        zusatz.append(f"{zeit.second:02d}")
    if not uhr.format24:
        zusatz.append("AM" if zeit.hour < 12 else "PM")
    if zusatz:
        _text_mittig(bild, " ".join(zusatz), (rechts - breite * 0.06, oben + hoehe * 0.5),
                     hoehe * 0.13, breite * 0.3, uhr.schema.gedimmt, bold=True, anker="rm")


# -- 7-Segment -------------------------------------------------------------

#: Welche Segmente je Ziffer leuchten: a oben, b oben rechts, c unten
#: rechts, d unten, e unten links, f oben links, g Mitte.
_SEGMENTE = {
    "0": "abcdef", "1": "bc", "2": "abged", "3": "abgcd", "4": "fgbc",
    "5": "afgcd", "6": "afgedc", "7": "abc", "8": "abcdefg", "9": "abcdfg",
}


def _ziffernreihe(feld, anzahl: int, verhaeltnis: float, luecke: float):
    """Verteilt ``anzahl`` Ziffern in Paaren über das Feld.

    Zwischen den Paaren bleibt Platz für einen Doppelpunkt. Zurück kommen
    die Kästen der Ziffern und die Mitten der Doppelpunkte.
    """
    links, oben, rechts, unten = feld
    breite, hoehe = rechts - links, unten - oben
    paare = anzahl // 2
    # Ziffernbreite aus der Höhe, dann notfalls schrumpfen, bis es passt.
    zh = hoehe * 0.8
    zb = zh * verhaeltnis
    gesamt = anzahl * zb + (anzahl - paare) * zb * luecke + (paare - 1) * zb * 0.6
    if gesamt > breite:
        faktor = breite / gesamt
        zb, zh = zb * faktor, zh * faktor
        gesamt = breite
    x = links + (breite - gesamt) / 2
    y = oben + (hoehe - zh) / 2
    kaesten, punkte = [], []
    for i in range(anzahl):
        kaesten.append((x, y, x + zb, y + zh))
        x += zb
        if i % 2 == 0:
            x += zb * luecke
        elif i < anzahl - 1:
            punkte.append((x + zb * 0.3, y + zh / 2))
            x += zb * 0.6
    return kaesten, punkte, zh


def _segment(bild, feld, zeit: datetime, uhr: Uhr) -> None:
    text = z.ziffern(zeit, format24=uhr.format24, sekunden=uhr.sekunden)
    groesse = (bild.width * FAKTOR, bild.height * FAKTOR)
    ebene = Image.new("RGBA", groesse, (0, 0, 0, 0))
    draw = ImageDraw.Draw(ebene)
    f = [v * FAKTOR for v in feld]
    kaesten, punkte, zh = _ziffernreihe(f, len(text), 0.5, 0.18)
    aus = (*uhr.schema.gedimmt[:3], 70)
    for ziffer, (x0, y0, x1, y1) in zip(text, kaesten):
        _sieben(draw, (x0, y0, x1, y1), _SEGMENTE[ziffer], uhr.schema.schrift, aus)
    _doppelpunkte(draw, punkte, zh, uhr.schema.schrift)
    bild.alpha_composite(ebene.resize(bild.size, Image.Resampling.LANCZOS))
    if not uhr.format24:
        _ampm(bild, feld, zeit, uhr)


def _sieben(draw, kasten, an: str, farbe, aus) -> None:
    x0, y0, x1, y1 = kasten
    b, h = x1 - x0, y1 - y0
    d = b * 0.2  # Segmentdicke
    m = y0 + h / 2

    def waagrecht(y):
        return [(x0 + d * 0.6, y), (x0 + d, y - d / 2), (x1 - d, y - d / 2),
                (x1 - d * 0.6, y), (x1 - d, y + d / 2), (x0 + d, y + d / 2)]

    def senkrecht(x, ya, yb):
        return [(x, ya + d * 0.6), (x + d / 2, ya + d), (x + d / 2, yb - d),
                (x, yb - d * 0.6), (x - d / 2, yb - d), (x - d / 2, ya + d)]

    formen = {
        "a": waagrecht(y0 + d / 2), "g": waagrecht(m), "d": waagrecht(y1 - d / 2),
        "f": senkrecht(x0 + d / 2, y0, m), "b": senkrecht(x1 - d / 2, y0, m),
        "e": senkrecht(x0 + d / 2, m, y1), "c": senkrecht(x1 - d / 2, m, y1),
    }
    for name, form in formen.items():
        draw.polygon(form, fill=farbe if name in an else aus)


def _doppelpunkte(draw, punkte, zh, farbe) -> None:
    d = zh * 0.06
    for x, y in punkte:
        for dy in (-zh * 0.2, zh * 0.2):
            draw.ellipse((x - d, y + dy - d, x + d, y + dy + d), fill=farbe)


# -- Punktmatrix -----------------------------------------------------------

#: Ziffern als 5×7-Raster, Zeile für Zeile.
_MATRIX = {
    "0": ["01110", "10001", "10011", "10101", "11001", "10001", "01110"],
    "1": ["00100", "01100", "00100", "00100", "00100", "00100", "01110"],
    "2": ["01110", "10001", "00001", "00010", "00100", "01000", "11111"],
    "3": ["11110", "00001", "00001", "01110", "00001", "00001", "11110"],
    "4": ["00010", "00110", "01010", "10010", "11111", "00010", "00010"],
    "5": ["11111", "10000", "11110", "00001", "00001", "10001", "01110"],
    "6": ["00110", "01000", "10000", "11110", "10001", "10001", "01110"],
    "7": ["11111", "00001", "00010", "00100", "01000", "01000", "01000"],
    "8": ["01110", "10001", "10001", "01110", "10001", "10001", "01110"],
    "9": ["01110", "10001", "10001", "01111", "00001", "00010", "01100"],
}


def _matrix(bild, feld, zeit: datetime, uhr: Uhr) -> None:
    text = z.ziffern(zeit, format24=uhr.format24, sekunden=uhr.sekunden)
    groesse = (bild.width * FAKTOR, bild.height * FAKTOR)
    ebene = Image.new("RGBA", groesse, (0, 0, 0, 0))
    draw = ImageDraw.Draw(ebene)
    f = [v * FAKTOR for v in feld]
    kaesten, punkte, zh = _ziffernreihe(f, len(text), 5 / 7, 0.2)
    aus = (*uhr.schema.gedimmt[:3], 60)
    for ziffer, (x0, y0, x1, y1) in zip(text, kaesten):
        raster = (y1 - y0) / 7
        d = raster * 0.4
        for zeile, bits in enumerate(_MATRIX[ziffer]):
            for spalte, bit in enumerate(bits):
                mx = x0 + (spalte + 0.5) * raster
                my = y0 + (zeile + 0.5) * raster
                draw.ellipse((mx - d, my - d, mx + d, my + d),
                             fill=uhr.schema.schrift if bit == "1" else aus)
    _doppelpunkte(draw, punkte, zh, uhr.schema.schrift)
    bild.alpha_composite(ebene.resize(bild.size, Image.Resampling.LANCZOS))
    if not uhr.format24:
        _ampm(bild, feld, zeit, uhr)


# -- Klappzahlen -----------------------------------------------------------


def _klappen(bild, feld, zeit: datetime, uhr: Uhr) -> None:
    text = z.ziffern(zeit, format24=uhr.format24, sekunden=uhr.sekunden)
    links, oben, rechts, unten = feld
    paare = [text[i:i + 2] for i in range(0, len(text), 2)]
    luecke = (rechts - links) * 0.05
    karte_b = ((rechts - links) - luecke * (len(paare) - 1)) / len(paare)
    karte_h = min(unten - oben, karte_b * 1.15)
    y0 = oben + ((unten - oben) - karte_h) / 2
    hell = uhr.schema.blatt is not None and sum(uhr.schema.blatt[:3]) > 384
    karte = (40, 40, 46, 255) if not hell else (226, 232, 240, 255)
    ebene = Image.new("RGBA", bild.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(ebene)
    for i, paar in enumerate(paare):
        x0 = links + i * (karte_b + luecke)
        draw.rounded_rectangle((x0, y0, x0 + karte_b, y0 + karte_h),
                               radius=max(2, karte_b * 0.12), fill=karte)
    bild.alpha_composite(ebene)
    for i, paar in enumerate(paare):
        x0 = links + i * (karte_b + luecke)
        groesse = _passend(paar, karte_b * 0.9, karte_h * 0.78, True, "")
        _text_mittig(bild, paar, (x0 + karte_b / 2, y0 + karte_h / 2), groesse, karte_b,
                     uhr.schema.schrift, bold=True)
    # Der Spalt quer durch die Karten — erst nach den Zahlen, er liegt darüber.
    draw = ImageDraw.Draw(bild)
    for i in range(len(paare)):
        x0 = links + i * (karte_b + luecke)
        mitte = y0 + karte_h / 2
        draw.line([(x0, mitte), (x0 + karte_b, mitte)], fill=(0, 0, 0, 200),
                  width=max(1, round(karte_h * 0.025)))
    if not uhr.format24:
        _ampm(bild, feld, zeit, uhr)


# -- Binär -----------------------------------------------------------------


def _binaer(bild, feld, zeit: datetime, uhr: Uhr) -> None:
    """Jede Ziffer eine Spalte, von unten 1, 2, 4, 8 — wie die BCD-Uhren."""
    text = z.ziffern(zeit, format24=uhr.format24, sekunden=uhr.sekunden)
    links, oben, rechts, unten = [v * FAKTOR for v in feld]
    ebene = Image.new("RGBA", (bild.width * FAKTOR, bild.height * FAKTOR), (0, 0, 0, 0))
    draw = ImageDraw.Draw(ebene)
    spalten = len(text)
    paar_luecke = 0.6
    einheiten = spalten + paar_luecke * (spalten // 2 - 1)
    raster = min((rechts - links) / einheiten, (unten - oben) / 4)
    gesamt_b = raster * einheiten
    x = links + ((rechts - links) - gesamt_b) / 2
    y0 = oben + ((unten - oben) - raster * 4) / 2
    aus = (*uhr.schema.gedimmt[:3], 110)
    for i, ziffer in enumerate(text):
        wert = int(ziffer)
        for bit in range(4):
            mx = x + raster / 2
            my = y0 + (3 - bit + 0.5) * raster
            d = raster * 0.36
            an = bool(wert & (1 << bit))
            farbe = (uhr.schema.akzent if i % 2 else uhr.schema.schrift) if an else aus
            draw.ellipse((mx - d, my - d, mx + d, my + d), fill=farbe)
        x += raster
        if i % 2 == 1:
            x += raster * paar_luecke
    bild.alpha_composite(ebene.resize(bild.size, Image.Resampling.LANCZOS))


# -- Tagesbogen ------------------------------------------------------------


def _tagesbogen(bild, feld, zeit: datetime, uhr: Uhr) -> None:
    """Die Uhrzeit in einem Bogen, der zeigt, wie viel vom Tag vorbei ist."""
    links, oben, rechts, unten = feld
    seite = min(rechts - links, unten - oben)
    cx, cy = (links + rechts) / 2, (oben + unten) / 2
    ebene = Image.new("RGBA", (bild.width * FAKTOR, bild.height * FAKTOR), (0, 0, 0, 0))
    draw = ImageDraw.Draw(ebene)
    r = seite / 2 * FAKTOR
    dicke = r * 0.12
    kasten = (cx * FAKTOR - r + dicke / 2, cy * FAKTOR - r + dicke / 2,
              cx * FAKTOR + r - dicke / 2, cy * FAKTOR + r - dicke / 2)
    draw.arc(kasten, 0, 360, fill=uhr.schema.gedimmt, width=round(dicke))
    anteil = (zeit.hour * 3600 + zeit.minute * 60 + zeit.second) / 86400
    if anteil > 0:
        draw.arc(kasten, -90, -90 + 360 * anteil, fill=uhr.schema.akzent, width=round(dicke))
    bild.alpha_composite(ebene.resize(bild.size, Image.Resampling.LANCZOS))

    text, tageszeit = z.uhrzeit(zeit, format24=uhr.format24, sekunden=False)
    innen = seite * 0.68
    groesse = _passend(text, innen, seite * 0.3, True, "")
    _text_mittig(bild, text, (cx, cy - (seite * 0.06 if uhr.sekunden or tageszeit else 0)),
                 groesse, innen, uhr.schema.schrift, bold=True)
    zusatz = " ".join(t for t in (f"{zeit.second:02d}" if uhr.sekunden else "", tageszeit) if t)
    if zusatz:
        _text_mittig(bild, zusatz, (cx, cy + seite * 0.2), seite * 0.13, innen,
                     uhr.schema.gedimmt, bold=True)


# -- In Worten -------------------------------------------------------------


def _worte(bild, feld, zeit: datetime, uhr: Uhr) -> None:
    links, oben, rechts, unten = feld
    worte = z.in_worten(zeit).split()
    breite, hoehe = rechts - links, unten - oben
    # So viele Zeilen wie nötig, höchstens vier, und die Schrift so groß,
    # wie es der Platz erlaubt.
    beste = None
    for zeilen in range(1, min(4, len(worte)) + 1):
        aufgeteilt = _umbrechen(worte, zeilen)
        groesse = min(_passend(zeile, breite, hoehe / zeilen * 0.78, True, "")
                      for zeile in aufgeteilt)
        if beste is None or groesse > beste[0]:
            beste = (groesse, aufgeteilt)
    groesse, aufgeteilt = beste
    zeilenhoehe = hoehe / len(aufgeteilt)
    for i, zeile in enumerate(aufgeteilt):
        farbe = uhr.schema.akzent if i == len(aufgeteilt) - 1 else uhr.schema.schrift
        _text_mittig(bild, zeile, ((links + rechts) / 2, oben + zeilenhoehe * (i + 0.5)),
                     groesse, breite, farbe, bold=True)


def _umbrechen(worte: list[str], zeilen: int) -> list[str]:
    """Wörter auf ``zeilen`` Zeilen verteilen, möglichst gleich lang."""
    if zeilen <= 1:
        return [" ".join(worte)]
    gesamt = sum(len(w) for w in worte) + len(worte) - 1
    ziel = gesamt / zeilen
    ergebnis, aktuell = [], []
    for wort in worte:
        probe = " ".join([*aktuell, wort])
        if aktuell and len(probe) > ziel and len(ergebnis) < zeilen - 1:
            ergebnis.append(" ".join(aktuell))
            aktuell = [wort]
        else:
            aktuell.append(wort)
    ergebnis.append(" ".join(aktuell))
    return ergebnis


# ==========================================================================
# Schrift
# ==========================================================================


def _ampm(bild, feld, zeit: datetime, uhr: Uhr) -> None:
    links, oben, rechts, unten = feld
    _text_mittig(bild, "AM" if zeit.hour < 12 else "PM",
                 (rechts, oben + (unten - oben) * 0.08), (unten - oben) * 0.16,
                 (rechts - links) * 0.3, uhr.schema.akzent, bold=True, anker="rm")


def _passend(text: str, breite: float, hoehe: float, fett: bool, familie: str) -> float:
    """Die größte Schriftgröße bis ``hoehe``, bei der ``text`` in ``breite`` passt."""
    groesse = max(6, round(hoehe))
    while groesse > 6:
        font = load_font(groesse, bold=fett, family=familie)
        l, o, r, u = font.getbbox(text)
        if r - l <= breite:
            break
        groesse -= 1
    return groesse


def _text_mittig(bild, text, mitte, groesse, max_breite, farbe, *, bold=False, family="",
                 anker="mm") -> None:
    """Text mittig auf einen Punkt; schrumpft, bis er in ``max_breite`` passt."""
    if not text:
        return
    groesse = _passend(text, max_breite, groesse, bold, family)
    font = load_font(max(6, round(groesse)), bold=bold, family=family)
    ImageDraw.Draw(bild).text(mitte, text, font=font, fill=farbe, anchor=anker)
