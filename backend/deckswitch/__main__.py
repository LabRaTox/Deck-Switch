"""Einstiegspunkt: startet Runtime und lokalen Server gemeinsam.

Beide teilen sich einen Event-Loop — der Server ist nur die Fernbedienung für
die Runtime, kein eigener Prozess.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import signal
import sys
from pathlib import Path

import uvicorn

from . import paths
from .runtime import Runtime
from .server import create_app


def setup_logging(verbose: bool) -> None:
    paths.DATA_DIR.mkdir(parents=True, exist_ok=True)
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stderr)]
    with contextlib.suppress(OSError):
        handlers.append(logging.FileHandler(paths.LOG_FILE, encoding="utf-8"))

    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        # Millisekunden im Zeitstempel: bei Gesten auf dem Touchstrip sind die
        # Abstände zwischen Ereignissen die eigentliche Information.
        format="%(asctime)s.%(msecs)03d %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        handlers=handlers,
    )
    # Der Zugriffs-Log von uvicorn ist bei einem lokalen Backend nur Lärm.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


def port_available(host: str, port: int) -> bool:
    """Prüft den Port, *bevor* das Gerät geöffnet wird.

    uvicorn beendet den Prozess bei einem Bind-Fehler per ``SystemExit``.
    Wäre das Deck da schon offen, käme unser Aufräumcode nie dran — und
    libusb quittiert das Prozessende mit einer Assertion statt einer
    Exception. Also lieber vorher fragen.
    """
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind((host, port))
        except OSError:
            return False
    return True


async def run(args: argparse.Namespace) -> int:
    log = logging.getLogger(__name__)

    # Config einmal ohne laufende Runtime lesen, um Host/Port zu erfahren.
    probe_runtime = Runtime(Path(args.config) if args.config else None)
    with contextlib.suppress(Exception):
        probe_runtime.store.load()
    host = args.host or probe_runtime.store.config.app.host
    port = args.port or probe_runtime.store.config.app.port

    if not port_available(host, port):
        log.error(
            "Port %s:%s ist belegt. Anderen Port wählen: --port <nummer> "
            "(oder in der GUI unter Einstellungen ändern)",
            host,
            port,
        )
        return 1

    runtime = probe_runtime
    await runtime.start()

    app = create_app(runtime, host=host, port=port)
    server = uvicorn.Server(
        uvicorn.Config(app, host=host, port=port, log_level="warning", access_log=False)
    )

    loop = asyncio.get_running_loop()
    stopping = asyncio.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, stopping.set)

    serve_task = asyncio.create_task(server.serve(), name="uvicorn")
    log.info("Backend läuft auf http://%s:%s", host, port)

    tray_task = None
    tray = None
    if not args.no_tray:
        # Das Tray ist Beiwerk: Scheitert es — keine Leiste, kaputtes D-Bus,
        # ungewöhnliche Umgebung —, darf das die Gerätesteuerung nicht
        # mitreißen.
        try:
            tray, tray_task = await _start_tray(
                runtime, f"http://{host}:{port}", stopping
            )
        except Exception:
            log.warning("Tray-Symbol nicht verfügbar", exc_info=True)

    await asyncio.wait(
        [serve_task, asyncio.create_task(stopping.wait())],
        return_when=asyncio.FIRST_COMPLETED,
    )

    if tray_task is not None:
        tray_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await tray_task
    if tray is not None:
        await tray.stop()

    server.should_exit = True
    with contextlib.suppress(asyncio.CancelledError, Exception):
        await asyncio.wait_for(serve_task, timeout=5)
    await runtime.stop()
    return 0


async def _start_tray(runtime: Runtime, url: str, stopping: asyncio.Event):
    """Meldet das Tray-Symbol an und hält es am Gerätezustand.

    Läuft die Sitzung ohne passende Leiste (oder gar ohne Sitzung), bleibt
    das folgenlos — das Backend arbeitet unverändert weiter.
    """
    from .events import EVT_DEVICE_STATE
    from .tray import SystemTray

    def reconnect() -> None:
        runtime.device.close()

    def brightness(step: int) -> None:
        device = runtime.config.device
        device.brightness = max(5, min(100, device.brightness + step))
        runtime.device.set_brightness(device.brightness)
        runtime.save_config()

    tray = SystemTray(
        url=url,
        on_reconnect=reconnect,
        on_quit=stopping.set,
        on_brightness=brightness,
    )
    if not await tray.start():
        return None, None

    def refresh() -> None:
        info = runtime.device.info
        tray.update(
            connected=info.connected,
            dimmed=bool(getattr(runtime, "_dimmed", False)),
            device_name=info.deck_type,
        )

    refresh()

    async def follow() -> None:
        """Folgt den Gerätemeldungen, statt im Sekundentakt nachzusehen."""
        async with runtime.bus.subscribe() as queue:
            while True:
                event = await queue.get()
                if event.type == EVT_DEVICE_STATE:
                    refresh()

    return tray, asyncio.create_task(follow(), name="tray")


def main() -> int:
    parser = argparse.ArgumentParser(prog="deckswitch", description=__doc__)
    parser.add_argument("--host", help="Bind-Adresse (Standard: 127.0.0.1)")
    parser.add_argument("--port", type=int, help="Port (Standard: 8765)")
    parser.add_argument("--config", help="Abweichender Pfad zur config.json")
    parser.add_argument(
        "--no-tray", action="store_true", help="Kein Symbol im Systemabschnitt"
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Debug-Ausgaben")
    args = parser.parse_args()

    setup_logging(args.verbose)
    try:
        return asyncio.run(run(args))
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
