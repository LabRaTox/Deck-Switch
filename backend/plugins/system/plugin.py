"""System-Plugin: Programme, Tastenkombinationen, Text, Medien, Sitzung.

Gestartete Prozesse werden bewusst abgekoppelt (eigene Session, Ausgabe
verworfen): das Deck ist eine Fernbedienung, kein Terminal — ein gestartetes
Programm darf nicht sterben, wenn das Backend neu startet.

Zwei Nachbarmodule gehören dazu: ``sysinfo`` liest die Messwerte,
``ddc`` regelt die Monitorhelligkeit. Letzteres ist deshalb ausgelagert,
weil ``ddcutil`` fast zwei Sekunden pro Aufruf braucht und das eine eigene
Behandlung verlangt — siehe die Erklärung dort.

Die Aktionen rund um Tastatur, Medien und Sitzung liegen in den Diensten der
App (``services/input.py``, ``media.py``, ``desktop.py``); hier steht nur,
was eine Taste damit anstellt.
"""

from __future__ import annotations

import asyncio
import os
import shlex
import shutil
import subprocess
import time
from pathlib import Path

from deckswitch.plugins.base import ActionPlugin

from .ddc import DdcController
from .sysinfo import Reading, SystemInfo

ACCENT = "#0ea5e9"

#: So lange bleibt eine Aktion mit Rückfrage „scharf", nachdem sie einmal
#: gedrückt wurde. Danach fängt das Zählen von vorn an — sonst schaltete ein
#: vergessener erster Druck Stunden später den Rechner aus.
CONFIRM_WINDOW_S = 3.0

#: Ab diesen Anteilen färbt sich der Balken einer Monitor-Kachel um.
WARN_AT = 0.75
ALERT_AT = 0.90

BAR_OK = "#22c55e"
BAR_WARN = "#f59e0b"
BAR_ALERT = "#ef4444"

#: Kürzel vor dem Wert. Bewusst ohne Einheit — die steht schon im Wert
#: selbst, sonst läse man „CPU °C 50 °C“. Und bewusst ohne Pfeilzeichen:
#: Die mitgelieferte Schrift kennt ↓/↑ nicht und malt Kästchen.
METRIC_LABELS = {
    "cpu": "CPU",
    "cpu_temp": "CPU",
    "memory": "RAM",
    "swap": "Swap",
    "gpu": "GPU",
    "gpu_temp": "GPU",
    "gpu_memory": "VRAM",
    "nvme_temp": "SSD",
    "disk": "Platte",
    "net_down": "Down",
    "net_up": "Up",
}


