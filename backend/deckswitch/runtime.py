"""Die laufende Anwendung: Gerät ↔ Belegung ↔ Plugins.

Verantwortlich für
* Laden von Config und Plugins,
* Verbinden/Wiederverbinden des Decks,
* Zeichnen der aktuellen Seite (Tasten und Touchstrip-Segmente),
* Verteilen der Eingaben an die zuständigen Plugins (inkl. Lang-Druck),
* periodischen Tick, Idle-Dimming und Seiten-Navigation.

Nebenläufigkeit: alles Fachliche läuft im asyncio-Loop. Geräte-Events kommen
aus dem Reader-Thread der ``streamdeck``-Bibliothek und werden per
``call_soon_threadsafe`` hereingereicht. Plugin-Hooks dürfen synchron sein —
die laufen dann im Executor, damit ein ``wpctl``-Aufruf nie den Loop blockiert.
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import inspect
import logging
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

from . import events as ev
from . import paths
from .config import (
    Appearance,
    Background,
    Config,
    ConfigLoadError,
    ConfigStore,
    Page,
    Slot,
    TouchWallpaper,
)
from .device import StreamDeckDevice
from .events import EventBus
from .plugins.base import Services, SlotContext
from .plugins.loader import PluginRegistry
from .services import screensaver, wallpaper
from .services.audio import AudioService
from .services.icons import IconService
from .services.render import RenderService

log = logging.getLogger(__name__)

RECONNECT_INTERVAL_S = 3.0

#: Pause zwischen zwei Teilstrecken, ab der eine neue Wischgeste beginnt.
#: Während eines Wischs kommen die Teilstrecken deutlich dichter.
SWIPE_GESTURE_GAP_S = 0.4

#: Sperre nach einem ausgelösten Seitenwechsel, damit die verbleibenden
#: Teilstrecken desselben Wischs nicht gleich mehrere Seiten weiterblättern.
SWIPE_COOLDOWN_S = 0.6

#: So lange wartet eine über streamdeck:// angeforderte Installation auf
#: Bestätigung. Danach verfällt sie — ein Dialog Tage später wäre nur noch
#: verwirrend und ließe sich nicht mehr zuordnen.
INSTALL_REQUEST_TTL_S = 600

#: Ersatz-Hintergrund für Segmente, unter denen ein Seitenbild liegt.
TRANSPARENT_BACKGROUND = Background(kind="solid", color="#00000000")


def _uses_default_background(appearance: Appearance) -> bool:
    """Hat für diese Belegung *niemand* einen Hintergrund gewählt?

    Nur dann darf das Seitenbild durchscheinen. Verglichen wird gegen den
    Auslieferungszustand — wer Farbe, Verlauf oder Bild eingestellt hat,
    meinte das so, und dem wird nichts untergeschoben.
    """
    return appearance.background == Background()


class Runtime:
    def __init__(self, config_path: Path | None = None) -> None:
        self.bus = EventBus()
        self.store = ConfigStore(config_path)
        self.config: Config = self.store.config

        self.audio = AudioService()
        self.icons = IconService()
        self.render = RenderService(self.icons)
        self.registry = PluginRegistry()
        self.device = StreamDeckDevice()

        self._loop: asyncio.AbstractEventLoop | None = None
        self._executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="sd-hook")
        self._contexts: dict[str, SlotContext] = {}
        self._dirty: set[tuple[str, int]] = set()
        self._redraw_all = False
        self._render_event = asyncio.Event()
        self._tasks: list[asyncio.Task] = []

        self.current_page_id_value: str = ""
        self.errors: list[dict[str, Any]] = []
        self.install_requests: list[Any] = []

        # Lang-Druck
        self._press_started: dict[int, float] = {}
        self._long_fired: set[int] = set()
        self._long_timers: dict[int, asyncio.TimerHandle] = {}

        #: Belegung samt Seite, die eine gedrückte Taste beim Drücken hatte.
        #: Öffnet der Druck einen Ordner, liegt beim Loslassen längst eine
        #: andere Belegung an dieser Stelle — die darf den Rest des Drucks
        #: nicht abbekommen.
        self._held_slots: dict[int, tuple[str, Slot]] = {}

        # Idle-Dimming
        self._last_input = time.monotonic()
        self._dimmed = False

        # Bildschirmschoner: läuft als eigene Aufgabe, solange er zu sehen ist.
        self._screensaver_task: asyncio.Task | None = None

        # Zerlegtes Touchstrip-Hintergrundbild — ändert sich selten.
        self._wallpaper_cache = wallpaper.WallpaperCache()

        # Wischgesten: aufsummierte Strecke der laufenden Geste
        self._swipe_distance = 0.0
        self._swipe_last_at = 0.0
        self._swipe_blocked_until = 0.0

    # ======================================================================
    # Start / Stop
    # ======================================================================

    async def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        self.bus.bind_loop(self._loop)
        paths.ensure_dirs()

        try:
            self.config = self.store.load()
        except ConfigLoadError as exc:
            self.config = self.store.config
            self._record_error("config", str(exc))

        self.current_page_id_value = self.config.active_profile().root_page().id
        self.load_plugins()

        self.audio.add_listener(self._on_audio_event)
        self.audio.start_watcher()

        self.device.on_key = self._key_event_threadsafe
        self.device.on_dial_rotate = self._dial_rotate_threadsafe
        self.device.on_dial_push = self._dial_push_threadsafe
        self.device.on_touch = self._touch_threadsafe
        self.device.on_disconnect = lambda: self._publish_device_state_threadsafe()

        await self._setup_plugins()

        self._tasks = [
            asyncio.create_task(self._render_loop(), name="render"),
            asyncio.create_task(self._tick_loop(), name="tick"),
            asyncio.create_task(self._connection_loop(), name="connection"),
        ]

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._tasks.clear()

        for timer in self._long_timers.values():
            timer.cancel()
        self._long_timers.clear()

        self.audio.stop_watcher()

        for loaded in self.registry.code_plugins:
            if loaded.instance is not None:
                try:
                    await loaded.instance.teardown()
                except Exception:
                    log.exception("teardown von '%s' fehlgeschlagen", loaded.id)

        # Erst warten, bis kein Worker mehr am Gerät hängt: ein noch laufendes
        # device.open() im Executor und ein gleichzeitiges close() hier greifen
        # sonst zeitgleich auf dasselbe libusb-Handle zu — das endet in einer
        # Assertion tief in libusb, nicht in einer Python-Exception.
        self._executor.shutdown(wait=True)
        self.device.clear()
        self.device.close()

    # ======================================================================
    # Plugins
    # ======================================================================

    def load_plugins(self) -> None:
        self.registry.discover(
            self._services_for,
            disabled=self.config.disabled_plugins,
        )
        self.icons.bind_registry(self.registry)
        for error in self.registry.errors:
            self._record_error(
                error.plugin_id, error.message, source="plugin", traceback=error.traceback
            )

    def _services_for(self, plugin_dir: Path) -> Services:
        return Services(
            audio=self.audio,
            icons=self.icons,
            render=self.render,
            runtime=self,
            config=self.config,
            plugin_dir=plugin_dir,
        )

    async def _setup_plugins(self) -> None:
        for loaded in self.registry.code_plugins:
            if loaded.instance is None or not loaded.enabled:
                continue
            try:
                await loaded.instance.setup()
            except Exception as exc:
                loaded.error = f"setup: {type(exc).__name__}: {exc}"
                self._record_error(
                    loaded.id, loaded.error, source="plugin", traceback=traceback.format_exc()
                )

    async def reload_plugins(self) -> None:
        """Plugins neu einlesen — nach Installation oder Aktivierungswechsel."""
        for loaded in self.registry.code_plugins:
            if loaded.instance is not None:
                with contextlib.suppress(Exception):
                    await loaded.instance.teardown()
        self._contexts.clear()
        self.errors = [e for e in self.errors if e.get("source") != "plugin"]
        self.load_plugins()
        await self._setup_plugins()
        self.request_redraw()
        self.bus.publish(ev.EVT_CONFIG_CHANGED, reason="plugins_reloaded")

    # ======================================================================
    # RuntimeApi — was Plugins aufrufen dürfen
    # ======================================================================

    def request_redraw(self, ctx: SlotContext | None = None) -> None:
        """Threadsicher: sofortiges Neuzeichnen anstoßen."""
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        if ctx is None:
            loop.call_soon_threadsafe(self._mark_all_dirty)
        else:
            target = (ctx.input_type, ctx.index)
            page_id = ctx.page_id
            loop.call_soon_threadsafe(self._mark_dirty, target, page_id)

    def _mark_dirty(self, target: tuple[str, int], page_id: str | None = None) -> None:
        if page_id is not None and page_id != self.current_page_id_value:
            return  # Belegung liegt auf einer Seite, die gerade nicht sichtbar ist
        self._dirty.add(target)
        self._render_event.set()

    def _mark_all_dirty(self) -> None:
        self._redraw_all = True
        self._render_event.set()

    def navigate(self, page_id: str) -> None:
        profile = self.config.active_profile()
        if page_id not in profile.pages:
            self.notify("warning", f"Seite '{page_id}' existiert nicht")
            return
        self.current_page_id_value = page_id
        self._contexts.clear()
        self._mark_all_dirty()
        self.bus.publish(ev.EVT_PAGE_CHANGED, page_id=page_id)

    def navigate_home(self) -> None:
        self.navigate(self.config.active_profile().root_page().id)

    def navigate_back(self) -> None:
        profile = self.config.active_profile()
        page = profile.pages.get(self.current_page_id_value)
        if page is None or page.parent_id is None:
            self.navigate_home()
            return
        self.navigate(page.parent_id)

    def current_page_id(self) -> str:
        return self.current_page_id_value

    def page_number(self) -> int:
        """1-basierte Position der aktuellen Seite unter ihren Geschwistern."""
        siblings = self.sibling_pages()
        for i, page in enumerate(siblings):
            if page.id == self.current_page_id_value:
                return i + 1
        return 1

    def sibling_pages(self) -> list[Page]:
        profile = self.config.active_profile()
        current = profile.pages.get(self.current_page_id_value)
        parent_id = current.parent_id if current else None
        # Über ``children`` und nicht über die Dict-Reihenfolge: was der User
        # in der GUI sortiert, ist auch die Reihenfolge beim Wischen.
        return profile.children(parent_id)

    def step_page(self, delta: int, *, wrap: bool = True) -> bool:
        """Blättert innerhalb der Geschwister-Seiten weiter.

        Gemeinsame Grundlage für die Blätter-Aktionen des Streamdeck-Plugins
        und für das Wischen über den Touchstrip. Liefert ``True``, wenn
        tatsächlich gewechselt wurde.
        """
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
    # Installationsanfragen über streamdeck://
    # ======================================================================

    def add_install_request(self, url: str, origin: str = "") -> "InstallRequest":
        """Merkt eine angeforderte Installation vor — ohne sie auszuführen.

        Ein Klick auf einen Link im Browser darf niemals ungefragt Code
        installieren. Die Anfrage landet hier und wird erst nach Bestätigung
        in der GUI ausgeführt.
        """
        from .plugins.installer import InstallRequest

        now = time.time()
        self._expire_install_requests(now)

        request = InstallRequest(
            id=uuid.uuid4().hex[:12], url=url, origin=origin, created_at=now
        )
        self.install_requests.append(request)
        del self.install_requests[:-10]
        self.bus.publish(ev.EVT_INSTALL_REQUEST, **request.as_dict())
        log.info("Installationsanfrage über streamdeck://: %s", url)
        return request

    def take_install_request(self, request_id: str) -> "InstallRequest | None":
        self._expire_install_requests(time.time())
        for i, request in enumerate(self.install_requests):
            if request.id == request_id:
                return self.install_requests.pop(i)
        return None

    def pending_install_requests(self) -> list[dict[str, Any]]:
        self._expire_install_requests(time.time())
        return [r.as_dict() for r in self.install_requests]

    def _expire_install_requests(self, now: float) -> None:
        """Alte Anfragen verwerfen — sonst poppt Tage später ein Dialog auf."""
        self.install_requests = [
            r for r in self.install_requests if now - r.created_at < INSTALL_REQUEST_TTL_S
        ]

    def publish_plugin_status(self, plugin_id: str) -> None:
        """Verbindungszustand eines Plugins an die GUI melden. Threadsicher."""
        loaded = self.registry.get(plugin_id)
        status = None
        if loaded is not None and loaded.instance is not None:
            try:
                status = loaded.instance.get_status()
            except Exception as exc:
                log.debug("get_status von '%s' fehlgeschlagen: %s", plugin_id, exc)
        self.bus.publish_threadsafe(
            ev.EVT_PLUGIN_STATE, plugin_id=plugin_id, status=status
        )

    def plugin_status(self, plugin_id: str) -> dict[str, Any] | None:
        loaded = self.registry.get(plugin_id)
        if loaded is None or loaded.instance is None:
            return None
        try:
            return loaded.instance.get_status()
        except Exception as exc:
            log.debug("get_status von '%s' fehlgeschlagen: %s", plugin_id, exc)
            return None

    def notify(self, level: str, message: str, **extra: Any) -> None:
        log.log(
            {"error": logging.ERROR, "warning": logging.WARNING}.get(level, logging.INFO),
            "%s",
            message,
        )
        # plugin_id geht als eigenes Argument weiter — es darf nicht
        # zusätzlich in **extra stecken, sonst kommt es doppelt an.
        plugin_id = extra.pop("plugin_id", "")
        self._record_error(plugin_id, message, level=level, **extra)

    def save_config(self) -> None:
        self.store.save(self.config)

    # ======================================================================
    # Fehlerzustände (die GUI zeigt sie an, statt sie im Log zu verlieren)
    # ======================================================================

    def _record_error(
        self,
        plugin_id: str,
        message: str,
        *,
        level: str = "error",
        source: str = "runtime",
        **extra: Any,
    ) -> None:
        # Wiederholt sich derselbe Fehler (etwa weil er bei jedem Tick
        # auftritt), wird mitgezählt statt die Liste zuzumüllen — sonst
        # verdeckt ein einziges hakendes Plugin binnen Sekunden alles andere.
        for existing in reversed(self.errors[-10:]):
            if existing["plugin_id"] == plugin_id and existing["message"] == message:
                existing["count"] = existing.get("count", 1) + 1
                existing["time"] = time.time()
                self.bus.publish(ev.EVT_PLUGIN_ERROR, **existing)
                return

        entry = {
            "plugin_id": plugin_id,
            "message": message,
            "level": level,
            "source": source,
            "time": time.time(),
            "count": 1,
            **{k: v for k, v in extra.items() if k != "plugin_id"},
        }
        self.errors.append(entry)
        del self.errors[:-100]
        self.bus.publish(ev.EVT_PLUGIN_ERROR, **entry)

    def clear_errors(self) -> None:
        self.errors.clear()
        self.bus.publish(ev.EVT_PLUGIN_ERROR, cleared=True)

    # ======================================================================
    # Verbindung
    # ======================================================================

    async def _connection_loop(self) -> None:
        while True:
            if not self.device.connected:
                opened = await asyncio.get_running_loop().run_in_executor(
                    self._executor, self.device.open
                )
                if opened:
                    self.device.set_brightness(self.config.device.brightness)
                    self._dimmed = False
                    self._last_input = time.monotonic()
                    self._mark_all_dirty()
                self._publish_device_state()
            await asyncio.sleep(RECONNECT_INTERVAL_S)

    def _publish_device_state(self) -> None:
        self.bus.publish(ev.EVT_DEVICE_STATE, **self.device.info.as_dict())

    def _publish_device_state_threadsafe(self) -> None:
        loop = self._loop
        if loop is not None and not loop.is_closed():
            loop.call_soon_threadsafe(self._publish_device_state)

    # ======================================================================
    # Belegungen und Kontexte
    # ======================================================================

    @property
    def current_page(self) -> Page:
        return self.config.page(self.current_page_id_value)

    def slot_at(self, input_type: str, index: int) -> Slot | None:
        page = self.current_page
        return (page.keys if input_type == "key" else page.dials).get(index)

    def _context(
        self, input_type: str, index: int, slot: Slot, page_id: str | None = None
    ) -> SlotContext:
        """Kontext je Belegung, mit stabilem ``scratch`` über Aufrufe hinweg.

        ``page_id`` ist die Seite, zu der die Belegung gehört — nicht
        zwangsläufig die gerade sichtbare: ein Tastendruck kann die Seite
        wechseln und wird trotzdem auf seiner Ursprungsseite zu Ende gebracht.
        """
        if page_id is None:
            page_id = self.current_page_id_value
        key = f"{page_id}:{input_type}:{index}"
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

        ctx = SlotContext(
            action_id=slot.action_id,
            settings=slot.settings,
            appearance=slot.appearance,
            input_type=input_type,  # type: ignore[arg-type]
            index=index,
            page_id=page_id,
            profile_id=self.config.active_profile_id,
            size=size,
            services=self._services_for(
                self.registry.get(slot.plugin_id).directory
                if self.registry.get(slot.plugin_id)
                else Path()
            ),
            slot=slot,
            scratch=existing.scratch if existing else {},
        )
        self._contexts[key] = ctx
        return ctx

    # ======================================================================
    # Rendering
    # ======================================================================

    async def _render_loop(self) -> None:
        # Erstes Zeichnen anstoßen, sobald der Loop läuft.
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
        dials = self.device.info.dial_count or 4
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

        if input_type == "key":
            image = (
                self.render.empty_slot(size)
                if slot is None
                else await self._render_slot(slot, input_type, index, size)
            )
            self.device.set_key_image(index, image)
            return

        # Touchstrip: erst das Seitenbild, dann die Belegung darüber.
        base = self._wallpaper_segment(self.current_page, index, size)

        if slot is None:
            image = base if base is not None else self.render.blank(size)
        else:
            image = await self._render_slot(
                slot, input_type, index, size, transparent_background=base is not None
            )
            if base is not None:
                merged = base.copy()
                merged.alpha_composite(image.convert("RGBA"))
                image = merged

        self.device.set_touchscreen_image(image, x=index * size[0], y=0)

    def _wallpaper_segment(
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
        count = self.device.info.dial_count or 4
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
            segments = self._build_wallpaper(settings, strip, count)
        except Exception as exc:
            self._record_error(
                settings.source, f"Hintergrundbild nicht ladbar: {exc}", source="wallpaper"
            )
            # Leeres Ergebnis merken, damit nicht jedes Neuzeichnen erneut
            # scheitert und die Fehlerliste flutet.
            self._wallpaper_cache.put(key, [])
            return []

        self._wallpaper_cache.put(key, segments)
        return segments

    def _build_wallpaper(self, settings, strip, count) -> list[Image.Image]:
        kind, _, name = settings.source.partition(":")

        if kind == "plugin":
            loaded = self.registry.plugins.get(name)
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

    async def _render_slot(
        self,
        slot: Slot,
        input_type: str,
        index: int,
        size: tuple[int, int],
        *,
        transparent_background: bool = False,
    ) -> Image.Image:
        plugin = self.registry.instance(slot.plugin_id)
        if plugin is None:
            return self.render.error_slot(size, slot.plugin_id or "?")

        ctx = self._context(input_type, index, slot)
        if transparent_background and _uses_default_background(slot.appearance):
            # Ein Seitenbild liegt darunter. Der Standard-Hintergrund ist
            # deckendes Schwarz und würde es vollständig verdecken — also
            # hier durchsichtig zeichnen. Wer für dieses Segment bewusst
            # eine Farbe gewählt hat, behält sie.
            # Kopie, nicht am Original ändern: ``_context`` gibt gecachte
            # Instanzen zurück, die auch die Eingabe-Hooks benutzen.
            ctx = dataclasses.replace(
                ctx,
                appearance=slot.appearance.model_copy(
                    update={"background": TRANSPARENT_BACKGROUND}
                ),
            )
        try:
            image = await self._call_hook(
                plugin.render, slot.action_id, slot.settings, ctx
            )
        except Exception as exc:
            self._record_error(
                slot.plugin_id,
                f"render({slot.action_id}): {type(exc).__name__}: {exc}",
                source="plugin",
                traceback=traceback.format_exc(),
            )
            return self.render.error_slot(size, slot.action_id)

        if not isinstance(image, Image.Image):
            return self.render.error_slot(size, "kein Bild")
        if image.size != size:
            image = image.resize(size, Image.LANCZOS)
        return image

    async def render_preview(
        self, page_id: str, input_type: str, index: int
    ) -> Image.Image:
        """Einzelne Kachel für die GUI-Vorschau zeichnen.

        Nutzt denselben Weg wie das Gerät, damit die Vorschau nicht
        auseinanderläuft.
        """
        profile = self.config.active_profile()
        page = profile.pages.get(page_id) or profile.root_page()
        slot = (page.keys if input_type == "key" else page.dials).get(index)
        size = (
            self.device.info.key_size
            if input_type == "key"
            else self.device.info.segment_size
        )
        # Das Seitenbild gehört auch in die Vorschau — sonst zeigte die GUI
        # etwas anderes als das Gerät, und genau dafür ist sie da.
        base = (
            self._wallpaper_segment(page, index, size) if input_type == "dial" else None
        )

        if slot is None:
            if input_type == "key":
                return self.render.empty_slot(size)
            return base if base is not None else self.render.blank(size)

        image: Image.Image | None = None

        # Vorschau einer *anderen* Seite darf den Live-Kontext nicht stören.
        if page_id != self.current_page_id_value:
            appearance = slot.appearance
            if base is not None and _uses_default_background(appearance):
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
                services=self._services_for(Path()),
                slot=slot,
            )
            plugin = self.registry.instance(slot.plugin_id)
            if plugin is None:
                return self.render.error_slot(size, slot.plugin_id or "?")
            try:
                rendered = await self._call_hook(
                    plugin.render, slot.action_id, slot.settings, ctx
                )
            except Exception:
                return self.render.error_slot(size, slot.action_id)
            image = rendered if isinstance(rendered, Image.Image) else self.render.error_slot(size)
        else:
            image = await self._render_slot(
                slot, input_type, index, size, transparent_background=base is not None
            )

        if base is None:
            return image
        merged = base.copy()
        merged.alpha_composite(image.convert("RGBA"))
        return merged

    # ======================================================================
    # Tick und Idle-Dimming
    # ======================================================================

    async def _tick_loop(self) -> None:
        while True:
            interval = max(0.1, self.config.device.tick_interval_s)
            await asyncio.sleep(interval)
            self._check_idle()
            if not self.device.connected:
                continue

            page = self.current_page
            for input_type, mapping in (("key", page.keys), ("dial", page.dials)):
                for index, slot in list(mapping.items()):
                    plugin = self.registry.instance(slot.plugin_id)
                    if plugin is None:
                        continue
                    ctx = self._context(input_type, index, slot)
                    try:
                        await self._call_hook(
                            plugin.on_tick, slot.action_id, slot.settings, ctx
                        )
                    except Exception as exc:
                        self._record_error(
                            slot.plugin_id,
                            f"on_tick({slot.action_id}): {exc}",
                            source="plugin",
                        )

    def _check_idle(self) -> None:
        settings = self.config.device
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
            self.bus.publish(ev.EVT_DEVICE_STATE, dimmed=True, **self.device.info.as_dict())

        saver = settings.screensaver
        if (
            saver.enabled
            and saver.source
            and saver.after_s > 0
            and self._screensaver_task is None
            and idle_for >= saver.after_s
        ):
            self._screensaver_task = asyncio.create_task(
                self._screensaver_loop(), name="screensaver"
            )

    def _wake(self) -> None:
        self._last_input = time.monotonic()
        self._stop_screensaver()
        if self._dimmed:
            self._dimmed = False
            self.device.set_brightness(self.config.device.brightness)
            self.bus.publish(ev.EVT_DEVICE_STATE, dimmed=False, **self.device.info.as_dict())

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
            self.config.device.idle_brightness if self._dimmed else self.config.device.brightness
        )
        # Der Schoner hat jede Kachel überschrieben — alles neu zeichnen.
        self._mark_all_dirty()
        self.bus.publish(ev.EVT_DEVICE_STATE, screensaver=False, **self.device.info.as_dict())

    async def _screensaver_loop(self) -> None:
        """Zeigt den Schoner, bis die Aufgabe abgebrochen wird."""
        settings = self.config.device.screensaver
        deck = screensaver.layout(
            self.device.info.key_size,
            self.device.info.key_count or 8,
            self.device.info.touchscreen_size,
        )

        try:
            frames, plugin = self._screensaver_source(settings.source, deck)
        except Exception as exc:
            self._record_error(
                settings.source, f"Schoner nicht ladbar: {exc}", source="screensaver"
            )
            self._screensaver_task = None
            return

        if frames is None and plugin is None:
            self._screensaver_task = None
            return

        self.device.set_brightness(settings.brightness)
        self.bus.publish(ev.EVT_DEVICE_STATE, screensaver=True, **self.device.info.as_dict())

        started = time.monotonic()
        try:
            if plugin is not None:
                await self._run_screensaver_plugin(plugin, deck, settings, started)
            else:
                await self._run_screensaver_frames(frames)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._record_error(
                settings.source, f"Schoner abgebrochen: {exc}", source="screensaver",
                traceback=traceback.format_exc(),
            )

    def _screensaver_source(self, source: str, deck) -> tuple[list | None, Any]:
        """Löst ``upload:…`` bzw. ``plugin:…`` auf."""
        kind, _, name = source.partition(":")

        if kind == "plugin":
            loaded = self.registry.plugins.get(name)
            if loaded is None or not loaded.enabled or loaded.instance is None:
                raise ValueError(f"Schoner-Plugin '{name}' ist nicht verfügbar")
            return None, loaded.instance

        if kind == "upload":
            path = paths.image_path(name)
            if path is None:
                raise FileNotFoundError(f"Datei nicht gefunden: {name}")
            with Image.open(path) as image:
                return screensaver.load_frames(
                    image, deck, self.config.device.screensaver.fit
                ), None

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

    async def _run_screensaver_plugin(self, plugin, deck, settings, started: float) -> None:
        """Lässt ein Plugin zeichnen — einmalig oder fortlaufend."""
        # Damit ein Plugin etwas pro Taste zeigen kann, muss es wissen, wo
        # die Schnitte verlaufen.
        plugin.deck_layout = deck
        while True:
            elapsed = time.monotonic() - started
            try:
                image = plugin.render(deck.canvas, elapsed)
            except Exception as exc:
                self._record_error(
                    plugin.manifest.id, f"Schoner render(): {exc}", source="plugin",
                    traceback=traceback.format_exc(),
                )
                return

            if image is not None:
                canvas = screensaver.fit(image, deck.canvas, settings.fit)
                keys, strip = screensaver.split(canvas, deck)
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

    def wallpaper_preview(
        self, source: str, *, fit: str = "cover", opacity: int = 100
    ) -> Image.Image:
        """Baut den Streifen für die GUI-Vorschau.

        Quelle, Einpassung und Deckkraft kommen von außen — damit lässt sich
        ein Bild samt Wirkung ansehen, bevor es der Seite zugewiesen wird.
        """
        settings = TouchWallpaper(
            enabled=True, source=source, fit=fit, opacity=max(1, min(100, opacity))
        )
        segments = self._build_wallpaper(
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

    def start_screensaver_now(self) -> None:
        """Startet den Schoner sofort — für den Ausprobieren-Knopf."""
        if self._screensaver_task is not None:
            return
        self._screensaver_task = asyncio.create_task(
            self._screensaver_loop(), name="screensaver"
        )

    def screensaver_preview(self, source: str, deck) -> Image.Image:
        """Baut ein Vorschaubild, wie der Schoner auf dem Deck ankommt.

        Nicht einfach die Quelldatei ausliefern: Interessant ist ja gerade,
        wie das Motiv nach dem Zerschneiden wirkt. Die Fugen werden deshalb
        schwarz eingezeichnet — was dort verschwindet, sieht man später am
        Gerät auch nicht.
        """
        frames, plugin = self._screensaver_source(source, deck)
        if plugin is not None:
            plugin.deck_layout = deck
            image = plugin.render(deck.canvas, 0.0)
            if image is None:
                raise ValueError("Das Plugin hat kein Bild geliefert")
            canvas = screensaver.fit(image, deck.canvas, self.config.device.screensaver.fit)
            keys, strip = screensaver.split(canvas, deck)
        else:
            if not frames:
                raise ValueError("Kein Einzelbild gefunden")
            keys, strip = frames[0].keys, frames[0].strip

        preview = Image.new("RGBA", deck.canvas, (0, 0, 0, 255))
        for (x, y, w, h), image in zip(deck.keys, keys):
            preview.paste(image.resize((w, h), Image.LANCZOS), (x, y))
        x, y, w, h = deck.strip
        preview.paste(strip.resize((w, h), Image.LANCZOS), (x, y))
        return preview

    # ======================================================================
    # Eingaben — Einstieg aus dem Reader-Thread
    # ======================================================================

    def _dispatch(self, coro_factory) -> None:
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        loop.call_soon_threadsafe(lambda: asyncio.ensure_future(coro_factory()))

    def _key_event_threadsafe(self, index: int, pressed: bool) -> None:
        self._dispatch(lambda: self._handle_key(index, pressed))

    def _dial_rotate_threadsafe(self, index: int, delta: int) -> None:
        self._dispatch(lambda: self._handle_dial_rotate(index, delta))

    def _dial_push_threadsafe(self, index: int, pressed: bool) -> None:
        self._dispatch(lambda: self._handle_dial_push(index, pressed))

    def _touch_threadsafe(self, kind: str, value: dict) -> None:
        self._dispatch(lambda: self._handle_touch(kind, value))

    # -- Tasten ------------------------------------------------------------

    async def _handle_key(self, index: int, pressed: bool) -> None:
        self._wake()

        if pressed:
            slot = self.slot_at("key", index)
            if slot is None:
                return

            # Die Taste gehört ab jetzt dieser Belegung — auch wenn der Druck
            # gleich die Seite wechselt.
            page_id = self.current_page_id_value
            self._held_slots[index] = (page_id, slot)
            self._press_started[index] = time.monotonic()
            self._long_fired.discard(index)

            if slot.long_press is None:
                # Ohne Zweitbelegung sofort auslösen — kein künstlicher Verzug.
                await self._fire_key(slot, index, page_id, down=True)
                return

            # Mit Zweitbelegung muss erst feststehen, ob kurz oder lang.
            loop = asyncio.get_running_loop()
            delay = max(0.05, self.config.device.long_press_ms / 1000)
            handle = loop.call_later(
                delay, lambda: asyncio.ensure_future(self._fire_long_press(index))
            )
            self._long_timers[index] = handle
            return

        # Loslassen
        timer = self._long_timers.pop(index, None)
        if timer is not None:
            timer.cancel()
        started = self._press_started.pop(index, None)
        held = self._held_slots.pop(index, None)
        if held is None:
            # Kein zugehöriger Druck (z. B. Taste war beim Start schon unten).
            self._long_fired.discard(index)
            return
        page_id, slot = held

        if index in self._long_fired:
            self._long_fired.discard(index)
            if slot.long_press is not None:
                await self._fire_key(slot.long_press, index, page_id, down=False, long=True)
            return

        if slot.long_press is not None and started is not None:
            # Kurzer Druck: jetzt nachholen, was beim Drücken verzögert wurde.
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
        self, slot: Slot, index: int, page_id: str, *, down: bool, long: bool = False
    ) -> None:
        plugin = self.registry.instance(slot.plugin_id)
        if plugin is None:
            self._record_error(slot.plugin_id, f"Plugin '{slot.plugin_id}' nicht geladen")
            return
        ctx = self._context("key", index, slot, page_id=page_id)
        ctx.is_long_press = long
        hook = plugin.on_key_down if down else plugin.on_key_up
        try:
            await self._call_hook(hook, slot.action_id, slot.settings, ctx)
        except Exception as exc:
            self._record_error(
                slot.plugin_id,
                f"{'on_key_down' if down else 'on_key_up'}({slot.action_id}): {exc}",
                source="plugin",
                traceback=traceback.format_exc(),
            )
        self._mark_dirty(("key", index))

    # -- Dials -------------------------------------------------------------

    async def _handle_dial_rotate(self, index: int, delta: int) -> None:
        self._wake()
        slot = self.slot_at("dial", index)
        if slot is None:
            return
        plugin = self.registry.instance(slot.plugin_id)
        if plugin is None:
            return
        ctx = self._context("dial", index, slot)
        try:
            await self._call_hook(
                plugin.on_dial_rotate, slot.action_id, slot.settings, delta, ctx
            )
        except Exception as exc:
            self._record_error(
                slot.plugin_id, f"on_dial_rotate({slot.action_id}): {exc}", source="plugin"
            )
        self._mark_dirty(("dial", index))

    async def _handle_dial_push(self, index: int, pressed: bool) -> None:
        self._wake()
        if not pressed:
            return
        slot = self.slot_at("dial", index)
        if slot is None:
            return
        plugin = self.registry.instance(slot.plugin_id)
        if plugin is None:
            return
        ctx = self._context("dial", index, slot)
        try:
            await self._call_hook(
                plugin.on_dial_push, slot.action_id, slot.settings, ctx
            )
        except Exception as exc:
            self._record_error(
                slot.plugin_id, f"on_dial_push({slot.action_id}): {exc}", source="plugin"
            )
        self._mark_dirty(("dial", index))

    # -- Touchstrip --------------------------------------------------------

    async def _handle_touch(self, kind: str, value: dict) -> None:
        self._wake()
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
        plugin = self.registry.instance(slot.plugin_id)
        if plugin is None:
            return

        ctx = self._context("dial", index, slot)
        local_x = x - index * segment_width
        try:
            await self._call_hook(
                plugin.on_touch, slot.action_id, slot.settings, local_x, y, ctx
            )
        except Exception as exc:
            self._record_error(
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
        settings = self.config.device
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
    # Externe Ereignisse
    # ======================================================================

    def _on_audio_event(self, event: str, facility: str) -> None:
        """Aus dem ``pactl subscribe``-Thread: Audio hat sich von außen geändert."""
        self.request_redraw()
        self.bus.publish_threadsafe(ev.EVT_PLUGIN_STATE, plugin_id="audio", event=event,
                                    facility=facility)

    # ======================================================================
    # Config-Änderungen aus der GUI
    # ======================================================================

    def apply_config(self, config: Config, *, save: bool = True) -> None:
        """Übernimmt eine geänderte Config sofort — ohne Neustart des Backends."""
        self.config = config
        self.store.config = config
        if save:
            self.store.save(config)

        profile = config.active_profile()
        if self.current_page_id_value not in profile.pages:
            self.current_page_id_value = profile.root_page().id

        # Services tragen eine Config-Referenz — die muss mitwandern.
        for loaded in self.registry.code_plugins:
            if loaded.instance is not None:
                loaded.instance.services.config = config

        self._contexts.clear()
        self.icons.clear_cache()
        self._wallpaper_cache.clear()
        # Ein laufender Schoner hätte noch die alte Quelle und die alte
        # Helligkeit — beim nächsten Ruhezeitpunkt startet er ohnehin neu.
        self._stop_screensaver()
        self.device.set_brightness(
            config.device.idle_brightness if self._dimmed else config.device.brightness
        )
        self._mark_all_dirty()
        self.bus.publish(ev.EVT_CONFIG_CHANGED)

    def notify_plugin_config_changed(self, plugin_id: str) -> None:
        plugin = self.registry.instance(plugin_id)
        if plugin is None:
            return
        try:
            plugin.on_plugin_config_changed(
                self.config.plugin_settings.get(plugin_id, {})
            )
        except Exception as exc:
            self._record_error(plugin_id, f"on_plugin_config_changed: {exc}", source="plugin")

    # ======================================================================
    # Hilfen
    # ======================================================================

    async def _call_hook(self, hook, *args) -> Any:
        """Ruft einen Plugin-Hook auf, egal ob sync oder async.

        Synchrone Hooks landen im Executor: Plugins dürfen ``subprocess`` &
        Co. benutzen, ohne den Event-Loop anzuhalten.
        """
        if inspect.iscoroutinefunction(hook):
            return await hook(*args)
        result = await asyncio.get_running_loop().run_in_executor(
            self._executor, lambda: hook(*args)
        )
        if inspect.isawaitable(result):
            return await result
        return result
