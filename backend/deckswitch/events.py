"""Ereignis-Bus zwischen Runtime, Plugins und GUI.

Das Backend mischt zwangsläufig Threads und asyncio: die ``streamdeck``-
Bibliothek liefert Tasten-/Dial-Events aus einem eigenen Reader-Thread,
``pactl subscribe`` läuft als Subprozess-Reader, der HTTP-/WebSocket-Server
dagegen im asyncio-Loop. Der Bus ist deshalb von beiden Seiten benutzbar:
``publish`` (nur aus dem Loop) und ``publish_threadsafe`` (von überall).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)

#: Ereignistypen, die auch die GUI sieht.
EVT_CONFIG_CHANGED = "config_changed"
EVT_PAGE_CHANGED = "page_changed"
EVT_DEVICE_STATE = "device_state"
#: Etwas an einem einzelnen Deck hat sich geändert, ohne dass die
#: Verbindung betroffen wäre — etwa der aktive Eintrag eines Dial-Stacks.
EVT_DECK_STATE = "deck_state"
#: Ein Deck ist dazugekommen oder verschwunden.
EVT_DECKS_CHANGED = "decks_changed"
#: Eine Kachel eines virtuellen Decks hat ein neues Bild. Das Overlay holt
#: sich daraufhin genau diese eine — statt im Takt alles abzufragen.
EVT_DECK_IMAGE = "deck_image"
EVT_PLUGIN_ERROR = "plugin_error"
EVT_PLUGIN_STATE = "plugin_state"
EVT_KEY_PREVIEW = "key_preview"
EVT_INSTALL_REQUEST = "install_request"
EVT_LOG = "log"


@dataclass(slots=True)
class Event:
    type: str
    data: dict[str, Any] = field(default_factory=dict)


class EventBus:
    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue[Event]] = set()
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    # -- Senden ------------------------------------------------------------

    def publish(self, type_: str, **data: Any) -> None:
        """Aus dem asyncio-Loop heraus senden."""
        event = Event(type_, data)
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                # Ein hängender Client darf das Backend nicht ausbremsen.
                log.warning("Event-Queue voll, verwerfe %s", type_)

    def publish_threadsafe(self, type_: str, **data: Any) -> None:
        """Aus einem beliebigen Thread senden."""
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        loop.call_soon_threadsafe(lambda: self.publish(type_, **data))

    # -- Empfangen ---------------------------------------------------------

    @contextlib.asynccontextmanager
    async def subscribe(self, maxsize: int = 256) -> AsyncIterator[asyncio.Queue[Event]]:
        queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=maxsize)
        self._subscribers.add(queue)
        try:
            yield queue
        finally:
            self._subscribers.discard(queue)

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)
