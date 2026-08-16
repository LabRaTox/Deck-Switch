"""Ein einzelnes angeschlossenes Deck und alles, was ihm allein gehört.

Mehrere Decks laufen nebeneinander, und praktisch jeder Zustand ist dabei
*pro Gerät* zu führen: die aktuelle Seite, die gedrückten Tasten, der
Bildschirmschoner, das Abdunkeln, laufende Multi-Aktionen, der Dial-Stack.
Genau das steckt in dieser Klasse.

Geteilt bleibt, was zwischen Geräten sinnvoll geteilt wird: Config, Plugins,
Icons, Audio und die Systemdienste. Die liegen in der :class:`Runtime`, die
diese Sitzungen hält.

Für Plugins ändert sich dadurch nichts: Sie bekommen über ``ctx`` eine Sicht
auf *ihr* Deck (:class:`DeckView`), die dieselben Methoden anbietet wie die
Runtime — ``navigate``, ``step_page``, ``request_redraw``. Ein Plugin, das
auf einer Taste des zweiten Decks liegt, blättert damit auch dort.
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import logging
import time
import traceback
from pathlib import Path
from typing import TYPE_CHECKING, Any

from PIL import Image, ImageDraw

from . import events as ev
from . import paths
from .config import (
    Appearance,
    Background,
    DeckBinding,
    DeviceSettings,
    Page,
    Profile,
    Slot,
    Step,
    TouchWallpaper,
)
from .device import StreamDeckDevice
from .plugins.base import Services, SlotContext
from .services import screensaver, wallpaper

if TYPE_CHECKING:  # pragma: no cover
    from .runtime import Runtime

log = logging.getLogger(__name__)

#: Pause zwischen zwei Teilstrecken, ab der eine neue Wischgeste beginnt.
SWIPE_GESTURE_GAP_S = 0.4

#: Sperre nach einem ausgelösten Seitenwechsel, damit die verbleibenden
#: Teilstrecken desselben Wischs nicht gleich mehrere Seiten weiterblättern.
SWIPE_COOLDOWN_S = 0.6

#: Ersatz-Hintergrund für Segmente, unter denen ein Seitenbild liegt.
TRANSPARENT_BACKGROUND = Background(kind="solid", color="#00000000")


def uses_default_background(appearance: Appearance) -> bool:
    """Hat für diese Belegung *niemand* einen Hintergrund gewählt?

    Nur dann darf das Seitenbild durchscheinen. Verglichen wird gegen den
    Auslieferungszustand — wer Farbe, Verlauf oder Bild eingestellt hat,
    meinte das so, und dem wird nichts untergeschoben.
    """
    return appearance.background == Background()


class Deck:
    """Eine Gerätesitzung: ein Deck, sein Profil, seine Eingaben, sein Bild."""

    def __init__(self, runtime: "Runtime", binding: DeckBinding) -> None:
        self.runtime = runtime
        self.binding = binding
        self.device = StreamDeckDevice()
        self.view = DeckView(self)

        self.current_page_id_value: str = ""
        self._contexts: dict[str, SlotContext] = {}
        self._dirty: set[tuple[str, int]] = set()
        self._redraw_all = False
        self._render_event = asyncio.Event()
        self._tasks: list[asyncio.Task] = []

        # Tastenlogik: Druck, Doppeldruck, Halten
        self._press_started: dict[int, float] = {}
        self._long_fired: set[int] = set()
        self._long_timers: dict[int, asyncio.TimerHandle] = {}
        self._pending_single: dict[int, asyncio.TimerHandle] = {}
        self._double_armed: dict[int, float] = {}

        #: Belegung samt Seite, die eine gedrückte Taste beim Drücken hatte.
        #: Öffnet der Druck einen Ordner, liegt beim Loslassen längst eine
        #: andere Belegung an dieser Stelle — die darf den Rest des Drucks
        #: nicht abbekommen.
        self._held_slots: dict[int, tuple[str, Slot]] = {}

        # Dial-Stack
        self._stack_index: dict[tuple[str, int], int] = {}
        self._dial_press_started: dict[int, float] = {}
        self._dial_long_timers: dict[int, asyncio.TimerHandle] = {}
        self._dial_long_fired: set[int] = set()

        # Drehrichtungen: gezählte Rasten je Dial und die Richtung, in die
        # zuletzt gedreht wurde.
        self._turn_count: dict[tuple[str, int], int] = {}
        self._turn_direction: dict[tuple[str, int], str] = {}

        # Laufende Multi-Aktionen, je Belegung eine
        self._chains: dict[str, asyncio.Task] = {}

        # Animation
        self._started_at = time.monotonic()

        # Idle-Dimming
        self._last_input = time.monotonic()
        self._dimmed = False
        self._screensaver_task: asyncio.Task | None = None

        self._wallpaper_cache = wallpaper.WallpaperCache()

        # Wischgesten
        self._swipe_distance = 0.0
        self._swipe_last_at = 0.0
        self._swipe_blocked_until = 0.0

        self.current_page_id_value = self.profile.root_page().id

    def __repr__(self) -> str:  # pragma: no cover - nur fürs Log
        return f"<Deck {self.label!r} serial={self.binding.serial!r}>"

    # ======================================================================
    # Stammdaten
    # ======================================================================

    @property
    def serial(self) -> str:
        return self.binding.serial or self.device.info.serial

    @property
    def label(self) -> str:
        return self.binding.name or self.device.info.deck_type or "Deck"

    @property
    def settings(self) -> DeviceSettings:
        return self.binding.device

    @property
    def profile(self) -> Profile:
        return self.runtime.config.profile(self.binding.profile_id)

    @property
    def current_page(self) -> Page:
        return self.runtime.config.page(self.current_page_id_value, self.binding.profile_id)

    def as_dict(self) -> dict[str, Any]:
        """Alles, was die GUI über dieses Deck wissen muss."""
        return {
            **self.device.info.as_dict(),
            "id": self.key,
            "serial": self.serial,
            "name": self.label,
            "profile_id": self.profile.id,
            "current_page_id": self.current_page_id_value,
            "dimmed": self._dimmed,
            "screensaver": self._screensaver_task is not None,
            "settings": self.binding.device.model_dump(mode="json"),
            "order": self.binding.order,
        }

    @property
    def key(self) -> str:
        """Kennung der Bindung — auch dann stabil, wenn nichts angesteckt ist."""
        return self.binding.serial

    # ======================================================================
    # Lebenszyklus
    # ======================================================================

    def start(self) -> None:
        """Startet die Schleifen dieses Decks."""
        if self._tasks:
            return
        self._tasks = [
            asyncio.create_task(self._render_loop(), name=f"render-{self.key}"),
            asyncio.create_task(self._tick_loop(), name=f"tick-{self.key}"),
            asyncio.create_task(self._animation_loop(), name=f"anim-{self.key}"),
        ]

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._tasks.clear()

        for timers in (self._long_timers, self._pending_single, self._dial_long_timers):
            for timer in timers.values():
                timer.cancel()
            timers.clear()

        for task in self._chains.values():
            task.cancel()
        self._chains.clear()

        self._stop_screensaver()
        self.device.clear()
        self.device.close()

    def attach(self, device: StreamDeckDevice) -> bool:
        """Übernimmt ein bereits geöffnetes Gerät.

        Geöffnet wird im Worker-Thread (USB blockiert), übernommen hier im
        Loop: Aufgaben starten und Ereignisse verschicken geht nur von dort.
        """
        if not device.connected:
            return False
        if self.device is not device:
            self.device.close()
            self.device = device

        info = self.device.info
        if not self.binding.serial and info.serial:
            # Der Platzhalter aus einer Ein-Deck-Config bekommt jetzt seine
            # Seriennummer — ab da findet er sein Gerät wieder.
            self.binding.serial = info.serial
        self.binding.deck_type = info.deck_type or self.binding.deck_type
        if not self.binding.name:
            self.binding.name = info.deck_type or "Deck"

        self.device.on_key = self._key_event_threadsafe
        self.device.on_dial_rotate = self._dial_rotate_threadsafe
        self.device.on_dial_push = self._dial_push_threadsafe
        self.device.on_touch = self._touch_threadsafe
        self.device.on_disconnect = self._disconnected_threadsafe

        self.device.set_brightness(self.settings.brightness)
        self._dimmed = False
        self._last_input = time.monotonic()
        self._mark_all_dirty()
        self.start()
        log.info("Deck '%s' übernommen (Serial %s)", self.label, self.serial)
        return True

    def detach(self) -> None:
        """Das Gerät ist weg — Zustand zurücksetzen, Bindung behalten."""
        self.device.close()
        self._stop_screensaver()
        # Wurde beim Abziehen gerade eine Taste per Push-to-Talk gehalten,
        # kommt das Loslassen nie. Ein steckengebliebenes Strg macht den
        # ganzen Desktop unbedienbar, deshalb hier ausdrücklich freigeben.
        try:
            self.runtime.input.release_all()
        except Exception:  # pragma: no cover - beim Aufräumen egal
            log.debug("Freigeben hängender Tasten fehlgeschlagen", exc_info=True)

    @property
    def connected(self) -> bool:
        return self.device.connected

    # ======================================================================
    # Navigation (auch die Plugin-Schnittstelle, über DeckView)
    # ======================================================================

    def navigate(self, page_id: str) -> None:
        profile = self.profile
        if page_id not in profile.pages:
            self.runtime.notify("warning", f"Seite '{page_id}' existiert nicht")
            return
        self.current_page_id_value = page_id
        self._contexts.clear()
        self._mark_all_dirty()
        self.runtime.bus.publish(ev.EVT_PAGE_CHANGED, page_id=page_id, deck=self.key)

    def navigate_home(self) -> None:
        self.navigate(self.profile.root_page().id)

    def navigate_back(self) -> None:
        page = self.profile.pages.get(self.current_page_id_value)
        if page is None or page.parent_id is None:
            self.navigate_home()
            return
        self.navigate(page.parent_id)

    def current_page_id(self) -> str:
        return self.current_page_id_value

    def page_number(self) -> int:
        """1-basierte Position der aktuellen Seite unter ihren Geschwistern."""
        for i, page in enumerate(self.sibling_pages()):
            if page.id == self.current_page_id_value:
                return i + 1
        return 1

    def sibling_pages(self) -> list[Page]:
        profile = self.profile
        current = profile.pages.get(self.current_page_id_value)
        parent_id = current.parent_id if current else None
        # Über ``children`` und nicht über die Dict-Reihenfolge: was der User
        # in der GUI sortiert, ist auch die Reihenfolge beim Wischen.
        return profile.children(parent_id)

    def step_page(self, delta: int, *, wrap: bool = True) -> bool:
        """Blättert innerhalb der Geschwister-Seiten weiter."""
        siblings = self.sibling_pages()
        if len(siblings) < 2 or delta == 0:
            return False

        ids = [page.id for page in siblings]
        try:
            position = ids.index(self.current_page_id_value)
        except ValueError:
            position = 0

        target = position + (1 if delta > 0 else -1)
        if wrap:
            target %= len(ids)
        else:
            target = max(0, min(len(ids) - 1, target))

        if ids[target] == self.current_page_id_value:
            return False
        self.navigate(ids[target])
        return True

    # ======================================================================
    # Belegungen und Kontexte
    # ======================================================================

    def base_slot_at(
        self, input_type: str, index: int, page_id: str | None = None
    ) -> Slot | None:
        """Die Belegung, wie sie in der Config steht — ohne Dial-Stack."""
        page = (
            self.runtime.config.page(page_id, self.binding.profile_id)
            if page_id
            else self.current_page
        )
        return (page.keys if input_type == "key" else page.dials).get(index)

    def slot_at(self, input_type: str, index: int) -> Slot | None:
        """Die Belegung, die gerade *gilt*.

        Bei einem Dial mit Stack ist das der Eintrag, der obenauf liegt.
        Alles andere — Zeichnen, Drehen, Tippen, Tick — arbeitet dadurch
        unverändert weiter und muss vom Stack nichts wissen.
        """
        slot = self.base_slot_at(input_type, index)
        if slot is None or input_type != "dial" or not slot.stack:
            return slot
        position = self.stack_index(index)
        if position <= 0 or position > len(slot.stack):
            return slot
        return slot.stack[position - 1]

    def stack_index(self, index: int, page_id: str | None = None) -> int:
        return self._stack_index.get((page_id or self.current_page_id_value, index), 0)

    def cycle_stack(self, index: int, delta: int = 1) -> bool:
        """Schaltet einen Dial-Stack weiter. ``False`` = da ist kein Stack."""
        page_id = self.current_page_id_value
        slot = self.base_slot_at("dial", index)
        if slot is None or not slot.stack:
            return False
        count = len(slot.stack) + 1
        key = (page_id, index)
        self._stack_index[key] = (self._stack_index.get(key, 0) + delta) % count
        self._contexts.pop(f"{page_id}:dial:{index}", None)
        self._mark_dirty(("dial", index))
        self.runtime.bus.publish(
            ev.EVT_DECK_STATE,
            deck=self.key,
            page_id=page_id,
            dial=index,
            stack_index=self._stack_index[key],
        )
        return True

    def context(
        self,
        input_type: str,
        index: int,
        slot: Slot,
        page_id: str | None = None,
        *,
        suffix: str = "",
    ) -> SlotContext:
        """Kontext je Belegung, mit stabilem ``scratch`` über Aufrufe hinweg.

        ``page_id`` ist die Seite, zu der die Belegung gehört — nicht
        zwangsläufig die gerade sichtbare: ein Tastendruck kann die Seite
        wechseln und wird trotzdem auf seiner Ursprungsseite zu Ende gebracht.

        ``suffix`` trennt Kontexte, die sich Seite und Index teilen — die
        Zweige einer Taste, die Einträge eines Dial-Stacks und die Schritte
        einer Multi-Aktion. Ohne ihn überschrieben sie gegenseitig ihren
        ``scratch``.
        """
        if page_id is None:
            page_id = self.current_page_id_value
        if not suffix and input_type == "dial":
            position = self.stack_index(index, page_id)
            if position:
                suffix = f"stack{position}"
        key = f"{page_id}:{input_type}:{index}" + (f":{suffix}" if suffix else "")
        existing = self._contexts.get(key)
        size = (
            self.device.info.key_size
            if input_type == "key"
            else self.device.info.segment_size
        )
        if existing is not None and existing.slot is slot:
            existing.settings = slot.settings
            existing.appearance = slot.appearance
            existing.size = size
            return existing

        registry = self.runtime.registry
        loaded = registry.get(slot.plugin_id)
        ctx = SlotContext(
            action_id=slot.action_id,
            settings=slot.settings,
            appearance=slot.appearance,
            input_type=input_type,  # type: ignore[arg-type]
            index=index,
            page_id=page_id,
            profile_id=self.profile.id,
            size=size,
            services=self.services_for(loaded.directory if loaded else Path()),
            slot=slot,
            scratch=existing.scratch if existing else {},
            deck_serial=self.key,
        )
        self._contexts[key] = ctx
        return ctx

    def services_for(self, plugin_dir: Path) -> Services:
        """Wie ``Runtime._services_for``, aber mit diesem Deck als Runtime.

        Der Unterschied ist der Kern der Mehrgeräte-Unterstützung: Ein
        Plugin, das über seinen ``ctx`` navigiert, navigiert auf dem Deck,
        auf dem es gedrückt wurde.
        """
        services = self.runtime._services_for(plugin_dir)
        services.runtime = self.view
        return services

    def drop_context(self, page_id: str, input_type: str, index: int) -> None:
        prefix = f"{page_id}:{input_type}:{index}"
        for key in [k for k in self._contexts if k == prefix or k.startswith(prefix + ":")]:
            self._contexts.pop(key, None)

    # ======================================================================
    # Multi-Aktionen
    # ======================================================================

    async def run_steps(
        self, steps: list[Step], ctx: SlotContext, *, repeat: bool = False
    ) -> None:
        """Führt eine Kette aus. Ein zweiter Aufruf löst den ersten ab.

        Die Kette läuft als eigene Aufgabe: Ein ``delay``-Schritt darf sich
        Zeit lassen, ohne dass das Deck währenddessen steht. Genau deshalb
        ist die Kette auch abbrechbar — eine Wiederholschleife bräuchte sonst
        einen Neustart des Backends, um sie wieder loszuwerden.
        """
        usable = [s for s in steps if s.enabled]
        if not usable:
            self.runtime.notify("info", "Die Multi-Aktion hat keine aktiven Schritte")
            return

        self.stop_steps(ctx)
        key = ctx.key
        task = asyncio.create_task(
            self._run_chain(usable, ctx, repeat), name=f"chain-{self.key}-{key}"
        )
        self._chains[key] = task
        task.add_done_callback(lambda _t, k=key: self._chain_finished(k))

    def stop_steps(self, ctx: SlotContext) -> bool:
        task = self._chains.pop(ctx.key, None)
        if task is None:
            return False
        task.cancel()
        return True

    def steps_running(self, ctx: SlotContext) -> bool:
        task = self._chains.get(ctx.key)
        return task is not None and not task.done()

    def _chain_finished(self, key: str) -> None:
        self._chains.pop(key, None)
        self._mark_all_dirty()

    async def _run_chain(self, steps: list[Step], ctx: SlotContext, repeat: bool) -> None:
        while True:
            for position, step in enumerate(steps):
                if step.kind == "delay":
                    await asyncio.sleep(max(0, step.delay_ms) / 1000)
                    continue
                await self._run_step(step, ctx, position)
            if not repeat:
                return
            # Eine Schleife ohne jede Pause würde das Deck und alles
            # Angesprochene fluten — ein Mindestabstand ist Notwehr.
            pause = sum(s.delay_ms for s in steps if s.kind == "delay") / 1000
            await asyncio.sleep(max(0.05, pause))

    async def _run_step(self, step: Step, ctx: SlotContext, position: int) -> None:
        """Löst einen einzelnen Schritt aus — wie ein kurzer Tastendruck."""
        if step.plugin_id == "multi":
            # Ketten in Ketten wären eine hübsche Schleife, die niemand mehr
            # anhält. Elgato lässt sie aus demselben Grund nicht zu.
            self.runtime.notify(
                "warning", "Eine Multi-Aktion kann keine Multi-Aktion enthalten"
            )
            return

        plugin = self.runtime.registry.instance(step.plugin_id)
        if plugin is None:
            self.runtime._record_error(
                step.plugin_id,
                f"Schritt {position + 1}: Plugin '{step.plugin_id}' nicht geladen",
            )
            return

        step_slot = Slot(
            plugin_id=step.plugin_id,
            action_id=step.action_id,
            settings=step.settings,
            appearance=ctx.appearance,
        )
        step_ctx = self.context(
            ctx.input_type,
            ctx.index,
            step_slot,
            page_id=ctx.page_id,
            suffix=f"step-{step.id}",
        )

        for hook, name in (
            (plugin.on_key_down, "on_key_down"),
            (plugin.on_key_up, "on_key_up"),
        ):
            try:
                await self.runtime._call_hook(hook, step.action_id, step.settings, step_ctx)
            except Exception as exc:
                self.runtime._record_error(
                    step.plugin_id,
                    f"Schritt {position + 1} — {name}({step.action_id}): {exc}",
                    source="plugin",
                    traceback=traceback.format_exc(),
                )
                return

    # ======================================================================
    # Zeichnen
    # ======================================================================

    def request_redraw(self, ctx: SlotContext | None = None) -> None:
        """Threadsicher: sofortiges Neuzeichnen anstoßen."""
        loop = self.runtime._loop
        if loop is None or loop.is_closed():
            return
        if ctx is None:
            loop.call_soon_threadsafe(self._mark_all_dirty)
        else:
            loop.call_soon_threadsafe(
                self._mark_dirty, (ctx.input_type, ctx.index), ctx.page_id
            )

    def _mark_dirty(self, target: tuple[str, int], page_id: str | None = None) -> None:
        if page_id is not None and page_id != self.current_page_id_value:
            return  # Belegung liegt auf einer Seite, die gerade nicht sichtbar ist
        self._dirty.add(target)
        self._render_event.set()

    def _mark_all_dirty(self) -> None:
        self._redraw_all = True
        self._render_event.set()

    async def _render_loop(self) -> None:
        self._mark_all_dirty()
        while True:
            await self._render_event.wait()
            self._render_event.clear()

            if self._redraw_all:
                self._redraw_all = False
                self._dirty.clear()
                targets = self._all_targets()
            else:
                targets = sorted(self._dirty)
                self._dirty.clear()

            for input_type, index in targets:
                try:
                    await self._render_target(input_type, index)
                except Exception:
                    log.exception("Rendern von %s %s fehlgeschlagen", input_type, index)

            # Kurz durchatmen: bündelt Event-Salven (z. B. schnelles Drehen)
            # zu einem Frame statt jedes Delta einzeln zu zeichnen.
            await asyncio.sleep(0.02)

    def _all_targets(self) -> list[tuple[str, int]]:
        keys = self.device.info.key_count or 8
        # Kein ``or 4`` für die Dials: Ein Deck ohne Drehregler meldet hier
        # zu Recht 0 — ein Stream Deck MK.2 ebenso wie ein virtuelles Deck,
        # das ohne Regler eingerichtet wurde. Der Ersatzwert ließ uns vier
        # Segmente der Größe 0×0 zeichnen, und daran starb die Renderschleife.
        dials = max(0, self.device.info.dial_count)
        return [("key", i) for i in range(keys)] + [("dial", i) for i in range(dials)]

    async def _render_target(self, input_type: str, index: int) -> None:
        if not self.device.connected:
            return
        # Während der Schoner läuft, gehört ihm das Deck. Ein Plugin, das
        # nebenher ein Neuzeichnen anfordert, würde sonst einzelne Kacheln
        # aus dem Bild stanzen.
        if self._screensaver_task is not None:
            return
        slot = self.slot_at(input_type, index)
        size = (
            self.device.info.key_size
            if input_type == "key"
            else self.device.info.segment_size
        )
        # Nichts zu zeichnen, wenn das Gerät für diese Art keine Fläche hat.
        # Ohne die Prüfung liefe alles Weitere auf ein Bild der Größe 0 zu,
        # und Pillow bricht dort mitten im Zeichnen ab.
        if size[0] <= 0 or size[1] <= 0:
            return

        if input_type == "key":
            image = (
                self.runtime.render.empty_slot(size)
                if slot is None
                else await self.render_slot(slot, input_type, index, size)
            )
            self.device.set_key_image(index, image)
            return

        # Touchstrip: erst das Seitenbild, dann die Belegung darüber.
        base = self.wallpaper_segment(self.current_page, index, size)

        if slot is None:
            image = base if base is not None else self.runtime.render.blank(size)
        else:
            image = await self.render_slot(
                slot, input_type, index, size, transparent_background=base is not None
            )
            if base is not None:
                merged = base.copy()
                merged.alpha_composite(image.convert("RGBA"))
                image = merged

        self.device.set_touchscreen_image(image, x=index * size[0], y=0)

    async def render_slot(
        self,
        slot: Slot,
        input_type: str,
        index: int,
        size: tuple[int, int],
        *,
        transparent_background: bool = False,
    ) -> Image.Image:
        render = self.runtime.render
        plugin = self.runtime.registry.instance(slot.plugin_id)
        if plugin is None:
            return render.error_slot(size, slot.plugin_id or "?")

        ctx = self.context(input_type, index, slot)
        # Animierte Bilder wählen ihr Einzelbild über die Laufzeit. Steht die
        # Kachel still, ist der Wert belanglos — dann gibt es nur ein Bild.
        ctx.frame_time = time.monotonic() - self._started_at
        if transparent_background and uses_default_background(slot.appearance):
            # Ein Seitenbild liegt darunter. Der Standard-Hintergrund ist
            # deckendes Schwarz und würde es vollständig verdecken — also
            # hier durchsichtig zeichnen. Wer für dieses Segment bewusst
            # eine Farbe gewählt hat, behält sie.
            # Kopie, nicht am Original ändern: ``context`` gibt gecachte
            # Instanzen zurück, die auch die Eingabe-Hooks benutzen.
            ctx = dataclasses.replace(
                ctx,
                appearance=slot.appearance.model_copy(
                    update={"background": TRANSPARENT_BACKGROUND}
                ),
            )
        try:
            image = await self.runtime._call_hook(
                plugin.render, slot.action_id, slot.settings, ctx
            )
        except Exception as exc:
            self.runtime._record_error(
                slot.plugin_id,
                f"render({slot.action_id}): {type(exc).__name__}: {exc}",
                source="plugin",
                traceback=traceback.format_exc(),
            )
            return render.error_slot(size, slot.action_id)

        if not isinstance(image, Image.Image):
            return render.error_slot(size, "kein Bild")
        if image.size != size:
            image = image.resize(size, Image.LANCZOS)
        return image

    async def render_preview(
        self, page_id: str, input_type: str, index: int, entry: int | None = None
    ) -> Image.Image:
        """Einzelne Kachel für die GUI-Vorschau zeichnen.

        Nutzt denselben Weg wie das Gerät, damit die Vorschau nicht
        auseinanderläuft.

        ``entry`` wählt bei einem Dial-Stack einen bestimmten Eintrag. Ohne
        Angabe wird gezeigt, was gerade auf dem Gerät steht — der Editor
        fragt dagegen nach dem Eintrag, den er gerade bearbeitet.
        """
        render = self.runtime.render
        profile = self.profile
        page = profile.pages.get(page_id) or profile.root_page()
        slot = (page.keys if input_type == "key" else page.dials).get(index)
        size = (
            self.device.info.key_size
            if input_type == "key"
            else self.device.info.segment_size
        )
        # Das Seitenbild gehört auch in die Vorschau — sonst zeigte die GUI
        # etwas anderes als das Gerät, und genau dafür ist sie da.
        base = self.wallpaper_segment(page, index, size) if input_type == "dial" else None

        if slot is None:
            if input_type == "key":
                return render.empty_slot(size)
            return base if base is not None else render.blank(size)

        # Dial-Stack auflösen.
        live = page_id == self.current_page_id_value
        if input_type == "dial" and slot.stack:
            active = self.stack_index(index, page_id) if live else 0
            position = active if entry is None else entry
            if 0 < position <= len(slot.stack):
                slot = slot.stack[position - 1]
            # Nur der gerade *aktive* Eintrag darf über den Live-Kontext
            # gezeichnet werden — sonst überschriebe die Vorschau eines
            # anderen Eintrags dessen Zwischenspeicher.
            live = live and position == active

        # Vorschau einer *anderen* Seite darf den Live-Kontext nicht stören.
        if not live:
            appearance = slot.appearance
            if base is not None and uses_default_background(appearance):
                appearance = appearance.model_copy(
                    update={"background": TRANSPARENT_BACKGROUND}
                )
            ctx = SlotContext(
                action_id=slot.action_id,
                settings=slot.settings,
                appearance=appearance,
                input_type=input_type,  # type: ignore[arg-type]
                index=index,
                page_id=page_id,
                profile_id=profile.id,
                size=size,
                services=self.services_for(Path()),
                slot=slot,
                deck_serial=self.key,
            )
            plugin = self.runtime.registry.instance(slot.plugin_id)
            if plugin is None:
                return render.error_slot(size, slot.plugin_id or "?")
            try:
                rendered = await self.runtime._call_hook(
                    plugin.render, slot.action_id, slot.settings, ctx
                )
            except Exception:
                return render.error_slot(size, slot.action_id)
            image = (
                rendered if isinstance(rendered, Image.Image) else render.error_slot(size)
            )
        else:
            image = await self.render_slot(
                slot, input_type, index, size, transparent_background=base is not None
            )

        if base is None:
            return image
        merged = base.copy()
        merged.alpha_composite(image.convert("RGBA"))
        return merged

    # -- Touchstrip-Hintergrundbild ---------------------------------------

    def wallpaper_segment(
        self, page: Page, index: int, size: tuple[int, int]
    ) -> Image.Image | None:
        """Der Bildausschnitt für dieses Segment, oder ``None``."""
        segments = self._wallpaper_segments(page)
        if not segments or index >= len(segments):
            return None
        segment = segments[index]
        if segment.size != size:
            segment = segment.resize(size, Image.LANCZOS)
        return segment.convert("RGBA")

    @staticmethod
    def _source_mtime(source: str) -> float:
        """Änderungszeit einer ``upload:``-Quelle, 0 für alles andere."""
        kind, _, name = source.partition(":")
        if kind != "upload":
            return 0.0
        path = paths.image_path(name)
        return path.stat().st_mtime if path is not None else 0.0

    def _wallpaper_segments(self, page: Page) -> list[Image.Image]:
        """Die zerlegten Segmente dieser Seite, ggf. aus dem Zwischenspeicher."""
        settings = page.touch_wallpaper
        if not settings.enabled or not settings.source:
            return []

        strip = self.device.info.touchscreen_size
        count = max(0, self.device.info.dial_count)
        if count <= 0 or strip[0] <= 0 or strip[1] <= 0:
            return []  # kein Touchstrip, nichts zu zerlegen
        # Die Seiten-ID gehört in den Schlüssel: Sonst zeigte der Cache nach
        # einem Seitenwechsel weiter das Bild der vorigen Seite. Die
        # Änderungszeit ebenso — wer eine Bilddatei austauscht, ohne ihren
        # Namen zu ändern, sähe sonst bis zum Neustart das alte Bild.
        key = (
            page.id,
            settings.source,
            self._source_mtime(settings.source),
            strip,
            count,
            settings.fit,
            settings.opacity,
        )

        cached = self._wallpaper_cache.get(key)
        if cached is not None:
            return cached

        try:
            segments = self.build_wallpaper(settings, strip, count)
        except Exception as exc:
            self.runtime._record_error(
                settings.source, f"Hintergrundbild nicht ladbar: {exc}", source="wallpaper"
            )
            # Leeres Ergebnis merken, damit nicht jedes Neuzeichnen erneut
            # scheitert und die Fehlerliste flutet.
            self._wallpaper_cache.put(key, [])
            return []

        self._wallpaper_cache.put(key, segments)
        return segments

    def build_wallpaper(self, settings, strip, count) -> list[Image.Image]:
        kind, _, name = settings.source.partition(":")

        if kind == "plugin":
            loaded = self.runtime.registry.plugins.get(name)
            if loaded is None or not loaded.enabled or loaded.instance is None:
                raise ValueError(f"Plugin '{name}' ist nicht verfügbar")
            image = loaded.instance.render(strip, 0.0)
            if image is None:
                raise ValueError("Das Plugin hat kein Bild geliefert")
            return wallpaper.split(image, strip, count, settings.fit, settings.opacity)

        if kind == "upload":
            path = paths.image_path(name)
            if path is None:
                raise FileNotFoundError(f"Datei nicht gefunden: {name}")
            with Image.open(path) as image:
                return wallpaper.load(image, strip, count, settings.fit, settings.opacity)

        raise ValueError(f"Unbekannte Quelle: '{settings.source}'")

    def wallpaper_preview(
        self, source: str, *, fit: str = "cover", opacity: int = 100
    ) -> Image.Image:
        """Baut den Streifen für die GUI-Vorschau."""
        settings = TouchWallpaper(
            enabled=True, source=source, fit=fit, opacity=max(1, min(100, opacity))
        )
        segments = self.build_wallpaper(
            settings, self.device.info.touchscreen_size, self.device.info.dial_count or 4
        )
        width, height = self.device.info.touchscreen_size
        preview = Image.new("RGBA", (width, height), (0, 0, 0, 255))
        for index, segment in enumerate(segments):
            preview.paste(segment, (index * segment.width, 0))
        # Segmentgrenzen andeuten: Über jedem Viertel sitzt ein Dial, das
        # sieht man dem Bild sonst nicht an.
        pen = ImageDraw.Draw(preview)
        step = width // max(1, len(segments) or 1)
        for index in range(1, len(segments)):
            pen.line([(index * step, 0), (index * step, height)], fill=(255, 255, 255, 60))
        return preview

    # ======================================================================
    # Animierte Kacheln
    # ======================================================================

    async def _animation_loop(self) -> None:
        """Zeichnet bewegte Kacheln immer wieder neu.

        Bewusst getrennt vom Tick: Der läuft einmal pro Sekunde und fragt
        Plugins nach ihrem Zustand — für eine Animation viel zu langsam,
        und umgekehrt wäre es Verschwendung, jedes Plugin zehnmal je Sekunde
        zu befragen, nur weil irgendwo ein GIF läuft.

        Neu gezeichnet wird ausschließlich, was sich wirklich bewegt: Jede
        Kachel geht einzeln über USB zum Deck, und die Bandbreite ist das
        knappste Gut, das dieses Gerät hat.
        """
        while True:
            settings = self.settings
            fps = max(1, min(30, settings.animation_fps))
            await asyncio.sleep(1 / fps)

            if not settings.animations or not self.device.connected:
                continue
            if self._screensaver_task is not None:
                continue

            targets = self._animated_targets()
            if not targets:
                continue
            self._dirty.update(targets)
            self._render_event.set()

    def _animated_targets(self) -> list[tuple[str, int]]:
        page = self.current_page
        targets: list[tuple[str, int]] = []
        for input_type, mapping in (("key", page.keys), ("dial", page.dials)):
            for index in mapping:
                slot = self.slot_at(input_type, index)
                if slot is not None and self._is_animated(slot):
                    targets.append((input_type, index))
        return targets

    def _is_animated(self, slot: Slot) -> bool:
        """Bewegt sich an dieser Belegung etwas?"""
        icons = self.runtime.icons
        background = slot.appearance.background
        if background.kind == "image" and icons.is_animated_upload(background.upload):
            return True
        return any(
            icon.kind == "upload" and icons.is_animated_upload(icon.upload)
            for icon in slot.appearance.icon_by_state.values()
        )

    # ======================================================================
    # Tick und Idle-Dimming
    # ======================================================================

    async def _tick_loop(self) -> None:
        while True:
            interval = max(0.1, self.settings.tick_interval_s)
            await asyncio.sleep(interval)
            self.check_idle()
            if not self.device.connected:
                continue

            page = self.current_page
            for input_type, mapping in (("key", page.keys), ("dial", page.dials)):
                for index, slot in list(mapping.items()):
                    active = self.slot_at(input_type, index) or slot
                    plugin = self.runtime.registry.instance(active.plugin_id)
                    if plugin is None:
                        continue
                    ctx = self.context(input_type, index, active)
                    try:
                        await self.runtime._call_hook(
                            plugin.on_tick, active.action_id, active.settings, ctx
                        )
                    except Exception as exc:
                        self.runtime._record_error(
                            active.plugin_id,
                            f"on_tick({active.action_id}): {exc}",
                            source="plugin",
                        )

    def check_idle(self) -> None:
        settings = self.settings
        if not self.device.connected:
            return
        idle_for = time.monotonic() - self._last_input

        if (
            settings.idle_dim_after_s > 0
            and not self._dimmed
            and idle_for >= settings.idle_dim_after_s
        ):
            self._dimmed = True
            self.device.set_brightness(settings.idle_brightness)
            self._publish_state(dimmed=True)

        saver = settings.screensaver
        if (
            saver.enabled
            and saver.source
            and saver.after_s > 0
            and self._screensaver_task is None
            and idle_for >= saver.after_s
        ):
            self._screensaver_task = asyncio.create_task(
                self._screensaver_loop(), name=f"screensaver-{self.key}"
            )

    def wake(self) -> None:
        self._last_input = time.monotonic()
        self._stop_screensaver()
        if self._dimmed:
            self._dimmed = False
            self.device.set_brightness(self.settings.brightness)
            self._publish_state(dimmed=False)

    def _publish_state(self, **extra: Any) -> None:
        self.runtime.bus.publish(ev.EVT_DEVICE_STATE, **{**self.as_dict(), **extra})

    def _publish_state_threadsafe(self, **extra: Any) -> None:
        loop = self.runtime._loop
        if loop is not None and not loop.is_closed():
            loop.call_soon_threadsafe(lambda: self._publish_state(**extra))

    # ======================================================================
    # Bildschirmschoner
    # ======================================================================

    def _stop_screensaver(self) -> None:
        """Beendet den Schoner und holt das normale Bild zurück."""
        task = self._screensaver_task
        if task is None:
            return
        self._screensaver_task = None
        task.cancel()
        self.device.set_brightness(
            self.settings.idle_brightness if self._dimmed else self.settings.brightness
        )
        # Der Schoner hat jede Kachel überschrieben — alles neu zeichnen.
        self._mark_all_dirty()
        self._publish_state(screensaver=False)

    def start_screensaver_now(self) -> None:
        """Startet den Schoner sofort — für den Ausprobieren-Knopf."""
        if self._screensaver_task is not None:
            return
        self._screensaver_task = asyncio.create_task(
            self._screensaver_loop(), name=f"screensaver-{self.key}"
        )

    async def _screensaver_loop(self) -> None:
        """Zeigt den Schoner, bis die Aufgabe abgebrochen wird."""
        settings = self.settings.screensaver
        layout = screensaver.layout(
            self.device.info.key_size,
            self.device.info.key_count or 8,
            self.device.info.touchscreen_size,
        )

        try:
            frames, plugin = self.screensaver_source(settings.source, layout)
        except Exception as exc:
            self.runtime._record_error(
                settings.source, f"Schoner nicht ladbar: {exc}", source="screensaver"
            )
            self._screensaver_task = None
            return

        if frames is None and plugin is None:
            self._screensaver_task = None
            return

        self.device.set_brightness(settings.brightness)
        self._publish_state(screensaver=True)

        started = time.monotonic()
        try:
            if plugin is not None:
                await self._run_screensaver_plugin(plugin, layout, settings, started)
            else:
                await self._run_screensaver_frames(frames)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.runtime._record_error(
                settings.source,
                f"Schoner abgebrochen: {exc}",
                source="screensaver",
                traceback=traceback.format_exc(),
            )

    def screensaver_source(self, source: str, layout) -> tuple[list | None, Any]:
        """Löst ``upload:…`` bzw. ``plugin:…`` auf."""
        kind, _, name = source.partition(":")

        if kind == "plugin":
            loaded = self.runtime.registry.plugins.get(name)
            if loaded is None or not loaded.enabled or loaded.instance is None:
                raise ValueError(f"Schoner-Plugin '{name}' ist nicht verfügbar")
            return None, loaded.instance

        if kind == "upload":
            path = paths.image_path(name)
            if path is None:
                raise FileNotFoundError(f"Datei nicht gefunden: {name}")
            with Image.open(path) as image:
                return (
                    screensaver.load_frames(image, layout, self.settings.screensaver.fit),
                    None,
                )

        raise ValueError(f"Unbekannte Schoner-Quelle: '{source}'")

    async def _run_screensaver_frames(self, frames: list) -> None:
        """Spielt vorbereitete Einzelbilder ab."""
        if not frames:
            return
        if len(frames) == 1:
            self._show_screensaver_frame(frames[0].keys, frames[0].strip)
            # Nichts mehr zu tun — schlafen, bis jemand das Deck anfasst.
            while True:
                await asyncio.sleep(3600)

        while True:
            for frame in frames:
                self._show_screensaver_frame(frame.keys, frame.strip)
                await asyncio.sleep(frame.duration_s)

    async def _run_screensaver_plugin(self, plugin, layout, settings, started: float) -> None:
        """Lässt ein Plugin zeichnen — einmalig oder fortlaufend."""
        # Damit ein Plugin etwas pro Taste zeigen kann, muss es wissen, wo
        # die Schnitte verlaufen.
        plugin.deck_layout = layout
        while True:
            elapsed = time.monotonic() - started
            try:
                image = plugin.render(layout.canvas, elapsed)
            except Exception as exc:
                self.runtime._record_error(
                    plugin.manifest.id,
                    f"Schoner render(): {exc}",
                    source="plugin",
                    traceback=traceback.format_exc(),
                )
                return

            if image is not None:
                canvas = screensaver.fit(image, layout.canvas, settings.fit)
                keys, strip = screensaver.split(canvas, layout)
                self._show_screensaver_frame(keys, strip)

            interval = getattr(plugin, "interval_s", 0.0)
            if interval <= 0:
                while True:
                    await asyncio.sleep(3600)
            await asyncio.sleep(max(screensaver.MIN_FRAME_S, interval))

    def _show_screensaver_frame(self, keys: list, strip) -> None:
        if not self.device.connected:
            return
        for index, image in enumerate(keys):
            self.device.set_key_image(index, image)
        self.device.set_touchscreen_image(strip, x=0, y=0)

    def screensaver_preview(self, source: str, layout) -> Image.Image:
        """Baut ein Vorschaubild, wie der Schoner auf dem Deck ankommt.

        Nicht einfach die Quelldatei ausliefern: Interessant ist ja gerade,
        wie das Motiv nach dem Zerschneiden wirkt. Die Fugen werden deshalb
        schwarz eingezeichnet — was dort verschwindet, sieht man später am
        Gerät auch nicht.
        """
        frames, plugin = self.screensaver_source(source, layout)
        if plugin is not None:
            plugin.deck_layout = layout
            image = plugin.render(layout.canvas, 0.0)
            if image is None:
                raise ValueError("Das Plugin hat kein Bild geliefert")
            canvas = screensaver.fit(image, layout.canvas, self.settings.screensaver.fit)
            keys, strip = screensaver.split(canvas, layout)
        else:
            if not frames:
                raise ValueError("Kein Einzelbild gefunden")
            keys, strip = frames[0].keys, frames[0].strip

        preview = Image.new("RGBA", layout.canvas, (0, 0, 0, 255))
        for (x, y, w, h), image in zip(layout.keys, keys):
            preview.paste(image.resize((w, h), Image.LANCZOS), (x, y))
        x, y, w, h = layout.strip
        preview.paste(strip.resize((w, h), Image.LANCZOS), (x, y))
        return preview

    # ======================================================================
    # Eingaben — Einstieg aus dem Reader-Thread
    # ======================================================================

    def _dispatch(self, coro_factory) -> None:
        loop = self.runtime._loop
        if loop is None or loop.is_closed():
            return
        loop.call_soon_threadsafe(lambda: asyncio.ensure_future(coro_factory()))

    def _key_event_threadsafe(self, index: int, pressed: bool) -> None:
        self._dispatch(lambda: self.handle_key(index, pressed))

    def _dial_rotate_threadsafe(self, index: int, delta: int) -> None:
        self._dispatch(lambda: self.handle_dial_rotate(index, delta))

    def _dial_push_threadsafe(self, index: int, pressed: bool) -> None:
        self._dispatch(lambda: self.handle_dial_push(index, pressed))

    def _touch_threadsafe(self, kind: str, value: dict) -> None:
        self._dispatch(lambda: self.handle_touch(kind, value))

    def _disconnected_threadsafe(self) -> None:
        self._publish_state_threadsafe()

    # -- Tasten ------------------------------------------------------------

    async def handle_key(self, index: int, pressed: bool) -> None:
        """Verteilt einen Tastendruck auf Druck, Doppeldruck oder Halten.

        Der Grundsatz: **Wer nichts Zweites hinterlegt hat, wartet auch auf
        nichts.** Eine Taste mit nur einer Aktion löst weiterhin im Moment
        des Drückens aus. Erst wer Doppeldruck oder Halten belegt, kauft
        sich die dafür nötige Verzögerung ein — bei Elgato ist das genauso,
        und anders ginge es auch nicht: Ob ein zweiter Druck folgt, weiß man
        erst hinterher.
        """
        self.wake()
        if pressed:
            await self._on_key_down(index)
            return
        await self._on_key_up(index)

    async def _on_key_down(self, index: int) -> None:
        slot = self.slot_at("key", index)
        if slot is None:
            return

        # Zweiter Druck innerhalb des Fensters → Doppeldruck.
        pending = self._pending_single.pop(index, None)
        if pending is not None:
            pending.cancel()
            held = self._held_slots.get(index)
            page_id = held[0] if held else self.current_page_id_value
            base = held[1] if held else slot
            self._double_armed.pop(index, None)
            if base.double_press is not None:
                self._held_slots[index] = (page_id, base)
                self._press_started[index] = time.monotonic()
                self._long_fired.discard(index)
                self._double_armed[index] = time.monotonic()
                await self._fire_key(
                    base.double_press, index, page_id, down=True, branch="double"
                )
                return

        # Die Taste gehört ab jetzt dieser Belegung — auch wenn der Druck
        # gleich die Seite wechselt.
        page_id = self.current_page_id_value
        self._held_slots[index] = (page_id, slot)
        self._press_started[index] = time.monotonic()
        self._long_fired.discard(index)

        if slot.long_press is None and slot.double_press is None:
            # Ohne Zweitbelegung sofort auslösen — kein künstlicher Verzug.
            await self._fire_key(slot, index, page_id, down=True)
            return

        if slot.long_press is not None:
            loop = asyncio.get_running_loop()
            delay = max(0.05, self.settings.long_press_ms / 1000)
            self._long_timers[index] = loop.call_later(
                delay, lambda: asyncio.ensure_future(self._fire_long_press(index))
            )

    async def _on_key_up(self, index: int) -> None:
        timer = self._long_timers.pop(index, None)
        if timer is not None:
            timer.cancel()
        started = self._press_started.pop(index, None)
        held = self._held_slots.get(index)
        if held is None:
            # Kein zugehöriger Druck (z. B. Taste war beim Start schon unten).
            self._long_fired.discard(index)
            return
        page_id, slot = held

        # Doppeldruck läuft gerade — nur noch das Loslassen nachreichen.
        if self._double_armed.pop(index, None) is not None:
            self._held_slots.pop(index, None)
            if slot.double_press is not None:
                await self._fire_key(
                    slot.double_press, index, page_id, down=False, branch="double"
                )
            return

        if index in self._long_fired:
            self._long_fired.discard(index)
            self._held_slots.pop(index, None)
            if slot.long_press is not None:
                await self._fire_key(slot.long_press, index, page_id, down=False, long=True)
            return

        if slot.double_press is not None:
            # Jetzt entscheidet sich nichts: Erst wenn das Fenster ohne
            # zweiten Druck verstreicht, war es ein einfacher Druck.
            loop = asyncio.get_running_loop()
            window = max(0.08, self.settings.double_press_ms / 1000)
            elapsed = time.monotonic() - started if started else 0.0
            self._pending_single[index] = loop.call_later(
                max(0.02, window - elapsed),
                lambda: asyncio.ensure_future(self._fire_pending_single(index)),
            )
            return

        self._held_slots.pop(index, None)

        if slot.long_press is not None and started is not None:
            # Kurzer Druck: jetzt nachholen, was beim Drücken verzögert wurde.
            await self._fire_key(slot, index, page_id, down=True)

        await self._fire_key(slot, index, page_id, down=False)

    async def _fire_pending_single(self, index: int) -> None:
        """Das Fenster für einen zweiten Druck ist zu — es war ein einfacher."""
        self._pending_single.pop(index, None)
        held = self._held_slots.pop(index, None)
        if held is None:
            return
        page_id, slot = held
        await self._fire_key(slot, index, page_id, down=True)
        await self._fire_key(slot, index, page_id, down=False)

    async def _fire_long_press(self, index: int) -> None:
        held = self._held_slots.get(index)
        if held is None:
            return
        page_id, slot = held
        if slot.long_press is None:
            return
        if index not in self._press_started:
            return
        self._long_fired.add(index)
        await self._fire_key(slot.long_press, index, page_id, down=True, long=True)

    async def _fire_key(
        self,
        slot: Slot,
        index: int,
        page_id: str,
        *,
        down: bool,
        long: bool = False,
        branch: str = "",
    ) -> None:
        plugin = self.runtime.registry.instance(slot.plugin_id)
        if plugin is None:
            self.runtime._record_error(
                slot.plugin_id, f"Plugin '{slot.plugin_id}' nicht geladen"
            )
            return
        # Jeder Zweig einer Taste bekommt seinen eigenen Kontext: Druck,
        # Doppeldruck und Halten sind verschiedene Belegungen und dürfen sich
        # ihren Zwischenspeicher nicht gegenseitig überschreiben.
        suffix = branch or ("long" if long else "")
        ctx = self.context("key", index, slot, page_id=page_id, suffix=suffix)
        ctx.is_long_press = long
        hook = plugin.on_key_down if down else plugin.on_key_up
        try:
            await self.runtime._call_hook(hook, slot.action_id, slot.settings, ctx)
        except Exception as exc:
            self.runtime._record_error(
                slot.plugin_id,
                f"{'on_key_down' if down else 'on_key_up'}({slot.action_id}): {exc}",
                source="plugin",
                traceback=traceback.format_exc(),
            )
        self._mark_dirty(("key", index))

    # -- Dials -------------------------------------------------------------

    async def handle_dial_rotate(self, index: int, delta: int) -> None:
        """Drehen — entweder als Delta an die Grundaktion oder als Auslöser.

        Zwei Betriebsarten, und die Belegung entscheidet:

        * **Ohne Richtungsbelegung** bekommt die Grundaktion das Delta und
          regelt damit stufenlos. Das ist der Normalfall (Lautstärke,
          Helligkeit) und bleibt unverändert.
        * **Mit Richtungsbelegung** wirkt jede Drehung wie ein kurzer Druck
          auf die hinterlegte Action — „nächster Titel“, „Szene weiter“.
          Ausgelöst wird nach je ``turn_every`` Rasten, nicht bei jeder:
          Ein zügiger Dreh sind schnell fünfzehn davon.
        """
        self.wake()
        slot = self.slot_at("dial", index)
        if slot is None:
            return

        # Richtung immer mitführen, auch wenn diese Seite nicht belegt ist:
        # Wer zwei Rasten vor und eine zurück dreht, hat nicht drei in eine
        # Richtung gedreht, und der Zähler darf das nicht anders sehen.
        direction = "left" if delta < 0 else "right"
        key = (self.current_page_id_value, index)
        if self._turn_direction.get(key) != direction:
            self._turn_direction[key] = direction
            self._turn_count[key] = 0

        branch = slot.turn_left if delta < 0 else slot.turn_right
        if branch is not None:
            await self._fire_turn(index, delta, slot, branch, key)
            return

        plugin = self.runtime.registry.instance(slot.plugin_id)
        if plugin is None:
            return
        ctx = self.context("dial", index, slot)
        try:
            await self.runtime._call_hook(
                plugin.on_dial_rotate, slot.action_id, slot.settings, delta, ctx
            )
        except Exception as exc:
            self.runtime._record_error(
                slot.plugin_id, f"on_dial_rotate({slot.action_id}): {exc}", source="plugin"
            )
        self._mark_dirty(("dial", index))

    async def _fire_turn(
        self, index: int, delta: int, slot: Slot, branch: Slot, key: tuple[str, int]
    ) -> None:
        """Zählt Rasten und löst aus, sobald genug zusammengekommen sind."""
        direction = "left" if delta < 0 else "right"
        self._turn_count[key] = self._turn_count.get(key, 0) + abs(delta)
        every = max(1, slot.turn_every)
        if self._turn_count[key] < every:
            return
        self._turn_count[key] -= every

        page_id = self.current_page_id_value
        plugin = self.runtime.registry.instance(branch.plugin_id)
        if plugin is None:
            self.runtime._record_error(
                branch.plugin_id, f"Plugin '{branch.plugin_id}' nicht geladen"
            )
            return

        # Wie ein kurzer Druck: erst down, dann up. Damit funktionieren auch
        # Actions auf einem Dial, die eigentlich für Tasten gedacht sind.
        ctx = self.context("dial", index, branch, page_id=page_id, suffix=f"turn-{direction}")
        for hook, name in (
            (plugin.on_key_down, "on_key_down"),
            (plugin.on_key_up, "on_key_up"),
        ):
            try:
                await self.runtime._call_hook(hook, branch.action_id, branch.settings, ctx)
            except Exception as exc:
                self.runtime._record_error(
                    branch.plugin_id,
                    f"{name}({branch.action_id}) beim Drehen: {exc}",
                    source="plugin",
                    traceback=traceback.format_exc(),
                )
                break
        self._mark_dirty(("dial", index))

    async def handle_dial_push(self, index: int, pressed: bool) -> None:
        """Druck auf einen Dial — und bei einem Stack das Weiterschalten.

        Liegt auf dem Dial ein Stack, schaltet **langes Drücken** zum
        nächsten Eintrag. Der kurze Druck bleibt bei der Aktion: Wer einen
        Dial drückt, will meistens stummschalten, nicht umschalten. Ohne
        Stack ändert sich nichts — dann löst der Druck sofort aus.
        """
        base = self.base_slot_at("dial", index)
        self.wake()

        if base is None:
            return

        if not base.stack:
            if pressed:
                await self._fire_dial_push(index)
            return

        if pressed:
            self._dial_press_started[index] = time.monotonic()
            self._dial_long_fired.discard(index)
            loop = asyncio.get_running_loop()
            delay = max(0.05, self.settings.long_press_ms / 1000)
            self._dial_long_timers[index] = loop.call_later(
                delay, lambda: self._cycle_stack_from_hold(index)
            )
            return

        timer = self._dial_long_timers.pop(index, None)
        if timer is not None:
            timer.cancel()
        self._dial_press_started.pop(index, None)
        if index in self._dial_long_fired:
            self._dial_long_fired.discard(index)
            return
        await self._fire_dial_push(index)

    def _cycle_stack_from_hold(self, index: int) -> None:
        if index not in self._dial_press_started:
            return
        self._dial_long_fired.add(index)
        self.cycle_stack(index)

    async def _fire_dial_push(self, index: int) -> None:
        slot = self.slot_at("dial", index)
        if slot is None:
            return
        plugin = self.runtime.registry.instance(slot.plugin_id)
        if plugin is None:
            return
        ctx = self.context("dial", index, slot)
        try:
            await self.runtime._call_hook(
                plugin.on_dial_push, slot.action_id, slot.settings, ctx
            )
        except Exception as exc:
            self.runtime._record_error(
                slot.plugin_id, f"on_dial_push({slot.action_id}): {exc}", source="plugin"
            )
        self._mark_dirty(("dial", index))

    # -- Touchstrip --------------------------------------------------------

    async def handle_touch(self, kind: str, value: dict) -> None:
        self.wake()
        x = int(value.get("x", 0))
        y = int(value.get("y", 0))

        # Die Geste klassifiziert die Firmware, nicht wir — dieses Protokoll
        # zeigt, was tatsächlich ankommt, wenn Wischen mal nicht greift.
        log.debug("Touch %-5s %s", kind, value)

        # Wischen gehört dem Gerät, Tippen den Plugins: eine Wischgeste über
        # den Streifen blättert die Seite weiter und wird deshalb nicht mehr
        # an die Belegung darunter durchgereicht.
        if kind == "drag" and self._handle_swipe(value):
            return

        segment_width = max(1, self.device.info.segment_size[0])
        index = max(0, min((self.device.info.dial_count or 4) - 1, x // segment_width))

        slot = self.slot_at("dial", index)
        if slot is None:
            return
        plugin = self.runtime.registry.instance(slot.plugin_id)
        if plugin is None:
            return

        ctx = self.context("dial", index, slot)
        local_x = x - index * segment_width
        try:
            await self.runtime._call_hook(
                plugin.on_touch, slot.action_id, slot.settings, local_x, y, ctx
            )
        except Exception as exc:
            self.runtime._record_error(
                slot.plugin_id, f"on_touch({slot.action_id}): {exc}", source="plugin"
            )
        self._mark_dirty(("dial", index))

    def _handle_swipe(self, value: dict) -> bool:
        """Wertet eine Wischgeste auf dem Touchstrip aus.

        Das Gerät meldet einen durchgehenden Wisch nicht als ein Ereignis,
        sondern in Teilstrecken von je rund 40–120 px — gemessen auf einem
        800 px breiten Streifen. Jede Teilstrecke einzeln zu bewerten hieße,
        die meisten Wischer zu verpassen. Deshalb werden aufeinanderfolgende
        Teilstrecken zu einer Geste aufaddiert und erst gemeinsam bewertet.

        Nach links wischen blättert vorwärts — dieselbe Richtung wie beim
        Umblättern auf einem Telefon.

        Liefert immer ``True``: eine Wischbewegung gehört dem Gerät, nicht
        der Belegung darunter. Andernfalls würde eine zu kurze Teilstrecke
        als Tippen durchgereicht und mitten im Wischen etwa stummschalten.
        """
        settings = self.settings
        if not settings.swipe_switches_page:
            return False

        start_x = int(value.get("x", 0))
        end_x = int(value.get("x_out", start_x))
        start_y = int(value.get("y", 0))
        end_y = int(value.get("y_out", start_y))
        distance = end_x - start_x

        now = time.monotonic()

        # Neue Geste, wenn seit der letzten Teilstrecke eine Pause lag — oder
        # wenn die Richtung kippt: ein Wisch geht in genau eine Richtung, und
        # zwei entgegengesetzte Wischer dürfen sich nicht gegenseitig
        # aufheben.
        gap = now - self._swipe_last_at > SWIPE_GESTURE_GAP_S
        reversed_direction = distance * self._swipe_distance < 0
        if gap or reversed_direction:
            self._swipe_distance = 0.0

        self._swipe_last_at = now

        # Senkrechtes Streifen soll nicht blättern.
        if abs(end_y - start_y) > abs(distance):
            return True

        self._swipe_distance += distance
        threshold = max(10, settings.swipe_min_distance)
        if abs(self._swipe_distance) < threshold:
            return True

        # Eine kurze Sperre nach dem Wechsel: die restlichen Teilstrecken
        # desselben Wischs sollen nicht gleich mehrere Seiten weiterblättern.
        if now >= self._swipe_blocked_until:
            direction = 1 if self._swipe_distance < 0 else -1
            if self.step_page(direction, wrap=settings.swipe_wraps):
                log.debug("Seitenwechsel per Wischen (%+d px)", round(self._swipe_distance))
            self._swipe_blocked_until = now + SWIPE_COOLDOWN_S

        self._swipe_distance = 0.0
        return True

    # ======================================================================
    # Config-Änderungen
    # ======================================================================

    def apply_config(self) -> None:
        """Nach einer Änderung an der Config alles Abhängige auffrischen."""
        profile = self.profile
        if self.current_page_id_value not in profile.pages:
            self.current_page_id_value = profile.root_page().id
        self._contexts.clear()
        self._wallpaper_cache.clear()
        # Ein Dial-Stack kann kürzer geworden sein — dann zeigte der gemerkte
        # Eintrag ins Leere.
        self._stack_index.clear()
        self._turn_count.clear()
        self._turn_direction.clear()
        # Ein laufender Schoner hätte noch die alte Quelle und die alte
        # Helligkeit — beim nächsten Ruhezeitpunkt startet er ohnehin neu.
        self._stop_screensaver()
        self.device.set_brightness(
            self.settings.idle_brightness if self._dimmed else self.settings.brightness
        )
        self._mark_all_dirty()


class DeckView:
    """Was ein Plugin von *seinem* Deck aus erreicht.

    Alles Deck-Bezogene beantwortet die Sitzung, alles andere die Runtime.
    Damit funktioniert bestehender Plugin-Code unverändert — er merkt nur,
    dass ``navigate`` jetzt das richtige von mehreren Geräten trifft.
    """

    __slots__ = ("_deck",)

    def __init__(self, deck: Deck) -> None:
        self._deck = deck

    # Deck-bezogen
    def navigate(self, page_id: str) -> None:
        self._deck.navigate(page_id)

    def navigate_home(self) -> None:
        self._deck.navigate_home()

    def navigate_back(self) -> None:
        self._deck.navigate_back()

    def current_page_id(self) -> str:
        return self._deck.current_page_id()

    def page_number(self) -> int:
        return self._deck.page_number()

    def sibling_pages(self) -> list[Page]:
        return self._deck.sibling_pages()

    def step_page(self, delta: int, *, wrap: bool = True) -> bool:
        return self._deck.step_page(delta, wrap=wrap)

    def request_redraw(self, ctx: SlotContext | None = None) -> None:
        self._deck.request_redraw(ctx)

    async def run_steps(self, steps, ctx, *, repeat: bool = False) -> None:
        await self._deck.run_steps(steps, ctx, repeat=repeat)

    def stop_steps(self, ctx) -> bool:
        return self._deck.stop_steps(ctx)

    def steps_running(self, ctx) -> bool:
        return self._deck.steps_running(ctx)

    def cycle_stack(self, index: int, delta: int = 1) -> bool:
        return self._deck.cycle_stack(index, delta)

    @property
    def deck(self) -> Deck:
        return self._deck

    @property
    def device(self):
        return self._deck.device

    @property
    def device_settings(self) -> DeviceSettings:
        return self._deck.settings

    # Alles Übrige gehört der Runtime: Registry, Config, Fehler, Speichern.
    def __getattr__(self, name: str) -> Any:
        return getattr(self._deck.runtime, name)
