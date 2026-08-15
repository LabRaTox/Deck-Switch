"""OBS-Studio-Steuerung über obs-websocket v5 (simpleobsws).

Deckt den Funktionsumfang des offiziellen Elgato-OBS-Plugins ab: Aufnahme
(inkl. Pause und Kapitelmarken), Stream, Wiedergabepuffer, Szenensammlungen,
Szenen, Quellen, Ton, Medienwiedergabe, Studio-Modus, Filter, Screenshots und
Übergänge.

Der Zustand wird nicht gepollt: OBS schickt Events, und darauf hin wird
sofort neu gezeichnet. Der Tick aktualisiert nur mitlaufende Zeitanzeigen.

OBS läuft nicht immer. „Nicht verbunden“ ist deshalb ein sichtbarer Zustand
auf der Taste, kein Fehler im Log.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from pathlib import Path

import simpleobsws
from PIL import Image

from deckswitch.plugins.base import ActionPlugin

ACCENT = "#ef4444"
RECONNECT_INTERVAL_S = 5.0

#: Wie lange eine Erfolgsmeldung ("gespeichert") auf der Taste stehen bleibt.
FLASH_S = 1.5

MEDIA_ACTIONS = {
    "restart": "OBS_WEBSOCKET_MEDIA_INPUT_ACTION_RESTART",
    "stop": "OBS_WEBSOCKET_MEDIA_INPUT_ACTION_STOP",
    "next": "OBS_WEBSOCKET_MEDIA_INPUT_ACTION_NEXT",
    "previous": "OBS_WEBSOCKET_MEDIA_INPUT_ACTION_PREVIOUS",
}

#: Quellen ohne eigene Audiospur — bei „Ton stumm“ nicht anbieten.
_NON_AUDIO_KINDS = ("image_source", "color_source", "text_", "browser_source")


class ObsPlugin(ActionPlugin):
    def __init__(self, manifest, services):
        super().__init__(manifest, services)
        self.client: simpleobsws.WebSocketClient | None = None
        self.connected = False
        self._task: asyncio.Task | None = None
        self._connect_lock = asyncio.Lock()

        # Gespiegelter OBS-Zustand, damit render() nie blockieren muss.
        self.current_scene: str = ""
        self.preview_scene: str = ""
        self.scenes: list[str] = []
        self.scene_collections: list[str] = []
        self.current_collection: str = ""
        self.transitions: list[str] = []
        self.current_transition: str = ""
        self.streaming = False
        self.recording = False
        self.record_paused = False
        self.replay_active = False
        self.virtual_cam = False
        self.studio_mode = False
        self.stream_started_at: float | None = None
        self.record_started_at: float | None = None

        self._mute_states: dict[str, bool] = {}
        self._media_states: dict[str, str] = {}
        self._item_states: dict[tuple[str, str], bool] = {}
        self._filter_states: dict[tuple[str, str], bool] = {}
        self._confirm_pending: dict[str, float] = {}
        self._flash_until: dict[str, float] = {}

    # ======================================================================
    # Lebenszyklus
    # ======================================================================

    async def setup(self):
        if self.plugin_config.get("auto_connect", True):
            self._task = asyncio.create_task(self._connection_loop(), name="obs-connect")

    async def teardown(self):
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        await self._disconnect()

    def on_plugin_config_changed(self, config):
        async def restart():
            await self.teardown()
            await self.setup()

        self.run_async(restart())

    async def _connection_loop(self):
        while True:
            if not self.connected:
                await self._connect()
            await asyncio.sleep(RECONNECT_INTERVAL_S)

    async def _connect(self):
        async with self._connect_lock:
            if self.connected:
                return
            config = self.plugin_config
            host = config.get("host") or "127.0.0.1"
            port = int(config.get("port") or 4455)
            password = config.get("password") or None

            client = simpleobsws.WebSocketClient(url=f"ws://{host}:{port}", password=password)
            try:
                await client.connect()
                identified = await asyncio.wait_for(client.wait_until_identified(), timeout=5)
            except Exception as exc:
                self.log.debug("OBS nicht erreichbar: %s", exc)
                with contextlib.suppress(Exception):
                    await client.disconnect()
                self._set_offline()
                return

            if not identified:
                self.log.warning("OBS hat die Anmeldung abgelehnt (Passwort?)")
                with contextlib.suppress(Exception):
                    await client.disconnect()
                self._set_offline()
                self.notify_error("OBS: Anmeldung fehlgeschlagen — Passwort prüfen")
                return

            self.client = client
            self.connected = True
            self._register_events(client)
            await self._refresh_state()
            self.log.info("Mit OBS verbunden (%s:%s)", host, port)
            self.services.runtime.request_redraw()
            self.services.runtime.publish_plugin_status(self.manifest.id)

    async def _disconnect(self):
        client, self.client = self.client, None
        self.connected = False
        if client is not None:
            with contextlib.suppress(Exception):
                await client.disconnect()

    def _set_offline(self):
        was_connected = self.connected
        self.connected = False
        self.client = None
        if was_connected:
            self.services.runtime.request_redraw()
            self.services.runtime.publish_plugin_status(self.manifest.id)

    def get_status(self):
        config = self.plugin_config
        target = f"{config.get('host') or '127.0.0.1'}:{config.get('port') or 4455}"
        if self.connected:
            return {"connected": True, "detail": f"{target} · {len(self.scenes)} Szenen"}
        return {"connected": False, "detail": f"{target} nicht erreichbar"}

    # ======================================================================
    # Events
    # ======================================================================

    def _register_events(self, client):
        register = client.register_event_callback
        redraw = self.services.runtime.request_redraw

        async def on_scene(data):
            self.current_scene = data.get("sceneName", "")
            redraw()

        async def on_preview(data):
            self.preview_scene = data.get("sceneName", "")
            redraw()

        async def on_scene_list(_data=None):
            await self._refresh_scenes()
            redraw()

        async def on_stream(data):
            self.streaming = bool(data.get("outputActive"))
            self.stream_started_at = time.monotonic() if self.streaming else None
            redraw()

        async def on_record(data):
            self.recording = bool(data.get("outputActive"))
            state = data.get("outputState", "")
            if state == "OBS_WEBSOCKET_OUTPUT_PAUSED":
                self.record_paused = True
            elif state in ("OBS_WEBSOCKET_OUTPUT_RESUMED", "OBS_WEBSOCKET_OUTPUT_STARTED"):
                self.record_paused = False
            if not self.recording:
                self.record_paused = False
                self.record_started_at = None
            elif self.record_started_at is None:
                self.record_started_at = time.monotonic()
            redraw()

        async def on_replay(data):
            self.replay_active = bool(data.get("outputActive"))
            redraw()

        async def on_virtual_cam(data):
            self.virtual_cam = bool(data.get("outputActive"))
            redraw()

        async def on_studio(data):
            self.studio_mode = bool(data.get("studioModeEnabled"))
            if self.studio_mode:
                await self._refresh_scenes()
            redraw()

        async def on_item_visibility(data):
            scene = data.get("sceneName", "")
            # Der Name der Quelle steckt nicht im Event, nur die Item-ID —
            # deshalb den Cache dieser Szene verwerfen und neu erfragen.
            for key in [k for k in self._item_states if k[0] == scene]:
                self._item_states.pop(key, None)
            redraw()

        async def on_mute(data):
            self._mute_states[data.get("inputName", "")] = bool(data.get("inputMuted"))
            redraw()

        async def on_media(data):
            self._media_states[data.get("inputName", "")] = data.get("mediaState", "")
            redraw()

        async def on_filter(data):
            key = (data.get("sourceName", ""), data.get("filterName", ""))
            self._filter_states[key] = bool(data.get("filterEnabled"))
            redraw()

        async def on_collection(data):
            self.current_collection = data.get("sceneCollectionName", "")
            await self._refresh_state()
            redraw()

        async def on_transition(data):
            self.current_transition = data.get("transitionName", "")
            redraw()

        async def on_input_list(_data=None):
            self._mute_states.clear()
            self._media_states.clear()
            redraw()

        async def on_exit(_data=None):
            self._set_offline()

        register(on_scene, "CurrentProgramSceneChanged")
        register(on_preview, "CurrentPreviewSceneChanged")
        register(on_scene_list, "SceneListChanged")
        register(on_stream, "StreamStateChanged")
        register(on_record, "RecordStateChanged")
        register(on_replay, "ReplayBufferStateChanged")
        register(on_virtual_cam, "VirtualcamStateChanged")
        register(on_studio, "StudioModeStateChanged")
        register(on_item_visibility, "SceneItemEnableStateChanged")
        register(on_mute, "InputMuteStateChanged")
        register(on_media, "MediaInputPlaybackStarted")
        register(on_media, "MediaInputPlaybackEnded")
        register(on_filter, "SourceFilterEnableStateChanged")
        register(on_collection, "CurrentSceneCollectionChanged")
        register(on_transition, "CurrentSceneTransitionChanged")
        register(on_input_list, "InputCreated")
        register(on_input_list, "InputRemoved")
        register(on_exit, "ExitStarted")

    async def _refresh_state(self):
        await self._refresh_scenes()

        stream = await self._call("GetStreamStatus")
        if stream:
            self.streaming = bool(stream.get("outputActive"))
            self.stream_started_at = (
                time.monotonic() - stream.get("outputDuration", 0) / 1000
                if self.streaming
                else None
            )

        record = await self._call("GetRecordStatus")
        if record:
            self.recording = bool(record.get("outputActive"))
            self.record_paused = bool(record.get("outputPaused"))
            self.record_started_at = (
                time.monotonic() - record.get("outputDuration", 0) / 1000
                if self.recording
                else None
            )

        for request, attribute in (
            ("GetVirtualCamStatus", "virtual_cam"),
            ("GetReplayBufferStatus", "replay_active"),
        ):
            data = await self._call(request)
            if data:
                setattr(self, attribute, bool(data.get("outputActive")))

        studio = await self._call("GetStudioModeEnabled")
        if studio:
            self.studio_mode = bool(studio.get("studioModeEnabled"))

        collections = await self._call("GetSceneCollectionList")
        if collections:
            self.scene_collections = collections.get("sceneCollections", [])
            self.current_collection = collections.get("currentSceneCollectionName", "")

        transitions = await self._call("GetSceneTransitionList")
        if transitions:
            self.transitions = [
                t.get("transitionName", "") for t in transitions.get("transitions", [])
            ]
            self.current_transition = transitions.get("currentSceneTransitionName", "")

    async def _refresh_scenes(self):
        data = await self._call("GetSceneList")
        if not data:
            return
        self.current_scene = data.get("currentProgramSceneName", "")
        self.preview_scene = data.get("currentPreviewSceneName", "") or ""
        self.scenes = [s.get("sceneName", "") for s in reversed(data.get("scenes", []))]

    async def _call(self, request: str, data: dict | None = None) -> dict | None:
        client = self.client
        if client is None or not self.connected:
            return None
        try:
            response = await asyncio.wait_for(
                client.call(simpleobsws.Request(request, data or {})), timeout=5
            )
        except Exception as exc:
            self.log.warning("OBS-Request '%s' fehlgeschlagen: %s", request, exc)
            self._set_offline()
            return None
        if not response.ok():
            self.log.info("OBS lehnt '%s' ab: %s", request, response.requestStatus.comment)
            return None
        return response.responseData or {}

    # ======================================================================
    # Eingaben
    # ======================================================================

    async def on_key_down(self, action_id, settings, ctx):
        if action_id == "mute":
            mode = ctx.setting("mode", "toggle")
            if mode in ("push_to_talk", "push_to_mute"):
                await self._set_mute(settings, mode == "push_to_mute")
                return
        await self._activate(action_id, settings, ctx)

    async def on_key_up(self, action_id, settings, ctx):
        if action_id == "mute":
            mode = ctx.setting("mode", "toggle")
            if mode in ("push_to_talk", "push_to_mute"):
                await self._set_mute(settings, mode == "push_to_talk")

    async def on_dial_push(self, action_id, settings, ctx):
        await self._activate(action_id, settings, ctx)

    async def on_dial_rotate(self, action_id, settings, delta, ctx):
        """Drehen blättert durch die jeweilige Liste."""
        if not self.connected:
            return
        step = 1 if delta > 0 else -1

        if action_id == "scene" and self.scenes:
            target = _step(self.scenes, self.current_scene, step)
            request = (
                "SetCurrentPreviewScene" if ctx.setting("preview", False) else "SetCurrentProgramScene"
            )
            await self._call(request, {"sceneName": target})

        elif action_id == "transition" and self.transitions:
            target = _step(self.transitions, self.current_transition, step)
            await self._call("SetCurrentSceneTransition", {"transitionName": target})

        elif action_id == "scene_collection" and self.scene_collections:
            target = _step(self.scene_collections, self.current_collection, step)
            await self._call("SetCurrentSceneCollection", {"sceneCollectionName": target})

    async def _activate(self, action_id, settings, ctx):
        if not self.connected:
            await self._connect()
            if not self.connected:
                self.notify_info("OBS nicht erreichbar — läuft obs-websocket?")
                return

        handler = getattr(self, f"_do_{action_id}", None)
        if handler is None:
            self.notify_error(f"Unbekannte Aktion '{action_id}'")
            return
        await handler(settings, ctx)

    # -- Einzelne Aktionen -------------------------------------------------

    async def _do_record(self, settings, ctx):
        if self.recording and ctx.setting("confirm", False) and not self._confirmed(ctx):
            return
        await self._call("ToggleRecord")

    async def _do_record_pause(self, settings, ctx):
        if not self.recording:
            self.notify_info("Es läuft keine Aufnahme")
            return
        await self._call("ToggleRecordPause")

    async def _do_stream(self, settings, ctx):
        if self.streaming and ctx.setting("confirm", True) and not self._confirmed(ctx):
            return
        await self._call("ToggleStream")

    async def _do_replay_buffer(self, settings, ctx):
        await self._call("ToggleReplayBuffer")

    async def _do_save_replay(self, settings, ctx):
        if not self.replay_active:
            self.notify_info("Der Wiedergabepuffer ist nicht aktiv")
            return
        if await self._call("SaveReplayBuffer") is not None:
            self._flash(ctx)

    async def _do_scene_collection(self, settings, ctx):
        collection = settings.get("collection")
        if not collection:
            self.notify_error("Keine Szenensammlung eingestellt")
            return
        await self._call("SetCurrentSceneCollection", {"sceneCollectionName": collection})

    async def _do_scene(self, settings, ctx):
        scene = settings.get("scene")
        if not scene:
            self.notify_error("Keine Szene eingestellt")
            return
        request = (
            "SetCurrentPreviewScene" if settings.get("preview") else "SetCurrentProgramScene"
        )
        await self._call(request, {"sceneName": scene})

    async def _do_source(self, settings, ctx):
        source = (settings.get("source") or "").strip()
        if not source:
            self.notify_error("Keine Quelle eingestellt")
            return
        scene = (settings.get("scene") or "").strip() or self.current_scene

        found = await self._call("GetSceneItemId", {"sceneName": scene, "sourceName": source})
        if not found:
            self.notify_error(f"Quelle '{source}' nicht in Szene '{scene}'")
            return
        item_id = found.get("sceneItemId")

        state = await self._call(
            "GetSceneItemEnabled", {"sceneName": scene, "sceneItemId": item_id}
        )
        enabled = bool(state.get("sceneItemEnabled")) if state else False
        await self._call(
            "SetSceneItemEnabled",
            {"sceneName": scene, "sceneItemId": item_id, "sceneItemEnabled": not enabled},
        )
        self._item_states[(scene, source)] = not enabled

    async def _do_mute(self, settings, ctx):
        name = (settings.get("input") or "").strip()
        if not name:
            self.notify_error("Keine Audioquelle eingestellt")
            return
        result = await self._call("ToggleInputMute", {"inputName": name})
        if result is not None:
            self._mute_states[name] = bool(result.get("inputMuted"))

    async def _set_mute(self, settings, muted: bool):
        name = (settings.get("input") or "").strip()
        if not name or not self.connected:
            return
        await self._call("SetInputMute", {"inputName": name, "inputMuted": muted})
        self._mute_states[name] = muted
        self.services.runtime.request_redraw()

    async def _do_media(self, settings, ctx):
        name = (settings.get("input") or "").strip()
        if not name:
            self.notify_error("Keine Medienquelle eingestellt")
            return

        action = settings.get("action") or "play_pause"
        if action == "play_pause":
            state = self._media_states.get(name, "")
            playing = state == "OBS_MEDIA_STATE_PLAYING"
            request = (
                "OBS_WEBSOCKET_MEDIA_INPUT_ACTION_PAUSE"
                if playing
                else "OBS_WEBSOCKET_MEDIA_INPUT_ACTION_PLAY"
            )
        else:
            request = MEDIA_ACTIONS.get(action)
            if request is None:
                self.notify_error(f"Unbekannte Medienaktion '{action}'")
                return

        await self._call("TriggerMediaInputAction", {"inputName": name, "mediaAction": request})
        status = await self._call("GetMediaInputStatus", {"inputName": name})
        if status:
            self._media_states[name] = status.get("mediaState", "")

    async def _do_studio_mode(self, settings, ctx):
        await self._call("SetStudioModeEnabled", {"studioModeEnabled": not self.studio_mode})

    async def _do_preview_scene(self, settings, ctx):
        if not self.studio_mode:
            self.notify_info("Der Studio-Modus ist nicht aktiv")
            return
        await self._call("TriggerStudioModeTransition")

    async def _do_filter(self, settings, ctx):
        source = (settings.get("source") or "").strip()
        name = (settings.get("filter") or "").strip()
        if not source or not name:
            self.notify_error("Quelle und Filter müssen eingestellt sein")
            return

        state = await self._call(
            "GetSourceFilter", {"sourceName": source, "filterName": name}
        )
        if state is None:
            self.notify_error(f"Filter '{name}' an '{source}' nicht gefunden")
            return
        enabled = bool(state.get("filterEnabled"))
        await self._call(
            "SetSourceFilterEnabled",
            {"sourceName": source, "filterName": name, "filterEnabled": not enabled},
        )
        self._filter_states[(source, name)] = not enabled

    async def _do_screenshot(self, settings, ctx):
        source = (settings.get("source") or "").strip() or self.current_scene
        if not source:
            self.notify_error("Keine Quelle für den Screenshot")
            return

        image_format = settings.get("format") or "png"
        folder = Path(
            (self.plugin_config.get("screenshot_dir") or "~/Bilder/OBS")
        ).expanduser()
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self.notify_error(f"Screenshot-Ordner nicht nutzbar: {exc}")
            return

        stamp = time.strftime("%Y-%m-%d_%H-%M-%S")
        target = folder / f"{_safe_name(source)}_{stamp}.{image_format}"
        result = await self._call(
            "SaveSourceScreenshot",
            {
                "sourceName": source,
                "imageFormat": image_format,
                "imageFilePath": str(target),
            },
        )
        if result is None:
            self.notify_error("Screenshot fehlgeschlagen — Pfad für OBS erreichbar?")
            return
        self.log.info("Screenshot gespeichert: %s", target)
        self._flash(ctx)

    async def _do_transition(self, settings, ctx):
        name = (settings.get("transition") or "").strip()
        if not name:
            self.notify_error("Kein Übergang eingestellt")
            return
        await self._call("SetCurrentSceneTransition", {"transitionName": name})

        duration = int(ctx.setting("duration", 0) or 0)
        if duration > 0:
            await self._call("SetCurrentSceneTransitionDuration", {"transitionDuration": duration})

    async def _do_chapter_marker(self, settings, ctx):
        if not self.recording:
            self.notify_info("Kapitelmarken gehen nur während einer Aufnahme")
            return
        payload = {}
        name = (settings.get("name") or "").strip()
        if name:
            payload["chapterName"] = name

        if await self._call("CreateRecordChapter", payload) is None:
            self.notify_error(
                "Kapitelmarke abgelehnt — OBS 30.2+ und Hybrid-MP4 als "
                "Aufnahmeformat nötig."
            )
            return
        self._flash(ctx)

    async def _do_virtual_cam(self, settings, ctx):
        await self._call("ToggleVirtualCam")

    # -- Hilfen für Eingaben ----------------------------------------------

    def _confirmed(self, ctx) -> bool:
        """Zweimal drücken innerhalb von 3 s — schützt vor Fehlgriffen im Live."""
        now = time.monotonic()
        pending = self._confirm_pending.get(ctx.key, 0)
        if now - pending < 3.0:
            self._confirm_pending.pop(ctx.key, None)
            return True
        self._confirm_pending[ctx.key] = now
        ctx.scratch["confirm_until"] = now + 3.0
        ctx.request_redraw()
        return False

    def _flash(self, ctx) -> None:
        """Kurze Rückmeldung auf der Taste, dass etwas geklappt hat."""
        self._flash_until[ctx.key] = time.monotonic() + FLASH_S
        ctx.request_redraw()

    def _flashing(self, ctx) -> bool:
        return self._flash_until.get(ctx.key, 0) > time.monotonic()

    # ======================================================================
    # Zustand und Darstellung
    # ======================================================================

    def get_state(self, action_id, settings, ctx):
        if not self.connected:
            return "offline"

        if action_id == "record":
            if self.recording:
                return "paused" if self.record_paused else "on"
            return "off"

        if action_id == "record_pause":
            if not self.recording:
                return "idle"
            return "paused" if self.record_paused else "recording"

        if action_id == "stream":
            return "on" if self.streaming else "off"

        if action_id == "replay_buffer":
            return "on" if self.replay_active else "off"

        if action_id == "save_replay":
            if self._flashing(ctx):
                return "saved"
            return "ready" if self.replay_active else "inactive"

        if action_id == "scene_collection":
            return "active" if settings.get("collection") == self.current_collection else "inactive"

        if action_id == "scene":
            target = settings.get("scene")
            if not target:
                return "inactive"
            if target == self.current_scene:
                return "active"
            if self.studio_mode and target == self.preview_scene:
                return "preview"
            return "inactive"

        if action_id == "source":
            scene = (settings.get("scene") or "").strip() or self.current_scene
            source = (settings.get("source") or "").strip()
            return "on" if self._item_states.get((scene, source), False) else "off"

        if action_id == "mute":
            name = (settings.get("input") or "").strip()
            return "muted" if self._mute_states.get(name, False) else "live"

        if action_id == "media":
            state = self._media_states.get((settings.get("input") or "").strip(), "")
            if state == "OBS_MEDIA_STATE_PLAYING":
                return "playing"
            if state == "OBS_MEDIA_STATE_PAUSED":
                return "paused"
            return "stopped"

        if action_id == "studio_mode":
            return "on" if self.studio_mode else "off"

        if action_id == "preview_scene":
            return "ready" if self.studio_mode else "inactive"

        if action_id == "filter":
            key = ((settings.get("source") or "").strip(), (settings.get("filter") or "").strip())
            return "on" if self._filter_states.get(key, False) else "off"

        if action_id in ("screenshot", "chapter_marker"):
            if self._flashing(ctx):
                return "saved"
            if action_id == "chapter_marker" and not self.recording:
                return "idle"
            return "ready"

        if action_id == "transition":
            return "active" if settings.get("transition") == self.current_transition else "inactive"

        if action_id == "virtual_cam":
            return "on" if self.virtual_cam else "off"

        return None

    def get_label(self, action_id, settings, ctx):
        if not self.connected:
            return None

        if action_id == "stream":
            if ctx.scratch.get("confirm_until", 0) > time.monotonic():
                return "Nochmal?"
            if self.streaming and ctx.setting("show_time", True):
                return _duration(self.stream_started_at)

        if action_id == "record":
            if ctx.scratch.get("confirm_until", 0) > time.monotonic():
                return "Nochmal?"
            if self.recording and ctx.setting("show_time", True):
                return _duration(self.record_started_at)

        if ctx.appearance.label_text:
            return None

        # Ohne eigenes Label den eingestellten Namen zeigen — sonst stünde
        # auf der Taste nichts als das Icon.
        if action_id == "scene":
            return settings.get("scene") or None
        if action_id == "scene_collection":
            return settings.get("collection") or None
        if action_id == "source":
            return settings.get("source") or None
        if action_id == "mute":
            return settings.get("input") or None
        if action_id == "filter":
            return settings.get("filter") or None
        if action_id == "transition":
            return settings.get("transition") or None
        if action_id == "preview_scene" and ctx.setting("show_scene", True):
            return self.preview_scene or None
        if action_id == "media":
            return settings.get("input") or None
        return None

    async def on_tick(self, action_id, settings, ctx):
        # Muss asynchron sein: synchrone Hooks führt die Runtime in einem
        # Worker-Thread aus, und dort gibt es keinen Event-Loop für die
        # Nachfragen weiter unten.
        # Laufzeiten sekündlich, alles andere kommt per Event.
        if action_id == "stream" and self.streaming and ctx.setting("show_time", True):
            ctx.request_redraw()
        elif action_id == "record" and self.recording and ctx.setting("show_time", True):
            if not self.record_paused:
                ctx.request_redraw()

        if ctx.scratch.get("confirm_until", 0) and ctx.scratch["confirm_until"] < time.monotonic():
            ctx.scratch["confirm_until"] = 0
            ctx.request_redraw()

        # Erfolgsmeldung wieder abräumen.
        flash = self._flash_until.get(ctx.key, 0)
        if flash and flash < time.monotonic():
            self._flash_until.pop(ctx.key, None)
            ctx.request_redraw()

        # Zustände, die OBS nur auf Nachfrage herausgibt.
        if self.connected:
            await self._poll_lazy_state(action_id, settings, ctx)

    async def _poll_lazy_state(self, action_id, settings, ctx):
        """Fragt Zustände nach, für die es kein Event beim Verbinden gibt."""
        try:
            if action_id == "source":
                scene = (settings.get("scene") or "").strip() or self.current_scene
                source = (settings.get("source") or "").strip()
                if not source or (scene, source) in self._item_states:
                    return
                found = await self._call(
                    "GetSceneItemId", {"sceneName": scene, "sourceName": source}
                )
                if not found:
                    return
                state = await self._call(
                    "GetSceneItemEnabled",
                    {"sceneName": scene, "sceneItemId": found.get("sceneItemId")},
                )
                if state is not None:
                    self._item_states[(scene, source)] = bool(state.get("sceneItemEnabled"))
                    ctx.request_redraw()

            elif action_id == "mute":
                name = (settings.get("input") or "").strip()
                if not name or name in self._mute_states:
                    return
                state = await self._call("GetInputMute", {"inputName": name})
                if state is not None:
                    self._mute_states[name] = bool(state.get("inputMuted"))
                    ctx.request_redraw()

            elif action_id == "media":
                name = (settings.get("input") or "").strip()
                if not name:
                    return
                status = await self._call("GetMediaInputStatus", {"inputName": name})
                if status is not None:
                    new = status.get("mediaState", "")
                    if self._media_states.get(name) != new:
                        self._media_states[name] = new
                        ctx.request_redraw()

            elif action_id == "filter":
                source = (settings.get("source") or "").strip()
                name = (settings.get("filter") or "").strip()
                if not source or not name or (source, name) in self._filter_states:
                    return
                state = await self._call(
                    "GetSourceFilter", {"sourceName": source, "filterName": name}
                )
                if state is not None:
                    self._filter_states[(source, name)] = bool(state.get("filterEnabled"))
                    ctx.request_redraw()
        except Exception as exc:
            self.log.debug("Nachfrage für '%s' fehlgeschlagen: %s", action_id, exc)

    def render(self, action_id, settings, ctx):
        state = self.get_state(action_id, settings, ctx)
        render = self.services.render
        image = render.render_slot(
            ctx,
            state=state,
            label_override=self.get_label(action_id, settings, ctx),
            accent=ACCENT,
        )

        if state == "offline":
            # Nicht verbunden: sichtbar abdunkeln statt stumm falsch anzeigen.
            image.alpha_composite(Image.new("RGBA", image.size, (0, 0, 0, 140)))
            return image

        if state == "saved":
            render.draw_badge(image, "#22c55e")
        elif action_id == "scene" and state == "active":
            render.draw_badge(image, ctx.setting("active_badge", ACCENT))
        elif action_id == "scene" and state == "preview":
            render.draw_badge(image, "#eab308", width=3)
        elif state in ("on", "recording", "playing", "active") and action_id != "source":
            render.draw_badge(image, "#ef4444" if action_id in
                              ("stream", "record", "replay_buffer", "virtual_cam") else "#22c55e")
        elif state in ("muted", "paused") and action_id in ("mute", "record", "record_pause"):
            render.draw_badge(image, "#eab308", width=3)
        elif state in ("idle", "inactive") and action_id in (
            "record_pause", "save_replay", "preview_scene", "chapter_marker"
        ):
            image.alpha_composite(Image.new("RGBA", image.size, (0, 0, 0, 90)))

        return image

    # ======================================================================
    # Auswahllisten und Kommandos für die GUI
    # ======================================================================

    async def gui_command(self, command, payload):
        if command == "status":
            return {
                "connected": self.connected,
                "scenes": len(self.scenes),
                "current_scene": self.current_scene,
                "studio_mode": self.studio_mode,
                "streaming": self.streaming,
                "recording": self.recording,
                "replay_buffer": self.replay_active,
            }
        if command == "reconnect":
            await self._disconnect()
            await self._connect()
            return {"connected": self.connected}
        raise NotImplementedError(f"OBS kennt kein Kommando '{command}'")

    def get_dynamic_options(self, source, context=None):
        context = context or {}

        if source == "scenes":
            return [{"value": name, "label": name} for name in self.scenes]

        if source == "scene_collections":
            return [{"value": name, "label": name} for name in self.scene_collections]

        if source == "transitions":
            return [{"value": name, "label": name} for name in self.transitions]

        if source == "scene_items":
            scene = (context.get("scene") or "").strip() or self.current_scene
            return self._sync_call(self._list_scene_items(scene))

        if source == "audio_inputs":
            return self._sync_call(self._list_inputs(audio_only=True))

        if source == "media_inputs":
            return self._sync_call(self._list_inputs(media_only=True))

        if source == "filterable_sources":
            return self._sync_call(self._list_filterable())

        if source == "filters":
            name = (context.get("source") or "").strip()
            return self._sync_call(self._list_filters(name)) if name else []

        return []

    def _sync_call(self, coro):
        """Führt eine Coroutine aus dem Executor-Thread im Loop aus.

        ``get_dynamic_options`` läuft synchron im Worker-Thread, die
        OBS-Abfragen brauchen aber den Event-Loop.
        """
        loop = getattr(self.services.runtime, "_loop", None)
        if loop is None or not self.connected:
            return []
        try:
            return asyncio.run_coroutine_threadsafe(coro, loop).result(timeout=6)
        except Exception as exc:
            self.log.warning("Auswahlliste nicht abrufbar: %s", exc)
            return []

    async def _list_scene_items(self, scene: str) -> list[dict]:
        if not scene:
            return []
        data = await self._call("GetSceneItemList", {"sceneName": scene})
        if not data:
            return []
        return [
            {"value": item.get("sourceName"), "label": item.get("sourceName")}
            for item in data.get("sceneItems", [])
            if item.get("sourceName")
        ]

    async def _list_inputs(self, *, audio_only=False, media_only=False) -> list[dict]:
        data = await self._call("GetInputList")
        if not data:
            return []

        result = []
        for entry in data.get("inputs", []):
            name = entry.get("inputName")
            kind = (entry.get("inputKind") or "").lower()
            if not name:
                continue
            if media_only and "media" not in kind and "vlc" not in kind:
                continue
            if audio_only and any(k in kind for k in _NON_AUDIO_KINDS):
                continue
            result.append({"value": name, "label": name})
        return result

    async def _list_filterable(self) -> list[dict]:
        """Quellen und Szenen — Filter können an beiden hängen."""
        names: list[str] = list(self.scenes)
        data = await self._call("GetInputList")
        if data:
            names.extend(
                entry["inputName"] for entry in data.get("inputs", []) if entry.get("inputName")
            )
        seen: set[str] = set()
        return [
            {"value": n, "label": n}
            for n in names
            if not (n in seen or seen.add(n))
        ]

    async def _list_filters(self, source: str) -> list[dict]:
        data = await self._call("GetSourceFilterList", {"sourceName": source})
        if not data:
            return []
        return [
            {"value": f.get("filterName"), "label": f.get("filterName")}
            for f in data.get("filters", [])
            if f.get("filterName")
        ]


# --------------------------------------------------------------------------
# Hilfen
# --------------------------------------------------------------------------


def _duration(started_at: float | None) -> str:
    if started_at is None:
        return "00:00"
    seconds = int(time.monotonic() - started_at)
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def _step(values: list[str], current: str, direction: int) -> str:
    try:
        position = values.index(current)
    except ValueError:
        position = 0
    return values[(position + direction) % len(values)]


def _safe_name(text: str) -> str:
    keep = "-_ "
    cleaned = "".join(c if c.isalnum() or c in keep else "-" for c in text).strip()
    return (cleaned or "screenshot").replace(" ", "-")[:60]
