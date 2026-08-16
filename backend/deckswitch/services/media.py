"""Der gerade laufende Medienspieler — über MPRIS.

Anders als das Spotify-Plugin, das *einen* Player fest im Blick hat, geht es
hier um „was gerade spielt". Genau das erwartet man von einer
Multimedia-Taste: Sie soll den Browser pausieren, wenn dort ein Video läuft,
und den Musikspieler, wenn dort Musik läuft.

Findet sich gar kein MPRIS-Player, fallen die Aktionen auf die
Multimedia-Tasten einer Tastatur zurück (über :mod:`.input`). Das ist genau
der Weg, den auch eine echte Tastatur nimmt — der Desktop verteilt die Taste
dann selbst.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass
from typing import Any

from dbus_next import BusType, Message, MessageType, Variant
from dbus_next.aio import MessageBus

log = logging.getLogger(__name__)

BUS_PREFIX = "org.mpris.MediaPlayer2."
OBJECT_PATH = "/org/mpris/MediaPlayer2"
PLAYER_IFACE = "org.mpris.MediaPlayer2.Player"
PROPS_IFACE = "org.freedesktop.DBus.Properties"

#: Player, die zwar mitreden, aber nie gemeint sind: Die
#: Browser-Integration von Plasma spiegelt nur, was der Browser ohnehin
#: meldet, und kdeconnect steuert das Telefon.
IGNORED = ("plasma-browser-integration", "kdeconnect")

#: Multimedia-Taste je Kommando — der Rückfallweg ohne MPRIS.
FALLBACK_KEYS = {
    "play_pause": "KEY_PLAYPAUSE",
    "play": "KEY_PLAY",
    "pause": "KEY_PAUSECD",
    "stop": "KEY_STOPCD",
    "next": "KEY_NEXTSONG",
    "previous": "KEY_PREVIOUSSONG",
}


@dataclass(slots=True)
class MediaState:
    """Was für die Anzeige auf einer Taste reicht."""

    available: bool = False
    playing: bool = False
    status: str = "Stopped"
    title: str = ""
    artist: str = ""
    player: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "playing": self.playing,
            "status": self.status,
            "title": self.title,
            "artist": self.artist,
            "player": self.player,
        }


class MediaService:
    """Steuert den aktiven Player und kennt dessen Zustand."""

    def __init__(self) -> None:
        self.bus: MessageBus | None = None
        self.state = MediaState()
        self._lock = asyncio.Lock()
        self._input = None

    def bind_input(self, input_service) -> None:
        """Der Rückfallweg über Multimedia-Tasten braucht die Tastatur."""
        self._input = input_service

    # -- Verbindung --------------------------------------------------------

    async def _connect(self) -> MessageBus | None:
        if self.bus is not None:
            return self.bus
        async with self._lock:
            if self.bus is None:
                try:
                    self.bus = await MessageBus(bus_type=BusType.SESSION).connect()
                except Exception as exc:
                    log.debug("Sitzungsbus nicht erreichbar: %s", exc)
                    return None
        return self.bus

    async def close(self) -> None:
        bus, self.bus = self.bus, None
        if bus is not None:
            with contextlib.suppress(Exception):
                bus.disconnect()

    # -- Player finden -----------------------------------------------------

    async def list_players(self) -> list[str]:
        """Alle laufenden Player — für die Auswahlliste in der GUI."""
        names = await self._list_names()
        return sorted(
            {
                name[len(BUS_PREFIX) :].split(".instance")[0]
                for name in names
                if name.startswith(BUS_PREFIX)
                and not any(ignored in name for ignored in IGNORED)
            }
        )

    async def _list_names(self) -> list[str]:
        reply = await self._send(
            destination="org.freedesktop.DBus",
            path="/org/freedesktop/DBus",
            interface="org.freedesktop.DBus",
            member="ListNames",
        )
        return list(reply.body[0]) if reply and reply.body else []

    async def _pick(self, preferred: str = "") -> str | None:
        """Der Player, den eine Taste meint.

        Ohne Vorgabe gewinnt der, der gerade *spielt* — sonst wäre nicht
        vorhersehbar, welchen von drei offenen Programmen die Taste trifft.
        Spielt keiner, bleibt der erste pausierte übrig, damit „weiter" auch
        aus dem Stand funktioniert.
        """
        candidates = [
            name
            for name in await self._list_names()
            if name.startswith(BUS_PREFIX)
            and not any(ignored in name for ignored in IGNORED)
        ]
        if not candidates:
            return None

        if preferred:
            wanted = preferred.strip().lower()
            for name in candidates:
                if name[len(BUS_PREFIX) :].lower().startswith(wanted):
                    return name
            return None

        paused: str | None = None
        for name in candidates:
            status = await self._get(name, "PlaybackStatus")
            if status == "Playing":
                return name
            if status == "Paused" and paused is None:
                paused = name
        return paused or candidates[0]

    # -- Lesen -------------------------------------------------------------

    async def refresh(self, preferred: str = "") -> MediaState:
        name = await self._pick(preferred)
        if name is None:
            self.state = MediaState()
            return self.state

        reply = await self._send(
            destination=name,
            path=OBJECT_PATH,
            interface=PROPS_IFACE,
            member="GetAll",
            signature="s",
            body=[PLAYER_IFACE],
        )
        if reply is None or not reply.body:
            self.state = MediaState()
            return self.state

        props = {k: v.value for k, v in reply.body[0].items()}
        status = str(props.get("PlaybackStatus", "Stopped"))
        title = artist = ""
        metadata = props.get("Metadata")
        if isinstance(metadata, dict):
            title = str(_unwrap(metadata.get("xesam:title")) or "")
            artists = _unwrap(metadata.get("xesam:artist")) or []
            artist = (
                ", ".join(str(a) for a in artists)
                if isinstance(artists, list)
                else str(artists)
            )

        self.state = MediaState(
            available=True,
            playing=status == "Playing",
            status=status,
            title=title,
            artist=artist,
            player=name[len(BUS_PREFIX) :].split(".instance")[0],
        )
        return self.state

    async def _get(self, destination: str, name: str) -> Any:
        reply = await self._send(
            destination=destination,
            path=OBJECT_PATH,
            interface=PROPS_IFACE,
            member="Get",
            signature="ss",
            body=[PLAYER_IFACE, name],
        )
        if reply is None or not reply.body:
            return None
        value = reply.body[0]
        return value.value if isinstance(value, Variant) else value

    # -- Steuern -----------------------------------------------------------

    async def control(self, command: str, *, player: str = "") -> bool:
        """Führt ``play_pause``, ``next``, … aus. ``False`` = nichts erreicht."""
        member = {
            "play_pause": "PlayPause",
            "play": "Play",
            "pause": "Pause",
            "stop": "Stop",
            "next": "Next",
            "previous": "Previous",
        }.get(command)
        if member is None:
            raise ValueError(f"Unbekanntes Medienkommando: {command}")

        name = await self._pick(player)
        if name is not None:
            reply = await self._send(
                destination=name,
                path=OBJECT_PATH,
                interface=PLAYER_IFACE,
                member=member,
            )
            if reply is not None:
                return True

        return self._fallback(command)

    def _fallback(self, command: str) -> bool:
        """Kein Player erreichbar — die Multimedia-Taste selbst schicken."""
        key = FALLBACK_KEYS.get(command)
        if key is None or self._input is None:
            return False
        try:
            self._input.send_combo(key)
        except Exception as exc:
            log.debug("Multimedia-Taste '%s' nicht sendbar: %s", key, exc)
            return False
        return True

    # -- D-Bus -------------------------------------------------------------

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
        bus = await self._connect()
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
            return None
        return reply


def _unwrap(value: Any) -> Any:
    return value.value if isinstance(value, Variant) else value
