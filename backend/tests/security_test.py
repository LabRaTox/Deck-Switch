"""Prüft die Riegel, die bei der Code-Durchsicht am 2026-08-16 entstanden.

Diese Prüfungen sind bewusst eng an den gefundenen Schwachstellen gebaut —
sie sollen fehlschlagen, wenn jemand einen der Riegel wieder herausnimmt:

* Herkunftsprüfung des WebSockets (jede offene Webseite konnte mitlesen)
* Vite-Ports nur im Entwicklungsmodus
* „Programm beenden" mit zu breitem Muster
* Längengrenze beim Tippen und Freigeben hängender Tasten
* Ein verbundenes Deck überlebt einen veralteten Config-Stand
* Animierte Bilder fressen keinen Speicher mehr

Der WebSocket wird gegen einen echten Server geprüft — mit einem
nachgebauten Handshake, damit der Test ohne zusätzliche Pakete auskommt.

Aufruf:

    cd backend
    env XDG_CONFIG_HOME=/tmp/sd-test XDG_DATA_HOME=/tmp/sd-test \\
        ../.venv/bin/python tests/security_test.py
"""
import _wache  # bricht ab, statt in die echte Config zu schreiben
_wache.sichere_umgebung()
import asyncio
import contextlib
import base64
import os
import sys

from PIL import Image

FAILS = []


def check(name, condition, detail=""):
    mark = "✔" if condition else "✘"
    print(f"  {mark} {name}" + (f"  ({detail})" if detail else ""))
    if not condition:
        FAILS.append(name)


async def handshake(port: int, origin: str | None) -> int:
    """Baut einen WebSocket-Handshake von Hand und liefert den Statuscode."""
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    key = base64.b64encode(os.urandom(16)).decode()
    lines = [
        "GET /ws HTTP/1.1",
        f"Host: 127.0.0.1:{port}",
        "Upgrade: websocket",
        "Connection: Upgrade",
        f"Sec-WebSocket-Key: {key}",
        "Sec-WebSocket-Version: 13",
    ]
    if origin is not None:
        lines.append(f"Origin: {origin}")
    writer.write(("\r\n".join(lines) + "\r\n\r\n").encode())
    await writer.drain()

    status_line = await asyncio.wait_for(reader.readline(), timeout=5)
    writer.close()
    try:
        await writer.wait_closed()
    except Exception:
        pass
    parts = status_line.decode(errors="replace").split()
    return int(parts[1]) if len(parts) > 1 else 0


