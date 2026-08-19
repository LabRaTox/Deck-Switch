"""Globale Kurzbefehle: Anmelden, Auslösen, Abmelden.

Diese Suite redet mit dem *echten* ``kglobalaccel`` der laufenden Sitzung —
anders wäre nichts davon geprüft, sondern nur nachgespielt. Sie meldet ihre
Kurzbefehle am Ende wieder ab; in den Systemeinstellungen bleibt nichts
stehen.

Das Overlay selbst wird dabei nicht gestartet: ``overlay.toggle`` ist für
die Dauer der Prüfung durch einen Mitschreiber ersetzt. Sonst spränge
mitten im Testlauf eine Fläche über den Bildschirm.

Läuft nur unter Plasma. Ohne ``kglobalaccel`` auf dem Bus meldet sich die
Suite ab, statt Fehler zu melden, die keine sind.

Aufruf (mit eigener Config, damit die echte unangetastet bleibt):

    cd backend
    d=$(mktemp -d)
    env XDG_CONFIG_HOME=$d XDG_DATA_HOME=$d ../.venv/bin/python tests/hotkey_test.py
"""
import _wache  # bricht ab, statt in die echte Config zu schreiben

_wache.sichere_umgebung()

import asyncio
import sys

from dbus_next import BusType, Message, MessageType
from dbus_next.aio import MessageBus

from deckswitch.runtime import Runtime
from deckswitch.services import shortcuts as sc

FAILS = []

#: Absichtlich abwegig — eine Kombination, die niemand belegt hat.
COMBO = "ctrl+alt+shift+f9"
COMBO_ZWEI = "ctrl+alt+shift+f10"


def check(name, condition, detail=""):
    mark = "✔" if condition else "✘"
    print(f"  {mark} {name}" + (f"  ({detail})" if detail else ""))
    if not condition:
        FAILS.append(name)


async def kde_kennt(bus, deck_key: str) -> list[int]:
    """Was Plasma für diese Aktion gespeichert hat — leer heißt: nichts."""
    antwort = await bus.call(
        Message(
            destination=sc.KGLOBALACCEL,
            path=sc.KGLOBALACCEL_PATH,
            interface=sc.KGLOBALACCEL_IFACE,
            member="shortcut",
            signature="as",
            body=[sc.ShortcutService._aktion(deck_key, "egal")],
        )
    )
    if antwort is None or antwort.message_type == MessageType.ERROR:
        return []
    return list(antwort.body[0]) if antwort.body else []


async def _gehoert_kwin(bus) -> bool:
    """Hält KWin ``Meta+D`` noch? Sonst hätten wir es ihm weggenommen."""
    antwort = await bus.call(
        Message(
            destination=sc.KGLOBALACCEL,
            path=sc.KGLOBALACCEL_PATH,
            interface=sc.KGLOBALACCEL_IFACE,
            member="getGlobalShortcutsByKey",
            signature="i",
            body=[sc.qt_keycode("super+d")],
        )
    )
    eintraege = list(antwort.body[0]) if antwort.body else []
    return any(e[2] == "kwin" for e in eintraege)


