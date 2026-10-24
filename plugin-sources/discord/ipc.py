"""Minimaler Client für Discords lokale RPC-Schnittstelle.

Discord legt einen Unix-Socket (``discord-ipc-0`` … ``-9``) im Runtime-Ordner
an. Darüber läuft ein Frame-Protokoll: 4 Byte Opcode + 4 Byte Länge (beide
little-endian) + JSON.

Ablauf einer Sitzung:
  1. HANDSHAKE mit der Application-ID  → Discord antwortet mit ``READY``
  2. ``AUTHORIZE`` (nur beim ersten Mal) → der User bestätigt im Discord-
     Client, wir bekommen einen einmaligen Code
  3. Code gegen ein Access-Token tauschen (dafür ist das Client-Secret nötig)
  4. ``AUTHENTICATE`` mit dem Token → ab jetzt sind die RPC-Kommandos offen

Der Token wird gespeichert, Schritt 2 und 3 passieren also genau einmal. Er
gilt 7 Tage und wird vorher mit dem ``refresh_token`` erneuert, ohne Dialog.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import struct
import uuid
from collections.abc import Callable
from pathlib import Path

from deckswitch.plugins.base import plugin_text

log = logging.getLogger(__name__)

OP_HANDSHAKE = 0
OP_FRAME = 1
OP_CLOSE = 2
OP_PING = 3
OP_PONG = 4

RPC_SCOPES = ["rpc", "rpc.voice.read", "rpc.voice.write"]
TOKEN_URL = "https://discord.com/api/oauth2/token"
DEFAULT_REDIRECT_URI = "http://localhost"

#: Discord steht hinter Cloudflare, und Cloudflare weist Anfragen mit dem
#: Standard-User-Agent von urllib ("Python-urllib/3.x") ab — mit HTTP 403 und
#: "error code: 1010", noch bevor Discord die Anfrage sieht. Ein eigener
#: User-Agent ist deshalb Pflicht, nicht Kosmetik.
USER_AGENT = "StreamDeckApp/0.1 (Linux; +local)"

RESPONSE_TIMEOUT_S = 30.0


class DiscordIpcError(RuntimeError):
    pass


class DiscordAuthRequired(DiscordIpcError):
    """Es fehlt ein gültiges Token — der User muss den Zugriff bestätigen."""


def socket_candidates() -> list[Path]:
    """Mögliche Socket-Pfade, inklusive Flatpak- und Snap-Ablagen."""
    base = (
        os.environ.get("XDG_RUNTIME_DIR")
        or os.environ.get("TMPDIR")
        or os.environ.get("TMP")
        or "/tmp"
    )
    roots = [
        Path(base),
        Path(base) / "app" / "com.discordapp.Discord",
        Path(base) / "app" / "com.discordapp.DiscordCanary",
        Path(base) / "snap.discord",
    ]
    return [root / f"discord-ipc-{i}" for root in roots for i in range(10)]


class DiscordIpc:
    """Async-Verbindung zu einem laufenden Discord-Client."""

    def __init__(self, client_id: str) -> None:
        self.client_id = client_id
        self.reader: asyncio.StreamReader | None = None
        self.writer: asyncio.StreamWriter | None = None
        self.connected = False
        self.user: dict | None = None

        self._pending: dict[str, asyncio.Future] = {}
        self._reader_task: asyncio.Task | None = None
        self._event_handlers: dict[str, Callable] = {}
        self._write_lock = asyncio.Lock()

    def on_event(self, name: str, handler: Callable) -> None:
        self._event_handlers[name] = handler

    # -- Verbindung --------------------------------------------------------

    async def connect(self) -> None:
        if self.connected:
            return
        if not self.client_id:
            raise DiscordIpcError(_t("ipc.keine_client_id"))

        last_error: Exception | None = None
        for path in socket_candidates():
            if not path.exists():
                continue
            try:
                self.reader, self.writer = await asyncio.open_unix_connection(str(path))
            except OSError as exc:
                last_error = exc
                continue

            self._reader_task = asyncio.create_task(self._read_loop(), name="discord-ipc")
            try:
                ready = await self._handshake()
            except Exception as exc:
                await self.close()
                last_error = exc
                continue

            self.connected = True
            self.user = (ready.get("data") or {}).get("user")
            log.info("Discord-IPC verbunden über %s", path)
            return

        raise DiscordIpcError(
            _t("ipc.kein_socket_grund", grund=last_error) if last_error else _t("ipc.kein_socket")
        )

    async def close(self) -> None:
        self.connected = False
        if self._reader_task is not None:
            self._reader_task.cancel()
            self._reader_task = None
        writer, self.writer = self.writer, None
        self.reader = None
        if writer is not None:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass
        for future in self._pending.values():
            if not future.done():
                future.cancel()
        self._pending.clear()

    async def _handshake(self) -> dict:
        future: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending["__ready__"] = future
        await self._send(OP_HANDSHAKE, {"v": 1, "client_id": self.client_id})
        return await asyncio.wait_for(future, timeout=10)

    # -- Protokoll ---------------------------------------------------------

    async def _send(self, opcode: int, payload: dict) -> None:
        writer = self.writer
        if writer is None:
            raise DiscordIpcError(_t("ipc.nicht_verbunden"))
        data = json.dumps(payload).encode("utf-8")
        async with self._write_lock:
            writer.write(struct.pack("<II", opcode, len(data)) + data)
            await writer.drain()

    async def _read_loop(self) -> None:
        try:
            while True:
                reader = self.reader
                if reader is None:
                    return
                header = await reader.readexactly(8)
                opcode, length = struct.unpack("<II", header)
                body = await reader.readexactly(length) if length else b"{}"
                try:
                    payload = json.loads(body)
                except json.JSONDecodeError:
                    continue

                if opcode == OP_PING:
                    await self._send(OP_PONG, payload)
                    continue
                if opcode == OP_CLOSE:
                    log.info("Discord hat die Verbindung geschlossen: %s", payload)
                    self.connected = False
                    self._fail_pending()
                    return
                self._dispatch(payload)
        except (asyncio.IncompleteReadError, ConnectionResetError):
            log.info("Discord-IPC-Verbindung beendet")
            self.connected = False
            self._fail_pending()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Discord-IPC-Leseschleife abgebrochen")
            self.connected = False
            self._fail_pending()

    def _fail_pending(self) -> None:
        """Wer noch auf eine Antwort wartet, bekommt keine mehr — sofort Bescheid geben."""
        pending, self._pending = self._pending, {}
        for future in pending.values():
            if not future.done():
                future.set_exception(DiscordIpcError(_t("ipc.nicht_verbunden")))

    def _dispatch(self, payload: dict) -> None:
        event = payload.get("evt")
        nonce = payload.get("nonce")

        if event == "READY":
            future = self._pending.pop("__ready__", None)
            if future is not None and not future.done():
                future.set_result(payload)
            return

        if nonce is not None:
            future = self._pending.pop(nonce, None)
            if future is not None and not future.done():
                if event == "ERROR":
                    data = payload.get("data") or {}
                    future.set_exception(
                        DiscordIpcError(data.get("message") or _t("ipc.unbekannter_fehler"))
                    )
                else:
                    future.set_result(payload.get("data") or {})
            return

        if event:
            handler = self._event_handlers.get(event)
            if handler is not None:
                result = handler(payload.get("data") or {})
                if asyncio.iscoroutine(result):
                    asyncio.create_task(result)

    async def command(self, cmd: str, args: dict | None = None, *, timeout: float = 10.0) -> dict:
        nonce = uuid.uuid4().hex
        future: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[nonce] = future
        await self._send(OP_FRAME, {"cmd": cmd, "args": args or {}, "nonce": nonce})
        try:
            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError:
            self._pending.pop(nonce, None)
            raise DiscordIpcError(_t("ipc.zeitueberschreitung", befehl=cmd)) from None

    async def subscribe(self, event: str, args: dict | None = None) -> None:
        nonce = uuid.uuid4().hex
        future: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[nonce] = future
        await self._send(
            OP_FRAME, {"cmd": "SUBSCRIBE", "evt": event, "args": args or {}, "nonce": nonce}
        )
        try:
            await asyncio.wait_for(future, timeout=10)
        except asyncio.TimeoutError:
            self._pending.pop(nonce, None)

    # -- Autorisierung -----------------------------------------------------

    async def authenticate(self, access_token: str) -> dict:
        return await self.command("AUTHENTICATE", {"access_token": access_token})

    async def authorize(self) -> str:
        """Fragt den User im Discord-Client um Erlaubnis; liefert den Code.

        Der Dialog erscheint im laufenden Discord — deshalb der großzügige
        Timeout.
        """
        data = await self.command(
            "AUTHORIZE",
            {"client_id": self.client_id, "scopes": RPC_SCOPES},
            timeout=RESPONSE_TIMEOUT_S,
        )
        code = data.get("code")
        if not code:
            raise DiscordIpcError(_t("ipc.kein_code"))
        return code


def exchange_code(
    client_id: str, client_secret: str, code: str, redirect_uri: str = DEFAULT_REDIRECT_URI
) -> dict:
    """Tauscht den Autorisierungs-Code gegen ein Token.

    Liefert die ganze Antwort: ``access_token``, ``refresh_token`` und
    ``expires_in`` (Sekunden, bei Discord 7 Tage). Blockierend (``urllib``),
    vom Aufrufer im Executor auszuführen.
    """
    return _token_request(
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
        }
    )


def refresh_token(client_id: str, client_secret: str, refresh: str) -> dict:
    """Holt mit dem ``refresh_token`` ein neues Token, ohne Dialog in Discord.

    Die Antwort hat denselben Aufbau wie beim Code-Tausch. Discord gibt dabei
    jedes Mal ein neues ``refresh_token`` aus, und das alte ist danach
    ungültig. Wer erneuert, muss das neue also sofort speichern.
    Blockierend, vom Aufrufer im Executor auszuführen.
    """
    return _token_request(
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "refresh_token",
            "refresh_token": refresh,
        },
        erneuerung=True,
    )


def _token_request(felder: dict, *, erneuerung: bool = False) -> dict:
    import urllib.error
    import urllib.parse
    import urllib.request

    request = urllib.request.Request(
        TOKEN_URL,
        data=urllib.parse.urlencode(felder).encode(),
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            payload = json.loads(response.read())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        if erneuerung and exc.code in (400, 401):
            raise DiscordIpcError(_t("ipc.erneuerung_abgelehnt", detail=detail)) from exc
        raise DiscordIpcError(_explain_token_error(exc.code, detail)) from exc
    except urllib.error.URLError as exc:
        raise DiscordIpcError(_t("ipc.token_nicht_moeglich", grund=exc.reason)) from exc

    if not payload.get("access_token"):
        raise DiscordIpcError(_t("ipc.antwort_ohne_token", antwort=payload))
    return payload


def _explain_token_error(status: int, detail: str) -> str:
    """Übersetzt die Antwort des Token-Endpunkts in etwas Handhabbares."""
    if "error code: 1010" in detail:
        return _t("ipc.token_cloudflare")
    if "invalid_client" in detail:
        return _t("ipc.token_invalid_client")
    if "invalid_grant" in detail:
        return _t("ipc.token_invalid_grant")
    if "invalid_scope" in detail:
        return _t("ipc.token_invalid_scope")
    return _t("ipc.token_abgelehnt", status=status, detail=detail)


def _t(schluessel: str, **werte) -> str:
    return plugin_text(Path(__file__).resolve().parent, "discord", schluessel, werte)