class SystemPlugin(ActionPlugin):
    def __init__(self, manifest, services):
        super().__init__(manifest, services)
        self.info = SystemInfo()
        self.ddc = DdcController()

    def _apply_units(self) -> None:
        """Einheit aus den Plugin-Einstellungen übernehmen."""
        self.info.fahrenheit = self.plugin_config.get("temperature_unit") == "fahrenheit"

    def on_plugin_config_changed(self, config):
        self._apply_units()
        self.services.runtime.request_redraw()

    async def setup(self):
        self._apply_units()
        # Monitore und ihre Helligkeit einmal im Hintergrund ermitteln.
        # ``ddcutil detect`` braucht knapp zwei Sekunden — im Vordergrund
        # würde der Start des Backends genau so lange stehen.
        self.run_async(self._prime_displays())

    async def _prime_displays(self):
        import asyncio

        def work():
            for display in self.ddc.displays():
                self.ddc.read_brightness(display.number)

        await asyncio.get_running_loop().run_in_executor(None, work)
        self.services.runtime.request_redraw()

    async def teardown(self):
        self.ddc.shutdown()

    def on_key_down(self, action_id, settings, ctx):
        if action_id == "hotkey" and settings.get("mode") == "hold":
            # Push-to-Talk: die Kombination bleibt gedrückt, solange die
            # Taste unten ist. Deshalb hier nur drücken, nicht tippen.
            self._hold_hotkey(settings, ctx, pressed=True)
            return
        self._activate(action_id, settings, ctx)

    def on_key_up(self, action_id, settings, ctx):
        if action_id == "hotkey" and settings.get("mode") == "hold":
            self._hold_hotkey(settings, ctx, pressed=False)

    def on_dial_push(self, action_id, settings, ctx):
        self._activate(action_id, settings, ctx)

    def on_dial_rotate(self, action_id, settings, delta, ctx):
        if action_id != "display_brightness":
            return
        number = _display_number(settings)
        if number is None:
            self.notify_error("Kein Monitor eingestellt")
            return
        step = int(ctx.setting("step", 5))
        self.ddc.nudge(number, delta * step)
        ctx.request_redraw()

    def render(self, action_id, settings, ctx):
        if action_id in ("monitor", "display_brightness"):
            return self._render_gauge(action_id, settings, ctx)
        return self.services.render.render_slot(
            ctx,
            state=None,
            label_override=self.get_label(action_id, settings, ctx),
            accent=ACCENT,
        )

    def _render_gauge(self, action_id, settings, ctx):
        """Kachel mit Messwert und Balken."""
        reading = self._reading(action_id, settings, ctx)
        render = self.services.render
        show_bar = reading.fraction is not None and ctx.setting("show_bar", True)

        width, height = ctx.size
        if ctx.input_type == "dial":
            # Ein Segment kann auf einem virtuellen Deck halb so hoch sein
            # wie der Streifen des Geräts — feste Abstände tragen da nicht.
            box = render.bar_box(ctx.size)
        else:
            box = (10, height - 12, width - 10, height - 6)

        # Der Balken sitzt am unteren Rand — dort stünde sonst die
        # Beschriftung, und beides übereinander ist unlesbar. Statt die
        # Position umzubiegen, wird der Platz reserviert: Icon und Label
        # rücken nach oben und behalten ihre eingestellte Anordnung.
        image = render.render_slot(
            ctx,
            state=None,
            label_override=self.get_label(action_id, settings, ctx),
            accent=ACCENT,
            reserve_bottom=render.bar_reserve(ctx.size, box) if show_bar else 0,
        )

        if not show_bar:
            return image

        colour = ctx.setting("bar_color", "")
        if not colour:
            # Ohne eigene Farbe warnt der Balken selbst — bei Temperatur und
            # Auslastung ist genau das die interessante Information.
            colour = (
                BAR_ALERT if reading.fraction >= ALERT_AT
                else BAR_WARN if reading.fraction >= WARN_AT
                else BAR_OK
            )

        render.draw_bar(image, reading.fraction, box=box, color=colour)
        return image

    def _reading(self, action_id, settings, ctx):
        if action_id == "display_brightness":
            number = _display_number(settings)
            value = self.ddc.brightness(number) if number is not None else None
            if value is None:
                # Noch kein Wert gelesen — das dauert beim ersten Mal knapp
                # zwei Sekunden und läuft im Hintergrund.
                return Reading(0.0, None, "…", available=False)
            return Reading(float(value), value / 100, f"{value} %")

        metric = settings.get("metric") or "cpu"
        info = self.info
        if metric == "cpu":
            return info.cpu_percent()
        if metric == "cpu_temp":
            return info.cpu_temp()
        if metric == "memory":
            return info.memory()
        if metric == "swap":
            return info.swap()
        if metric == "gpu":
            return info.gpu("utilization")
        if metric == "gpu_temp":
            return info.gpu("temperature")
        if metric == "gpu_memory":
            return info.gpu("memory")
        if metric == "nvme_temp":
            return info.nvme_temp()
        if metric == "disk":
            return info.disk_usage(settings.get("path") or "/")
        if metric in ("net_down", "net_up"):
            return info.network(settings.get("interface") or "", metric.split("_")[1])
        return Reading(0.0, None, "—", available=False)

    def on_tick(self, action_id, settings, ctx):
        """Messwerte neu holen — nur für die Kacheln, die welche zeigen."""
        if action_id == "multimedia":
            # Der Zustand kommt von einem fremden Programm; ohne Nachfragen
            # bliebe das Symbol auf „spielt", nachdem woanders pausiert wurde.
            self.run_async(self._refresh_media(settings, ctx))
            return
        if action_id not in ("monitor", "display_brightness"):
            return
        reading = self._reading(action_id, settings, ctx)
        # Nur neu zeichnen, wenn sich der *angezeigte* Text ändert. Sonst
        # schickt eine CPU-Anzeige jede Sekunde ein Bild über USB, obwohl
        # dieselbe Zahl daraufsteht.
        if ctx.scratch.get("text") != reading.text:
            ctx.scratch["text"] = reading.text
            ctx.request_redraw()

    async def _refresh_media(self, settings, ctx) -> None:
        state = await self.services.media.refresh(settings.get("player") or "")
        signature = (state.playing, state.title, state.artist)
        if ctx.scratch.get("media") != signature:
            ctx.scratch["media"] = signature
            ctx.request_redraw()

    def get_label(self, action_id, settings, ctx):
        if action_id == "power" and ctx.scratch.get("armed_until", 0) > time.monotonic():
            # Während der Rückfrage schlägt die Beschriftung alles andere —
            # der Benutzer muss sehen, dass der nächste Druck ernst wird.
            return "Sicher?"
        if ctx.appearance.label_text:
            return None
        if action_id == "hotkey":
            return (settings.get("combo") or "").strip() or None
        if action_id == "window":
            return (settings.get("shortcut") or "").strip() or None
        if action_id == "multimedia" and settings.get("show_title"):
            state = self.services.media.state
            return state.title or state.player or None
        # Ohne eigenes Label wenigstens einen sprechenden Namen zeigen.
        if action_id == "launch":
            command = (settings.get("command") or "").strip()
            return Path(shlex.split(command)[0]).name if command else None
        if action_id in ("open_folder", "open_file"):
            path = (settings.get("path") or "").strip()
            return Path(path).name or path if path else None
        if action_id == "open_url":
            url = (settings.get("url") or "").strip()
            return url.replace("https://", "").replace("http://", "").split("/")[0] or None
        if action_id in ("monitor", "display_brightness"):
            reading = self._reading(action_id, settings, ctx)
            if action_id == "monitor" and ctx.setting("show_name", True):
                name = METRIC_LABELS.get(settings.get("metric") or "cpu", "")
                return f"{name} {reading.text}" if name else reading.text
            return reading.text
        return None

    def get_state(self, action_id, settings, ctx):
        if action_id == "hotkey":
            return "held" if ctx.scratch.get("held") else "default"
        if action_id == "hotkey_switch":
            return "b" if ctx.scratch.get("toggled") else "a"
        if action_id == "power":
            return "armed" if ctx.scratch.get("armed_until", 0) > time.monotonic() else "default"
        if action_id == "multimedia":
            return "playing" if self.services.media.state.playing else "paused"
        return None

    # -- Auswahllisten -----------------------------------------------------

    def get_dynamic_options(self, source, context=None):
        # Die D-Bus-Listen sind ``async``; dieser Hook läuft in einem
        # Worker-Thread und darf deshalb auf sie warten.
        if source == "players":
            players = self._await(self.services.media.list_players()) or []
            return [{"value": "", "label": "Automatisch (was gerade spielt)"}] + [
                {"value": name, "label": name} for name in players
            ]
        if source == "shortcut_components":
            return self._await(self.services.desktop.list_components()) or []
        if source == "shortcuts":
            component = (context or {}).get("component") or "kwin"
            return self._await(self.services.desktop.list_shortcuts(component)) or []
        if source == "displays":
            if not self.ddc.available():
                return []
            return [
                {"value": str(d.number), "label": d.label} for d in self.ddc.displays()
            ]
        if source == "interfaces":
            return [{"value": "", "label": "Alle zusammen"}] + [
                {"value": name, "label": name} for name in self.info.interfaces()
            ]
        return []

    def _await(self, coro, timeout: float = 8.0):
        """Wartet aus einem Worker-Thread heraus auf eine Coroutine.

        Die Auswahllisten kommen über D-Bus und damit aus dem Event-Loop,
        aufgerufen wird ``get_dynamic_options`` aber synchron im Executor.
        Ohne diese Brücke bliebe die Liste in der GUI leer.
        """
        loop = getattr(self.services.runtime, "_loop", None)
        if loop is None or loop.is_closed():
            coro.close()
            return None
        try:
            return asyncio.run_coroutine_threadsafe(coro, loop).result(timeout)
        except Exception as exc:
            self.log.warning("Auswahlliste nicht abrufbar: %s", exc)
            return None

    def get_status(self):
        """Hinweis in der Plugin-Liste, wenn DDC nicht durchkommt."""
        if not self.ddc.available():
            return None
        displays = self.ddc.displays()
        if displays:
            return {"connected": True, "detail": f"{len(displays)} Monitor(e) über DDC"}
        return {"connected": False, "detail": self.ddc.last_error or "kein DDC-Monitor"}

    # -- Ausführung --------------------------------------------------------

    def _activate(self, action_id, settings, ctx) -> None:
        try:
            if action_id == "launch":
                self._launch(settings)
            elif action_id in ("open_folder", "open_file"):
                self._open_path(settings)
            elif action_id == "open_url":
                self._open_url(settings)
            elif action_id == "run_script":
                self._run_script(settings)
            elif action_id == "display_brightness":
                self._toggle_brightness(settings, ctx)
            elif action_id == "hotkey":
                self._send_hotkey(settings)
            elif action_id == "hotkey_switch":
                self._switch_hotkey(settings, ctx)
            elif action_id == "text":
                self._type_text(settings)
            elif action_id == "multimedia":
                self._multimedia(settings, ctx)
            elif action_id == "power":
                self._power(settings, ctx)
            elif action_id == "screenshot":
                self._screenshot(settings)
            elif action_id == "close_app":
                self._close_app(settings)
            elif action_id == "window":
                self._window(settings)
        except Exception as exc:
            self.notify_error(f"{action_id}: {exc}")

    # -- Tastatur ----------------------------------------------------------

    def _send_hotkey(self, settings) -> None:
        combo = (settings.get("combo") or "").strip()
        if not combo:
            raise ValueError("Keine Tastenkombination eingestellt")
        self.services.input.send_combo(combo)

    def _hold_hotkey(self, settings, ctx, *, pressed: bool) -> None:
        combo = (settings.get("combo") or "").strip()
        if not combo:
            if pressed:
                self.notify_error("Keine Tastenkombination eingestellt")
            return
        try:
            self.services.input.hold_combo(combo, pressed)
        except Exception as exc:
            self.notify_error(f"hotkey: {exc}")
            return
        ctx.scratch["held"] = pressed
        ctx.request_redraw()

    def _switch_hotkey(self, settings, ctx) -> None:
        """Zwei Kombinationen im Wechsel — Elgatos „Hotkey Switch“."""
        second = ctx.scratch.get("toggled", False)
        key = "combo_b" if not second else "combo_a"
        combo = (settings.get(key) or "").strip()
        if not combo:
            raise ValueError(
                "Für diese Richtung ist keine Tastenkombination eingestellt"
            )
        self.services.input.send_combo(combo)
        ctx.scratch["toggled"] = not second
        ctx.request_redraw()

    def _type_text(self, settings) -> None:
        text = settings.get("text") or ""
        if not text:
            raise ValueError("Kein Text eingetragen")
        if settings.get("enter_after"):
            text += "\n"
        typed = self.services.input.type_text(
            text, delay_s=max(0, int(settings.get("delay_ms") or 12)) / 1000
        )
        if typed == 0:
            raise ValueError("Kein Zeichen war auf der Tastaturbelegung erreichbar")

    # -- Medien ------------------------------------------------------------

    def _multimedia(self, settings, ctx) -> None:
        command = settings.get("command") or "play_pause"
        player = settings.get("player") or ""
        self.run_async(self._multimedia_async(command, player, ctx))

    async def _multimedia_async(self, command: str, player: str, ctx) -> None:
        media = self.services.media
        if not await media.control(command, player=player):
            self.notify_info("Kein Medienspieler erreichbar")
        await media.refresh(player)
        ctx.request_redraw()

    # -- Sitzung, Fenster, Bildschirmfoto ---------------------------------

    def _power(self, settings, ctx) -> None:
        command = settings.get("command") or "lock"
        if settings.get("confirm") and not self._confirmed(ctx):
            return
        self.run_async(self._desktop_call(self.services.desktop.power(command)))

    def _window(self, settings) -> None:
        component = settings.get("component") or "kwin"
        shortcut = (settings.get("shortcut") or "").strip()
        self.run_async(
            self._desktop_call(
                self.services.desktop.invoke_shortcut(component, shortcut)
            )
        )

    async def _desktop_call(self, coro) -> None:
        try:
            await coro
        except Exception as exc:
            self.notify_error(str(exc))

    def _screenshot(self, settings) -> None:
        path = self.services.desktop.screenshot(
            settings.get("mode") or "fullscreen",
            directory=(settings.get("directory") or "").strip(),
            to_clipboard=bool(settings.get("clipboard")),
            delay_ms=int(settings.get("delay_ms") or 0),
        )
        self.notify_info(
            f"Bildschirmfoto gespeichert: {path}" if path
            else "Bildschirmfoto in der Zwischenablage"
        )

    def _close_app(self, settings) -> None:
        pattern = (settings.get("pattern") or "").strip()
        hits = self.services.desktop.close_application(
            pattern, force=bool(settings.get("force"))
        )
        if not hits:
            self.notify_info(f"Kein laufender Prozess passt auf '{pattern}'")

    def _confirmed(self, ctx) -> bool:
        """„Zweimal drücken“ — der erste Druck macht nur scharf.

        Ein versehentlich getroffenes Herunterfahren wäre der teuerste
        Fehlgriff, den dieses Gerät anbieten kann.
        """
        now = time.monotonic()
        armed_until = ctx.scratch.get("armed_until", 0.0)
        if now < armed_until:
            ctx.scratch["armed_until"] = 0.0
            ctx.request_redraw()
            return True
        ctx.scratch["armed_until"] = now + CONFIRM_WINDOW_S
        ctx.request_redraw()
        self.run_async(self._disarm_later(ctx))
        return False

    async def _disarm_later(self, ctx) -> None:
        await asyncio.sleep(CONFIRM_WINDOW_S)
        if ctx.scratch.get("armed_until"):
            ctx.scratch["armed_until"] = 0.0
            ctx.request_redraw()

    def _toggle_brightness(self, settings, ctx) -> None:
        """Druck auf das Dial: zwischen zwei Werten hin- und herschalten."""
        number = _display_number(settings)
        if number is None:
            raise ValueError("Kein Monitor eingestellt")
        low = int(ctx.setting("preset_low", 20))
        high = int(ctx.setting("preset_high", 80))
        current = self.ddc.brightness(number)
        target = high if current is None or current <= (low + high) // 2 else low
        self.ddc.set(number, target)
        ctx.request_redraw()

    def _launch(self, settings) -> None:
        raw = (settings.get("command") or "").strip()
        if not raw:
            raise ValueError("Kein Befehl eingetragen")

        parts = shlex.split(raw)
        binary = parts[0]
        if shutil.which(binary) is None and not Path(binary).expanduser().is_file():
            raise FileNotFoundError(f"'{binary}' nicht gefunden")

        if settings.get("single_instance") and _is_running(Path(binary).name):
            self.log.info("'%s' läuft bereits — nicht erneut gestartet", binary)
            return

        working_dir = (settings.get("working_dir") or "").strip()
        cwd = str(Path(working_dir).expanduser()) if working_dir else None
        _spawn(parts, cwd=cwd)

    def _open_path(self, settings) -> None:
        raw = (settings.get("path") or "").strip()
        if not raw:
            raise ValueError("Kein Pfad eingetragen")
        path = Path(raw).expanduser()
        if not path.exists():
            raise FileNotFoundError(f"'{path}' existiert nicht")
        _spawn(["xdg-open", str(path)])

    def _open_url(self, settings) -> None:
        url = (settings.get("url") or "").strip()
        if not url:
            raise ValueError("Keine URL eingetragen")
        if "://" not in url:
            url = f"https://{url}"
        if not url.startswith(("http://", "https://")):
            raise ValueError("Nur http(s)-Links werden geöffnet")
        _spawn(["xdg-open", url])

    def _run_script(self, settings) -> None:
        command = (settings.get("command") or "").strip()
        if not command:
            raise ValueError("Kein Befehl eingetragen")
        shell = settings.get("shell") or "fish"
        if shutil.which(shell) is None:
            shell = "sh"
        _spawn([shell, "-c", command])


def _display_number(settings) -> int | None:
    raw = (settings.get("display") or "").strip()
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _spawn(command: list[str], cwd: str | None = None) -> None:
    subprocess.Popen(
        command,
        cwd=cwd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        env=os.environ.copy(),
    )


def _is_running(name: str) -> bool:
    if shutil.which("pgrep") is None:
        return False
    result = subprocess.run(
        ["pgrep", "-x", name], capture_output=True, text=True, check=False
    )
    return result.returncode == 0
