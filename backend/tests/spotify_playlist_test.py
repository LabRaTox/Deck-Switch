"""Prüft die Playlist-Aktion des Spotify-Plugins.

Zwei Teile: Die Erkennung der Adresse läuft immer — daran scheitert es im
Alltag, weil aus Spotify heraus ein Web-Link im Umlauf ist und keine URI.
Der zweite Teil spricht den echten Client an und wird übersprungen, wenn
Spotify nicht läuft.

Aufruf:

    cd backend
    ../.venv/bin/python tests/spotify_playlist_test.py          # nur Erkennung
    ../.venv/bin/python tests/spotify_playlist_test.py --live   # auch OpenUri
"""
import _wache  # bricht ab, statt in die echte Config zu schreiben
_wache.sichere_umgebung()
import asyncio, importlib.util, pathlib, sys, types

SPOTIFY = pathlib.Path(__file__).resolve().parent.parent.parent / "plugin-sources" / "spotify"
sys.path.insert(0, str(SPOTIFY))

FAILS = []


def check(name, condition, detail=""):
    print(("  ✔ " if condition else "  ✘ ") + name + (f"  ({detail})" if detail else ""))
    if not condition:
        FAILS.append(name)


def load_plugin_module():
    """Lädt plugin.py ohne die Runtime — nur für die reinen Funktionen.

    ``ActionPlugin`` und ``MprisPlayer`` werden dabei durch Platzhalter
    ersetzt: Der Test braucht kein Deck und keinen D-Bus, nur das Modul.
    """
    base = types.ModuleType("deckswitch.plugins.base")
    base.ActionPlugin = object
    sys.modules.setdefault("deckswitch", types.ModuleType("deckswitch"))
    sys.modules.setdefault("deckswitch.plugins", types.ModuleType("deckswitch.plugins"))
    sys.modules["deckswitch.plugins.base"] = base

    # Das Plugin ist ein Paket und importiert ``from .mpris import …`` — die
    # Attrappe muss deshalb unter dem Paketnamen stehen, nicht unter dem
    # nackten Modulnamen. Ohne D-Bus soll hier nichts nach draußen greifen.
    paket = "spotify_plugin"
    spec = importlib.util.spec_from_file_location(
        paket, SPOTIFY / "plugin.py", submodule_search_locations=[str(SPOTIFY)]
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[paket] = module

    stub = types.ModuleType(f"{paket}.mpris")
    stub.LOOP_CYCLE = []
    stub.MprisPlayer = object
    sys.modules[f"{paket}.mpris"] = stub

    spec.loader.exec_module(module)
    return module


def test_uri(module):
    print("== Adresse erkennen ==")
    cases = [
        # Was beim Teilen aus Spotify herauskommt — mit ?si=-Anhang.
        ("https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M?si=abc123",
         "spotify:playlist:37i9dQZF1DXcBWIGoYBM5M"),
        # Sprach-Segment, das Spotify je nach Oberfläche einschiebt.
        ("https://open.spotify.com/intl-de/track/70pVCVMGjmIWPbWXDwf11e",
         "spotify:track:70pVCVMGjmIWPbWXDwf11e"),
        ("spotify:playlist:37i9dQZF1DXcBWIGoYBM5M",
         "spotify:playlist:37i9dQZF1DXcBWIGoYBM5M"),
        ("  https://open.spotify.com/album/1A2GTWGtFfWp7KSQTwWOyo  ",
         "spotify:album:1A2GTWGtFfWp7KSQTwWOyo"),
        ("open.spotify.com/artist/0OdUWJ0sBjDrqHygGUXeCF",
         "spotify:artist:0OdUWJ0sBjDrqHygGUXeCF"),
        ("", None),
        ("Hallo Welt", None),
        ("https://example.com/playlist/123", None),
        ("spotify:kaputt:123", None),
        ("spotify:playlist:", None),
    ]
    for raw, expected in cases:
        got = module.spotify_uri(raw)
        check(f"{raw[:46] or '(leer)'} → {expected}", got == expected, repr(got))


#: Zwei Titel, gegen die geprüft wird. Zwei, weil einer nicht reicht: Läuft
#: er beim Start zufällig schon, wäre nicht zu unterscheiden, ob ``OpenUri``
#: gewirkt hat oder ohnehin nichts passiert wäre.
LIVE_TRACKS = [
    ("70pVCVMGjmIWPbWXDwf11e", "petal"),
    ("2Rf1VKlFjf0oXgVkoeC2hZ", "Ignore The Static"),
]


async def test_live():
    print("\n== Gegen den laufenden Client ==")
    from mpris import MprisPlayer  # echtes Modul, nicht der Platzhalter

    player = MprisPlayer("spotify")
    if not await player.connect():
        print("  … übersprungen: Spotify läuft nicht")
        return

    was_playing = (await player.refresh()).playing
    for track_id, title in LIVE_TRACKS:
        check(
            f"OpenUri nimmt {title!r} an",
            await player.open_uri(f"spotify:track:{track_id}"),
        )
        # Der Client braucht einen Moment, bis die neuen Daten am Bus stehen.
        for _ in range(10):
            await asyncio.sleep(0.5)
            state = await player.refresh()
            if state.title == title:
                break
        check(f"… und spielt {title!r}", state.title == title, f"läuft: {state.title!r}")

    if not was_playing:
        # So verlassen, wie es angetroffen wurde — der Test soll niemandem
        # ungefragt Musik anlassen.
        await player.pause()
    await player.close()


def main(argv):
    module = load_plugin_module()
    test_uri(module)

    if "--live" in argv:
        # Der Platzhalter darf den echten Import nicht blockieren.
        del sys.modules["mpris"]
        asyncio.run(test_live())

    print()
    if FAILS:
        print(f"FEHLGESCHLAGEN ({len(FAILS)}): " + ", ".join(FAILS))
        return 1
    print("Alle Prüfungen bestanden.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