async def main():
    from deckswitch.config import Appearance, Config, DeckBinding, Slot
    from deckswitch.runtime import Runtime
    from deckswitch.server import _allowed_origins, create_app
    from deckswitch.services.desktop import DesktopError, DesktopService
    from deckswitch.services.input import MAX_TEXT_LENGTH, InputService, InputUnavailable

    print("\n== Erlaubte Herkünfte ==")
    normal = _allowed_origins("127.0.0.1", 8770, dev=False)
    dev = _allowed_origins("127.0.0.1", 8770, dev=True)
    check("die eigene Adresse ist erlaubt", "http://127.0.0.1:8770" in normal)
    check("Vite-Ports sind im Normalbetrieb NICHT erlaubt",
          not any(":5173" in o for o in normal), str(sorted(normal)))
    check("im Entwicklungsmodus dagegen schon",
          any(":5173" in o for o in dev))
    check("das Tauri-Fenster ist erlaubt", "tauri://localhost" in normal)

    print("\n== WebSocket-Handshake ==")
    import uvicorn

    runtime = Runtime()
    await runtime.start()
    port = 8791
    config = uvicorn.Config(
        create_app(runtime, port=port), host="127.0.0.1", port=port, log_level="error"
    )
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    for _ in range(50):
        await asyncio.sleep(0.1)
        if server.started:
            break

    fremd = await handshake(port, "http://evil.example")
    check("fremde Herkunft wird abgewiesen", fremd == 403, f"HTTP {fremd}")
    vite = await handshake(port, "http://localhost:5173")
    check("Vite-Port ohne Entwicklungsmodus abgewiesen", vite == 403, f"HTTP {vite}")
    eigen = await handshake(port, f"http://127.0.0.1:{port}")
    check("die eigene GUI kommt durch", eigen == 101, f"HTTP {eigen}")
    ohne = await handshake(port, None)
    check("ohne Origin (Kommandozeile) kommt durch", ohne == 101, f"HTTP {ohne}")

    server.should_exit = True
    # Mit Grenze: Ein Test, der hängt, blockiert jeden automatischen Lauf und
    # sagt dabei nicht einmal, was schiefging. Bleibt der Server stehen, ist
    # das selbst ein Befund — deshalb wird er hart beendet und gemeldet.
    try:
        await asyncio.wait_for(task, timeout=10)
        check("der Server fährt sauber herunter", True)
    except TimeoutError:
        server.force_exit = True
        with contextlib.suppress(Exception):
            await asyncio.wait_for(task, timeout=5)
        check("der Server fährt sauber herunter", False,
              "hing an einer offenen Verbindung")

    print("\n== Programm beenden ==")
    desktop = DesktopService()
    for muster in ("", "a", "."):
        try:
            desktop.close_application(muster)
            check(f"zu breites Muster {muster!r} wird abgelehnt", False, "durchgelassen")
        except DesktopError:
            check(f"zu breites Muster {muster!r} wird abgelehnt", True)
    check("ein Muster ohne Treffer beendet nichts",
          desktop.close_application("garantiert-kein-prozess-xyz") == 0)

    print("\n== Tastatur ==")
    service = InputService()
    try:
        service.type_text("x" * (MAX_TEXT_LENGTH + 1))
        check("zu langer Text wird abgelehnt", False, "durchgelassen")
    except InputUnavailable:
        check("zu langer Text wird abgelehnt", True, f"Grenze {MAX_TEXT_LENGTH}")
    check("Freigeben ohne gehaltene Taste tut nichts", service.release_all() == 0)

    print("\n== Veralteter Config-Stand ==")
    profile = runtime.config.new_profile_for_deck("Zweites Deck")
    runtime.config.decks["SERIAL-X"] = DeckBinding(
        serial="SERIAL-X", name="Zweites Deck", profile_id=profile.id
    )
    runtime._sync_decks()
    deck = runtime.decks["SERIAL-X"]
    deck.device.deck = object()
    deck.device.info.connected = True
    deck.device.set_brightness = lambda value: None
    deck.device.set_key_image = lambda index, image: None
    deck.device.set_touchscreen_image = lambda image, x=0, y=0: None
    deck.profile.root_page().keys[0] = Slot(
        plugin_id="streamdeck", action_id="home", appearance=Appearance()
    )

    veraltet = Config.model_validate(runtime.config.model_dump(mode="json"))
    veraltet.decks.pop("SERIAL-X")
    veraltet.profiles.pop(profile.id)
    veraltet.app.language = "en"
    runtime.apply_config(veraltet)

    check("die Bindung des verbundenen Decks überlebt", "SERIAL-X" in runtime.config.decks)
    check("sein Profil überlebt", profile.id in runtime.config.profiles)
    check("und seine Belegung auch",
          0 in runtime.decks["SERIAL-X"].profile.root_page().keys)
    check("die eigentliche Änderung kommt trotzdem an",
          runtime.config.app.language == "en")

    # Ein Deck, das nicht angeschlossen ist, muss entfernbar bleiben.
    runtime.config.decks["SERIAL-Y"] = DeckBinding(
        serial="SERIAL-Y", name="Weg damit", profile_id=profile.id
    )
    runtime._sync_decks()
    ohne_y = Config.model_validate(runtime.config.model_dump(mode="json"))
    ohne_y.decks.pop("SERIAL-Y")
    runtime.apply_config(ohne_y)
    check("ein getrenntes Deck lässt sich weiterhin entfernen",
          "SERIAL-Y" not in runtime.config.decks)

    print("\n== Speicher animierter Bilder ==")
    from deckswitch import paths
    from deckswitch.services.icons import MAX_FRAME_EDGE, IconService

    paths.UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    sample = paths.UPLOADS_DIR / "_security-test.gif"
    frames = [Image.new("RGB", (1280, 720), (i * 6 % 255, 0, 0)) for i in range(12)]
    frames[0].save(sample, save_all=True, append_images=frames[1:], duration=80, loop=0)

    icons = IconService()

    def rss() -> float:
        for line in open("/proc/self/status"):
            if line.startswith("VmRSS"):
                return int(line.split()[1]) / 1024
        return 0.0

    before = rss()
    check("die Frage nach Bewegung stimmt", icons.is_animated_upload(sample.name))
    check("und kostet keinen nennenswerten Speicher", rss() - before < 5,
          f"+{rss()-before:.1f} MB")

    loaded = icons._raw_frames(sample)
    check("Einzelbilder werden verkleinert gehalten",
          all(max(image.size) <= MAX_FRAME_EDGE for image, _ in loaded),
          f"größte Kante {max(max(i.size) for i, _ in loaded)} px")
    sample.unlink()

    await runtime.stop()

    print()
    if FAILS:
        print(f"FEHLGESCHLAGEN ({len(FAILS)}): " + ", ".join(FAILS))
        sys.exit(1)
    print("Alle Prüfungen bestanden.")


asyncio.run(main())
