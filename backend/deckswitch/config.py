"""Datenmodell der Belegungen und dessen Persistenz.

Hierarchie: ``Config → Profile → Page → Slot``.

Die Seiten-Ebene ist keine spätere Zutat, sondern von Anfang an da: das
Streamdeck-Plugin (Ordner/Home/Zurück/Gehe-zu-Seite) navigiert genau darauf.
Ein "Ordner" ist keine eigene Entität — es ist eine Page mit ``parent``-Verweis,
auf die eine Taste per Action zeigt.

Profile sind strukturell vollständig vorhanden (mehrere unabhängige
Belegungs-Sets), auch wenn die GUI-Umschaltung nicht v1-kritisch ist.
"""

from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

from . import paths

CONFIG_VERSION = 1

# Stream Deck+ Geometrie. Bewusst hier gespiegelt, damit das Datenmodell auch
# ohne angeschlossenes Gerät validierbar ist.
KEY_COUNT = 8
DIAL_COUNT = 4


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


# --------------------------------------------------------------------------
# Aussehen einer Belegung (generisch, nicht pluginspezifisch)
# --------------------------------------------------------------------------


class IconRef(BaseModel):
    """Verweis auf ein Icon. Die Auflösungs-Priorität steckt im IconService."""

    kind: Literal["iconset", "upload", "none"] = "none"
    #: Plugin-ID des Iconsets (bei kind="iconset"), z. B. "iconset-tabler".
    set_id: str | None = None
    #: Icon-Name innerhalb des Iconsets, z. B. "volume".
    name: str | None = None
    #: Dateiname unterhalb von UPLOADS_DIR (bei kind="upload").
    upload: str | None = None
    #: Einfärbung des Icons als #rrggbb; None = Originalfarben des SVG.
    color: str | None = "#ffffff"


class Background(BaseModel):
    """Hintergrund einer Taste oder eines Touchstrip-Segments.

    Wird *vor* dem Content der Action gezeichnet — die Action malt darüber.
    """

    #: ``transparent`` lässt das Hintergrundbild der Seite durchscheinen —
    #: nur bei Touchstrip-Segmenten sinnvoll, auf einer Taste bleibt es
    #: schlicht schwarz.
    kind: Literal["solid", "gradient", "noise", "accent", "image", "transparent"] = "solid"
    color: str = "#000000"
    #: Zweite Farbe bei kind="gradient".
    color2: str = "#1a1a1a"
    #: Richtung bei kind="gradient".
    direction: Literal["vertical", "horizontal"] = "vertical"
    #: Stärke bei kind="noise" (0..100).
    intensity: int = 12
    #: Bei kind="accent": None = Akzentfarbe der Action verwenden.
    accent: str | None = None
    #: Dateiname unterhalb von UPLOADS_DIR (bei kind="image").
    upload: str | None = None


class Appearance(BaseModel):
    """Generisches Erscheinungsbild einer Belegung.

    Bewusst *nicht* pluginspezifisch: jedes Action-Plugin liefert nur seinen
    State ("muted", "active", …), das Zeichnen von Hintergrund + Icon + Label
    macht der gemeinsame RenderService. Plugins können das überschreiben,
    müssen aber nicht.
    """

    #: State-Name → Icon. Der Key "default" greift, wenn ein State kein
    #: eigenes Icon hat. Beispiel: {"default": …, "muted": …}
    icon_by_state: dict[str, IconRef] = Field(default_factory=dict)
    #: Icon-Kantenlänge in Prozent der kurzen Kachelseite.
    icon_size: int = 55
    label_text: str = ""
    label_size: int = 16
    label_color: str = "#ffffff"
    label_position: Literal["bottom", "top", "center"] = "bottom"
    show_label: bool = True
    background: Background = Field(default_factory=Background)

    def icon_for_state(self, state: str | None) -> IconRef | None:
        if state and state in self.icon_by_state:
            return self.icon_by_state[state]
        return self.icon_by_state.get("default")


# --------------------------------------------------------------------------
# Belegung
# --------------------------------------------------------------------------


