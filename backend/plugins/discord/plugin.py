"""Discord-Plugin über die lokale RPC/IPC-Schnittstelle.

Scope bewusst breiter als reines Mute: Mute, Deafen, Kanalwechsel, Kanal
verlassen und Eingangspegel — alles gegen den *laufenden* Discord-Client des
Users, nicht gegen einen Bot.

Einmalige Einrichtung (siehe docs/discord-setup.md):
  1. Eigene Application im Discord Developer Portal anlegen
  2. Application-ID und Client-Secret in die Plugin-Einstellungen eintragen
  3. Beim ersten Verbinden im Discord-Client den Zugriff bestätigen

Das Access-Token landet danach in einer eigenen Datei mit 0600 — nicht in der
Config, die exportiert und weitergegeben werden kann.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
from pathlib import Path

from PIL import Image, ImageDraw

from deckswitch import paths
from deckswitch.plugins.base import ActionPlugin

from ipc import USER_AGENT, DiscordIpc, DiscordIpcError, exchange_code

ACCENT = "#5865f2"
RECONNECT_INTERVAL_S = 8.0
TOKEN_FILE = paths.CONFIG_DIR / "discord-token.json"

#: Serverlogos liegen im Cache, nicht bei den Nutzerdaten — sie kommen
#: jederzeit wieder von Discords CDN und dürfen jederzeit weggeräumt werden.
GUILD_ICON_DIR = paths.DATA_DIR / "cache" / "discord-guilds"
#: Kantenlänge des heruntergeladenen Logos. Eine Taste ist 120 px breit,
#: 256 px lassen also Luft für größere Icon-Einstellungen.
GUILD_ICON_PX = 256

#: Kanaltypen aus der Discord-API.
VOICE_CHANNEL = 2
#: 0 = normaler Textkanal, 5 = Ankündigungskanal. Beide kann man öffnen, und
#: für den Sprung dorthin verhalten sie sich gleich.
TEXT_CHANNELS = frozenset({0, 5})


class DiscordPlugin(ActionPlugin):
    def __init__(self, manifest, services):
        super().__init__(manifest, services)
        self.ipc: DiscordIpc | None = None
        self.authenticated = False
        self._task: asyncio.Task | None = None
        self._connect_lock = asyncio.Lock()

        # Gespiegelter Zustand — render() darf nie auf Netzwerk warten.
        self.muted = False
        self.deafened = False
        self.input_volume = 100.0
        self.current_channel_id: str | None = None
        self.channels: list[dict] = []
        self.text_channels: list[dict] = []
        self.last_error: str | None = None

        #: Server-ID → heruntergeladenes Logo im Cache.
        self.guild_icons: dict[str, Path] = {}
        #: Fertig zugeschnittene Logos je (Datei, Kantenlänge).
        self._icon_images: dict[tuple[Path, int], Image.Image] = {}

    # -- Lebenszyklus ------------------------------------------------------

    async def setup(self):
        if self.plugin_config.get("auto_connect", True):
            self._task = asyncio.create_task(self._connection_loop(), name="discord-connect")

    async def teardown(self):
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        if self.ipc is not None:
            await self.ipc.close()
            self.ipc = None
        self.authenticated = False

    def on_plugin_config_changed(self, config):
        async def restart():
            await self.teardown()
            await self.setup()

        self.run_async(restart())

    async def _connection_loop(self):
        while True:
            if not self.authenticated:
                await self._connect()
            await asyncio.sleep(RECONNECT_INTERVAL_S)

    # -- Verbindung --------------------------------------------------------

    async def _connect(self, *, interactive: bool = False) -> bool:
        """Verbindet und meldet sich an.

        ``interactive=True`` erlaubt den Autorisierungs-Dialog im Discord-
        Client. Im Hintergrund-Reconnect ist das unerwünscht — sonst poppt
        alle paar Sekunden ein Dialog auf.
        """
        async with self._connect_lock:
            if self.authenticated:
                return True

            client_id = (self.plugin_config.get("client_id") or "").strip()
            if not client_id:
                self.last_error = "Keine Application-ID eingetragen"
                return False

            token = _load_token(client_id)
            if token is None and not interactive:
                self.last_error = "Noch nicht autorisiert — in den Einstellungen verbinden"
                return False

            ipc = DiscordIpc(client_id)
            try:
                await ipc.connect()
            except DiscordIpcError as exc:
                self.last_error = str(exc)
                self._mark_offline()
                return False

            try:
                if token is None:
                    token = await self._authorize(ipc, client_id)
                await ipc.authenticate(token)
            except DiscordIpcError as exc:
                retried = False
                if token is not None and interactive:
                    # Gespeichertes Token abgelaufen: einmal neu autorisieren.
                    _clear_token()
                    try:
                        token = await self._authorize(ipc, client_id)
                        await ipc.authenticate(token)
                        retried = True
                    except DiscordIpcError as retry_exc:
                        exc = retry_exc
                if not retried:
                    self.last_error = f"Anmeldung fehlgeschlagen: {exc}"
                    await ipc.close()
                    self._mark_offline()
                    return False

            self.ipc = ipc
            self.authenticated = True
            self.last_error = None
            self._register_events(ipc)
            await self._refresh_state()
            self.log.info("Mit Discord verbunden")
            self.services.runtime.request_redraw()
            self.services.runtime.publish_plugin_status(self.manifest.id)
            return True

    async def _authorize(self, ipc: DiscordIpc, client_id: str) -> str:
        secret = (self.plugin_config.get("client_secret") or "").strip()
        if not secret:
            raise DiscordIpcError("Kein Client-Secret eingetragen")

        code = await ipc.authorize()
        redirect_uri = self.plugin_config.get("redirect_uri") or "http://localhost"
        token = await asyncio.get_running_loop().run_in_executor(
            None, exchange_code, client_id, secret, code, redirect_uri
        )
        _store_token(client_id, token)
        return token

    async def gui_command(self, command, payload):
        if command == "connect":
            return await self.connect_interactive()
        if command == "disconnect":
            await self.teardown()
            return {"connected": False}
        if command == "forget":
            _clear_token()
            await self.teardown()
            return {"connected": False, "message": "Autorisierung gelöscht"}
        if command == "status":
            return {
                "connected": self.authenticated,
                "error": self.last_error,
                "user": self.ipc.user if self.ipc else None,
                "channels": len(self.channels),
            }
        raise NotImplementedError(f"Discord kennt kein Kommando '{command}'")

    async def connect_interactive(self) -> dict:
        """Von der GUI aufgerufen: Verbindung inklusive Zustimmungs-Dialog."""
        await self.teardown()
        ok = await self._connect(interactive=True)
        if ok and self.plugin_config.get("auto_connect", True):
            self._task = asyncio.create_task(self._connection_loop(), name="discord-connect")
        return {"connected": ok, "error": self.last_error, "user": (self.ipc.user if self.ipc else None)}

    def _mark_offline(self):
        was = self.authenticated
        self.authenticated = False
        self.ipc = None
        if was:
            self.services.runtime.request_redraw()
            self.services.runtime.publish_plugin_status(self.manifest.id)

    def get_status(self):
        if self.authenticated:
            user = (self.ipc.user or {}).get("username") if self.ipc else None
            detail = f"angemeldet als {user}" if user else "verbunden"
            return {"connected": True, "detail": detail}
        return {"connected": False, "detail": self.last_error or "nicht verbunden"}

    # -- Events ------------------------------------------------------------

    def _register_events(self, ipc: DiscordIpc):
        def on_voice_settings(data):
            self.muted = bool(data.get("mute"))
            self.deafened = bool(data.get("deaf"))
            volume = (data.get("input") or {}).get("volume")
            if volume is not None:
                self.input_volume = float(volume)
            self.services.runtime.request_redraw()

        def on_voice_channel(data):
            self.current_channel_id = (data or {}).get("channel_id")
            self.services.runtime.request_redraw()

        ipc.on_event("VOICE_SETTINGS_UPDATE", on_voice_settings)
        ipc.on_event("VOICE_CHANNEL_SELECT", on_voice_channel)

        async def subscribe():
            with contextlib.suppress(Exception):
                await ipc.subscribe("VOICE_SETTINGS_UPDATE")
                await ipc.subscribe("VOICE_CHANNEL_SELECT")

        asyncio.create_task(subscribe())

    async def _refresh_state(self):
        ipc = self.ipc
        if ipc is None:
            return
        with contextlib.suppress(DiscordIpcError):
            settings = await ipc.command("GET_VOICE_SETTINGS")
            self.muted = bool(settings.get("mute"))
            self.deafened = bool(settings.get("deaf"))
            self.input_volume = float((settings.get("input") or {}).get("volume", 100))

        with contextlib.suppress(DiscordIpcError):
            channel = await ipc.command("GET_SELECTED_VOICE_CHANNEL")
            self.current_channel_id = (channel or {}).get("id")

        await self._refresh_channels()

    async def _refresh_channels(self):
        ipc = self.ipc
        if ipc is None:
            return
        channels: list[dict] = []
        text_channels: list[dict] = []
        try:
            guilds = (await ipc.command("GET_GUILDS")).get("guilds", [])
        except DiscordIpcError as exc:
            self.log.debug("Serverliste nicht abrufbar: %s", exc)
            return

        for guild in guilds:
            try:
                data = await ipc.command("GET_CHANNELS", {"guild_id": guild["id"]})
            except DiscordIpcError:
                continue
            for channel in data.get("channels", []):
                entry = {
                    "id": channel["id"],
                    "name": channel.get("name", "?"),
                    "guild": guild.get("name", ""),
                    "guild_id": guild["id"],
                }
                kind = channel.get("type")
                if kind == VOICE_CHANNEL:
                    channels.append(entry)
                elif kind in TEXT_CHANNELS:
                    text_channels.append(entry)
        self.channels = channels
        self.text_channels = text_channels

        await self._refresh_guild_icons(guilds)

    async def _refresh_guild_icons(self, guilds: list[dict]):
        """Holt die Serverlogos ins Dateisystem.

        ``GET_GUILDS`` liefert nur Name und ID — die Bild-URL steht erst in
        ``GET_GUILD``, deshalb eine Abfrage je Server. Das passiert nur beim
        Verbinden, und geladen wird nur, was nicht schon im Cache liegt.
        """
        ipc = self.ipc
        if ipc is None:
            return
        changed = False
        reported = False
        for guild in guilds:
            guild_id = guild["id"]
            try:
                # ``timeout`` ist Discords eigene Wartezeit: ohne sie kann die
                # Antwort auf sich warten lassen, bis unsere greift.
                detail = await ipc.command(
                    "GET_GUILD", {"guild_id": guild_id, "timeout": 5}
                )
            except DiscordIpcError as exc:
                # Scheitert das, scheitert es meist bei allen Servern aus
                # demselben Grund — einmal ins Log genügt.
                if not reported:
                    self.log.info("Serverlogos nicht abrufbar: %s", exc)
                    reported = True
                self.log.debug("Server %s ohne Details: %s", guild_id, exc)
                continue
            url = (detail or {}).get("icon_url")
            if not url:
                # Server ohne Logo — die Taste bleibt beim normalen Icon.
                continue
            try:
                path = await asyncio.to_thread(_download_guild_icon, guild_id, url)
            except OSError as exc:
                self.log.debug("Serverlogo für %s nicht ladbar: %s", guild_id, exc)
                continue
            if self.guild_icons.get(guild_id) != path:
                self.guild_icons[guild_id] = path
                changed = True
        if changed:
            self.services.runtime.request_redraw()

    # -- Eingaben ----------------------------------------------------------

    async def on_key_down(self, action_id, settings, ctx):
        if action_id == "mute":
            mode = self._hold_mode(ctx)
            if mode in ("push_to_talk", "push_to_mute"):
                # Gedrückt: Push-to-Talk öffnet, Push-to-Mute schließt.
                await self._set_voice({"mute": mode == "push_to_mute"})
                return
        await self._activate(action_id, settings, ctx)

    async def on_key_up(self, action_id, settings, ctx):
        if action_id != "mute":
            return
        mode = self._hold_mode(ctx)
        if mode in ("push_to_talk", "push_to_mute"):
            # Losgelassen: genau andersherum.
            await self._set_voice({"mute": mode == "push_to_talk"})

    def _hold_mode(self, ctx) -> str:
        """``toggle`` | ``push_to_talk`` | ``push_to_mute``.

        Vor der Umstellung gab es hier ein Häkchen ``push_to_talk``. Wer das
        gesetzt hatte, soll nicht plötzlich eine umschaltende Taste haben —
        deshalb der Rückgriff auf den alten Schlüssel, solange kein ``mode``
        gewählt wurde.
        """
        mode = ctx.setting("mode", None)
        if mode:
            return mode
        return "push_to_talk" if ctx.setting("push_to_talk", False) else "toggle"

    async def on_dial_push(self, action_id, settings, ctx):
        await self._activate(action_id, settings, ctx)

    async def on_dial_rotate(self, action_id, settings, delta, ctx):
        if action_id != "input_volume" or not self.authenticated:
            return
        step = float(ctx.setting("step", 5))
        value = max(0.0, min(100.0, self.input_volume + delta * step))
        await self._set_voice({"input": {"volume": value}})
        self.input_volume = value

    async def _activate(self, action_id, settings, ctx):
        if not self.authenticated:
            self.notify_info(self.last_error or "Discord nicht verbunden")
            return

        if action_id == "mute":
            await self._set_voice({"mute": not self.muted})
        elif action_id == "deafen":
            await self._set_voice({"deaf": not self.deafened})
        elif action_id == "channel":
            channel_id = settings.get("channel_id")
            if not channel_id:
                self.notify_error("Kein Sprachkanal eingestellt")
                return
            await self._command("SELECT_VOICE_CHANNEL", {"channel_id": channel_id, "force": True})
        elif action_id == "leave":
            await self._command("SELECT_VOICE_CHANNEL", {"channel_id": None})
        elif action_id == "text_channel":
            channel_id = settings.get("channel_id")
            if not channel_id:
                self.notify_error("Kein Textkanal eingestellt")
                return
            await self._command("SELECT_TEXT_CHANNEL", {"channel_id": channel_id})
        elif action_id == "input_volume":
            await self._set_voice({"mute": not self.muted})

    async def _set_voice(self, args: dict):
        result = await self._command("SET_VOICE_SETTINGS", args)
        if result is None:
            return
        if "mute" in args:
            self.muted = bool(args["mute"])
        if "deaf" in args:
            self.deafened = bool(args["deaf"])
        self.services.runtime.request_redraw()

    async def _command(self, cmd: str, args: dict) -> dict | None:
        ipc = self.ipc
        if ipc is None or not self.authenticated:
            return None
        try:
            return await ipc.command(cmd, args)
        except DiscordIpcError as exc:
            self.last_error = str(exc)
            self.notify_error(f"Discord: {exc}")
            self._mark_offline()
            return None

    # -- Zustand und Darstellung ------------------------------------------

    def get_state(self, action_id, settings, ctx):
        if not self.authenticated:
            return "offline"
        if action_id == "mute":
            return "muted" if self.muted else "default"
        if action_id == "deafen":
            return "deafened" if self.deafened else "default"
        if action_id == "channel":
            return "active" if settings.get("channel_id") == self.current_channel_id else "inactive"
        if action_id == "text_channel":
            # Kein Aktiv-Zustand: Discords RPC kennt kein Gegenstück zu
            # GET_SELECTED_VOICE_CHANNEL für Textkanäle.
            return "default"
        return None

    def get_label(self, action_id, settings, ctx):
        if ctx.appearance.label_text:
            return None
        if action_id in ("channel", "text_channel"):
            pool = self.channels if action_id == "channel" else self.text_channels
            channel_id = settings.get("channel_id")
            for channel in pool:
                if channel["id"] == channel_id:
                    # Textkanäle heißen in Discord ohne Raute — mit ist es
                    # auf der Taste sofort als Textkanal erkennbar.
                    return f"#{channel['name']}" if action_id == "text_channel" else channel["name"]
        if action_id == "input_volume":
            return f"{round(self.input_volume)}%"
        return None

    def _guild_icon(self, action_id, settings, ctx, state):
        """Serverlogo für eine Kanaltaste — oder ``None``.

        Vorrang hat immer ein selbst gewähltes Icon: das Logo füllt nur die
        Lücke, in der sonst das generische Kanal-Symbol stünde.
        """
        if action_id not in ("channel", "text_channel"):
            return None
        if not ctx.setting("guild_icon", True):
            return None
        if ctx.appearance.icon_for_state(state) is not None:
            return None

        pool = self.channels if action_id == "channel" else self.text_channels
        channel_id = settings.get("channel_id")
        guild_id = next(
            (c.get("guild_id") for c in pool if c["id"] == channel_id), None
        )
        path = self.guild_icons.get(guild_id or "")
        if path is None:
            return None
        return self._icon_image(path, self.services.render.icon_px(
            ctx.size, ctx.appearance.icon_size
        ))

    def _icon_image(self, path: Path, size: int):
        """Lädt das Logo, skaliert es und schneidet es rund zu.

        Rund, weil Discord Serverlogos überall rund zeigt — eckig sähe auf
        der Taste nach fremdem Bild aus statt nach dem Server.
        """
        cached = self._icon_images.get((path, size))
        if cached is not None:
            return cached
        try:
            with Image.open(path) as source:
                image = source.convert("RGBA").resize((size, size), Image.LANCZOS)
        except (OSError, ValueError) as exc:
            self.log.debug("Serverlogo %s nicht lesbar: %s", path, exc)
            return None

        # Maske vierfach überabgetastet — sonst franst der Kreisrand aus.
        mask = Image.new("L", (size * 4, size * 4), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, size * 4 - 1, size * 4 - 1), fill=255)
        image.putalpha(mask.resize((size, size), Image.LANCZOS))

        self._icon_images[(path, size)] = image
        return image

    def render(self, action_id, settings, ctx):
        state = self.get_state(action_id, settings, ctx)
        render = self.services.render

        if action_id == "input_volume" and ctx.input_type == "dial":
            # Der Balken bekommt seinen Platz unten reserviert, sonst läge er
            # auf der Beschriftung.
            box = render.bar_box(ctx.size)
            image = render.render_slot(ctx, state=state, accent=ACCENT,
                                       label_override=self.get_label(action_id, settings, ctx),
                                       reserve_bottom=render.bar_reserve(ctx.size, box))
            render.draw_bar(image, self.input_volume / 100, box=box, color=ACCENT)
            return image

        image = render.render_slot(
            ctx,
            state=state,
            label_override=self.get_label(action_id, settings, ctx),
            accent=ACCENT,
            icon_override=self._guild_icon(action_id, settings, ctx, state),
        )
        if state in ("muted", "deafened"):
            render.draw_badge(image, "#ef4444", width=3)
        elif state == "active":
            render.draw_badge(image, "#22c55e", width=3)
        elif state == "offline":
            from PIL import Image

            image.alpha_composite(Image.new("RGBA", image.size, (0, 0, 0, 140)))
        return image

    # -- GUI ---------------------------------------------------------------

    def get_dynamic_options(self, source, context=None):
        if source == "voice_channels":
            return _channel_options(self.channels)
        if source == "text_channels":
            return _channel_options(self.text_channels, prefix="#")
        return []


def _channel_options(channels: list[dict], prefix: str = "") -> list[dict]:
    """Auswahlliste ``Server › Kanal`` für die GUI."""
    return [
        {
            "value": c["id"],
            "label": f"{c['guild']} › {prefix}{c['name']}" if c["guild"] else f"{prefix}{c['name']}",
        }
        for c in channels
    ]


# --------------------------------------------------------------------------
# Serverlogos
# --------------------------------------------------------------------------


def _guild_icon_source(url: str) -> str:
    """Vereinheitlicht Discords CDN-URL auf ein PNG fester Größe.

    Die URL aus ``GET_GUILD`` kommt je nach Server als ``.webp`` oder
    ``.gif`` und in wechselnder Größe. Das CDN liefert dieselbe Datei unter
    jeder Endung aus, und PNG kann Pillow ohne Zusatzpaket lesen.
    """
    base = url.split("?", 1)[0]
    stem = base.rsplit(".", 1)[0]
    return f"{stem}.png?size={GUILD_ICON_PX}"


def _download_guild_icon(guild_id: str, url: str) -> Path:
    """Lädt das Logo, sofern es nicht schon im Cache liegt. Blockierend.

    Der Dateiname enthält Discords Icon-Hash — ändert ein Server sein Logo,
    entsteht dadurch von selbst eine neue Datei.
    """
    import urllib.request

    source = _guild_icon_source(url)
    name = source.split("?", 1)[0].rsplit("/", 1)[-1]
    target = GUILD_ICON_DIR / f"{guild_id}-{name}"
    if target.is_file():
        return target

    request = urllib.request.Request(source, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=15) as response:
        data = response.read()

    GUILD_ICON_DIR.mkdir(parents=True, exist_ok=True)
    # Erst daneben schreiben, dann umbenennen — ein abgebrochener Download
    # soll beim nächsten Start nicht als gültiger Cache-Eintrag gelten.
    tmp = target.with_suffix(".part")
    tmp.write_bytes(data)
    tmp.replace(target)
    return target


# --------------------------------------------------------------------------
# Token-Ablage — bewusst außerhalb der Config, die man exportieren kann
# --------------------------------------------------------------------------


def _load_token(client_id: str) -> str | None:
    try:
        data = json.loads(TOKEN_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if data.get("client_id") != client_id:
        return None
    return data.get("access_token") or None


def _store_token(client_id: str, token: str) -> None:
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(
        json.dumps({"client_id": client_id, "access_token": token}), encoding="utf-8"
    )
    os.chmod(TOKEN_FILE, 0o600)


def _clear_token() -> None:
    with contextlib.suppress(OSError):
        Path(TOKEN_FILE).unlink()
