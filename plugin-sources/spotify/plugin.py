"""Spotify-Steuerung über MPRIS.

Steuert den lokal laufenden Spotify-Client per D-Bus — ohne Zugangsdaten,
ohne OAuth, ohne Einrichtung. Jeder andere Player, der MPRIS unterstützt,
funktioniert genauso; einzustellen unter *Plugins → Spotify*.

Der Zustand wird nicht gepollt: Titelwechsel, Play/Pause, Shuffle und
Wiederholung kommen als D-Bus-Signal herein und zeichnen die betroffenen
Tasten sofort neu.

Für die Lautstärke gibt es zwei Wege. Spotify bietet über MPRIS keine
verlässliche Lautstärkeregelung an, deshalb läuft sie standardmäßig über den
PipeWire-Stream des Players — dieselbe Stellschraube wie im Systemmixer.
"""

from __future__ import annotations

import asyncio
import contextlib
import io
import re
import urllib.parse
import urllib.request
from pathlib import Path

from PIL import Image

from deckswitch.plugins.base import ActionPlugin

from mpris import LOOP_CYCLE, MprisPlayer

ACCENT = "#1db954"
RECONNECT_INTERVAL_S = 5.0

#: Was hinter ``spotify:<typ>:<id>`` stehen darf. Alles davon lässt sich
#: über ``OpenUri`` starten — die Taste heißt nur nach dem häufigsten Fall.
URI_TYPES = frozenset(
    {"playlist", "album", "track", "artist", "show", "episode", "collection"}
)

#: ``https://open.spotify.com/playlist/<id>?si=…`` — mit optionalem
#: Sprach-Segment (``/intl-de/``), das Spotify beim Kopieren einfügt.
SHARE_LINK = re.compile(
    r"open\.spotify\.com/(?:intl-[a-z-]+/)?([a-z]+)/([A-Za-z0-9]+)"
)


