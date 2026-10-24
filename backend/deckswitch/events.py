"""Ereignis-Bus zwischen Runtime, Plugins und GUI.

Das Backend mischt zwangsläufig Threads und asyncio: die ``streamdeck``-
Bibliothek liefert Tasten-/Dial-Events aus einem eigenen Reader-Thread,
``pactl subscribe`` läuft als Subprozess-Reader, der HTTP-/WebSocket-Server
dagegen im asyncio-Loop. Der Bus ist deshalb von beiden Seiten benutzbar:
``publish`` (nur aus dem Loop) und ``publish_threadsafe`` (von überall).
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import contextlib
import functools
import logging
from collections.abc import AsyncIterator, Callable
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


#: So lange wartet ein Arbeitsthread höchstens darauf, dass der Loop seinen
#: Aufruf erledigt hat. Beim Herunterfahren kann der Loop schon stehen.
IM_LOOP_WARTEN_S = 10.0


def im_loop(
    loop: asyncio.AbstractEventLoop | None,
    fn: Callable[..., Any],
    *args: Any,
    warten: bool = True,
    **kwargs: Any,
) -> Any:
    """Führt ``fn`` im Event-Loop aus, auch wenn der Aufruf aus einem Thread kommt.

    Synchrone Plugin-Hooks laufen im Executor. Was sie anstoßen (blättern,
    speichern, Fehler melden), verändert aber Zustand, der dem Loop gehört:
    ``asyncio.Event`` und Queues sind nicht threadsicher und wecken den
    Loop von außen nicht einmal auf. Läuft der Aufruf schon im Loop, oder
    läuft gar keiner, wird ``fn`` direkt gerufen.

    Mit ``warten`` blockiert der Thread, bis das Ergebnis da ist.
    """
    if loop is None or loop.is_closed() or not loop.is_running():
        return fn(*args, **kwargs)
    try:
        laufend = asyncio.get_running_loop()
    except RuntimeError:
        laufend = None
    if laufend is loop:
        return fn(*args, **kwargs)

    aufruf = functools.partial(fn, *args, **kwargs)
    if not warten:
        loop.call_soon_threadsafe(aufruf)
        return None

    ergebnis: concurrent.futures.Future = concurrent.futures.Future()

    def ausfuehren() -> None:
        try:
            ergebnis.set_result(aufruf())
        except BaseException as exc:  # noqa: BLE001 - geht an den Aufrufer
            ergebnis.set_exception(exc)

    loop.call_soon_threadsafe(ausfuehren)
    try:
        return ergebnis.result(timeout=IM_LOOP_WARTEN_S)
    except concurrent.futures.TimeoutError:
        log.warning("Aufruf von %s im Loop kam nicht zurück", getattr(fn, "__name__", fn))
        return None


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
        """Senden. Aus einem fremden Thread geht es über den Loop."""
        loop = self._loop
        if loop is not None and loop.is_running() and not loop.is_closed():
            try:
                laufend = asyncio.get_running_loop()
            except RuntimeError:
                laufend = None
            if laufend is not loop:
                loop.call_soon_threadsafe(functools.partial(self._verteilen, type_, data))
                return
        self._verteilen(type_, data)

    def _verteilen(self, type_: str, data: dict[str, Any]) -> None:
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
        loop.call_soon_threadsafe(functools.partial(self._verteilen, type_, data))

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
