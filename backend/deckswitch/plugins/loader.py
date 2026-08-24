"""Findet, lädt und registriert Plugins.

Mitgelieferte und nachinstallierte Plugins laufen durch denselben Code —
"eingebaut" heißt hier nur "liegt in einem anderen Suchpfad", nicht
"Sonderweg im Backend".

Ladefehler werden gesammelt statt geworfen: ein kaputtes Drittanbieter-Plugin
darf die App nicht am Start hindern, muss aber in der GUI sichtbar werden.
"""

from __future__ import annotations

import importlib.util
import json
import logging
import sys
import traceback
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import ValidationError

from .. import paths
from .base import ActionPlugin, CanvasPlugin, Manifest, Services

log = logging.getLogger(__name__)

#: Plugin-Typen, deren Klasse von :class:`CanvasPlugin` erben muss.
CANVAS_TYPES = frozenset({"screensaver", "wallpaper"})


@dataclass(slots=True)
class LoadedPlugin:
    manifest: Manifest
    directory: Path
    instance: ActionPlugin | None = None
    #: True für mitgelieferte Plugins — die GUI blendet "Deinstallieren" aus.
    builtin: bool = False
    enabled: bool = True
    error: str | None = None

    @property
    def id(self) -> str:
        return self.manifest.id

    @property
    def is_iconset(self) -> bool:
        return self.manifest.type == "iconset"

    @property
    def is_screensaver(self) -> bool:
        return self.manifest.type == "screensaver"

    @property
    def is_wallpaper(self) -> bool:
        return self.manifest.type == "wallpaper"

    @property
    def icons_path(self) -> Path:
        return self.directory / self.manifest.icons_dir


@dataclass(slots=True)
class PluginError:
    plugin_id: str
    directory: str
    message: str
    traceback: str = ""


def _kollision(directory: Path) -> str:
    """Sucht den Grund, wenn ein Import in einem Plugin fehlgeschlagen ist.

    Ein Plugin darf seine Nachbardateien auch beim kurzen Namen importieren
    (``from api import …``) — dann teilt es sich den Modulraum mit allen
    anderen. Hieß dort eine Datei genauso, bekam es stillschweigend die
    fremde und scheiterte an einem Namen, den es in seiner eigenen Datei
    sehr wohl gibt; der Fehler zeigte auf den falschen Ordner.

    Gesucht wird das erst, wenn wirklich etwas schiefging. Vorher zu
    sperren wäre falsch: Wer relativ importiert (``from .api import …``),
    ist von allem abgeschottet, und zwei gleichnamige Dateien sind dann
    kein Problem, sondern normal.
    """
    for datei in sorted(directory.glob("*.py")):
        name = datei.stem
        if name in ("plugin", "screenshots", "__init__"):
            continue
        belegt = sys.modules.get(name)
        anderer = getattr(belegt, "__file__", None) if belegt is not None else None
        if anderer and Path(anderer).resolve() != datei.resolve():
            return (
                f" — Hinweis: Der Modulname '{name}' war schon von {anderer} "
                f"belegt. Importiere die Nachbardatei relativ "
                f"('from .{name} import …'), dann kann das nicht passieren."
            )
    return ""


