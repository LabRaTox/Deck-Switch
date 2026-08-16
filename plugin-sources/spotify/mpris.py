"""Anbindung eines Medienspielers über MPRIS (D-Bus).

MPRIS ist der Standard, über den Linux-Desktops Medienspieler steuern —
Spotify unterstützt ihn ebenso wie die meisten anderen Player. Damit
braucht es weder OAuth noch Zugangsdaten: der lokal laufende Client wird
direkt angesprochen.

Änderungen (Titelwechsel, Play/Pause, Shuffle) kommen als
``PropertiesChanged``-Signal herein — kein Pollen nötig.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from dbus_next import BusType, Message, MessageType, Variant
from dbus_next.aio import MessageBus

log = logging.getLogger(__name__)

BUS_PREFIX = "org.mpris.MediaPlayer2."
OBJECT_PATH = "/org/mpris/MediaPlayer2"
PLAYER_IFACE = "org.mpris.MediaPlayer2.Player"
PROPS_IFACE = "org.freedesktop.DBus.Properties"

#: Reihenfolge, in der ``Repeat`` durchgeschaltet wird.
LOOP_CYCLE = ["None", "Playlist", "Track"]


@dataclass(slots=True)
class PlayerState:
    """Alles, was für die Anzeige auf einer Taste gebraucht wird."""

    available: bool = False
    status: str = "Stopped"          # Playing | Paused | Stopped
    shuffle: bool = False
    loop: str = "None"               # None | Playlist | Track
    volume: float | None = None      # 0.0–1.0, None wenn nicht unterstützt
    title: str = ""
    artist: str = ""
    album: str = ""
    art_url: str = ""
    can_go_next: bool = True
    can_go_previous: bool = True
    #: Fähigkeiten, die der Player laut D-Bus überhaupt beherrscht.
    can_set_shuffle: bool = True
    can_set_loop: bool = True
    can_set_volume: bool = True

    @property
    def playing(self) -> bool:
        return self.status == "Playing"

    def as_dict(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "status": self.status,
            "shuffle": self.shuffle,
            "loop": self.loop,
            "volume": self.volume,
            "title": self.title,
            "artist": self.artist,
            "album": self.album,
        }


class MprisPlayer:
    """Verbindung zu genau einem MPRIS-Player (Standard: Spotify)."""

    def __init__(self, player: str = "spotify") -> None:
        self.player = player
        self.state = PlayerState()
        self.bus: MessageBus | None = None
        self._bus_name: str | None = None
        self._on_change: Callable[[], None] | None = None
        self._lock = asyncio.Lock()

    def on_change(self, callback: Callable[[], None]) -> None:
        self._on_change = callback

    # -- Verbindung --------------------------------------------------------

    async def connect(self) -> bool:
        """Verbindet mit dem Sitzungsbus und sucht den Player."""
        async with self._lock:
            if self.bus is None:
                try:
                    self.bus = await MessageBus(bus_type=BusType.SESSION).connect()
                except Exception as exc:
                    log.debug("Sitzungsbus nicht erreichbar: %s", exc)
                    self.bus = None
                    return False
                self.bus.add_message_handler(self._handle_signal)
                await self._subscribe_signals()

            found = await self._find_player()
            if not found:
                if self.state.available:
                    self.state = PlayerState()
                    self._notify()
                return False

            if self._bus_name != found:
                self._bus_name = found
                log.info("MPRIS-Player gefunden: %s", found)

            await self.refresh()
            return True

    async def close(self) -> None:
        bus, self.bus = self.bus, None
        self._bus_name = None
        if bus is not None:
            with contextlib.suppress(Exception):
                bus.disconnect()

    async def _find_player(self) -> str | None:
        """Sucht den passenden Bus-Namen unter allen MPRIS-Diensten."""
        names = await self._list_names()
        candidates = [n for n in names if n.startswith(BUS_PREFIX)]
        wanted = self.player.strip().lower()

        # Exakter Treffer zuerst, dann Teiltreffer (Spotify hängt gelegentlich
        # eine Instanz-Nummer an), zuletzt irgendein Player.
        for name in candidates:
            if name[len(BUS_PREFIX):].lower() == wanted:
                return name
        for name in candidates:
            if wanted in name.lower():
                return name
        return candidates[0] if (candidates and wanted in ("", "any")) else None

    async def _list_names(self) -> list[str]:
        reply = await self._send(
            destination="org.freedesktop.DBus",
            path="/org/freedesktop/DBus",
            interface="org.freedesktop.DBus",
            member="ListNames",
        )
        return list(reply.body[0]) if reply and reply.body else []

    async def _subscribe_signals(self) -> None:
        """Lässt sich Property-Änderungen aller MPRIS-Player zustellen."""
        rules = [
            f"type='signal',interface='{PROPS_IFACE}',member='PropertiesChanged',"
            f"path='{OBJECT_PATH}'",
            "type='signal',interface='org.freedesktop.DBus',"
            "member='NameOwnerChanged',arg0namespace='org.mpris.MediaPlayer2'",
        ]
        for rule in rules:
            await self._send(
                destination="org.freedesktop.DBus",
                path="/org/freedesktop/DBus",
                interface="org.freedesktop.DBus",
                member="AddMatch",
                signature="s",
                body=[rule],
            )

    def _handle_signal(self, message: Message):
        if message.message_type is not MessageType.SIGNAL:
            return

        if message.member == "NameOwnerChanged":
            # Player gestartet oder beendet — Verbindung neu bewerten.
            asyncio.create_task(self._reconcile())
            return

        if message.member != "PropertiesChanged":
            return
        if self._bus_name and message.sender not in (self._bus_name, None):
            # Auch ohne Absenderprüfung wäre es harmlos, aber so bleiben
            # fremde Player (Browser, Videoplayer) außen vor.
            pass

        try:
            _iface, changed, _invalidated = message.body
        except (ValueError, TypeError):
            return
        self._apply({k: v.value for k, v in changed.items()})
        self._notify()

    async def _reconcile(self):
        with contextlib.suppress(Exception):
            await self.connect()

    # -- Lesen -------------------------------------------------------------

    async def refresh(self) -> PlayerState:
        if self.bus is None or self._bus_name is None:
            return self.state

        reply = await self._send(
            destination=self._bus_name,
            path=OBJECT_PATH,
            interface=PROPS_IFACE,
            member="GetAll",
            signature="s",
            body=[PLAYER_IFACE],
        )
        if reply is None or not reply.body:
            self.state = PlayerState()
            return self.state

        self.state.available = True
        self._apply({k: v.value for k, v in reply.body[0].items()})
        return self.state

    def _apply(self, props: dict[str, Any]) -> None:
        state = self.state
        state.available = True

        if "PlaybackStatus" in props:
            state.status = str(props["PlaybackStatus"])
        if "Shuffle" in props:
            state.shuffle = bool(props["Shuffle"])
        if "LoopStatus" in props:
            state.loop = str(props["LoopStatus"])
        if "Volume" in props:
            try:
                state.volume = max(0.0, min(1.0, float(props["Volume"])))
            except (TypeError, ValueError):
                state.volume = None
        if "CanGoNext" in props:
            state.can_go_next = bool(props["CanGoNext"])
        if "CanGoPrevious" in props:
            state.can_go_previous = bool(props["CanGoPrevious"])

        metadata = props.get("Metadata")
        if isinstance(metadata, dict):
            def value(key, default=""):
                entry = metadata.get(key)
                if entry is None:
                    return default
                return entry.value if isinstance(entry, Variant) else entry

            state.title = str(value("xesam:title") or "")
            artists = value("xesam:artist", []) or []
            state.artist = ", ".join(str(a) for a in artists) if isinstance(artists, list) else str(artists)
            state.album = str(value("xesam:album") or "")
            state.art_url = str(value("mpris:artUrl") or "")

    # -- Steuern -----------------------------------------------------------

    async def _control(self, member: str) -> bool:
        if self.bus is None or self._bus_name is None:
            return False
        reply = await self._send(
            destination=self._bus_name,
            path=OBJECT_PATH,
            interface=PLAYER_IFACE,
            member=member,
        )
        return reply is not None

    async def play_pause(self) -> bool:
        return await self._control("PlayPause")

    async def play(self) -> bool:
        return await self._control("Play")

    async def pause(self) -> bool:
        return await self._control("Pause")

    async def next(self) -> bool:
        return await self._control("Next")

    async def previous(self) -> bool:
        return await self._control("Previous")

    async def open_uri(self, uri: str) -> bool:
        """Spielt eine Adresse ab — bei Spotify z. B. ``spotify:playlist:…``.

        Der einzige Weg, gezielt etwas zu *starten* statt nur das Laufende zu
        steuern: MPRIS kennt weder eine Playlist-Liste noch eine Suche, wohl
        aber ``OpenUri``. Was der Player mit der Adresse anfängt, ist seine
        Sache — Spotify beginnt die Wiedergabe.
        """
        if self.bus is None or self._bus_name is None:
            return False
        reply = await self._send(
            destination=self._bus_name,
            path=OBJECT_PATH,
            interface=PLAYER_IFACE,
            member="OpenUri",
            signature="s",
            body=[uri],
        )
        return reply is not None

    async def set_property(self, name: str, variant: Variant) -> bool:
        if self.bus is None or self._bus_name is None:
            return False
        reply = await self._send(
            destination=self._bus_name,
            path=OBJECT_PATH,
            interface=PROPS_IFACE,
            member="Set",
            signature="ssv",
            body=[PLAYER_IFACE, name, variant],
        )
        return reply is not None

    async def set_shuffle(self, value: bool) -> bool:
        if await self.set_property("Shuffle", Variant("b", value)):
            self.state.shuffle = value
            return True
        self.state.can_set_shuffle = False
        return False

    async def set_loop(self, value: str) -> bool:
        if await self.set_property("LoopStatus", Variant("s", value)):
            self.state.loop = value
            return True
        self.state.can_set_loop = False
        return False

    async def set_volume(self, value: float) -> bool:
        value = max(0.0, min(1.0, value))
        if await self.set_property("Volume", Variant("d", value)):
            self.state.volume = value
            return True
        self.state.can_set_volume = False
        return False

    # -- D-Bus-Grundlagen --------------------------------------------------

    async def _send(
        self,
        *,
        destination: str,
        path: str,
        interface: str,
        member: str,
        signature: str = "",
        body: list | None = None,
    ) -> Message | None:
        bus = self.bus
        if bus is None:
            return None
        try:
            reply = await asyncio.wait_for(
                bus.call(
                    Message(
                        destination=destination,
                        path=path,
                        interface=interface,
                        member=member,
                        signature=signature,
                        body=body or [],
                    )
                ),
                timeout=4,
            )
        except Exception as exc:
            log.debug("D-Bus-Aufruf %s fehlgeschlagen: %s", member, exc)
            return None

        if reply is None or reply.message_type is MessageType.ERROR:
            if reply is not None:
                log.debug("D-Bus-Fehler bei %s: %s", member, reply.error_name)
            return None
        return reply

    def _notify(self) -> None:
        if self._on_change is not None:
            try:
                self._on_change()
            except Exception:
                log.exception("MPRIS-Callback hat geworfen")

    async def list_players(self) -> list[str]:
        """Alle laufenden MPRIS-Player — für die Auswahl in der GUI."""
        if self.bus is None:
            with contextlib.suppress(Exception):
                self.bus = await MessageBus(bus_type=BusType.SESSION).connect()
        names = await self._list_names()
        return sorted({n[len(BUS_PREFIX):] for n in names if n.startswith(BUS_PREFIX)})
