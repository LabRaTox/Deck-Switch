"""System-Plugin: Programme starten, Systemwerte zeigen, Monitore regeln.

Gestartete Prozesse werden bewusst abgekoppelt (eigene Session, Ausgabe
verworfen): das Deck ist eine Fernbedienung, kein Terminal — ein gestartetes
Programm darf nicht sterben, wenn das Backend neu startet.

Zwei Nachbarmodule gehören dazu: ``sysinfo`` liest die Messwerte,
``ddc`` regelt die Monitorhelligkeit. Letzteres ist deshalb ausgelagert,
weil ``ddcutil`` fast zwei Sekunden pro Aufruf braucht und das eine eigene
Behandlung verlangt — siehe die Erklärung dort.
"""

from __future__ import annotations

import dataclasses
import os
import shlex
import shutil
import subprocess
from pathlib import Path

from deckswitch.plugins.base import ActionPlugin

from ddc import DdcController
from sysinfo import Reading, SystemInfo

ACCENT = "#0ea5e9"

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
        self._activate(action_id, settings, ctx)

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

        gauge_ctx = ctx
        if show_bar and ctx.appearance.label_position == "bottom":
            # Der Balken sitzt am unteren Rand — dort steht sonst die
            # Beschriftung, und beides übereinander ist unlesbar. Wer die
            # Position bewusst auf oben oder Mitte stellt, behält sie.
            gauge_ctx = dataclasses.replace(
                ctx,
                appearance=ctx.appearance.model_copy(update={"label_position": "top"}),
            )

        image = render.render_slot(
            gauge_ctx,
            state=None,
            label_override=self.get_label(action_id, settings, ctx),
            accent=ACCENT,
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

        width, height = ctx.size
        if ctx.input_type == "dial":
            box = (12, height - 22, width - 12, height - 12)
        else:
            box = (10, height - 12, width - 10, height - 6)
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
        if action_id not in ("monitor", "display_brightness"):
            return
        reading = self._reading(action_id, settings, ctx)
        # Nur neu zeichnen, wenn sich der *angezeigte* Text ändert. Sonst
        # schickt eine CPU-Anzeige jede Sekunde ein Bild über USB, obwohl
        # dieselbe Zahl daraufsteht.
        if ctx.scratch.get("text") != reading.text:
            ctx.scratch["text"] = reading.text
            ctx.request_redraw()

    def get_label(self, action_id, settings, ctx):
        if ctx.appearance.label_text:
            return None
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

    # -- Auswahllisten -----------------------------------------------------

    def get_dynamic_options(self, source, context=None):
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
        except Exception as exc:
            self.notify_error(f"{action_id}: {exc}")

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