class Slot(BaseModel):
    """Eine belegte Taste bzw. ein belegter Dial."""

    plugin_id: str
    action_id: str
    #: Pluginspezifische Einstellungen dieser einen Belegung.
    settings: dict[str, Any] = Field(default_factory=dict)
    appearance: Appearance = Field(default_factory=Appearance)
    #: Optionale zweite Action bei langem Druck (>``long_press_ms``).
    #: Nur eine Ebene tief gedacht — ein Long-Press-Slot hat selbst keinen.
    long_press: "Slot | None" = None


class TouchWallpaper(BaseModel):
    """Hintergrundbild des Touchstrips — je Seite eines.

    Es ersetzt den Grund der vier Dial-Segmente: Wo eine Belegung keinen
    eigenen Hintergrund gewählt hat, steht das Bild; wer für ein Segment
    bewusst eine Farbe oder einen Verlauf einstellt, bekommt weiterhin
    diese. Anders herum wäre es nie zu sehen — die Segmente zeichnen
    standardmäßig deckendes Schwarz.

    Maße: Der Streifen hat 800 × 100 Pixel. Elgatos SDK nennt 200 × 100 pro
    Dial-Segment, was dasselbe in vier Teilen ist.
    """

    enabled: bool = False
    #: ``upload:<dateiname>`` oder ``plugin:<id>``.
    source: str = ""
    #: ``cover`` füllt den Streifen, ``contain`` zeigt das ganze Bild.
    fit: Literal["cover", "contain"] = "cover"
    #: Deckkraft in Prozent. Unter 100 tritt das Bild hinter die Belegungen
    #: zurück, statt mit ihnen um Aufmerksamkeit zu ringen.
    opacity: int = 100


class Page(BaseModel):
    """Eine Seite bzw. ein Ordner innerhalb eines Profils."""

    id: str = Field(default_factory=_new_id)
    name: str = "Seite"
    #: None = Wurzelseite. Sonst die Page, zu der "Zurück" springt.
    parent_id: str | None = None
    #: Position unter den Geschwistern — kleiner Wert zuerst. Bestimmt die
    #: Reihenfolge in der GUI *und* die Blätter-Richtung von Wischen und
    #: "Nächste Seite". Bei Gleichstand (z. B. Configs aus der Zeit vor
    #: diesem Feld) entscheidet die Reihenfolge im ``pages``-Dict.
    order: int = 0
    #: Index (0..7) → Belegung. Leere Plätze fehlen schlicht.
    keys: dict[int, Slot] = Field(default_factory=dict)
    #: Index (0..3) → Belegung des Dials inkl. seines Touchstrip-Segments.
    dials: dict[int, Slot] = Field(default_factory=dict)
    #: Hintergrundbild des Touchstrips — je Seite ein eigenes.
    touch_wallpaper: TouchWallpaper = Field(default_factory=TouchWallpaper)


