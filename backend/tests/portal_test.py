"""Prüft den Portal-Weg für Kurzbefehle und Bildschirmfotos.

Das Portal ist der Weg für alle Desktops, die Plasmas Schnittstellen nicht
haben. Geprüft wird hier ohne laufendes Portal — also die Teile, die man
ohne Desktop prüfen kann: die Umrechnung der Kurzbefehle, der vorhergesagte
Antwortpfad und vor allem die *Weichen*: wann das Portal genommen wird und
wann nicht.

Die eigentliche Portal-Antwort ist am 2026-08-21 auf Heikos Plasma zu Fuß
geprüft worden — ein Bildschirmfoto über das Portal kam als 4178×1800-PNG
zurück, und ``BindShortcuts`` nahm die Struktur an (der Dialog wartete).
Was hier steht, hält das Verhalten fest, damit es so bleibt.

Aufruf (mit eigener Config, damit die echte unangetastet bleibt):

    cd backend
    env XDG_CONFIG_HOME=/tmp/sd-test XDG_DATA_HOME=/tmp/sd-test \\
        ../.venv/bin/python tests/portal_test.py
"""
import _wache  # bricht ab, statt in die echte Config zu schreiben
_wache.sichere_umgebung()

import asyncio
import json
import os
import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from deckswitch.services import portal as P  # noqa: E402
from deckswitch.services import session as sess  # noqa: E402

FAILS = []


def check(name, condition, detail=""):
    mark = "✔" if condition else "✘"
    print(f"  {mark} {name}" + (f"  ({detail})" if detail else ""))
    if not condition:
        FAILS.append(name)


def sitzung_mit(provider: str, cap_id: str):
    """Eine Sitzung, in der genau diese Fähigkeit von ``provider`` kommt."""
    caps = sess.SessionCapabilities()
    caps._set(cap_id, True, provider)
    return caps


