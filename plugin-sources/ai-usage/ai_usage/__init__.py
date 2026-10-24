"""KI-Nutzung aus CodexBar, mit direktem Claude-Abruf als Fallback.

Das Paket holt die Daten und übersetzt sie in das Modell aus
:mod:`.model`. Mit Tasten, Dials und Bildern hat es nichts zu tun, das
erledigt ``plugin.py``.
"""

from .codexbar import SourceError
from .model import ProviderUsage, Snapshot, UsageWindow, level
from .poller import Alerts, Poller, PollSettings

__all__ = [
    "Alerts",
    "PollSettings",
    "Poller",
    "ProviderUsage",
    "Snapshot",
    "SourceError",
    "UsageWindow",
    "level",
]
