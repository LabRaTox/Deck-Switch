"""Die laufende Anwendung: Geräte ↔ Belegungen ↔ Plugins.

Verantwortlich für alles, was sich **mehrere Decks teilen**:

* Config und Plugins laden,
* angeschlossene Geräte finden und an ihre Bindung hängen,
* Dienste bereitstellen (Audio, Eingabe, Medien, Desktop, Soundboard),
* Fehler sammeln und an die GUI melden.

Alles, was einem *einzelnen* Deck gehört — aktuelle Seite, Tastenlogik,
Zeichnen, Bildschirmschoner, Dial-Stack, laufende Multi-Aktionen — steckt in
:class:`deckswitch.deck.Deck`. Diese Trennung ist die ganze Mehrgeräte-
Unterstützung: Zwei Decks sind zwei Sitzungen auf denselben Plugins.

Nebenläufigkeit: alles Fachliche läuft im asyncio-Loop. Geräte-Events kommen
aus dem Reader-Thread der ``streamdeck``-Bibliothek und werden per
``call_soon_threadsafe`` hereingereicht. Plugin-Hooks dürfen synchron sein —
die laufen dann im Executor, damit ein ``wpctl``-Aufruf nie den Loop anhält.
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import logging
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from . import device as device_module
from . import events as ev
from . import paths
from .config import Config, ConfigLoadError, ConfigStore, DeckBinding, Page, Profile, Slot
from .netserver import NetzService
from .virtualdeck import DECK_TYPE as VIRTUAL_DECK_TYPE
from .virtualdeck import NETWORK_DECK_TYPE
from .virtualdeck import VirtualDevice
from .deck import Deck
from .events import EventBus
from .plugins.base import Services, SlotContext
from .plugins.loader import PluginRegistry
from .services.audio import AudioService
from .services.desktop import DesktopService
from .services.icons import IconService
from .services.input import InputService
from .services.media import MediaService
from .services.overlay import OverlayService
from .services.render import RenderService
from .services.session import SessionCapabilities
from .services.shortcuts import ShortcutService
from .services.sound import SoundService

log = logging.getLogger(__name__)

RECONNECT_INTERVAL_S = 3.0

#: So lange wartet eine über streamdeck:// angeforderte Installation auf
#: Bestätigung. Danach verfällt sie — ein Dialog Tage später wäre nur noch
#: verwirrend und ließe sich nicht mehr zuordnen.
INSTALL_REQUEST_TTL_S = 600


class Runtime:
    def __init__(self, config_path: Path | None = None) -> None:
        self.bus = EventBus()
        self.store = ConfigStore(config_path)
        self.config: Config = self.store.config

        #: Was diese Sitzung hergibt. Gefüllt wird es in :meth:`start`;
        #: bis dahin meldet es alles als nicht verfügbar. Die Oberfläche
        #: fragt es ab, um Aktionen gar nicht erst anzubieten, die hier
        #: ohnehin stumm blieben.
        self.session = SessionCapabilities()

        self.audio = AudioService()
        self.icons = IconService()
        self.render = RenderService(self.icons)
        self.registry = PluginRegistry()

        # Dienste für die Systemaktionen. Alle bauen ihre Verbindung erst
        # beim ersten Gebrauch auf — wer nur Lautstärke regelt, bekommt kein
        # virtuelles Eingabegerät ins System gehängt.
        self.input = InputService()
        self.media = MediaService()
        self.media.bind_input(self.input)
        self.desktop = DesktopService()
        self.sound = SoundService()
        self.sound.on_finished = lambda owner: self.request_redraw()
        #: Zeigt und versteckt die Overlays der virtuellen Decks.
        self.overlay = OverlayService(self)
        #: Holt dieselben Overlays per globalem Kurzbefehl.
        self.shortcuts = ShortcutService(self)
        self.netz = NetzService(self)

        self._loop: asyncio.AbstractEventLoop | None = None
        self._executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="sd-hook")
        self._tasks: list[asyncio.Task] = []

        #: Bindungs-ID (Seriennummer) → Sitzung.
        self.decks: dict[str, Deck] = {}
        #: Geräteknoten der Decks, die wir schon offen haben.
        self._open_paths: dict[str, str] = {}

        self.errors: list[dict[str, Any]] = []
        self.install_requests: list[Any] = []

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

        # Vor allem anderen abtasten, was die Sitzung kann: Die Plugins
        # bekommen das Ergebnis beim Laden mit, und die Aktionsbibliothek
        # richtet sich danach. Kostet neun Millisekunden — es wird nichts
        # ausgeführt, nur nachgesehen.
        await self.session.detect()

        # Der Desktop-Dienst braucht beides: zu wissen, was die Sitzung
        # hergibt, und einen Griff in den Event-Loop — seine Aktionen
        # laufen in einem Arbeitsthread, das Portal spricht asyncio.
        self.desktop.bind_session(self.session, self._loop)

        self.config.ensure_decks()
        self._sync_decks()
        self.load_plugins()

        self.audio.add_listener(self._on_audio_event)
        self.audio.start_watcher()

        await self._setup_plugins()

        for deck in self.decks.values():
            deck.start()

        # Netz-Decks anbieten, falls welche eingerichtet sind. Steht bewusst
        # hinter dem Start der Decks: Erst wenn gerendert wird, gibt es auch
        # Kacheln zu holen.
        await self.netz.sync()

        # Kurzbefehle zuletzt: Erst jetzt kann ein Tastendruck auch etwas
        # bewirken — vorher gäbe es kein Deck, das sich zeigen ließe.
        await self.shortcuts.sync()

        self._tasks = [
            asyncio.create_task(self._connection_loop(), name="connection"),
        ]

        # Als Dienst startet das Backend gelegentlich vor dem Sitzungsbus.
        # Dann gälte alles, was daran hängt, dauerhaft als nicht verfügbar —
        # Kurzbefehle, Tray, Fensteraktionen —, obwohl es Sekunden später
        # längst ginge. Deshalb noch einmal nachfassen, aber nur in genau
        # diesem Fall: Fehlt eine Fähigkeit, weil dieser Desktop sie nicht
        # kann, ändert kein Wiederholen etwas daran.
        if not self.session.bus_reachable:
            self._tasks.append(
                asyncio.create_task(self._session_retry_loop(), name="session-retry")
            )

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._tasks.clear()

        for deck in list(self.decks.values()):
            await deck.stop()

        with contextlib.suppress(Exception):
            await self.netz.stop()

        # Vor dem Ende abmelden: Ein Kurzbefehl, hinter dem kein Programm
        # mehr steht, bliebe sonst in den Systemeinstellungen stehen.
        with contextlib.suppress(Exception):
            await self.shortcuts.stop()

        self.audio.stop_watcher()
        self.sound.close()
        self.input.close()
        with contextlib.suppress(Exception):
            await self.overlay.shutdown()
        with contextlib.suppress(Exception):
            await self.media.close()

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

    # ======================================================================
    # Decks
    # ======================================================================

    def _sync_decks(self) -> None:
        """Legt für jede Bindung in der Config eine Sitzung an.

        Virtuelle Decks bekommen ihr „Gerät" gleich mit: Ein Overlay muss
        auf nichts warten, es ist da, sobald es in der Config steht.
        """
        for key, binding in self.config.decks.items():
            if key not in self.decks:
                if not binding.profile_id or binding.profile_id not in self.config.profiles:
                    binding.profile_id = self.config.active_profile().id
                deck = Deck(self, binding)
                self.decks[key] = deck
                if binding.is_virtual:
                    self._attach_virtual(deck)
        for key in [k for k in self.decks if k not in self.config.decks]:
            deck = self.decks.pop(key)
            deck.detach()

    def _attach_virtual(self, deck: Deck) -> None:
        """Hängt ein virtuelles Gerät an eine Sitzung und startet sie."""
        device = VirtualDevice(deck.binding)
        device.on_image = lambda kind, index, key=deck.key: self.bus.publish(
            ev.EVT_DECK_IMAGE, deck=key, input_type=kind, index=index
        )
        if deck.attach(device):
            log.info("Virtuelles Deck '%s' bereit", deck.label)

    def create_virtual_deck(
        self,
        name: str = "Virtuelles Deck",
        *,
        columns: int = 4,
        rows: int = 2,
        dials: int = 0,
    ) -> Deck:
        """Legt ein neues virtuelles Deck samt eigenem Profil an."""
        serial = f"virtual-{uuid.uuid4().hex[:8]}"
        profile = self.config.new_profile_for_deck(name)
        binding = DeckBinding(
            serial=serial,
            name=name,
            deck_type=VIRTUAL_DECK_TYPE,
            kind="virtual",
            profile_id=profile.id,
            device=self.config.device.model_copy(deep=True),
            order=len(self.config.decks),
            columns=max(1, min(16, columns)),
            rows=max(1, min(8, rows)),
            dials=max(0, min(8, dials)),
        )
        self.config.decks[serial] = binding
        self._sync_decks()
        self.save_config()
        self.bus.publish(ev.EVT_DECKS_CHANGED, decks=self.decks_payload())
        return self.decks[serial]

    def create_network_deck(
        self,
        name: str = "Netz-Deck",
        *,
        columns: int = 4,
        rows: int = 2,
        dials: int = 0,
    ) -> Deck:
        """Legt ein Deck an, das über das Netz bedient wird.

        Technisch dasselbe wie ein Overlay-Deck: Die Bilder entstehen im
        Speicher, Seiten und Tastenlogik gelten unverändert. Nur sitzt am
        anderen Ende ein Browser statt einer Fläche auf dem Bildschirm.

        Ohne Passwort wird es noch nicht angeboten — das setzt man danach.
        """
        serial = f"net-{uuid.uuid4().hex[:8]}"
        profile = self.config.new_profile_for_deck(name)
        binding = DeckBinding(
            serial=serial,
            name=name,
            deck_type=NETWORK_DECK_TYPE,
            kind="network",
            profile_id=profile.id,
            device=self.config.device.model_copy(deep=True),
            order=len(self.config.decks),
            columns=max(1, min(16, columns)),
            rows=max(1, min(8, rows)),
            dials=max(0, min(8, dials)),
        )
        self.config.decks[serial] = binding
        self._sync_decks()
        self.save_config()
        self.bus.publish(ev.EVT_DECKS_CHANGED, decks=self.decks_payload())
        return self.decks[serial]

    def update_virtual_geometry(self, deck: Deck) -> None:
        """Nach einer Rasteränderung neu vermessen und neu zeichnen."""
        device = deck.device
        if isinstance(device, VirtualDevice):
            device.refresh_geometry()
            deck._mark_all_dirty()

    @property
    def primary(self) -> Deck:
        """Das Deck, das gemeint ist, wenn niemand ein anderes nennt.

        Die Reihenfolge ist wichtig, seit es virtuelle Decks gibt: Die
        gelten *immer* als verbunden und würden das Hauptdeck sonst an sich
        reißen, sobald die Hardware kurz abgezogen ist — alles ohne
        ausdrückliches Deck (ältere Aufrufe, Plugins ohne ctx) zeigte dann
        stillschweigend woanders hin. Also: erst echte Hardware, dann
        Overlays.
        """
        reihenfolge = (
            lambda d: d.connected and not d.binding.is_virtual,
            lambda d: not d.binding.is_virtual,
            lambda d: d.connected,
        )
        for passt in reihenfolge:
            for deck in self.decks.values():
                if passt(deck):
                    return deck
        if self.decks:
            return next(iter(self.decks.values()))
        # Kein Eintrag in der Config — dann jetzt einen anlegen, damit es
        # immer ein Deck gibt, an das sich die GUI hängen kann.
        self.config.ensure_decks()
        self._sync_decks()
        return next(iter(self.decks.values()))

    def deck(self, key: str | None = None) -> Deck:
        """Sitzung zu einer Bindungs-ID, sonst das Hauptdeck."""
        if key is not None and key in self.decks:
            return self.decks[key]
        if key:
            for deck in self.decks.values():
                if deck.serial == key or deck.profile.id == key:
                    return deck
        return self.primary

    def decks_in_order(self) -> list[Deck]:
        return sorted(
            self.decks.values(),
            key=lambda d: (d.binding.order, d.label.lower(), d.key),
        )

    def deck_for_profile(self, profile_id: str) -> Deck | None:
        for deck in self.decks.values():
            if deck.binding.profile_id == profile_id:
                return deck
        return None

    async def _session_retry_loop(self) -> None:
        """Noch einmal nach dem Sitzungsbus sehen, mit wachsendem Abstand.

        Die Abstände wachsen, weil die beiden Fälle verschieden aussehen:
        Startet der Dienst dem Bus nur knapp zuvor, ist er nach zwei
        Sekunden da. Gibt es gar keinen, soll das Nachfassen nicht ewig
        weiterlaufen — nach gut zwei Minuten ist Schluss, und der Benutzer
        kann es in den Einstellungen von Hand auslösen.
        """
        for wartezeit in (2, 5, 10, 20, 30, 60):
            await asyncio.sleep(wartezeit)
            try:
                await self.session.detect()
            except Exception as exc:  # noqa: BLE001
                log.debug("Erneutes Abtasten der Sitzung: %s", exc)
                continue

            if not self.session.bus_reachable:
                continue

            log.info("Sitzungsbus jetzt erreichbar — Fähigkeiten neu erkannt")
            # Die Kurzbefehle hängen daran und wurden beim Start
            # übersprungen; jetzt lassen sie sich anmelden.
            with contextlib.suppress(Exception):
                await self.shortcuts.sync()
            # Die Oberfläche zeigt Aktionen nach diesen Angaben an.
            self.bus.publish(ev.EVT_CONFIG_CHANGED)
            return

        log.info(
            "Sitzungsbus blieb unerreichbar — was daran hängt, bleibt aus. "
            "In den Einstellungen lässt sich erneut prüfen."
        )

    async def _connection_loop(self) -> None:
        """Sucht regelmäßig nach Geräten und hängt sie an ihre Bindung."""
        while True:
            try:
                await self._scan_devices()
            except Exception:
                log.exception("Gerätesuche fehlgeschlagen")
            await asyncio.sleep(RECONNECT_INTERVAL_S)

    async def _scan_devices(self) -> None:
        loop = asyncio.get_running_loop()
        found = await loop.run_in_executor(self._executor, device_module.enumerate_decks)
        paths_now = {device_module.deck_path(raw): raw for raw in found}

        changed = False

        # Verschwundene Geräte abmelden.
        for key, path in list(self._open_paths.items()):
            deck = self.decks.get(key)
            if path in paths_now and deck is not None and deck.connected:
                continue
            self._open_paths.pop(key, None)
            if deck is not None:
                deck.detach()
                deck._publish_state()
            changed = True

        # Neue Geräte übernehmen. Geöffnet wird im Worker-Thread — das ist
        # blockierende USB-Arbeit —, zugeordnet wird hier im Loop.
        taken = set(self._open_paths.values())
        for path, raw in paths_now.items():
            if path in taken:
                continue
            device = await loop.run_in_executor(self._executor, self._open_device, raw)
            if device is None:
                continue
            deck = self._adopt(device)
            if deck is None:
                device.close()
                continue
            self._open_paths[deck.key] = path
            deck._publish_state()
            changed = True

        if changed:
            self.save_config()
            self.bus.publish(ev.EVT_DECKS_CHANGED, decks=self.decks_payload())

    def _open_device(self, raw) -> device_module.StreamDeckDevice | None:
        """Öffnet ein gefundenes Gerät (blockierend, gehört in den Executor)."""
        device = device_module.StreamDeckDevice()
        if not device.open(raw):
            if device.info.error:
                self._record_error("device", device.info.error, source="device")
            return None
        return device

    def _adopt(self, device: device_module.StreamDeckDevice) -> Deck | None:
        """Ordnet ein geöffnetes Gerät seiner Bindung zu.

        Die Zuordnung hängt an der **Seriennummer**, nicht am Geräteknoten:
        Ein Deck darf an einem anderen USB-Anschluss stecken und muss
        trotzdem seine Belegung wiederfinden.
        """
        serial = device.info.serial
        deck_type = device.info.deck_type

        deck = self.decks.get(serial)
        if deck is None:
            # Der Platzhalter einer Ein-Deck-Config übernimmt das erste
            # Gerät — samt bestehender Belegung.
            deck = next(
                (d for d in self.decks.values() if not d.binding.serial and not d.connected),
                None,
            )
            if deck is not None:
                self.config.decks.pop(deck.binding.serial, None)
                self.decks.pop(deck.binding.serial, None)
            else:
                deck = self._new_deck(serial, deck_type)

        if not deck.attach(device):
            return None

        # Die Bindung wird über die Seriennummer geführt — nach dem
        # Übernehmen des Platzhalters muss sie unter dem neuen Schlüssel
        # stehen.
        self.config.decks[deck.binding.serial] = deck.binding
        self.decks[deck.binding.serial] = deck
        return deck

    def _new_deck(self, serial: str, deck_type: str) -> Deck:
        """Bindung und Profil für ein bisher unbekanntes Gerät."""
        profile = self.config.new_profile_for_deck(deck_type or "Deck")
        binding = DeckBinding(
            serial=serial,
            name=deck_type or "Deck",
            deck_type=deck_type,
            profile_id=profile.id,
            device=self.config.device.model_copy(deep=True),
            order=len(self.config.decks),
        )
        self.config.decks[serial] = binding
        deck = Deck(self, binding)
        self.decks[serial] = deck
        log.info("Neues Deck '%s' (Serial %s) angelegt", binding.name, serial)
        return deck

    def decks_payload(self) -> list[dict[str, Any]]:
        eintraege = []
        for deck in self.decks_in_order():
            eintrag = deck.as_dict()
            eintrag["kind"] = deck.binding.kind
            eintrag["columns"] = deck.binding.columns
            eintrag["rows"] = deck.binding.rows
            eintrag["dials"] = deck.binding.dials
            eintrag["tile_size"] = deck.binding.key_size
            if deck.binding.is_virtual:
                eintrag["overlay_transparent"] = deck.binding.overlay_transparent
                eintrag["hide_empty"] = deck.binding.hide_empty
            if deck.binding.is_overlay:
                eintrag["overlay_visible"] = self.overlay.is_visible(deck.key)
                eintrag["overlay_available"] = self.overlay.available()[0]
                eintrag["overlay_reason"] = self.overlay.available()[1]
                eintrag["overlay_hotkey"] = deck.binding.overlay_hotkey
                # Warum der Kurzbefehl *nicht* wirkt, muss man sehen können —
                # sonst belegt man eine Taste und wundert sich später.
                eintrag["hotkey_reason"] = self.shortcuts.reason(deck.key)
                # Auf Desktops ohne kglobalaccel entscheidet der Benutzer im
                # Dialog des Portals, worauf der Kurzbefehl wirklich liegt.
                # Dann ist die eingetippte Kombination nur noch der Wunsch,
                # und die Oberfläche zeigt besser, was tatsächlich gilt.
                vergeben = self.shortcuts.vergebene_kombination(deck.key)
                if vergeben:
                    eintrag["hotkey_effective"] = vergeben
            if deck.binding.is_network:
                # Das Passwort selbst verlässt den Rechner nie — die
                # Oberfläche muss nur wissen, *ob* eines gesetzt ist.
                eintrag["has_password"] = bool(deck.binding.password_hash)
                eintrag["network_enabled"] = deck.binding.network_enabled
                eintrag["network_port"] = self.config.app.network_port
                eintrag["network_urls"] = self.netz.urls(deck.key)
                eintrag["network_running"] = self.netz.running
            eintraege.append(eintrag)
        return eintraege

    def forget_deck(self, key: str) -> bool:
        """Entfernt eine Bindung — für Geräte, die nicht mehr da sind."""
        deck = self.decks.get(key)
        if deck is None:
            return False
        # Ein virtuelles Deck ist immer „verbunden" — es zu entfernen muss
        # trotzdem gehen, sonst wird man es nie wieder los.
        if deck.connected and not deck.binding.is_virtual:
            raise ValueError("Ein verbundenes Deck lässt sich nicht entfernen")
        if len(self.decks) <= 1:
            raise ValueError("Das letzte Deck lässt sich nicht entfernen")
        self.decks.pop(key, None)
        self.config.decks.pop(key, None)
        self._open_paths.pop(key, None)
        self.save_config()
        self.bus.publish(ev.EVT_DECKS_CHANGED, decks=self.decks_payload())
        return True

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
            input=self.input,
            media=self.media,
            desktop=self.desktop,
            sound=self.sound,
            overlay=self.overlay,
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
        for deck in self.decks.values():
            deck._contexts.clear()
        self.errors = [e for e in self.errors if e.get("source") != "plugin"]
        self.load_plugins()
        await self._setup_plugins()
        self.request_redraw()
        self.bus.publish(ev.EVT_CONFIG_CHANGED, reason="plugins_reloaded")

    # ======================================================================
    # RuntimeApi — was Plugins aufrufen dürfen
    #
    # Über ``ctx.services.runtime`` bekommen Plugins eine Sicht auf ihr
    # eigenes Deck. Wer stattdessen die Runtime direkt anspricht (etwa aus
    # ``setup()`` heraus, wo es noch keinen ctx gibt), landet beim Hauptdeck —
    # bei einem einzelnen Gerät ist das dasselbe.
    # ======================================================================

    def request_redraw(self, ctx: SlotContext | None = None) -> None:
        """Threadsicher: sofortiges Neuzeichnen anstoßen."""
        if ctx is not None and ctx.deck_serial:
            deck = self.decks.get(ctx.deck_serial)
            if deck is not None:
                deck.request_redraw(ctx)
                return
        if ctx is None:
            # Ohne Bezug auf eine Belegung ist jedes Deck gemeint: Ein
            # Audio-Ereignis von außen betrifft alle Geräte, die eine
            # Lautstärke zeigen.
            for deck in self.decks.values():
                deck.request_redraw()
            return
        self.primary.request_redraw(ctx)

    def navigate(self, page_id: str) -> None:
        self.primary.navigate(page_id)

    def navigate_home(self) -> None:
        self.primary.navigate_home()

    def navigate_back(self) -> None:
        self.primary.navigate_back()

    def current_page_id(self) -> str:
        return self.primary.current_page_id()

    def page_number(self) -> int:
        return self.primary.page_number()

    def sibling_pages(self) -> list[Page]:
        return self.primary.sibling_pages()

    def step_page(self, delta: int, *, wrap: bool = True) -> bool:
        return self.primary.step_page(delta, wrap=wrap)

    async def run_steps(self, steps, ctx, *, repeat: bool = False) -> None:
        await self.deck(ctx.deck_serial).run_steps(steps, ctx, repeat=repeat)

    def stop_steps(self, ctx) -> bool:
        return self.deck(ctx.deck_serial).stop_steps(ctx)

    def steps_running(self, ctx) -> bool:
        return self.deck(ctx.deck_serial).steps_running(ctx)

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

    # -- Bequemlichkeit für Aufrufer, die nur ein Deck kennen --------------

    @property
    def device(self):
        return self.primary.device

    @property
    def current_page(self) -> Page:
        return self.primary.current_page

    def slot_at(self, input_type: str, index: int) -> Slot | None:
        return self.primary.slot_at(input_type, index)

    async def render_preview(
        self, page_id: str, input_type: str, index: int, deck: str | None = None
    ):
        return await self.deck(deck).render_preview(page_id, input_type, index)

    def wallpaper_preview(self, source: str, *, fit: str = "cover", opacity: int = 100):
        return self.primary.wallpaper_preview(source, fit=fit, opacity=opacity)

    def screensaver_preview(self, source: str, layout):
        return self.primary.screensaver_preview(source, layout)

    def start_screensaver_now(self) -> None:
        self.primary.start_screensaver_now()

    # ======================================================================
    # Installationsanfragen über streamdeck://
    # ======================================================================

    def add_install_request(
        self, url: str, origin: str = "", sha256: str = ""
    ) -> "InstallRequest":
        """Merkt eine angeforderte Installation vor — ohne sie auszuführen.

        Ein Klick auf einen Link im Browser darf niemals ungefragt Code
        installieren. Die Anfrage landet hier und wird erst nach Bestätigung
        in der GUI ausgeführt.
        """
        from .plugins.installer import InstallRequest

        now = time.time()
        self._expire_install_requests(now)

        request = InstallRequest(
            id=uuid.uuid4().hex[:12],
            url=url,
            origin=origin,
            created_at=now,
            sha256=sha256.strip().lower(),
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
    # Externe Ereignisse
    # ======================================================================

    def _on_audio_event(self, event: str, facility: str) -> None:
        """Aus dem ``pactl subscribe``-Thread: Audio hat sich von außen geändert."""
        self.request_redraw()
        self.bus.publish_threadsafe(
            ev.EVT_PLUGIN_STATE, plugin_id="audio", event=event, facility=facility
        )

    # ======================================================================
    # Config-Änderungen aus der GUI
    # ======================================================================

    def apply_config(self, config: Config, *, save: bool = True) -> None:
        """Übernimmt eine geänderte Config sofort — ohne Neustart des Backends."""
        self._carry_over_live_decks(config)
        self.config = config
        self.store.config = config
        config.ensure_decks()
        if save:
            self.store.save(config)

        # Services tragen eine Config-Referenz — die muss mitwandern.
        for loaded in self.registry.code_plugins:
            if loaded.instance is not None:
                loaded.instance.services.config = config

        # Bindungen können dazugekommen oder verschwunden sein; bestehende
        # Sitzungen bekommen ihre (neue) Bindung untergeschoben, damit ein
        # verbundenes Gerät nicht wegen einer Einstellungsänderung neu
        # verbinden muss.
        for key, binding in config.decks.items():
            deck = self.decks.get(key)
            if deck is not None:
                deck.binding = binding
        self._sync_decks()

        self.icons.clear_cache()
        for deck in self.decks.values():
            deck.apply_config()
            if not deck._tasks:
                deck.start()

        self.bus.publish(ev.EVT_CONFIG_CHANGED)

    def _carry_over_live_decks(self, incoming: Config) -> None:
        """Rettet angeschlossene Decks über eine veraltete Config hinweg.

        Die GUI schickt bei jeder Einstellungsänderung die **ganze** Config
        zurück. Hat sich in der Zwischenzeit ein Deck angemeldet, kennt ihr
        Stand dessen Bindung und Profil nicht — und ohne diese Rettung wären
        beide anschließend weg. Beim nächsten Suchlauf käme das Gerät als
        „neu“ zurück und bekäme ein leeres Profil; die Belegung des Nutzers
        wäre verwaist.

        Gerettet wird nur, was *gerade angeschlossen* ist. Ein Deck bewusst
        zu entfernen bleibt möglich — dafür gibt es den eigenen Weg, und
        dort ist es ohnehin nicht verbunden.
        """
        for key, deck in self.decks.items():
            if key in incoming.decks:
                continue
            if not deck.connected or deck.binding.is_virtual:
                continue
            log.info(
                "Deck '%s' fehlte in der eingehenden Config — Bindung behalten",
                deck.label,
            )
            incoming.decks[key] = deck.binding
            profile = self.config.profiles.get(deck.binding.profile_id)
            if profile is not None:
                incoming.profiles.setdefault(profile.id, profile)

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

    def profile_for(self, deck_key: str | None) -> Profile:
        """Das Profil, das die GUI gerade bearbeitet."""
        return self.deck(deck_key).profile

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

    # -- Weiterleitungen für Aufrufer mit einem Deck im Kopf ---------------
    # Die Tests und ältere Aufrufer sprechen die Runtime direkt an. Damit
    # das gültig bleibt, landen diese Aufrufe beim Hauptdeck.

    async def _handle_key(self, index: int, pressed: bool) -> None:
        await self.primary.handle_key(index, pressed)

    async def _handle_dial_rotate(self, index: int, delta: int) -> None:
        await self.primary.handle_dial_rotate(index, delta)

    async def _handle_dial_push(self, index: int, pressed: bool) -> None:
        await self.primary.handle_dial_push(index, pressed)

    async def _handle_touch(self, kind: str, value: dict) -> None:
        await self.primary.handle_touch(kind, value)

    def _check_idle(self) -> None:
        for deck in self.decks.values():
            deck.check_idle()

    def _wake(self) -> None:
        self.primary.wake()

    @property
    def _last_input(self) -> float:
        return self.primary._last_input

    @_last_input.setter
    def _last_input(self, value: float) -> None:
        self.primary._last_input = value

    @property
    def _dimmed(self) -> bool:
        return self.primary._dimmed

    @_dimmed.setter
    def _dimmed(self, value: bool) -> None:
        self.primary._dimmed = value

    @property
    def current_page_id_value(self) -> str:
        return self.primary.current_page_id_value

    @current_page_id_value.setter
    def current_page_id_value(self, value: str) -> None:
        self.primary.current_page_id_value = value

    @property
    def _contexts(self) -> dict[str, SlotContext]:
        return self.primary._contexts

    def _mark_dirty(self, target: tuple[str, int], page_id: str | None = None) -> None:
        self.primary._mark_dirty(target, page_id)

    def _mark_all_dirty(self) -> None:
        for deck in self.decks.values():
            deck._mark_all_dirty()