class Profile(BaseModel):
    """Ein unabhängiges Belegungs-Set (z. B. „Streaming“ vs. „Arbeit“)."""

    id: str = Field(default_factory=_new_id)
    name: str = "Standard"
    root_page_id: str = ""
    pages: dict[str, Page] = Field(default_factory=dict)

    def root_page(self) -> Page:
        page = self.pages.get(self.root_page_id)
        if page is None:
            # Selbstheilung: erste Wurzelseite nehmen, sonst eine anlegen.
            for candidate in self.pages.values():
                if candidate.parent_id is None:
                    self.root_page_id = candidate.id
                    return candidate
            page = Page(name="Start")
            self.pages[page.id] = page
            self.root_page_id = page.id
        return page

    def children(self, parent_id: str | None) -> list[Page]:
        """Unterseiten von ``parent_id`` in ihrer Sortierreihenfolge.

        ``sorted`` ist stabil: Seiten mit gleichem ``order`` behalten die
        Reihenfolge aus dem Dict. Damit sieht eine Config ohne gepflegte
        ``order``-Werte genauso aus wie vorher.
        """
        return sorted(
            (p for p in self.pages.values() if p.parent_id == parent_id),
            key=lambda p: p.order,
        )

    def subtree_ids(self, page_id: str) -> set[str]:
        """``page_id`` und alles darunter — für Löschen und Zyklusprüfung."""
        result = {page_id}
        pending = [page_id]
        while pending:
            current = pending.pop()
            for pid, page in self.pages.items():
                if page.parent_id == current and pid not in result:
                    result.add(pid)
                    pending.append(pid)
        return result

    def reindex(self, parent_id: str | None) -> None:
        """Vergibt 0..n-1 an die Geschwister — hält die Werte lückenlos."""
        for position, page in enumerate(self.children(parent_id)):
            page.order = position

    def move_page(self, page_id: str, parent_id: str | None, index: int) -> None:
        """Hängt eine Seite an ``parent_id`` und setzt sie auf Position ``index``.

        Der Aufrufer muss sichergestellt haben, dass ``parent_id`` weder die
        Seite selbst noch eine ihrer Unterseiten ist — sonst hinge der
        Teilbaum an sich selbst und wäre von der Wurzel aus unerreichbar.
        """
        page = self.pages[page_id]
        old_parent = page.parent_id
        page.parent_id = parent_id

        siblings = [p for p in self.children(parent_id) if p.id != page_id]
        index = max(0, min(index, len(siblings)))
        siblings.insert(index, page)
        for position, sibling in enumerate(siblings):
            sibling.order = position

        if old_parent != parent_id:
            self.reindex(old_parent)

    def path_to_root(self, page_id: str) -> list[str]:
        """Kette von der Wurzel bis ``page_id`` (für Breadcrumbs/Zurück)."""
        chain: list[str] = []
        seen: set[str] = set()
        current = page_id
        while current and current not in seen:
            seen.add(current)
            chain.append(current)
            page = self.pages.get(current)
            if page is None or page.parent_id is None:
                break
            current = page.parent_id
        chain.reverse()
        return chain


# --------------------------------------------------------------------------
# Geräte- und Anwendungseinstellungen
# --------------------------------------------------------------------------


class Screensaver(BaseModel):
    """Bildschirmschoner über das ganze Deck."""

    enabled: bool = False
    #: Woher das Bild kommt: ``upload:<dateiname>`` oder ``plugin:<id>``.
    #: Leer heißt „nichts gewählt“ — dann bleibt der Schoner aus, auch wenn
    #: ``enabled`` gesetzt ist.
    source: str = ""
    #: Nach so vielen Sekunden ohne Eingabe. Bewusst getrennt vom Abdunkeln:
    #: Erst dimmen, dann den Schoner zeigen ist die übliche Reihenfolge, und
    #: mancher will nur eines von beidem.
    after_s: int = 600
    #: Helligkeit während der Schoner läuft.
    brightness: int = 40
    #: ``cover`` füllt das Deck und schneidet ab, ``contain`` zeigt alles.
    fit: Literal["cover", "contain"] = "cover"


class DeviceSettings(BaseModel):
    brightness: int = 70
    #: Idle-Dimming: nach so vielen Sekunden ohne Eingabe abdunkeln. 0 = aus.
    idle_dim_after_s: int = 300
    idle_brightness: int = 15
    #: Schwelle, ab der ein Druck als "lang" gilt.
    long_press_ms: int = 500
    #: Intervall des periodischen ``on_tick``-Aufrufs.
    tick_interval_s: float = 1.0
    #: Wischen über den Touchstrip blättert zur nächsten/vorherigen Seite.
    swipe_switches_page: bool = True
    #: Mindeststrecke in Pixeln, ab der eine Bewegung als Wischen zählt —
    #: aufaddiert über die Teilstrecken einer Geste. Am Gerät gemessen liegen
    #: einzelne Teilstrecken bei 40–120 px, ein zügiger Wisch summiert sich
    #: also schnell darüber; kurzes Verrutschen beim Tippen bleibt darunter.
    swipe_min_distance: int = 50
    #: Am Ende der Seitenreihe wieder von vorn beginnen.
    swipe_wraps: bool = True
    #: Bildschirmschoner nach längerer Ruhe.
    screensaver: Screensaver = Field(default_factory=Screensaver)


