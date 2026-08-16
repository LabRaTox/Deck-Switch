"""Autostart des Backends als systemd-User-Dienst.

Der Schalter in den Einstellungen schreibt dieselbe Unit, die auch
``scripts/install-service.sh`` anlegt, und ruft danach ``systemctl --user
enable`` bzw. ``disable``. Beide Wege führen zum selben Ergebnis; wer das
Skript schon benutzt hat, sieht den Zustand im Schalter wieder.

systemd wird vorausgesetzt — die App zielt auf CachyOS und Arch, dort ist es
Standard. Geprüft wird trotzdem, ob eine *User-Instanz* erreichbar ist: Das
ist keine Distributionsfrage, sondern hängt an der Sitzung, und ohne Bus
gäbe es nur eine unverständliche Fehlermeldung.

Bewusst *ohne* ``--now``: Das Backend beantwortet gerade den Request, der
den Schalter umlegt. ``disable --now`` würde den eigenen Prozess mitten in
der Antwort beenden, ``enable --now`` eine zweite Instanz starten, wenn die
App von Hand aus dem Terminal läuft — und der HID-Zugriff aufs Deck ist
exklusiv. Der Schalter regelt darum nur den *nächsten* Login.

Die Unit wird bei jedem Einschalten neu geschrieben. Das ist idempotent und
heilt den Fall, dass das Repo seit der letzten Installation verschoben
wurde und die alte Unit ins Leere zeigt.
"""

from __future__ import annotations

import logging
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

log = logging.getLogger(__name__)

UNIT_NAME = "deckswitch.service"
UNIT_DIR = Path.home() / ".config" / "systemd" / "user"

COMMAND_TIMEOUT_S = 5.0


class AutostartUnavailable(RuntimeError):
    """Keine systemd-User-Instanz erreichbar."""


class AutostartError(RuntimeError):
    """systemctl hat den Wunsch abgelehnt."""


@dataclass(slots=True)
class AutostartStatus:
    #: Lässt sich der Autostart gerade schalten?
    supported: bool
    enabled: bool
    unit_installed: bool
    unit_path: str
    #: Gefüllt, wenn ``supported`` falsch ist — Text für die GUI.
    reason: str | None = None

    def as_dict(self) -> dict:
        return asdict(self)


# --------------------------------------------------------------------------
# Öffentlich
# --------------------------------------------------------------------------


def status() -> AutostartStatus:
    """Aktueller Zustand — ohne etwas zu verändern."""
    unit = UNIT_DIR / UNIT_NAME
    reason = _unsupported_reason()
    if reason is not None:
        return AutostartStatus(
            supported=False,
            enabled=False,
            unit_installed=unit.exists(),
            unit_path=str(unit),
            reason=reason,
        )

    result = _systemctl("is-enabled", UNIT_NAME)
    return AutostartStatus(
        supported=True,
        # "enabled" ist der einzige Wert, der wirklich Autostart bedeutet —
        # "linked", "static" und "disabled" tun es nicht.
        enabled=result.stdout.strip() == "enabled",
        unit_installed=unit.exists(),
        unit_path=str(unit),
    )


def set_enabled(enabled: bool) -> AutostartStatus:
    """Schaltet den Autostart und liefert den neuen Zustand zurück."""
    reason = _unsupported_reason()
    if reason is not None:
        raise AutostartUnavailable(reason)

    if enabled:
        _write_unit()
        _systemctl("daemon-reload")
        result = _systemctl("enable", UNIT_NAME)
    elif (UNIT_DIR / UNIT_NAME).exists():
        result = _systemctl("disable", UNIT_NAME)
    else:
        # Ohne Unit gibt es nichts abzuschalten — das Ziel ist schon erreicht.
        return status()

    if result.returncode != 0:
        message = (result.stderr or result.stdout).strip()
        raise AutostartError(message or "systemctl schlug ohne Meldung fehl")

    return status()


# --------------------------------------------------------------------------
# Intern
# --------------------------------------------------------------------------


def _systemctl(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["systemctl", "--user", *args],
        capture_output=True,
        text=True,
        timeout=COMMAND_TIMEOUT_S,
        check=False,
    )


def _unsupported_reason() -> str | None:
    """``None``, wenn geschaltet werden kann — sonst der Grund im Klartext."""
    try:
        probe = _systemctl("is-system-running")
    except (OSError, subprocess.SubprocessError) as exc:
        log.warning("systemctl nicht ausführbar: %s", exc)
        return f"systemctl ließ sich nicht ausführen: {exc}"
    # Ein Rückgabewert ungleich 0 heißt hier meist nur "degraded" — kein
    # Hinderungsgrund. Fehlt dagegen der Bus, gibt es keine User-Instanz,
    # die eine Unit aktivieren könnte.
    if "bus" in (probe.stderr or "").lower():
        return "Keine systemd-Sitzung für diesen Benutzer erreichbar."
    return None


def _repo_root() -> Path:
    """…/backend/deckswitch/services/autostart.py → Repo-Wurzel."""
    return Path(__file__).resolve().parents[3]


def _write_unit() -> Path:
    repo = _repo_root()
    template = repo / "packaging" / UNIT_NAME
    try:
        text = template.read_text(encoding="utf-8")
    except OSError as exc:
        raise AutostartError(f"Unit-Vorlage nicht lesbar: {template} ({exc})") from exc

    text = _use_running_interpreter(text.replace("__REPO__", str(repo)), repo)

    UNIT_DIR.mkdir(parents=True, exist_ok=True)
    unit = UNIT_DIR / UNIT_NAME
    unit.write_text(text, encoding="utf-8")
    log.info("Unit geschrieben: %s", unit)
    return unit


def _use_running_interpreter(text: str, repo: Path) -> str:
    """Setzt den echten Interpreter ein, wenn es keine ``.venv`` gibt.

    Die Vorlage geht von ``<repo>/.venv/bin/python`` aus. Läuft die App aus
    einer anders benannten Umgebung, zeigte die Unit sonst auf eine Datei,
    die es nicht gibt — der Dienst scheiterte dann erst beim nächsten Login,
    wo es niemand mehr mit dem Schalter in Verbindung bringt.
    """
    venv_python = repo / ".venv" / "bin" / "python"
    if venv_python.exists():
        return text
    return text.replace(str(venv_python), sys.executable)