def main():
    print("Kurzbefehle in die Schreibweise der Shortcuts-Spec")
    check("ctrl+alt+d", P.trigger_aus_combo("ctrl+alt+d") == "CTRL+ALT+d")
    # Die Meta-Taste heißt beim Portal LOGO, nicht SUPER oder META.
    check("super wird zu LOGO", P.trigger_aus_combo("super+d") == "LOGO+d")
    check("meta wird zu LOGO", P.trigger_aus_combo("meta+d") == "LOGO+d")
    check("Funktionstasten bleiben", P.trigger_aus_combo("ctrl+f9") == "CTRL+f9")

    fehler = None
    try:
        P.trigger_aus_combo("ctrl")
    except P.PortalError as exc:
        fehler = str(exc)
    check("Kombination ohne Taste wird abgelehnt", fehler is not None, fehler or "keine Ablehnung")

    fehler = None
    try:
        P.trigger_aus_combo("altgr+d")
    except P.PortalError as exc:
        fehler = str(exc)
    check("AltGr wird abgelehnt", fehler is not None, fehler or "keine Ablehnung")

    print("\nDer Antwortpfad wird vorhergesagt, nicht abgewartet")
    # Ohne das ginge die Antwort verloren, wenn sie schneller ist als die
    # Signalregel. Der Pfad ergibt sich aus Busname und Token.
    conn = P.PortalConnection()
    conn._bus = mock.Mock(unique_name=":1.460")
    pfad = conn._antwortpfad("deckswitch_probe_1")
    check("Pfad enthält den Sender mit Unterstrich", pfad.endswith("/request/1_460/deckswitch_probe_1"), pfad)

    print("\nDie Weiche für Kurzbefehle")
    # Der wichtigste Test der Datei: Auf Plasma darf NICHT das Portal
    # genommen werden. Es kann die Kombination nicht setzen, die der
    # Benutzer eingetippt hat — es fragt selbst nach. Diese Priorität war
    # zuerst falsch herum gebaut.
    from deckswitch.services.shortcuts import ShortcutService

    class FakeRuntime:
        def __init__(self, caps):
            self.session = caps
            self.decks = {}

    plasma = sitzung_mit("kglobalaccel", sess.GLOBAL_SHORTCUTS)
    dienst = ShortcutService(FakeRuntime(plasma))
    check("Plasma bleibt bei kglobalaccel", not dienst._ueber_portal())

    fremd = sitzung_mit("portal", sess.GLOBAL_SHORTCUTS)
    dienst = ShortcutService(FakeRuntime(fremd))
    check("ohne kglobalaccel geht es übers Portal", dienst._ueber_portal())

    ohne = sess.SessionCapabilities()  # nichts verfügbar
    dienst = ShortcutService(FakeRuntime(ohne))
    check("ohne beides gar kein Portal", not dienst._ueber_portal())

    print("\nDie Weiche fürs Bildschirmfoto")
    from deckswitch.services.desktop import DesktopService, DesktopError

    dienst = DesktopService()
    check("ohne gebundene Sitzung kein Portal", not dienst._nutzt_portal())

    dienst = DesktopService()
    dienst.bind_session(sitzung_mit("spectacle", sess.SCREENSHOT), asyncio.new_event_loop())
    check("mit Spectacle kein Portal", not dienst._nutzt_portal())

    dienst = DesktopService()
    dienst.bind_session(sitzung_mit("portal", sess.SCREENSHOT), asyncio.new_event_loop())
    check("ohne Spectacle das Portal", dienst._nutzt_portal())

    print("\nWas das Portal nicht kann, wird gesagt statt verschwiegen")
    # Die Zwischenablage kennt das Portal nicht. Stillschweigend eine Datei
    # anzulegen wäre die schlechtere Antwort: Der Benutzer drückte Einfügen
    # und bekäme, was vorher in der Ablage lag.
    with mock.patch("deckswitch.services.desktop.shutil.which", lambda p: None):
        fehler = None
        try:
            dienst.screenshot("fullscreen", to_clipboard=True)
        except DesktopError as exc:
            fehler = str(exc)
    check("Zwischenablage wird abgelehnt", fehler is not None and "Zwischenablage" in fehler,
          fehler or "keine Ablehnung")

    with mock.patch("deckswitch.services.desktop.shutil.which", lambda p: None):
        fehler = None
        try:
            dienst.screenshot("gibtsnicht")
        except DesktopError as exc:
            fehler = str(exc)
    check("unbekannte Aufnahmeart wird abgelehnt", fehler is not None, fehler or "keine Ablehnung")

    print("\nFensterbefehle an Hyprland und Sway")
    # Die Befehlslisten selbst sind am 2026-08-22 gegen echte, verschachtelt
    # gestartete Compositoren geprüft worden (Sway 1.12, Hyprland 0.56.2) —
    # 30 von 30 bzw. 29 von 31 wurden angenommen, die beiden übrigen
    # brauchen ein schwebendes Fenster und sagen das jetzt im Namen.
    #
    # Hier geht es um das, was ein solcher Lauf *nicht* absichert: dass der
    # Code die Befehle richtig zerlegt und eine Ablehnung auch als solche
    # erkennt. Letzteres ist der heikle Teil — hyprctl und swaymsg melden
    # Fehler nicht über den Rückgabewert, sondern im Text.
    from deckswitch.services import desktop as dt

    gerufen = []

    def falscher_lauf(argv, timeout=15):
        gerufen.append(argv)
        return antwort_fuer(argv)

    class Ergebnis:
        def __init__(self, code=0, out="", err=""):
            self.returncode, self.stdout, self.stderr = code, out, err

    antwort = {"wert": Ergebnis(0, "ok")}
    def antwort_fuer(argv):
        return antwort["wert"]

    async def ruf(weg, befehl, umgebung):
        dienst = dt.DesktopService()
        dienst.bind_session(sitzung_mit(weg, sess.WINDOW_CONTROL), asyncio.get_event_loop())
        with (mock.patch.object(dt, "_run", falscher_lauf),
              mock.patch.object(dt.shutil, "which", lambda p: f"/usr/bin/{p}")):
            await dienst.invoke_shortcut(weg, befehl)

    asyncio.run(ruf("hyprland", "movetoworkspace, 3", {}))
    check("Hyprland bekommt hyprctl dispatch",
          gerufen[-1] == ["hyprctl", "dispatch", "movetoworkspace", "3"],
          " ".join(gerufen[-1]))

    gerufen.clear()
    asyncio.run(ruf("hyprland", "killactive", {}))
    check("Befehl ohne Argument bleibt einteilig",
          gerufen[-1] == ["hyprctl", "dispatch", "killactive"], " ".join(gerufen[-1]))

    gerufen.clear()
    antwort["wert"] = Ergebnis(0, '[{"success": true}]')
    asyncio.run(ruf("sway", "workspace number 2", {}))
    check("Sway bekommt den Befehl am Stück",
          gerufen[-1] == ["swaymsg", "workspace number 2"], " ".join(gerufen[-1]))

    # Der wichtigste Teil: Eine Ablehnung darf nicht als Erfolg durchgehen.
    # Wortlaut wie von hyprctl 0.56.2 beobachtet.
    antwort["wert"] = Ergebnis(0, "Window does not qualify to be pinned")
    fehler = None
    try:
        asyncio.run(ruf("hyprland", "quatsch", {}))
    except dt.DesktopError as exc:
        fehler = str(exc)
    check("hyprctl-Ablehnung wird erkannt (Rückgabewert bleibt 0!)",
          fehler is not None, fehler or "durchgelassen")

    # Wortlaut wie von swaymsg 1.12 beobachtet.
    antwort["wert"] = Ergebnis(
        0, json.dumps([{"success": False, "error": "Can't move an empty workspace"}])
    )
    fehler = None
    try:
        asyncio.run(ruf("sway", "quatsch", {}))
    except dt.DesktopError as exc:
        fehler = str(exc)
    check("swaymsg-Ablehnung wird aus dem JSON gelesen",
          fehler is not None and "empty workspace" in fehler, fehler or "durchgelassen")

    antwort["wert"] = Ergebnis(0, '[{"success": true}]')
    fehler = None
    try:
        asyncio.run(ruf("sway", "fullscreen toggle", {}))
    except dt.DesktopError as exc:
        fehler = str(exc)
    check("Erfolg wird nicht als Fehler gemeldet", fehler is None, fehler or "")

    # Und wo gar nichts geht, muss es das auch sagen.
    async def ohne():
        dienst = dt.DesktopService()
        dienst.bind_session(sess.SessionCapabilities(), asyncio.get_event_loop())
        await dienst.invoke_shortcut("kwin", "irgendwas")
    fehler = None
    try:
        asyncio.run(ohne())
    except dt.DesktopError as exc:
        fehler = str(exc)
    check("ohne Fensterweg kommt eine klare Absage", fehler is not None, fehler or "")

    print("\nDas Portal kennt nur ganz oder interaktiv")
    check("Bereich braucht die Auswahl des Desktops",
          "region" in P.ScreenshotPortal.INTERAKTIV)
    check("Fenster braucht die Auswahl des Desktops",
          "window" in P.ScreenshotPortal.INTERAKTIV)
    check("ganzer Bildschirm nicht",
          "fullscreen" not in P.ScreenshotPortal.INTERAKTIV)

    print()
    if FAILS:
        print(f"FEHLGESCHLAGEN ({len(FAILS)}): " + ", ".join(FAILS))
        sys.exit(1)
    print("Alle Prüfungen bestanden.")


main()
