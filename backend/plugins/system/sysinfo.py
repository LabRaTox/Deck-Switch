"""Systemwerte sammeln — für die Monitor-Kacheln.

Alles, was aus ``/proc`` und ``/sys`` kommt, ist praktisch umsonst (unter
0,1 ms gemessen) und wird bei jedem Aufruf frisch gelesen. Nur ``nvidia-smi``
ist ein Unterprozess und kostet gut 20 ms; der Wert wird deshalb
zwischengespeichert, sonst zahlten acht Kacheln denselben Preis achtmal pro
Sekunde.

Werte, die eine Rate sind (CPU-Auslastung, Netzdurchsatz), brauchen zwei
Messungen. Der letzte Stand bleibt deshalb hier liegen.
"""

from __future__ import annotations

import glob
import logging
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

#: So lange gilt ein Wert von ``nvidia-smi`` als frisch.
GPU_TTL_S = 1.5
GPU_TIMEOUT_S = 4.0

#: hwmon-Treiber, die die CPU-Temperatur liefern — in dieser Reihenfolge.
CPU_TEMP_DRIVERS = ("k10temp", "coretemp", "zenpower", "cpu_thermal")


@dataclass
class Reading:
    """Ein Messwert samt Beschriftung."""

    value: float
    #: 0..1 für den Balken. ``None`` bei Werten ohne sinnvolle Obergrenze.
    fraction: float | None
    text: str
    available: bool = True


@dataclass
class _Rate:
    """Merkt sich den letzten Zählerstand für Delta-Berechnungen."""

    last: float = 0.0
    at: float = 0.0
    ready: bool = False


