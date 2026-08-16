"""Plugin-API: Basisklasse, Manifest-Modell und Services-Container.

Für Plugin-Autoren ist das die einzige Datei, die man kennen muss.

Ein Plugin besteht aus einem ``manifest.json`` und (bei Action-Plugins) einer
Python-Datei mit genau einer Klasse, die von :class:`ActionPlugin` erbt. Alle
Hooks sind optional; jeder darf ``def`` oder ``async def`` sein — die Runtime
führt synchrone Hooks in einem Worker-Thread aus, damit ein blockierender
Subprozess-Aufruf (``wpctl``, ``pactl``) niemals den Event-Loop anhält.

Hook-Signaturen folgen dem Muster ``(action_id, settings, …, ctx)``: der
``ctx`` ist nötig, weil dieselbe Action mehrfach belegt sein kann (z. B. eine
Taste je Ausgabegerät) und ein Hook wissen muss, *welche* Belegung ihn
aufruft — und weil er darüber ein sofortiges Neuzeichnen anstößt.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Protocol

from PIL import Image
from pydantic import BaseModel, Field

if TYPE_CHECKING:  # pragma: no cover - nur für Typprüfung
    from ..config import Appearance, Config, Slot
    from ..services.audio import AudioService
    from ..services.icons import IconService
    from ..services.render import RenderService

log = logging.getLogger(__name__)

InputType = Literal["key", "dial"]

# --------------------------------------------------------------------------
# Manifest
# --------------------------------------------------------------------------

#: Ein Text im Manifest darf entweder ein String oder ein Locale-Mapping sein:
#: ``"Lautstärke"`` oder ``{"de": "Lautstärke", "en": "Volume"}``.
LocalizedText = str | dict[str, str]


def localize(text: LocalizedText | None, language: str = "de") -> str:
    if text is None:
        return ""
    if isinstance(text, str):
        return text
    return text.get(language) or text.get("en") or next(iter(text.values()), "")


class SettingsField(BaseModel):
    """Ein Eingabefeld, das die GUI generisch rendern kann.

    Damit muss die GUI kein einziges Plugin namentlich kennen: sie baut das
    Formular aus dem Schema, das im Manifest steht.
    """

    key: str
    label: LocalizedText = ""
    type: Literal[
        "text", "number", "bool", "select", "color", "path", "file", "password", "hotkey"
    ] = "text"
    default: Any = None
    placeholder: LocalizedText = ""
    help: LocalizedText = ""
    options: list[dict[str, Any]] = Field(default_factory=list)
    #: Statt statischer ``options``: Bezeichner, den das Plugin zur Laufzeit
    #: über :meth:`ActionPlugin.get_dynamic_options` auflöst (z. B. Sink-Liste).
    options_source: str | None = None
    #: Felder, von denen die Auswahlliste abhängt — ändert sich eines davon,
    #: lädt die GUI die Optionen neu. Beispiel: die Filterliste hängt von der
    #: gewählten Quelle ab, die Quellenliste von der gewählten Szene.
    options_depend_on: list[str] = Field(default_factory=list)
    min: float | None = None
    max: float | None = None
    step: float | None = None
    #: Feld nur anzeigen, wenn ein anderes Feld einen bestimmten Wert hat.
    depends_on: dict[str, Any] | None = None


class ActionState(BaseModel):
    """Ein visueller Zustand einer Action (z. B. „normal“ / „stumm“)."""

    id: str
    name: LocalizedText = ""
    default_icon: str | None = None


class ActionDescriptor(BaseModel):
    id: str
    name: LocalizedText
    description: LocalizedText = ""
    #: Welche Eingabearten diese Action belegen kann.
    inputs: list[InputType] = Field(default_factory=lambda: ["key"])
    default_icon: str | None = None
    #: Standard-Label, das beim Ablegen auf eine Taste vorbelegt wird.
    default_label: LocalizedText = ""
    states: list[ActionState] = Field(default_factory=list)
    settings_schema: list[SettingsField] = Field(default_factory=list)
    #: Akzentfarbe für Hintergrund-Variante „accent“; None = Plugin-Akzent.
    accent: str | None = None


class Manifest(BaseModel):
    id: str
    name: LocalizedText
    version: str = "1.0.0"
    #: ``action`` belegt Tasten, ``iconset`` liefert Symbole, ``screensaver``
    #: malt den Bildschirmschoner, ``wallpaper`` den Grund des Touchstrips.
    #: Die letzten beiden tauchen bewusst *nicht* in der Aktionsbibliothek
    #: auf — man wählt sie in den Einstellungen.
    type: Literal["action", "iconset", "screensaver", "wallpaper"] = "action"
    description: LocalizedText = ""
    author: str = ""
    #: Bei allen Typen außer ``iconset``: Python-Datei im Plugin-Ordner.
    entry: str | None = None
    #: Bei allen Typen außer ``iconset``: Klassenname in ``entry``.
    plugin_class: str | None = Field(default=None, alias="class")
    accent: str = "#4b5563"
    #: Bilddatei im Plugin-Ordner, die das Plugin in der Übersicht vertritt —
    #: 256×256 PNG. Bewusst *nur* dort: In der Aktionsbibliothek stünde
    #: neben jeder Aktion desselben Plugins dasselbe Bild, das hilft beim
    #: Suchen nicht und macht die Liste unruhig.
    icon: str | None = None
    #: Globale Plugin-Einstellungen (OBS-Host, Discord-App-ID …) — getrennt
    #: von den Settings einer einzelnen Belegung.
    config_schema: list[SettingsField] = Field(default_factory=list)
    actions: list[ActionDescriptor] = Field(default_factory=list)
    #: Nur bei type="iconset": Ordner mit den SVG-Dateien.
    icons_dir: str = "icons"
    #: Nur bei type="iconset": Lizenzhinweis, den die GUI anzeigt.
    license: str = ""

    model_config = {"populate_by_name": True}

    def action(self, action_id: str) -> ActionDescriptor | None:
        for action in self.actions:
            if action.id == action_id:
                return action
        return None


# --------------------------------------------------------------------------
# Runtime-Schnittstelle (von der Runtime implementiert, hier nur als Vertrag)
# --------------------------------------------------------------------------


class RuntimeApi(Protocol):
    """Was ein Plugin von der laufenden Anwendung aus anstoßen darf."""

    def request_redraw(self, ctx: "SlotContext | None" = None) -> None:
        """Sofortiges Neuzeichnen anstoßen.

        Ohne ``ctx`` wird die komplette aktuelle Seite neu gezeichnet. Genau
        dafür da, dass ein Plugin auf Änderungen *von außen* reagieren kann,
        statt auf den nächsten Tick zu warten. Threadsicher.
        """

    def navigate(self, page_id: str) -> None: ...

    def navigate_home(self) -> None: ...

    def navigate_back(self) -> None: ...

    def step_page(self, delta: int, *, wrap: bool = True) -> bool:
        """Eine Seite vor oder zurück, innerhalb derselben Ebene."""

    def current_page_id(self) -> str: ...

    def page_number(self) -> int:
        """1-basierte Position der aktuellen Seite in der Geschwister-Reihe."""

    def notify(self, level: str, message: str, **extra: Any) -> None:
        """Meldung an die GUI (Fehler, Warnung, Info)."""

    async def run_steps(self, steps: list, ctx: "SlotContext", *, repeat: bool = False) -> None:
        """Führt eine Kette von Schritten aus (Multi-Aktion).

        Jeder Schritt ist entweder eine Pause oder eine ganz normale
        Plugin-Action, die genauso ausgelöst wird wie bei einem Tastendruck.
        Läuft im Hintergrund; ein zweiter Aufruf auf derselben Belegung
        bricht den ersten ab.
        """

    def stop_steps(self, ctx: "SlotContext") -> bool:
        """Bricht eine laufende Kette dieser Belegung ab."""

    def steps_running(self, ctx: "SlotContext") -> bool:
        """Läuft auf dieser Belegung gerade eine Kette?"""

    def publish_plugin_status(self, plugin_id: str) -> None:
        """Meldet der GUI, dass sich der Verbindungszustand geändert hat.

        Threadsicher. Die GUI holt sich daraufhin den neuen Status über
        :meth:`ActionPlugin.get_status`.
        """

    def save_config(self) -> None: ...


@dataclass(slots=True)
class Services:
    """Container, der jedem Plugin injiziert wird."""

    audio: "AudioService"
    icons: "IconService"
    render: "RenderService"
    runtime: RuntimeApi
    config: "Config"
    #: Ordner des jeweiligen Plugins — für mitgelieferte Assets.
    plugin_dir: Path = field(default_factory=Path)
    #: Virtuelle Tastatur (Tastenkombinationen, Text tippen).
    input: "Any" = None
    #: Der gerade laufende Medienspieler (MPRIS).
    media: "Any" = None
    #: Sitzung, Fenster, Bildschirmfotos.
    desktop: "Any" = None
    #: Soundboard-Wiedergabe.
    sound: "Any" = None
    #: Overlays der virtuellen Decks zeigen und verstecken.
    overlay: "Any" = None


# --------------------------------------------------------------------------
# Kontext einer einzelnen Belegung
# --------------------------------------------------------------------------


@dataclass(slots=True)
class SlotContext:
    """Alles, was ein Hook über die aufrufende Belegung wissen muss."""

    action_id: str
    settings: dict[str, Any]
    appearance: "Appearance"
    input_type: InputType
    #: Tastenindex 0..7 bzw. Dial-Index 0..3.
    index: int
    page_id: str
    profile_id: str
    #: Zeichenfläche in Pixeln: (120, 120) für Tasten, (200, 100) je Segment.
    size: tuple[int, int]
    services: Services
    slot: "Slot"
    #: Von der Runtime gesetzt: ob dies der Long-Press-Zweig einer Taste ist.
    is_long_press: bool = False
    #: Laufzeit in Sekunden, aus der animierte Bilder ihr Einzelbild wählen.
    #: Für stehende Kacheln bleibt sie 0 — dann ändert sich nichts.
    frame_time: float = 0.0
    #: Auf welchem Deck diese Belegung liegt. Bei nur einem Gerät belanglos;
    #: bei mehreren die Antwort auf „welches Deck hat mich gerufen?".
    deck_serial: str = ""
    #: Freier Zwischenspeicher pro Belegung, überlebt zwischen Hook-Aufrufen
    #: (z. B. gecachte Verbindungs-Handles oder letzte gelesene Werte).
    scratch: dict[str, Any] = field(default_factory=dict)

    @property
    def key(self) -> str:
        """Stabile Kennung dieser Belegung (Seite + Eingabeart + Index)."""
        return f"{self.page_id}:{self.input_type}:{self.index}"

    def request_redraw(self) -> None:
        self.services.runtime.request_redraw(self)

    def setting(self, name: str, default: Any = None) -> Any:
        value = self.settings.get(name, default)
        return default if value is None else value


# --------------------------------------------------------------------------
# Basisklassen
# --------------------------------------------------------------------------


class CanvasPlugin:
    """Basisklasse für Plugins, die eine Fläche füllen statt eine Taste.

    Zwei Sorten nutzen sie: ``screensaver`` malt über das ganze Deck,
    ``wallpaper`` hinter den Touchstrip. Beide bekommen nur eine Leinwand
    und deren Größe — wie das Ergebnis anschließend auf Tasten und Segmente
    verteilt wird, ist Sache der App, nicht des Plugins.

    Für ein festes Bild genügt es, :meth:`render` einmal zu beantworten und
    ``interval_s`` bei 0 zu lassen. Wer eine Uhr oder einen Visualizer baut,
    setzt ``interval_s`` auf den gewünschten Abstand und bekommt die
    verstrichene Zeit übergeben.
    """

    #: Abstand zwischen zwei Bildern in Sekunden. 0 heißt: einmal zeichnen
    #: und stehen lassen — das spart Strom und USB-Bandbreite.
    interval_s: float = 0.0

    #: Wo die Kacheln auf der Leinwand liegen — von der App gesetzt, bevor
    #: :meth:`render` gerufen wird. Die meisten Plugins malen einfach über
    #: die ganze Fläche und brauchen das nicht. Wer aber etwas *pro Taste*
    #: zeigen will (eine Ziffer je Taste zum Beispiel), muss wissen, wo die
    #: Schnitte verlaufen, sonst landet der Inhalt in den Fugen.
    #: Bei ``wallpaper``-Plugins bleibt es ``None`` — dort gibt es nur den
    #: durchgehenden Streifen.
    deck_layout: Any = None

    def __init__(self, manifest: Manifest, services: Services) -> None:
        self.manifest = manifest
        self.services = services
        self.log = logging.getLogger(f"screensaver.{manifest.id}")

    async def setup(self) -> None:
        """Einmalig beim Laden."""

    async def teardown(self) -> None:
        """Beim Beenden oder Deaktivieren."""

    def on_plugin_config_changed(self, config: dict[str, Any]) -> None:
        """Globale Plugin-Einstellungen wurden in der GUI geändert."""

    def render(self, size: tuple[int, int], elapsed_s: float) -> Image.Image | None:
        """Das Bild für die Leinwand ``size``.

        ``elapsed_s`` zählt, wie lange der Schoner schon läuft. ``None``
        heißt „diesmal nichts Neues“ — das vorige Bild bleibt stehen.
        """
        return None

    @property
    def plugin_config(self) -> dict[str, Any]:
        return self.services.config.plugin_settings.setdefault(self.manifest.id, {})


#: Sprechender Name für Schoner-Plugins. Technisch dieselbe Klasse — ein
#: Schoner und ein Hintergrundbild unterscheiden sich nur in der Größe der
#: Leinwand, die sie bekommen.
ScreensaverPlugin = CanvasPlugin
WallpaperPlugin = CanvasPlugin


class ActionPlugin:
    """Basisklasse aller Action-Plugins.

    Alle Methoden sind optional überschreibbar. Die Standard-Implementierung
    von :meth:`render` malt Hintergrund + Icon + Label über den gemeinsamen
    RenderService — ein Plugin muss also nur dann zeichnen, wenn es etwas
    Eigenes braucht (etwa den Lautstärke-Balken auf dem Touchstrip).
    """

    def __init__(self, manifest: Manifest, services: Services) -> None:
        self.manifest = manifest
        self.services = services
        self.log = logging.getLogger(f"plugin.{manifest.id}")

    # -- Lebenszyklus ------------------------------------------------------

    async def setup(self) -> None:
        """Einmalig beim Laden. Verbindungen aufbauen, Watcher starten."""

    async def teardown(self) -> None:
        """Beim Beenden oder Deaktivieren. Verbindungen sauber schließen."""

    def on_plugin_config_changed(self, config: dict[str, Any]) -> None:
        """Globale Plugin-Einstellungen wurden in der GUI geändert."""

    def get_status(self) -> dict[str, Any] | None:
        """Verbindungszustand für die Plugin-Liste in der GUI.

        Nur für Plugins sinnvoll, die von etwas Externem abhängen (OBS,
        Discord). Wer keine Verbindung braucht, gibt ``None`` zurück — dann
        zeigt die GUI auch keine Statusanzeige an.

        Erwartet ``{"connected": bool, "detail": str}``. Muss ohne Warten
        antworten, also aus gespiegeltem Zustand.
        """
        return None

    # -- Eingaben ----------------------------------------------------------

    def on_key_down(self, action_id: str, settings: dict[str, Any], ctx: SlotContext) -> None: ...

    def on_key_up(self, action_id: str, settings: dict[str, Any], ctx: SlotContext) -> None: ...

    def on_dial_rotate(
        self, action_id: str, settings: dict[str, Any], delta: int, ctx: SlotContext
    ) -> None: ...

    def on_dial_push(self, action_id: str, settings: dict[str, Any], ctx: SlotContext) -> None: ...

    def on_touch(
        self,
        action_id: str,
        settings: dict[str, Any],
        x: int,
        y: int,
        ctx: SlotContext,
    ) -> None:
        """Touch auf dem Segment. ``x``/``y`` sind bereits segment-relativ."""

    def on_tick(self, action_id: str, settings: dict[str, Any], ctx: SlotContext) -> None:
        """Periodisch (Default 1×/Sek.) für Status, der sich von außen ändert.

        Für Zustandsänderungen, über die es ein echtes Event gibt, ist
        ``services.runtime.request_redraw`` der bessere Weg — der Tick ist
        nur das Sicherheitsnetz.
        """

    # -- Darstellung -------------------------------------------------------

    def get_state(
        self, action_id: str, settings: dict[str, Any], ctx: SlotContext
    ) -> str | None:
        """Aktueller visueller Zustand, z. B. ``"muted"``.

        Der Rückgabewert wählt das Icon aus ``appearance.icon_by_state``.
        ``None`` bzw. ein unbekannter Zustand fällt auf ``"default"`` zurück.
        """
        return None

    def get_label(
        self, action_id: str, settings: dict[str, Any], ctx: SlotContext
    ) -> str | None:
        """Dynamischer Label-Text, der den konfigurierten überschreibt.

        Damit kann z. B. die Seitenanzeige die Seitennummer zeigen, ohne dass
        der User sie einträgt. ``None`` = konfiguriertes Label verwenden.
        """
        return None

    def render(
        self, action_id: str, settings: dict[str, Any], ctx: SlotContext
    ) -> Image.Image:
        """Zeichnet die Tasten-/Segment-Anzeige.

        Standard: gemeinsames Elgato-artiges Layout (Hintergrund, Icon
        zentriert im oberen Bereich, Label darunter).
        """
        state = self.get_state(action_id, settings, ctx)
        label = self.get_label(action_id, settings, ctx)
        return self.services.render.render_slot(ctx, state=state, label_override=label)

    # -- GUI-Unterstützung -------------------------------------------------

    def get_dynamic_options(
        self, source: str, context: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """Löst ``SettingsField.options_source`` zur Laufzeit auf.

        ``context`` enthält die bereits gesetzten Einstellungen derselben
        Belegung — nötig für Listen, die von einer anderen Auswahl abhängen
        (die Filter einer Quelle, die Quellen einer Szene).

        Erwartet eine Liste aus ``{"value": …, "label": …}``.
        """
        return []

    async def gui_command(self, command: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Aktion, die die GUI direkt am Plugin auslöst.

        Für Dinge, die in kein Settings-Feld passen — etwa Discords
        „Jetzt verbinden“, das einen Zustimmungs-Dialog öffnet.
        """
        raise NotImplementedError(f"Plugin kennt kein Kommando '{command}'")

    # -- Bequemlichkeit ----------------------------------------------------

    @property
    def plugin_config(self) -> dict[str, Any]:
        """Globale Einstellungen dieses Plugins aus der Config."""
        return self.services.config.plugin_settings.setdefault(self.manifest.id, {})

    def run_async(self, coro) -> None:
        """Startet eine Coroutine im Hintergrund — aus jedem Thread heraus.

        Synchrone Hooks (``render``, ``on_tick``, ``get_dynamic_options``)
        laufen in einem Worker-Thread, wo es keinen Event-Loop gibt.
        ``asyncio.create_task`` scheitert dort mit „no running event loop“ —
        dieser Helfer nicht.
        """
        import asyncio

        loop = getattr(self.services.runtime, "_loop", None)
        if loop is None or loop.is_closed():
            coro.close()
            return
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None

        if running is loop:
            loop.create_task(coro)
        else:
            asyncio.run_coroutine_threadsafe(coro, loop)

    def notify_error(self, message: str) -> None:
        """Echter Fehler — erscheint in der Fehlerleiste der GUI."""
        self.log.error(message)
        self.services.runtime.notify("error", message, plugin_id=self.manifest.id)

    def notify_info(self, message: str) -> None:
        """Hinweis, der nur ins Log geht.

        Für erwartbare Zustände: ein Dienst läuft gerade nicht, eine Aktion
        hat keine Voraussetzung. Das sieht man der Taste ohnehin an — eine
        rote Leiste in der GUI wäre dafür zu laut, zumal sie bei jedem
        Tastendruck erneut käme.
        """
        self.log.info(message)
        self.services.runtime.notify("info", message, plugin_id=self.manifest.id)