class SpotifyPlugin(ActionPlugin):
    def __init__(self, manifest, services):
        super().__init__(manifest, services)
        self.mpris = MprisPlayer(self._player_name())
        self._task: asyncio.Task | None = None
        self._art_cache: dict[str, Image.Image | None] = {}

    # ======================================================================
    # Lebenszyklus
    # ======================================================================

    async def setup(self):
        self.mpris.on_change(self._on_player_change)
        self._task = asyncio.create_task(self._connection_loop(), name="spotify-mpris")

    async def teardown(self):
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        await self.mpris.close()

    def on_plugin_config_changed(self, config):
        async def restart():
            await self.teardown()
            self.mpris = MprisPlayer(self._player_name())
            await self.setup()

        self.run_async(restart())

    async def _connection_loop(self):
        was_available = False
        while True:
            available = await self.mpris.connect()
            if available != was_available:
                was_available = available
                self.services.runtime.request_redraw()
                self.services.runtime.publish_plugin_status(self.manifest.id)
            await asyncio.sleep(RECONNECT_INTERVAL_S)

    def _on_player_change(self):
        """Kommt aus dem D-Bus-Signal — Tasten sofort auffrischen."""
        self.services.runtime.request_redraw()

    def _player_name(self) -> str:
        return (self.plugin_config.get("player") or "spotify").strip() or "spotify"

    def get_status(self):
        state = self.mpris.state
        if not state.available:
            return {
                "connected": False,
                "detail": f"{self._player_name()} läuft nicht",
            }
        playing = state.title or state.status
        return {"connected": True, "detail": playing}

    # ======================================================================
    # Eingaben
    # ======================================================================

    async def on_key_down(self, action_id, settings, ctx):
        await self._activate(action_id, settings, ctx)

    async def on_dial_push(self, action_id, settings, ctx):
        if action_id == "multimedia":
            await self.mpris.play_pause()
            return
        await self._activate(action_id, settings, ctx)

    async def on_dial_rotate(self, action_id, settings, delta, ctx):
        if not self.mpris.state.available:
            return

        if action_id == "volume":
            await self._change_volume(delta * float(ctx.setting("step", 5)))

        elif action_id == "multimedia":
            if ctx.setting("rotate", "track") == "volume":
                await self._change_volume(delta * float(ctx.setting("step", 5)))
            else:
                # Beim Blättern durch Titel zählt die Richtung, nicht die
                # Anzahl der Rasten — sonst überspringt ein Dreh zehn Lieder.
                await (self.mpris.next() if delta > 0 else self.mpris.previous())

        elif action_id == "repeat":
            await self._cycle_repeat(1 if delta > 0 else -1)

        elif action_id in ("next", "previous", "play_pause", "shuffle"):
            await (self.mpris.next() if delta > 0 else self.mpris.previous())

    async def _activate(self, action_id, settings, ctx):
        if not self.mpris.state.available:
            if not await self.mpris.connect():
                self.notify_info(f"{self._player_name()} läuft nicht")
                return

        if action_id in ("play_pause", "multimedia"):
            await self.mpris.play_pause()
        elif action_id == "next":
            await self.mpris.next()
        elif action_id == "previous":
            await self.mpris.previous()
        elif action_id == "shuffle":
            if not await self.mpris.set_shuffle(not self.mpris.state.shuffle):
                self.notify_error(
                    f"{self._player_name()} unterstützt keine Zufallswiedergabe über MPRIS"
                )
        elif action_id == "repeat":
            await self._cycle_repeat(1)
        elif action_id == "volume":
            await self._key_volume(ctx)
        elif action_id == "playlist":
            await self._open_uri(ctx)

        self.services.runtime.request_redraw()

    async def _open_uri(self, ctx) -> None:
        """Startet die eingestellte Playlist (oder was sonst verlinkt ist)."""
        uri = spotify_uri(ctx.setting("uri", ""))
        if uri is None:
            self.notify_error(
                "Kein gültiger Spotify-Link — in Spotify auf die Playlist "
                "rechtsklicken, Teilen → Link kopieren"
            )
            return

        # Vor dem Start gesetzt, damit die Playlist gleich gemischt beginnt.
        # Spotify behält den Modus über den Wechsel hinweg bei — nachgemessen,
        # weil ein Player ihn auch mit dem neuen Kontext überschreiben könnte.
        mode = ctx.setting("shuffle", "keep")
        if mode in ("on", "off") and not await self.mpris.set_shuffle(mode == "on"):
            self.notify_info(
                f"{self._player_name()} nimmt die Zufallswiedergabe über MPRIS nicht an"
            )

        if not await self.mpris.open_uri(uri):
            self.notify_error(f"{self._player_name()} hat '{uri}' nicht angenommen")

    async def _cycle_repeat(self, direction: int) -> None:
        try:
            position = LOOP_CYCLE.index(self.mpris.state.loop)
        except ValueError:
            position = 0
        target = LOOP_CYCLE[(position + direction) % len(LOOP_CYCLE)]
        if not await self.mpris.set_loop(target):
            self.notify_error(
                f"{self._player_name()} unterstützt keine Wiederholung über MPRIS"
            )

    async def _key_volume(self, ctx) -> None:
        step = float(ctx.setting("step", 5))
        mode = ctx.setting("direction", "up")
        if mode == "mute":
            await self._toggle_mute()
        else:
            await self._change_volume(step if mode == "up" else -step)

    # ======================================================================
    # Lautstärke — MPRIS oder PipeWire
    # ======================================================================

    def _use_pipewire(self) -> bool:
        return bool(self.plugin_config.get("volume_via_pipewire", True))

    def _stream(self) -> dict | None:
        """Der PipeWire-Stream des Players, falls er gerade Ton ausgibt."""
        needle = self._player_name().lower()
        for stream in self.services.audio.list_streams():
            if needle in stream["name"].lower():
                return stream
        return None

    async def _change_volume(self, delta_percent: float) -> None:
        if self._use_pipewire():
            stream = self._stream()
            if stream is not None:
                await self._in_thread(
                    self.services.audio.change_stream_volume, stream["index"], delta_percent
                )
                self.services.runtime.request_redraw()
                return

        # Kein Stream (Player still) oder MPRIS gewünscht.
        current = self.mpris.state.volume
        if current is None:
            await self.mpris.refresh()
            current = self.mpris.state.volume
        if current is None:
            self.notify_error("Lautstärke lässt sich für diesen Player nicht regeln")
            return
        await self.mpris.set_volume(current + delta_percent / 100)
        self.services.runtime.request_redraw()

    async def _toggle_mute(self) -> None:
        stream = self._stream() if self._use_pipewire() else None
        if stream is not None:
            await self._in_thread(self.services.audio.toggle_stream_mute, stream["index"])
            self.services.runtime.request_redraw()
            return

        # Ohne PipeWire-Stream bleibt nur Pausieren als Ersatz für „still“.
        await self.mpris.play_pause()

    async def _in_thread(self, function, *args):
        """Blockierende Audio-Aufrufe aus dem Loop heraushalten."""
        return await asyncio.get_running_loop().run_in_executor(
            None, lambda: function(*args)
        )

    def _volume_level(self) -> float | None:
        if self._use_pipewire():
            stream = self._stream()
            if stream is not None:
                return stream["volume"]
        return self.mpris.state.volume

    def _muted(self) -> bool:
        if self._use_pipewire():
            stream = self._stream()
            if stream is not None:
                return bool(stream["muted"])
        return False

    # ======================================================================
    # Zustand und Darstellung
    # ======================================================================

    def get_state(self, action_id, settings, ctx):
        state = self.mpris.state
        if not state.available:
            return "offline"

        if action_id in ("play_pause", "multimedia"):
            return {"Playing": "playing", "Paused": "paused"}.get(state.status, "stopped")
        if action_id == "shuffle":
            return "on" if state.shuffle else "off"
        if action_id == "repeat":
            return {"Playlist": "playlist", "Track": "track"}.get(state.loop, "off")
        if action_id == "volume":
            return "muted" if self._muted() else "default"
        return "ready"

    def get_label(self, action_id, settings, ctx):
        state = self.mpris.state
        if ctx.appearance.label_text or not state.available:
            return None

        if action_id == "play_pause":
            mode = ctx.setting("show_track", "title")
            if mode == "title":
                return state.title or None
            if mode == "artist":
                return state.artist or None
            if mode == "both" and (state.title or state.artist):
                return f"{state.title}\n{state.artist}".strip()
            return None

        if action_id == "repeat":
            return {"Playlist": "Playlist", "Track": "Titel"}.get(state.loop, "Aus")
        return None

    def on_tick(self, action_id, settings, ctx):
        """Nur die Lautstärke braucht Nachsehen — der Rest kommt per Signal."""
        if action_id not in ("volume", "multimedia"):
            return
        level = self._volume_level()
        signature = (round(level, 3) if level is not None else None, self._muted())
        if ctx.scratch.get("volume_signature") != signature:
            ctx.scratch["volume_signature"] = signature
            ctx.request_redraw()

    def render(self, action_id, settings, ctx):
        render = self.services.render
        state = self.get_state(action_id, settings, ctx)

        if action_id == "multimedia" and ctx.input_type == "dial":
            return self._render_multimedia(settings, ctx, state)

        image = render.render_slot(
            ctx,
            state=state,
            label_override=self.get_label(action_id, settings, ctx),
            accent=ACCENT,
        )

        if action_id == "volume":
            level = self._volume_level()
            if level is not None:
                width, height = ctx.size
                render.draw_bar(
                    image,
                    level,
                    box=(10, height - 12, width - 10, height - 6),
                    color="#6b7280" if self._muted() else ctx.setting("bar_color", ACCENT),
                )
        elif state == "playing" and action_id in ("play_pause", "shuffle", "repeat"):
            render.draw_badge(image, ACCENT, width=3)
        elif state in ("on", "playlist", "track"):
            render.draw_badge(image, ACCENT, width=3)

        if state == "offline":
            image.alpha_composite(Image.new("RGBA", image.size, (0, 0, 0, 140)))
        return image

    def _render_multimedia(self, settings, ctx, state):
        """Segment-Layout: Albumbild als Hintergrund, Titel und Künstler."""
        render = self.services.render
        player = self.mpris.state
        width, height = ctx.size

        art = self._album_art(ctx) if ctx.setting("show_art", True) else None
        if art is not None:
            image = _cover_blur(art, ctx.size)
        else:
            image = render.background(ctx.size, ctx.appearance, accent=ACCENT)

        icon = self.services.icons.resolve(
            ctx.appearance.icon_for_state(state),
            size=max(24, min(height - 40, round(min(ctx.size) * ctx.appearance.icon_size / 100))),
            fallback_name="player-pause" if state == "playing" else "player-play",
            fallback_set=self.services.config.app.active_iconset,
            color=ctx.appearance.label_color,
        )
        image.alpha_composite(icon, (10, (height - icon.height) // 2))

        text_left = 10 + icon.width + 10
        if player.available:
            render.draw_text_at(
                image,
                player.title or "—",
                x=text_left,
                y=14,
                size=ctx.appearance.label_size,
                color=ctx.appearance.label_color,
                max_width=width - text_left - 12,
            )
            render.draw_text_at(
                image,
                player.artist or "",
                x=text_left,
                y=14 + ctx.appearance.label_size + 6,
                size=max(9, ctx.appearance.label_size - 3),
                color="#c7c7d1",
                max_width=width - text_left - 12,
            )

        if ctx.setting("rotate", "track") == "volume":
            level = self._volume_level()
            if level is not None:
                render.draw_bar(
                    image,
                    level,
                    box=(text_left, height - 18, width - 12, height - 12),
                    color=ACCENT,
                )
        return image

    def _album_art(self, ctx) -> Image.Image | None:
        """Albumbild laden — nur lokale Dateien und Spotifys Bild-CDN."""
        url = self.mpris.state.art_url
        if not url:
            return None
        if url in self._art_cache:
            return self._art_cache[url]

        image: Image.Image | None = None
        try:
            parsed = urllib.parse.urlparse(url)
            if parsed.scheme == "file":
                path = Path(urllib.parse.unquote(parsed.path))
                if path.is_file():
                    image = Image.open(path).convert("RGBA")
            elif parsed.scheme == "https" and parsed.netloc.endswith("scdn.co"):
                # Spotify liefert die Cover über sein eigenes CDN.
                with urllib.request.urlopen(url, timeout=4) as response:
                    image = Image.open(io.BytesIO(response.read())).convert("RGBA")
        except Exception as exc:
            self.log.debug("Albumbild nicht ladbar (%s): %s", url, exc)
            image = None

        # Auch Fehlschläge merken, damit nicht bei jedem Frame neu geladen wird.
        self._art_cache[url] = image
        if len(self._art_cache) > 30:
            self._art_cache.pop(next(iter(self._art_cache)))
        return image

    # ======================================================================
    # GUI
    # ======================================================================

    def get_dynamic_options(self, source, context=None):
        if source != "players":
            return []

        loop = getattr(self.services.runtime, "_loop", None)
        found: list[str] = []
        if loop is not None:
            try:
                found = asyncio.run_coroutine_threadsafe(
                    self.mpris.list_players(), loop
                ).result(timeout=5)
            except Exception as exc:
                self.log.debug("Player-Liste nicht abrufbar: %s", exc)

        # Spotify immer anbieten, auch wenn es gerade nicht läuft.
        if "spotify" not in [p.lower() for p in found]:
            found.insert(0, "spotify")
        return [{"value": name, "label": name} for name in found]

    async def gui_command(self, command, payload):
        if command == "status":
            state = self.mpris.state
            return {"player": self._player_name(), **state.as_dict()}
        raise NotImplementedError(f"Spotify kennt kein Kommando '{command}'")


def spotify_uri(value: str) -> str | None:
    """Macht aus dem, was der User einträgt, eine ``spotify:``-Adresse.

    Aus Spotify heraus kopiert man einen Web-Link; die URI bekommt man nur
    über einen versteckten Umweg. Beides wird deshalb angenommen — und der
    ``?si=``-Anhang, den Spotify an geteilte Links hängt, fällt weg.
    """
    text = (value or "").strip()
    if not text:
        return None

    if text.startswith("spotify:"):
        parts = text.split("?", 1)[0].split(":")
        if len(parts) >= 3 and parts[1] in URI_TYPES and parts[2]:
            return ":".join(parts)
        return None

    match = SHARE_LINK.search(text)
    if match is not None and match.group(1) in URI_TYPES:
        return f"spotify:{match.group(1)}:{match.group(2)}"
    return None


def _cover_blur(art: Image.Image, size: tuple[int, int]) -> Image.Image:
    """Albumbild als Hintergrund: formatfüllend, abgedunkelt.

    Abgedunkelt, weil sonst der Text darüber auf hellen Covern untergeht.
    """
    from PIL import ImageEnhance, ImageFilter

    target_w, target_h = size
    scale = max(target_w / art.width, target_h / art.height)
    scaled = art.resize(
        (max(1, round(art.width * scale)), max(1, round(art.height * scale))),
        Image.LANCZOS,
    )
    left = (scaled.width - target_w) // 2
    top = (scaled.height - target_h) // 2
    cropped = scaled.crop((left, top, left + target_w, top + target_h))
    cropped = cropped.filter(ImageFilter.GaussianBlur(1.2))
    cropped = ImageEnhance.Brightness(cropped).enhance(0.45)
    return cropped.convert("RGBA")