class AppSettings(BaseModel):
    language: Literal["de", "en"] = "de"
    #: Iconset-Plugin, aus dem Icons ohne expliziten Set-Verweis kommen.
    active_iconset: str = "iconset-tabler"
    host: str = "127.0.0.1"
    port: int = 8770
    #: Vom User festgelegte Reihenfolge der Plugins (IDs). Was hier fehlt —
    #: etwa ein frisch installiertes Plugin — wird hinten angehängt.
    plugin_order: list[str] = Field(default_factory=list)


class Config(BaseModel):
    version: int = CONFIG_VERSION
    app: AppSettings = Field(default_factory=AppSettings)
    device: DeviceSettings = Field(default_factory=DeviceSettings)
    active_profile_id: str = ""
    profiles: dict[str, Profile] = Field(default_factory=dict)
    #: Globale Einstellungen pro Plugin (OBS-Host, Discord-App-ID, …) —
    #: getrennt von den Settings einer einzelnen Belegung.
    plugin_settings: dict[str, dict[str, Any]] = Field(default_factory=dict)
    #: Deaktivierte Plugins (ID-Liste), damit man sie in der GUI abschalten kann.
    disabled_plugins: list[str] = Field(default_factory=list)

    # -- Zugriffshelfer ----------------------------------------------------

    def active_profile(self) -> Profile:
        profile = self.profiles.get(self.active_profile_id)
        if profile is None:
            if not self.profiles:
                profile = _make_default_profile()
                self.profiles[profile.id] = profile
            else:
                profile = next(iter(self.profiles.values()))
            self.active_profile_id = profile.id
        return profile

    def page(self, page_id: str | None = None) -> Page:
        profile = self.active_profile()
        if page_id and page_id in profile.pages:
            return profile.pages[page_id]
        return profile.root_page()


Slot.model_rebuild()


def _make_default_profile() -> Profile:
    root = Page(name="Start")
    return Profile(name="Standard", root_page_id=root.id, pages={root.id: root})


def default_config() -> Config:
    profile = _make_default_profile()
    return Config(active_profile_id=profile.id, profiles={profile.id: profile})


# --------------------------------------------------------------------------
# Persistenz
# --------------------------------------------------------------------------


class ConfigStore:
    """Lädt/speichert die Config als JSON unter ``~/.config/deckswitch/``.

    Schreibt atomar (temp + replace) und legt bei kaputtem JSON eine
    ``.broken``-Kopie an, statt die Belegung des Users stillschweigend zu
    verlieren.
    """

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or paths.CONFIG_FILE
        self.config: Config = default_config()

    def load(self) -> Config:
        if not self.path.exists():
            self.config = default_config()
            self.save()
            return self.config

        raw = self.path.read_text(encoding="utf-8")
        try:
            data = json.loads(raw)
            self.config = Config.model_validate(data)
        except (json.JSONDecodeError, ValidationError) as exc:
            backup = self.path.with_suffix(".broken.json")
            shutil.copy2(self.path, backup)
            self.config = default_config()
            self.save()
            raise ConfigLoadError(
                f"Config unlesbar ({exc}). Kopie liegt unter {backup}, "
                f"es wurde eine frische Standard-Config angelegt."
            ) from exc

        self.config.active_profile()  # Selbstheilung erzwingen
        return self.config

    def save(self, config: Config | None = None) -> None:
        if config is not None:
            self.config = config
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        payload = self.config.model_dump(mode="json", exclude_none=False)
        tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.path)

    # -- Export/Import -----------------------------------------------------

    def export_json(self) -> str:
        return json.dumps(
            self.config.model_dump(mode="json"), indent=2, ensure_ascii=False
        )

    def import_json(self, raw: str, *, merge_profiles: bool = False) -> Config:
        """Importiert eine exportierte Config.

        ``merge_profiles=True`` übernimmt nur die Profile und lässt Geräte-/
        App-Einstellungen unangetastet — praktisch beim Umzug auf ein
        zweites System.
        """
        data = json.loads(raw)
        incoming = Config.model_validate(data)
        if merge_profiles:
            self.config.profiles.update(incoming.profiles)
            if incoming.active_profile_id in self.config.profiles:
                self.config.active_profile_id = incoming.active_profile_id
        else:
            self.config = incoming
        self.save()
        return self.config


class ConfigLoadError(RuntimeError):
    """Config war vorhanden, aber nicht lesbar — Detail steckt in der Message."""
