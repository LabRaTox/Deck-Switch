"""Prüft die Fähigkeiten-Erkennung der Sitzung.

Die Erkennung entscheidet, welche Aktionen die Bibliothek überhaupt
anbietet. Ein Fehler hier ist deshalb besonders unangenehm: Er zeigt sich
nicht als Absturz, sondern als Aktion, die es plötzlich nicht mehr gibt —
oder als eine, die man ablegen kann und die dann stumm bleibt.

Geprüft wird gegen *gestellte* Umgebungen, nicht gegen die laufende
Sitzung: Auf Heikos Plasma ist alles verfügbar, und eine Prüfung, die
überall „ja" sagt, prüft nichts.

Aufruf (mit eigener Config, damit die echte unangetastet bleibt):

    cd backend
    env XDG_CONFIG_HOME=/tmp/sd-test XDG_DATA_HOME=/tmp/sd-test \\
        ../.venv/bin/python tests/session_test.py
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

from deckswitch.plugins.base import Manifest  # noqa: E402
from deckswitch.services import session as sess  # noqa: E402

FAILS = []
WURZEL = Path(__file__).resolve().parents[2]


def check(name, condition, detail=""):
    mark = "✔" if condition else "✘"
    print(f"  {mark} {name}" + (f"  ({detail})" if detail else ""))
    if not condition:
        FAILS.append(name)


def erkenne(
    umgebung: dict[str, str],
    *,
    bus: set[str] | None,
    pfad: list[str] = (),
    portal_backend: bool = True,
):
    """Erkennung unter gestellten Bedingungen.

    ``pfad`` nennt die Programme, die als installiert gelten sollen; alles
    andere gilt als fehlend. So lässt sich ein Debian-GNOME ohne
    ``kscreen-doctor`` nachstellen, ohne eines zu besitzen.

    ``portal_backend`` stellt, ob hinter dem Portal auch jemand arbeitet.
    Ohne diesen Schalter läse die Prüfung die ``*.portal``-Dateien *dieses*
    Rechners — und ein simuliertes GNOME fiele durch, weil hier kein
    ``gnome.portal`` liegt.
    """
    vorhanden = set(pfad)

    async def lauf():
        caps = sess.SessionCapabilities()
        with (
            mock.patch.dict(os.environ, umgebung, clear=False),
            mock.patch.object(
                sess.shutil, "which", lambda p: f"/usr/bin/{p}" if p in vorhanden else None
            ),
            mock.patch.object(sess, "_bus_names", mock.AsyncMock(return_value=bus)),
            mock.patch.object(sess, "_uinput_usable", lambda: (True, "")),
            mock.patch.object(sess.Path, "exists", lambda self: True),
            mock.patch.object(
                sess, "_portal_backend_fuer", lambda *_: portal_backend
            ),
        ):
            await caps.detect()
        return caps

    return asyncio.run(lauf())


# Was eine vollständige Plasma-Sitzung mitbringt.
PLASMA_UMGEBUNG = {"XDG_CURRENT_DESKTOP": "KDE", "XDG_SESSION_TYPE": "wayland"}
PLASMA_BUS = {
    "org.kde.kglobalaccel",
    "org.kde.StatusNotifierWatcher",
    "org.freedesktop.portal.Desktop",
    # Diese beiden stehen nicht dauerhaft am Bus, sind aber aktivierbar —
    # am 2026-08-21 auf Heikos Plasma nachgesehen, beide vorhanden.
    "org.kde.LogoutPrompt",
    "org.kde.Shutdown",
}
PLASMA_PFAD = [
    "kscreen-doctor", "ddcutil", "wpctl", "pactl", "pw-play",
    "xdg-open", "pgrep", "systemctl", "spectacle", "qml6",
]


def main():
    print("Desktop und Anzeigeserver aus der Umgebung")
    # Ubuntu hängt seinen Namen vorn an; maßgeblich ist der letzte Eintrag.
    with mock.patch.dict(os.environ, {"XDG_CURRENT_DESKTOP": "ubuntu:GNOME"}, clear=False):
        check("'ubuntu:GNOME' wird als gnome erkannt", sess._detect_session().desktop == "gnome")
    with mock.patch.dict(os.environ, {"XDG_CURRENT_DESKTOP": "KDE"}, clear=False):
        check("'KDE' wird als kde erkannt", sess._detect_session().desktop == "kde")
    # Ohne XDG_CURRENT_DESKTOP bleibt der Pfad der Sitzungsdatei.
    umgebung = {k: v for k, v in os.environ.items() if k != "XDG_CURRENT_DESKTOP"}
    umgebung["DESKTOP_SESSION"] = "/usr/share/wayland-sessions/plasma.desktop"
    with mock.patch.dict(os.environ, umgebung, clear=True):
        check("DESKTOP_SESSION dient als Rückfallweg",
              sess._detect_session().desktop == "plasma")

    print("\nVollständige Plasma-Sitzung")
    plasma = erkenne(PLASMA_UMGEBUNG, bus=PLASMA_BUS, pfad=PLASMA_PFAD)
    fehlend = [c for c in sess.ALL_CAPABILITIES if not plasma.has(c)]
    check("alle Fähigkeiten verfügbar", not fehlend, ", ".join(fehlend) or "keine")
    check("Fenstersteuerung über kglobalaccel",
          plasma.caps[sess.WINDOW_CONTROL].provider == "kglobalaccel")
    check("Bildschirmfoto bevorzugt Spectacle",
          plasma.caps[sess.SCREENSHOT].provider == "spectacle")
    check("Kurzbefehle bevorzugen kglobalaccel (setzt die Kombination direkt)",
          plasma.caps[sess.GLOBAL_SHORTCUTS].provider == "kglobalaccel")

    print("\nGNOME unter Wayland, ohne KDE-Werkzeuge")
    # ``qml6`` steht bewusst mit im Pfad, obwohl es auf einem GNOME-System
    # selten ist: Sonst scheiterte das Overlay schon am fehlenden Programm,
    # und die eigentliche Regel — Mutter spricht kein zwlr_layer_shell_v1 —
    # bliebe ungeprüft. Genau so war es hier zuerst: Der Test war grün, und
    # ein absichtlich eingebauter Fehler in der Compositor-Liste fiel nicht
    # auf (Mutationsprobe am 2026-08-21).
    gnome = erkenne(
        {"XDG_CURRENT_DESKTOP": "GNOME", "XDG_SESSION_TYPE": "wayland"},
        bus={"org.freedesktop.portal.Desktop"},
        pfad=["pactl", "pw-play", "xdg-open", "pgrep", "systemctl", "qml6"],
    )
    check("kein Overlay (Mutter kann kein layer-shell)", not gnome.has(sess.OVERLAY))
    check("und zwar wegen des Compositors, nicht wegen fehlender Programme",
          "zwlr_layer_shell" in gnome.reason_for(sess.OVERLAY),
          gnome.reason_for(sess.OVERLAY))
    check("keine Fenstersteuerung", not gnome.has(sess.WINDOW_CONTROL))
    check("kein Bildschirm an/aus", not gnome.has(sess.SCREEN_POWER))
    check("Bildschirmfoto fällt aufs Portal zurück",
          gnome.caps[sess.SCREENSHOT].provider == "portal")
    check("Kurzbefehle gehen übers Portal",
          gnome.caps[sess.GLOBAL_SHORTCUTS].provider == "portal")
    check("Ton bleibt verfügbar", gnome.has(sess.AUDIO) and gnome.has(sess.SOUND_PLAYBACK))
    check("Tastendrücke bleiben verfügbar", gnome.has(sess.KEYBOARD_INPUT))
    check("kein Tray ohne Watcher", not gnome.has(sess.TRAY))
    check("jedes Nein hat eine Begründung",
          all(c.reason for c in gnome.caps.values() if not c.available))

    print("\nPlasma unter X11")
    x11 = erkenne(
        {"XDG_CURRENT_DESKTOP": "KDE", "XDG_SESSION_TYPE": "x11"},
        bus=PLASMA_BUS, pfad=PLASMA_PFAD,
    )
    # Früher galt X11 pauschal als „kein Overlay". Das war zu streng: Die
    # alten Fenster-Hinweise leisten dasselbe, und ein Klick lässt den
    # Tastaturfokus stehen (am 2026-08-21 mit xprop und XGetInputFocus
    # nachgemessen). Damit bekommen XFCE, Cinnamon, MATE, i3 und Plasma
    # unter X11 ihr virtuelles Deck.
    check("Overlay läuft auch unter X11", x11.has(sess.OVERLAY))
    check("und zwar über die Fenster-Hinweise",
          x11.caps[sess.OVERLAY].provider == "x11")
    check("Fenstersteuerung bleibt", x11.has(sess.WINDOW_CONTROL))

    print("\nInstalliert heißt nicht wirksam")
    # Auf einem Arch-Rechner mit KDE *und* Sway sind kscreen-doctor und
    # spectacle vorhanden, wirken unter Sway aber nicht. Am 2026-08-22
    # gemessen: kscreen-doctor endet mit Rückgabewert 1, und spectacle —
    # der gefährlichere Fall — meldet Erfolg und legt keine Datei an.
    mit_kde_werkzeugen = erkenne(
        {"XDG_CURRENT_DESKTOP": "sway", "XDG_SESSION_TYPE": "wayland",
         "SWAYSOCK": "/run/user/1000/sway.sock"},
        bus={"org.freedesktop.portal.Desktop"},
        pfad=["swaymsg", "kscreen-doctor", "spectacle", "pactl", "pw-play",
              "xdg-open", "pgrep", "systemctl", "qml6"],
    )
    check("Bildschirme laufen über Sway, nicht über kscreen-doctor",
          mit_kde_werkzeugen.caps[sess.SCREEN_POWER].provider == "sway")
    check("Bildschirmfoto nimmt das Portal, nicht Spectacle",
          mit_kde_werkzeugen.caps[sess.SCREENSHOT].provider == "portal")

    # Und ohne Compositor-IPC: kscheen-doctor allein reicht nicht.
    nur_kde_werkzeug = erkenne(
        {"XDG_CURRENT_DESKTOP": "XFCE", "XDG_SESSION_TYPE": "x11"},
        bus={"org.freedesktop.portal.Desktop"},
        pfad=["kscreen-doctor", "pactl", "systemctl", "qml6"],
    )
    check("kscreen-doctor ohne Plasma zählt nicht",
          not nur_kde_werkzeug.has(sess.SCREEN_POWER))
    check("und sagt auch, warum",
          "nur unter KDE Plasma" in nur_kde_werkzeug.reason_for(sess.SCREEN_POWER),
          nur_kde_werkzeug.reason_for(sess.SCREEN_POWER))

    print("\nWlroots-Desktop ohne Portal-Backend")
    # Der schlanke Fall: Sway ohne xdg-desktop-portal-wlr. Der Vermittler
    # steht am Bus, aber niemand arbeitet dahinter — genau das ist am
    # 2026-08-22 passiert, als der Portal-Screenshot mit „abgebrochen"
    # zurückkam.
    ohne_backend = erkenne(
        {"XDG_CURRENT_DESKTOP": "sway", "XDG_SESSION_TYPE": "wayland",
         "SWAYSOCK": "/run/user/1000/sway.sock"},
        bus={"org.freedesktop.portal.Desktop"},
        pfad=["swaymsg", "pactl", "systemctl", "qml6"],
        portal_backend=False,
    )
    check("keine Kurzbefehle ohne Backend", not ohne_backend.has(sess.GLOBAL_SHORTCUTS))
    check("kein Bildschirmfoto ohne Backend", not ohne_backend.has(sess.SCREENSHOT))
    check("Fenster und Bildschirme bleiben trotzdem",
          ohne_backend.has(sess.WINDOW_CONTROL) and ohne_backend.has(sess.SCREEN_POWER))

    print("\nPortal: läuft der Vermittler oder arbeitet auch jemand?")
    # Dass ``org.freedesktop.portal.Desktop`` am Bus steht, heißt nur, dass
    # der Vermittler da ist. Ohne Backend nimmt er die Anfrage an und
    # bricht sie ab — am 2026-08-22 unter Sway genau so erlebt.
    GS = "org.freedesktop.impl.portal.GlobalShortcuts"
    with mock.patch.object(sess, "PORTAL_BACKENDS", Path("/gibt/es/nicht")):
        check("ohne lesbares Verzeichnis im Zweifel ja", sess._portal_backend_fuer(GS, "sway"))

    import tempfile
    with tempfile.TemporaryDirectory() as ordner:
        verzeichnis = Path(ordner)
        (verzeichnis / "hyprland.portal").write_text(
            "[portal]\nInterfaces=org.freedesktop.impl.portal.Screenshot;"
            "org.freedesktop.impl.portal.GlobalShortcuts;\n"
            "UseIn=wlroots;Hyprland;sway;Wayfire;river;\n"
        )
        with mock.patch.object(sess, "PORTAL_BACKENDS", verzeichnis):
            check("Hyprland wird bedient", sess._portal_backend_fuer(GS, "hyprland"))
            check("Sway steht ausdrücklich mit drin", sess._portal_backend_fuer(GS, "sway"))
            # river steht nicht namentlich da, wohl aber „wlroots".
            check("river zählt über 'wlroots'", sess._portal_backend_fuer(GS, "river"))
            check("GNOME wird davon nicht bedient",
                  not sess._portal_backend_fuer(GS, "gnome"))
            check("und KDE auch nicht", not sess._portal_backend_fuer(GS, "kde"))

    print("\nFenster steuern auf Hyprland und Sway")
    # Beide bringen eine eigene IPC mit. Erkannt wird die *laufende*
    # Sitzung an ihrer Umgebungsvariablen — ein installiertes hyprctl
    # allein sagt nichts.
    hypr = erkenne(
        {"XDG_CURRENT_DESKTOP": "Hyprland", "XDG_SESSION_TYPE": "wayland",
         "HYPRLAND_INSTANCE_SIGNATURE": "abc123"},
        bus={"org.freedesktop.portal.Desktop"},
        pfad=["hyprctl", "pactl", "pw-play", "xdg-open", "pgrep", "systemctl", "qml6"],
    )
    check("Hyprland kann Fenster steuern", hypr.has(sess.WINDOW_CONTROL))
    check("und zwar über seine eigene IPC",
          hypr.caps[sess.WINDOW_CONTROL].provider == "hyprland")
    check("und zeigt das Overlay", hypr.has(sess.OVERLAY))

    sway = erkenne(
        {"XDG_CURRENT_DESKTOP": "sway", "XDG_SESSION_TYPE": "wayland",
         "SWAYSOCK": "/run/user/1000/sway-ipc.sock"},
        bus={"org.freedesktop.portal.Desktop"},
        pfad=["swaymsg", "pactl", "pw-play", "xdg-open", "pgrep", "systemctl", "qml6"],
    )
    check("Sway kann Fenster steuern", sway.caps[sess.WINDOW_CONTROL].provider == "sway")

    # Ohne laufende Sitzung zählt das installierte Programm nicht — sonst
    # böte ein Arch-Rechner mit installiertem Hyprland die Aktion auch
    # unter GNOME an, wo sie nichts bewirkt.
    nur_installiert = erkenne(
        {"XDG_CURRENT_DESKTOP": "GNOME", "XDG_SESSION_TYPE": "wayland"},
        bus={"org.freedesktop.portal.Desktop"},
        pfad=["hyprctl", "swaymsg", "pactl", "systemctl"],
    )
    check("installiertes hyprctl allein genügt nicht",
          not nur_installiert.has(sess.WINDOW_CONTROL))

    print("\nOhne Sitzungsbus")
    ohne_bus = erkenne(PLASMA_UMGEBUNG, bus=None, pfad=PLASMA_PFAD)
    for cap_id in (sess.WINDOW_CONTROL, sess.GLOBAL_SHORTCUTS, sess.TRAY, sess.SCREENSHOT):
        check(f"{cap_id} gilt als nicht verfügbar", not ohne_bus.has(cap_id))
    check("Begründung nennt den Bus",
          "D-Bus" in ohne_bus.reason_for(sess.WINDOW_CONTROL))
    check("Lokales bleibt unberührt", ohne_bus.has(sess.DDC) and ohne_bus.has(sess.AUDIO))

    print("\nUnbekannte Fähigkeiten gelten als erfüllt")
    # Ein Plugin, das etwas fordert, das wir noch nicht kennen, darf daran
    # nicht scheitern — sonst wäre jede neue Fähigkeit rückwärts kaputt.
    check("has() sagt ja", plasma.has("was_wir_noch_nicht_kennen"))
    check("missing() meldet nichts", plasma.missing(["was_wir_noch_nicht_kennen"]) == [])

    print("\nAnforderungen an einzelne Auswahlwerte")
    # „Sitzung" kann überall herunterfahren, aber nicht überall abmelden.
    # Die ganze Aktion auszublenden wäre zu grob — es zählt der einzelne
    # Auswahlwert.
    from deckswitch.server import _mark_options

    class FakeRuntime:
        def __init__(self, caps):
            self.session = caps

    manifest = json.loads(
        (WURZEL / "backend" / "plugins" / "system" / "manifest.json").read_text()
    )
    power = next(a for a in manifest["actions"] if a["id"] == "power")

    _mark_options(power, FakeRuntime(gnome))
    auswahl = {
        o["value"]: o.get("unavailable")
        for f in power["settings_schema"] for o in f.get("options", [])
    }
    check("'Bildschirme ausschalten' fällt weg (kein kscreen-doctor)",
          auswahl.get("screen_off") is not None)
    check("'Abmelden' fällt weg (keine Plasma-Sitzungsverwaltung)",
          auswahl.get("logout") is not None)
    check("'Ausschalten' bleibt (systemctl kann das überall)",
          auswahl.get("poweroff") is None)
    check("'Bereitschaft' bleibt", auswahl.get("suspend") is None)
    check("jede weggefallene Auswahl nennt einen Grund",
          all(v["reason"] for v in auswahl.values() if v))

    # Auf Plasma darf nichts wegfallen.
    power2 = next(a for a in json.loads(
        (WURZEL / "backend" / "plugins" / "system" / "manifest.json").read_text()
    )["actions"] if a["id"] == "power")
    _mark_options(power2, FakeRuntime(plasma))
    weg = [
        o["value"] for f in power2["settings_schema"]
        for o in f.get("options", []) if o.get("unavailable")
    ]
    check("auf Plasma bleibt jede Auswahl", not weg, ", ".join(map(str, weg)) or "keine")

    print("\nDer Sitzungsbus wird als erreichbar vermerkt")
    # Nur wenn er *unerreichbar* war, lohnt ein zweiter Versuch. „Dieser
    # Desktop kann es nicht" ändert sich durch Warten nie.
    check("mit Bus: erreichbar", plasma.bus_reachable)
    check("ohne Bus: nicht erreichbar", not ohne_bus.bus_reachable)

    print("\nDie Manifeste fordern nur bekannte Fähigkeiten")
    # Ein Tippfehler in `requires` wäre sonst unsichtbar: Die Aktion bliebe
    # einfach immer verfügbar, und das Ausblenden griffe nie.
    bekannt = set(sess.ALL_CAPABILITIES)
    unbekannt = []
    mit_bedarf = 0
    for datei in sorted((WURZEL / "backend" / "plugins").glob("*/manifest.json")):
        manifest = Manifest.model_validate(json.loads(datei.read_text()))
        for aktion in manifest.actions:
            if aktion.requires:
                mit_bedarf += 1
            for gefordert in aktion.requires:
                if gefordert not in bekannt:
                    unbekannt.append(f"{manifest.id}/{aktion.id}: {gefordert}")
            # Die Auswahlwerte tragen eigene Anforderungen — ein Tippfehler
            # dort wäre genauso unsichtbar wie einer an der Aktion.
            for feld in aktion.settings_schema:
                for option in feld.options:
                    for gefordert in option.get("requires") or []:
                        if gefordert not in bekannt:
                            unbekannt.append(
                                f"{manifest.id}/{aktion.id}/{option.get('value')}: {gefordert}"
                            )
    check("keine unbekannten Namen in requires", not unbekannt, "; ".join(unbekannt) or "keine")
    check("die Manifeste nutzen requires überhaupt", mit_bedarf >= 15, f"{mit_bedarf} Aktionen")

    print("\nZweiter Versuch, wenn der Bus beim Start fehlte")
    # Als Dienst startet das Backend gelegentlich vor dem Sitzungsbus. Ohne
    # Nachfassen bliebe alles, was daran hängt, bis zum Neustart aus.
    from deckswitch.runtime import Runtime

    class BusKommtSpaeter:
        """Beim ersten Abtasten kein Bus, ab dem zweiten schon."""

        def __init__(self):
            self.laeufe = 0
            self.bus_reachable = False
            self.caps = {}

        async def detect(self):
            self.laeufe += 1
            self.bus_reachable = self.laeufe >= 2

    async def probe():
        rt = Runtime.__new__(Runtime)          # ohne echten Start
        rt.session = BusKommtSpaeter()
        rt.bus = mock.Mock()
        rt.shortcuts = mock.Mock(sync=mock.AsyncMock())
        # Nicht wirklich Sekunden warten — nur die Reihenfolge zählt.
        with mock.patch("asyncio.sleep", mock.AsyncMock()):
            await rt._session_retry_loop()
        return rt

    rt = asyncio.run(probe())
    check("hat erneut abgetastet", rt.session.laeufe >= 2, f"{rt.session.laeufe} Läufe")
    check("hört auf, sobald der Bus da ist", rt.session.laeufe == 2)
    check("meldet die Kurzbefehle nach", rt.shortcuts.sync.await_count == 1)
    check("sagt der Oberfläche Bescheid", rt.bus.publish.call_count == 1)

    class NieEinBus(BusKommtSpaeter):
        async def detect(self):
            self.laeufe += 1
            self.bus_reachable = False

    async def probe_ohne():
        rt = Runtime.__new__(Runtime)
        rt.session = NieEinBus()
        rt.bus = mock.Mock()
        rt.shortcuts = mock.Mock(sync=mock.AsyncMock())
        with mock.patch("asyncio.sleep", mock.AsyncMock()):
            await rt._session_retry_loop()
        return rt

    rt2 = asyncio.run(probe_ohne())
    # Sonst liefe das Nachfassen für immer und hielte das Backend beim
    # Beenden auf.
    check("gibt irgendwann auf", 3 <= rt2.session.laeufe <= 10, f"{rt2.session.laeufe} Versuche")
    check("meldet dann nichts nach", rt2.shortcuts.sync.await_count == 0)

    print("\nDie Erkennung führt nichts aus")
    # ddcutil braucht 1,8 s je Aufruf. Würde die Erkennung Programme
    # starten statt nur nachzusehen, verzögerte sie jeden Backend-Start.
    with mock.patch.object(sess, "_bus_names", mock.AsyncMock(return_value=set())):
        import subprocess
        with mock.patch.object(subprocess, "run", side_effect=AssertionError("führt aus!")):
            with mock.patch.object(subprocess, "Popen", side_effect=AssertionError("führt aus!")):
                caps = sess.SessionCapabilities()
                try:
                    asyncio.run(caps.detect())
                    ausgefuehrt = False
                except AssertionError:
                    ausgefuehrt = True
    check("kein Subprozess während der Erkennung", not ausgefuehrt)

    print()
    if FAILS:
        print(f"FEHLGESCHLAGEN ({len(FAILS)}): " + ", ".join(FAILS))
        sys.exit(1)
    print("Alle Prüfungen bestanden.")


main()