class SystemInfo:
    #: Temperaturen in Fahrenheit statt Celsius ausgeben. Wird vom Plugin
    #: aus dessen Einstellungen gesetzt.
    fahrenheit: bool = False

    def __init__(self) -> None:
        self._cpu_prev: tuple[int, int] | None = None
        self._net: dict[str, _Rate] = {}
        self._gpu: dict[str, float] = {}
        self._gpu_at = 0.0
        self._gpu_failed = False
        self._hwmon: dict[str, Path] = {}

    # -- CPU ---------------------------------------------------------------

    def cpu_percent(self) -> Reading:
        """Auslastung seit dem letzten Aufruf.

        Der allererste Aufruf hat keine Vergleichsbasis und meldet 0 — nach
        einer Sekunde stimmt der Wert.
        """
        try:
            fields = Path("/proc/stat").read_text().split("\n", 1)[0].split()[1:]
        except OSError:
            return Reading(0.0, None, "—", available=False)

        values = [int(v) for v in fields]
        idle = values[3] + (values[4] if len(values) > 4 else 0)
        total = sum(values)

        previous = self._cpu_prev
        self._cpu_prev = (idle, total)
        if previous is None:
            return Reading(0.0, 0.0, "0 %")

        idle_delta = idle - previous[0]
        total_delta = total - previous[1]
        if total_delta <= 0:
            return Reading(0.0, 0.0, "0 %")

        percent = max(0.0, min(100.0, (1 - idle_delta / total_delta) * 100))
        return Reading(percent, percent / 100, f"{percent:.0f} %")

    def cpu_temp(self) -> Reading:
        path = self._temp_path(CPU_TEMP_DRIVERS)
        return self._read_temp(path, ceiling=95)

    # -- Speicher ----------------------------------------------------------

    def memory(self) -> Reading:
        info = self._meminfo()
        total = info.get("MemTotal", 0)
        available = info.get("MemAvailable", 0)
        if not total:
            return Reading(0.0, None, "—", available=False)
        used = total - available
        percent = used / total * 100
        return Reading(percent, percent / 100, f"{used / 1024 / 1024:.1f} GB")

    def swap(self) -> Reading:
        info = self._meminfo()
        total = info.get("SwapTotal", 0)
        if not total:
            return Reading(0.0, 0.0, "aus")
        used = total - info.get("SwapFree", 0)
        percent = used / total * 100
        return Reading(percent, percent / 100, f"{used / 1024 / 1024:.1f} GB")

    def _meminfo(self) -> dict[str, int]:
        try:
            lines = Path("/proc/meminfo").read_text().splitlines()
        except OSError:
            return {}
        result = {}
        for line in lines:
            name, _, rest = line.partition(":")
            parts = rest.split()
            if parts:
                result[name] = int(parts[0])  # kB
        return result

    # -- GPU ---------------------------------------------------------------

    def gpu(self, field_name: str) -> Reading:
        """``utilization``, ``temperature`` oder ``memory`` der NVIDIA-GPU."""
        values = self._gpu_values()
        if not values:
            return Reading(0.0, None, "—", available=False)

        if field_name == "temperature":
            celsius = values.get("temperature.gpu", 0.0)
            # Der Balken rechnet weiter in Celsius — 90 °C sind 90 °C, egal
            # in welcher Einheit die Zahl daneben steht.
            return Reading(celsius, min(1.0, celsius / 95), self._temperature(celsius))
        if field_name == "memory":
            used = values.get("memory.used", 0.0)
            total = values.get("memory.total", 0.0) or 1
            return Reading(used, used / total, f"{used / 1024:.1f} GB")
        value = values.get("utilization.gpu", 0.0)
        return Reading(value, value / 100, f"{value:.0f} %")

    def _gpu_values(self) -> dict[str, float]:
        now = time.monotonic()
        if self._gpu_failed:
            return {}
        if self._gpu and now - self._gpu_at < GPU_TTL_S:
            return self._gpu

        query = "utilization.gpu,temperature.gpu,memory.used,memory.total"
        try:
            result = subprocess.run(
                ["nvidia-smi", f"--query-gpu={query}", "--format=csv,noheader,nounits"],
                capture_output=True,
                text=True,
                timeout=GPU_TIMEOUT_S,
            )
        except (OSError, subprocess.SubprocessError):
            # Keine NVIDIA-GPU oder kein Treiber — einmal merken und nicht
            # jede Sekunde erneut einen Unterprozess dafür starten.
            self._gpu_failed = True
            return {}

        line = result.stdout.strip().splitlines()
        if result.returncode != 0 or not line:
            self._gpu_failed = True
            return {}

        parts = [p.strip() for p in line[0].split(",")]
        try:
            self._gpu = dict(zip(query.split(","), (float(p) for p in parts)))
        except ValueError:
            self._gpu_failed = True
            return {}
        self._gpu_at = now
        return self._gpu

    # -- Datenträger und Netz ---------------------------------------------

    def nvme_temp(self) -> Reading:
        return self._read_temp(self._temp_path(("nvme",)), ceiling=80)

    def disk_usage(self, path: str = "/") -> Reading:
        import shutil as _shutil

        try:
            usage = _shutil.disk_usage(path or "/")
        except OSError:
            return Reading(0.0, None, "—", available=False)
        percent = usage.used / usage.total * 100
        return Reading(percent, percent / 100, f"{usage.free / 1024**3:.0f} GB frei")

    def network(self, interface: str, direction: str) -> Reading:
        """Durchsatz in Byte/s. ``interface`` leer = alle zusammen."""
        try:
            lines = Path("/proc/net/dev").read_text().splitlines()[2:]
        except OSError:
            return Reading(0.0, None, "—", available=False)

        total = 0
        for line in lines:
            name, _, rest = line.partition(":")
            name = name.strip()
            if name == "lo":
                continue
            if interface and name != interface:
                continue
            fields = rest.split()
            if len(fields) < 9:
                continue
            total += int(fields[0] if direction == "down" else fields[8])

        key = f"{interface or '*'}:{direction}"
        rate = self._net.setdefault(key, _Rate())
        now = time.monotonic()
        elapsed = now - rate.at
        previous, rate.last, rate.at = rate.last, total, now

        if not rate.ready:
            rate.ready = True
            return Reading(0.0, 0.0, _bytes_per_second(0))

        per_second = max(0.0, (total - previous) / elapsed) if elapsed > 0 else 0.0
        # Balken relativ zu 100 MB/s — reicht für Gigabit und darüber
        # verhält es sich wie ein Vollausschlag.
        return Reading(per_second, min(1.0, per_second / 100e6), _bytes_per_second(per_second))

    def interfaces(self) -> list[str]:
        """Echte Schnittstellen — ohne Loopback und Container-Beiwerk.

        Docker-Brücken und die ``veth``-Hälften laufender Container stehen
        sonst zu Dutzenden in der Auswahl und verdecken die zwei, die man
        wirklich meint.
        """
        try:
            lines = Path("/proc/net/dev").read_text().splitlines()[2:]
        except OSError:
            return []
        names = [line.partition(":")[0].strip() for line in lines]
        return [
            n
            for n in names
            if n
            and n != "lo"
            and not n.startswith(("veth", "br-", "docker", "virbr", "tun", "tap"))
        ]

    # -- Temperaturen ------------------------------------------------------

    def _temp_path(self, drivers: tuple[str, ...]) -> Path | None:
        key = drivers[0]
        if key in self._hwmon:
            return self._hwmon[key]

        for wanted in drivers:
            for name_file in sorted(glob.glob("/sys/class/hwmon/hwmon*/name")):
                try:
                    if Path(name_file).read_text().strip() != wanted:
                        continue
                except OSError:
                    continue
                for candidate in sorted(Path(name_file).parent.glob("temp*_input")):
                    self._hwmon[key] = candidate
                    return candidate
        self._hwmon[key] = None  # type: ignore[assignment]
        return None

    def _read_temp(self, path: Path | None, ceiling: int) -> Reading:
        if path is None:
            return Reading(0.0, None, "—", available=False)
        try:
            millidegrees = int(path.read_text().strip())
        except (OSError, ValueError):
            return Reading(0.0, None, "—", available=False)
        celsius = millidegrees / 1000
        return Reading(celsius, min(1.0, celsius / ceiling), self._temperature(celsius))


    def _temperature(self, celsius: float) -> str:
        if self.fahrenheit:
            return f"{celsius * 9 / 5 + 32:.0f} °F"
        return f"{celsius:.0f} °C"


def _bytes_per_second(value: float) -> str:
    for unit, factor in (("GB/s", 1e9), ("MB/s", 1e6), ("kB/s", 1e3)):
        if value >= factor:
            return f"{value / factor:.1f} {unit}"
    return f"{value:.0f} B/s"