class PluginRegistry:
    def __init__(self) -> None:
        self.plugins: dict[str, LoadedPlugin] = {}
        self.errors: list[PluginError] = []
        #: Beim Scannen zu übernehmende Plugins — siehe :meth:`discover`.
        self._behalte: dict[str, LoadedPlugin] = {}

    # -- Suchen und Laden --------------------------------------------------

    def discover(
        self,
        services_factory,
        *,
        disabled: list[str] | None = None,
        search_paths: list[tuple[Path, bool]] | None = None,
        behalte: dict[str, "LoadedPlugin"] | None = None,
    ) -> None:
        """Scannt die Plugin-Ordner und lädt alles Gefundene.

        ``services_factory(plugin_dir)`` liefert den Services-Container für
        das jeweilige Plugin (Plugins bekommen ihren eigenen Ordner mit).

        ``behalte`` nennt Plugins, die schon laufen und unverändert sind:
        Sie werden übernommen statt neu erzeugt. Ohne das bekäme jedes
        Plugin bei jedem Scan eine frische Instanz — die alte liefe mit
        ihren Tasks und Verbindungen weiter, ohne dass sie noch jemand
        abbaut.
        """
        self.plugins.clear()
        self.errors.clear()
        disabled = disabled or []
        self._behalte = behalte or {}

        roots = search_paths or [
            (paths.BUILTIN_PLUGINS_DIR, True),
            (paths.USER_PLUGINS_DIR, False),
        ]

        for root, builtin in roots:
            if not root.is_dir():
                continue
            for directory in sorted(p for p in root.iterdir() if p.is_dir()):
                if directory.name.startswith((".", "_")):
                    continue
                self._load_one(directory, builtin, services_factory, disabled)

    def bestand(
        self, *, search_paths: list[tuple[Path, bool]] | None = None
    ) -> dict[str, tuple[Path, str]]:
        """Was auf der Platte liegt — ohne irgendetwas zu laden.

        Liefert ``{id: (ordner, version)}``. Gedacht für den Abgleich mit
        dem, was gerade läuft: Daran lässt sich ablesen, was neu dazukam,
        was verschwand und was eine andere Fassung bekommen hat — ohne ein
        einziges Plugin anzufassen.
        """
        roots = search_paths or [
            (paths.BUILTIN_PLUGINS_DIR, True),
            (paths.USER_PLUGINS_DIR, False),
        ]
        gefunden: dict[str, tuple[Path, str]] = {}
        for root, _builtin in roots:
            if not root.is_dir():
                continue
            for directory in sorted(p for p in root.iterdir() if p.is_dir()):
                if directory.name.startswith((".", "_")):
                    continue
                datei = directory / "manifest.json"
                if not datei.is_file():
                    continue
                try:
                    roh = json.loads(datei.read_text(encoding="utf-8"))
                    kennung = str(roh.get("id") or "")
                    fassung = str(roh.get("version") or "")
                except (json.JSONDecodeError, OSError):
                    continue
                if kennung and kennung not in gefunden:
                    gefunden[kennung] = (directory, fassung)
        return gefunden

    def _load_one(
        self,
        directory: Path,
        builtin: bool,
        services_factory,
        disabled: list[str],
    ) -> None:
        manifest_file = directory / "manifest.json"
        if not manifest_file.is_file():
            return

        # Läuft dieses Plugin schon unverändert, bleibt es, wie es ist.
        behalten = getattr(self, "_behalte", {})
        for kennung, vorhanden in behalten.items():
            if vorhanden.directory == directory:
                self.plugins[kennung] = vorhanden
                return

        try:
            manifest = Manifest.model_validate(
                json.loads(manifest_file.read_text(encoding="utf-8"))
            )
        except (json.JSONDecodeError, ValidationError) as exc:
            self._fail(directory.name, directory, f"Manifest ungültig: {exc}")
            return

        if manifest.id in self.plugins:
            self._fail(
                manifest.id,
                directory,
                f"Plugin-ID '{manifest.id}' doppelt vergeben — "
                f"{self.plugins[manifest.id].directory} gewinnt.",
            )
            return

        loaded = LoadedPlugin(
            manifest=manifest,
            directory=directory,
            builtin=builtin,
            enabled=manifest.id not in disabled,
        )

        if manifest.type == "iconset":
            if not loaded.icons_path.is_dir():
                loaded.error = f"Icon-Ordner fehlt: {loaded.icons_path}"
                self._fail(manifest.id, directory, loaded.error)
            self.plugins[manifest.id] = loaded
            return

        if loaded.enabled:
            try:
                loaded.instance = self._instantiate(
                    manifest, directory, services_factory(directory)
                )
            except Exception as exc:  # Plugin-Code — alles kann passieren
                loaded.error = f"{type(exc).__name__}: {exc}"
                self._fail(manifest.id, directory, loaded.error, traceback.format_exc())

        self.plugins[manifest.id] = loaded

    def _instantiate(
        self, manifest: Manifest, directory: Path, services: Services
    ) -> ActionPlugin:
        if not manifest.entry or not manifest.plugin_class:
            raise ValueError(
                f"{manifest.type}-Plugin braucht 'entry' und 'class' im Manifest"
            )

        entry = directory / manifest.entry
        if not entry.is_file():
            raise FileNotFoundError(f"Entry-Datei fehlt: {entry}")

        module_name = f"streamdeck_plugin_{manifest.id.replace('-', '_')}"
        # ``submodule_search_locations`` macht aus dem Modul ein Paket: Damit
        # findet ``from .api import …`` die Nachbardatei, und zwar genau die
        # aus *diesem* Ordner. Zwei Plugins dürfen ihre Hilfsdateien dann
        # gleich benennen, ohne sich in die Quere zu kommen.
        spec = importlib.util.spec_from_file_location(
            module_name, entry, submodule_search_locations=[str(directory)]
        )
        if spec is None or spec.loader is None:
            raise ImportError(f"Kann {entry} nicht laden")

        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        # Plugin-Ordner in den Suchpfad, damit mehrdateiige Plugins ihre
        # Nachbarmodule importieren können.
        added_path = str(directory)
        inserted = added_path not in sys.path
        if inserted:
            sys.path.insert(0, added_path)
        try:
            spec.loader.exec_module(module)
        except ImportError as exc:
            # Der häufigste Grund steht nicht in der Meldung — er steht in
            # sys.modules.
            raise ImportError(f"{exc}{_kollision(directory)}") from exc
        finally:
            if inserted:
                sys.path.remove(added_path)

        klass = getattr(module, manifest.plugin_class, None)
        if klass is None:
            raise AttributeError(
                f"Klasse '{manifest.plugin_class}' nicht in {manifest.entry} gefunden"
            )
        expected = CanvasPlugin if manifest.type in CANVAS_TYPES else ActionPlugin
        if not issubclass(klass, expected):
            raise TypeError(
                f"'{manifest.plugin_class}' erbt nicht von {expected.__name__} "
                f"(type='{manifest.type}' im Manifest)"
            )

        return klass(manifest, services)

    def _fail(
        self, plugin_id: str, directory: Path, message: str, tb: str = ""
    ) -> None:
        log.error("Plugin '%s' (%s): %s", plugin_id, directory, message)
        self.errors.append(PluginError(plugin_id, str(directory), message, tb))

    # -- Zugriff -----------------------------------------------------------

    def get(self, plugin_id: str) -> LoadedPlugin | None:
        return self.plugins.get(plugin_id)

    def instance(self, plugin_id: str) -> ActionPlugin | None:
        loaded = self.plugins.get(plugin_id)
        if loaded is None or not loaded.enabled:
            return None
        return loaded.instance

    @property
    def action_plugins(self) -> list[LoadedPlugin]:
        return [p for p in self.plugins.values() if p.manifest.type == "action"]

    @property
    def code_plugins(self) -> list[LoadedPlugin]:
        """Alles mit ausführbarem Code — Aktionen, Schoner, Hintergründe.

        Für Lebenszyklus und Config-Weitergabe: Nur ``action_plugins`` zu
        durchlaufen hieße, dass ein Schoner-Plugin nie ``setup()`` sähe und
        nach einem Config-Wechsel auf die alte Config zeigte.
        """
        return [
            p for p in self.plugins.values() if p.manifest.type != "iconset"
        ]

    @property
    def iconsets(self) -> list[LoadedPlugin]:
        return [p for p in self.plugins.values() if p.is_iconset]

    @property
    def screensavers(self) -> list[LoadedPlugin]:
        """Schoner-Plugins. Tauchen bewusst nicht unter ``action_plugins``
        auf — sie gehören in die Einstellungen, nicht auf eine Taste."""
        return [p for p in self.plugins.values() if p.is_screensaver]

    @property
    def wallpapers(self) -> list[LoadedPlugin]:
        """Plugins, die den Grund des Touchstrips malen."""
        return [p for p in self.plugins.values() if p.is_wallpaper]