async def main():
    print("\nUmrechnung in Qt-Tastencodes")
    check(
        "Modifier und Taste ergeben eine Zahl",
        sc.qt_keycode("ctrl+alt+d") == 0x04000000 | 0x08000000 | ord("D"),
        hex(sc.qt_keycode("ctrl+alt+d")),
    )
    check(
        "Funktionstasten zählen ab F1 durch",
        sc.qt_keycode("f9") == 0x01000038,
        hex(sc.qt_keycode("f9")),
    )
    check(
        "deutsche Tastennamen gehen auch",
        sc.qt_keycode("strg+entf") == sc.qt_keycode("ctrl+delete"),
    )
    check(
        "der Ziffernblock ist eine eigene Taste",
        sc.qt_keycode("ctrl+kp1") == 0x04000000 | ord("1") | 0x20000000,
    )
    for schlecht, was in (("altgr+x", "AltGr"), ("ctrl+", "Taste fehlt"), ("gibtsnicht", "Unsinn")):
        try:
            sc.qt_keycode(schlecht)
            check(f"'{schlecht}' wird abgelehnt", False)
        except sc.ShortcutError as exc:
            check(f"'{schlecht}' wird abgelehnt", True, f"{was}: {exc}")

    bus = await MessageBus(bus_type=BusType.SESSION).connect()
    antwort = await bus.call(
        Message(
            destination="org.freedesktop.DBus",
            path="/org/freedesktop/DBus",
            interface="org.freedesktop.DBus",
            member="NameHasOwner",
            signature="s",
            body=[sc.KGLOBALACCEL],
        )
    )
    if not (antwort.body and antwort.body[0]):
        print("\nkglobalaccel läuft hier nicht — der Rest der Suite braucht Plasma.")
        return abschluss()

    rt = Runtime()
    await rt.start()
    # Das Overlay bleibt aus: Geprüft wird der Weg bis zum Umschalten, nicht
    # das Fenster dahinter.
    gerufen = []
    rt.overlay.toggle = lambda key, **kw: gerufen.append(key) or _wahr()

    deck = rt.create_virtual_deck("Prüf-Overlay", columns=2, rows=1, dials=0)
    zweites = rt.create_virtual_deck("Zweites Overlay", columns=2, rows=1, dials=0)

    try:
        print("\nAnmelden")
        deck.binding.overlay_hotkey = COMBO
        await rt.shortcuts.sync()
        check("die Kombination ist angemeldet", rt.shortcuts.is_active(deck.key))
        check("es gibt nichts zu beanstanden", rt.shortcuts.reason(deck.key) == "",
              rt.shortcuts.reason(deck.key))
        check("Plasma hat sie gespeichert",
              await kde_kennt(bus, deck.key) == [sc.qt_keycode(COMBO)])

        print("\nAuslösen")
        await bus.call(
            Message(
                destination=sc.KGLOBALACCEL,
                path=f"/component/{sc.COMPONENT}",
                interface=sc.COMPONENT_IFACE,
                member="invokeShortcut",
                signature="s",
                body=[f"overlay:{deck.key}"],
            )
        )
        for _ in range(50):
            if gerufen:
                break
            await asyncio.sleep(0.05)
        check("der Kurzbefehl schaltet das Overlay um", gerufen == [deck.key], str(gerufen))

        # Und einmal richtig: über das virtuelle Eingabegerät, also durch
        # den Kernel und den Compositor hindurch. Erst das prüft, ob der
        # angemeldete Kurzbefehl auch wirklich greift.
        verfuegbar, grund = rt.input.available()
        if not verfuegbar:
            print(f"  – echter Tastendruck übersprungen ({grund})")
        else:
            gerufen.clear()
            await asyncio.to_thread(rt.input.send_combo, COMBO)
            for _ in range(60):
                if gerufen:
                    break
                await asyncio.sleep(0.05)
            check("ein echter Tastendruck greift genauso", gerufen == [deck.key], str(gerufen))

        print("\nWas schiefgehen kann")
        zweites.binding.overlay_hotkey = COMBO
        await rt.shortcuts.sync()
        check("eine doppelt vergebene Kombination wird gemeldet",
              "vergeben" in rt.shortcuts.reason(zweites.key),
              rt.shortcuts.reason(zweites.key))
        check("und nicht als angemeldet ausgegeben",
              not rt.shortcuts.is_active(zweites.key))
        check("das erste Deck behält sie",
              await kde_kennt(bus, deck.key) == [sc.qt_keycode(COMBO)])

        # Der Fall, der Schaden anrichten würde: Meta+D gehört KWin.
        zweites.binding.overlay_hotkey = "super+d"
        await rt.shortcuts.sync()
        check("eine fremde Kombination wird nicht weggenommen",
              "KWin" in rt.shortcuts.reason(zweites.key),
              rt.shortcuts.reason(zweites.key))
        check("und bleibt bei ihrem Besitzer",
              await _gehoert_kwin(bus))

        zweites.binding.overlay_hotkey = "altgr+ü"
        await rt.shortcuts.sync()
        check("eine unmögliche Kombination wird gemeldet",
              rt.shortcuts.reason(zweites.key) != "",
              rt.shortcuts.reason(zweites.key))

        print("\nÄndern und Wegnehmen")
        deck.binding.overlay_hotkey = COMBO_ZWEI
        await rt.shortcuts.sync()
        check("die neue Kombination steht bei Plasma",
              await kde_kennt(bus, deck.key) == [sc.qt_keycode(COMBO_ZWEI)])

        deck.binding.overlay_hotkey = ""
        await rt.shortcuts.sync()
        check("ohne Kombination ist nichts mehr angemeldet",
              not rt.shortcuts.is_active(deck.key))
        check("und Plasma hat sie auch nicht mehr", await kde_kennt(bus, deck.key) == [])

        print("\nIm Deck-Payload")
        deck.binding.overlay_hotkey = COMBO
        await rt.shortcuts.sync()
        eintrag = next(e for e in rt.decks_payload() if e["id"] == deck.key)
        check("die Oberfläche bekommt die Kombination", eintrag.get("overlay_hotkey") == COMBO)
        check("und den Grund, falls einer vorliegt", eintrag.get("hotkey_reason") == "")
    finally:
        await rt.stop()
        bus.disconnect()

    check("nach dem Beenden ist bei Plasma nichts übrig",
          await _nichts_mehr_da(deck.key))
    return abschluss()


async def _nichts_mehr_da(deck_key: str) -> bool:
    bus = await MessageBus(bus_type=BusType.SESSION).connect()
    try:
        return await kde_kennt(bus, deck_key) == []
    finally:
        bus.disconnect()


def _wahr():
    """Ein fertiges Ergebnis — ``toggle`` wird mit ``await`` gerufen."""
    async def nichts():
        return True

    return nichts()


def abschluss():
    print()
    if FAILS:
        print(f"FEHLGESCHLAGEN ({len(FAILS)}): " + ", ".join(FAILS))
        sys.exit(1)
    print("Alle Prüfungen bestanden.")


asyncio.run(main())
