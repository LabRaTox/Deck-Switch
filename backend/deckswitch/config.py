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
import logging
import shutil
import time
import uuid
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

from . import paths

log = logging.getLogger(__name__)

#: So viele frühere Stände bleiben liegen (ein Eintrag je Stunde).
BACKUP_KEEP = 30

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
    #: Einpassung bei kind="image": ``cover`` füllt und beschneidet,
    #: ``contain`` zeigt das ganze Bild, ``stretch`` verzerrt.
    fit: Literal["cover", "contain", "stretch"] = "cover"
    #: Deckkraft des Bildes in Prozent — darunter tritt es hinter Icon und
    #: Beschriftung zurück, statt mit ihnen um Aufmerksamkeit zu ringen.
    opacity: int = 100


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
    #: Schriftfamilie wie sie fontconfig kennt („Noto Sans“). Leer = Standard.
    #: Bewusst der Familienname und kein Pfad: Der Pfad hinge an der
    #: installierten Version, der Name überlebt ein Schriftpaket-Update.
    label_font: str = ""
    label_bold: bool = False
    label_italic: bool = False
    label_underline: bool = False
    label_align: Literal["center", "left", "right"] = "center"
    background: Background = Field(default_factory=Background)

    def icon_for_state(self, state: str | None) -> IconRef | None:
        if state and state in self.icon_by_state:
            return self.icon_by_state[state]
        return self.icon_by_state.get("default")


# --------------------------------------------------------------------------
# Belegung
# --------------------------------------------------------------------------


class Step(BaseModel):
    """Ein Schritt einer Aktionskette (Multi-Aktion).

    Zwei Sorten: ``action`` löst eine ganz normale Plugin-Action aus,
    ``delay`` wartet. Die Pause ist bewusst ein eigener Schritt und keine
    Eigenschaft der Aktion — so lässt sie sich verschieben, mehrfach
    einsetzen und einzeln abschalten, genau wie bei Elgato.
    """

    id: str = Field(default_factory=_new_id)
    kind: Literal["action", "delay"] = "action"
    plugin_id: str = ""
    action_id: str = ""
    settings: dict[str, Any] = Field(default_factory=dict)
    #: Wartezeit bei ``kind="delay"``.
    delay_ms: int = 200
    #: Abgeschaltete Schritte bleiben in der Kette stehen, laufen aber nicht
    #: mit — praktisch beim Suchen, welcher Schritt hakt.
    enabled: bool = True


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
    #: Optionale dritte Action bei Doppeldruck (zweiter Druck binnen
    #: ``double_press_ms``). Zusammen mit ``long_press`` ergibt das die drei
    #: Wege, die Elgato „Key Logic“ nennt: drücken, doppelt drücken, halten.
    double_press: "Slot | None" = None

    # -- Drehrichtungen (nur Dials) ----------------------------------------
    # Ohne diese beiden bekommt die Grundaktion das Drehen als Delta und
    # regelt stufenlos — Lautstärke, Helligkeit, Position. Wer hier etwas
    # hinterlegt, tauscht das Regeln gegen ein Auslösen: Jede Drehung wirkt
    # dann wie ein kurzer Druck auf diese Action.
    #
    # Die Richtungen sind unabhängig voneinander. Ist nur eine belegt, geht
    # die andere weiterhin an die Grundaktion — so lässt sich „links leiser,
    # rechts nächster Titel“ bauen, auch wenn das selten gemeint ist.

    #: Action beim Drehen gegen den Uhrzeigersinn.
    turn_left: "Slot | None" = None
    #: Action beim Drehen im Uhrzeigersinn.
    turn_right: "Slot | None" = None
    #: Nach wie vielen Rasten ausgelöst wird. Ein zügiger Dreh erzeugt
    #: schnell ein Dutzend Rasten — „nächster Titel“ darf nicht ein Dutzend
    #: Mal feuern. Gezählt statt nach Zeit gedrosselt: So führt dieselbe
    #: Handbewegung immer zum selben Ergebnis, egal wie schnell sie war.
    turn_every: int = 2

    # -- Multi-Aktion ------------------------------------------------------
    # Nur belegt, wenn die Belegung auf dem Plugin ``multi`` liegt. Die
    # Schritte stehen hier und nicht in ``settings``, weil sie *Verweise auf
    # Actions* sind: So sind sie typisiert, und beim Entfernen eines Plugins
    # findet die App auch die Schritte, die darauf zeigen.

    #: Schritte der Kette. Beim Umschalter (``action_id="switch"``) ist das
    #: die Kette für den Weg „aus → an“.
    steps: list[Step] = Field(default_factory=list)
    #: Zweite Kette des Umschalters („an → aus“).
    steps_off: list[Step] = Field(default_factory=list)
    #: Kette wiederholen, bis erneut gedrückt wird.
    repeat: bool = False
    #: Zustand des Umschalters — gehört in die Config, damit eine Taste nach
    #: einem Neustart nicht plötzlich verkehrt herum steht.
    toggled: bool = False

    # -- Dial-Stack --------------------------------------------------------

    #: Weitere Belegungen desselben Dials. Der Slot selbst ist Eintrag 1,
    #: hier stehen die Einträge 2..n. Umgeschaltet wird mit langem Druck auf
    #: den Dial; welcher Eintrag gerade oben liegt, führt die Runtime.
    stack: list["Slot"] = Field(default_factory=list)


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
    #: Fenster, in dem ein zweiter Druck als Doppeldruck zählt. Nur Tasten
    #: mit hinterlegtem Doppeldruck warten so lange — alle anderen lösen
    #: weiterhin sofort aus.
    double_press_ms: int = 280
    #: Animierte Tastenbilder (GIF, animiertes WebP/PNG) abspielen. Kostet
    #: USB-Bandbreite: jedes Bild geht einzeln zum Gerät.
    animations: bool = True
    #: Obergrenze der Bildrate für animierte Kacheln. Mehr als das schafft
    #: der USB-Weg zum Deck ohnehin nicht sinnvoll.
    animation_fps: int = 10
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


class DeckBinding(BaseModel):
    """Ein Gerät und was daran hängt.

    Mehrere Decks sind untereinander unabhängig: Jedes zeigt sein eigenes
    Profil, hat eigene Helligkeit, eigenen Bildschirmschoner und eigene
    Zeiten. Verknüpft wird über die **Seriennummer** — die bleibt gleich,
    auch wenn das Gerät an einem anderen USB-Anschluss steckt oder in einer
    anderen Reihenfolge erkannt wird.

    Ein leeres ``serial`` ist der Platzhalter für „das Gerät, das als
    erstes kommt". So funktioniert eine Config aus der Zeit vor mehreren
    Decks unverändert weiter: Sie hat genau eine Bindung ohne Seriennummer,
    und das erste angeschlossene Deck übernimmt sie samt Belegung.
    """

    serial: str = ""
    #: Anzeigename. Leer = Modellbezeichnung des Geräts.
    name: str = ""
    deck_type: str = ""
    profile_id: str = ""
    device: DeviceSettings = Field(default_factory=DeviceSettings)
    #: Reihenfolge in der GUI.
    order: int = 0

    #: ``hardware`` hängt am USB, ``virtual`` ist ein Overlay auf dem
    #: Bildschirm. Für alles darüber — Seiten, Tastenlogik, Multi-Aktionen —
    #: ist der Unterschied belanglos: Die Deck-Sitzung weiß nicht, woher ihre
    #: Eingaben kommen und wohin ihre Bilder gehen.
    kind: Literal["hardware", "virtual"] = "hardware"
    #: Nur bei ``virtual``: Größe des Rasters. Frei wählbar — ein Overlay hat
    #: keine feste Tastenzahl.
    columns: int = 4
    rows: int = 2
    #: Zahl der Dials unter den Tasten. 0 = keine.
    dials: int = 0
    #: Kantenlänge einer Kachel in Pixeln, in der gerendert wird.
    key_size: int = 120
    #: Overlay ohne eigenen Grund — es schweben dann nur die Kacheln über
    #: dem Bildschirm, ohne Platte darunter.
    overlay_transparent: bool = False
    #: Unbelegte Kacheln gar nicht erst zeigen. Auf einem Gerät muss jede
    #: Taste sichtbar bleiben, ein Overlay darf dagegen genau so groß sein
    #: wie das, was darauf liegt.
    hide_empty: bool = False
    #: Wo das Overlay zuletzt abgelegt wurde. ``-1`` heißt „noch nie
    #: verschoben" — dann sucht sich der Overlay-Dienst eine Stelle. Die
    #: Position gehört zum Deck und nicht zur auslösenden Taste: Wer das
    #: Overlay einmal dorthin gezogen hat, wo es ihm passt, will es dort
    #: wiederfinden, egal von welcher Taste aus er es ruft.
    overlay_x: int = -1
    overlay_y: int = -1

    @property
    def is_virtual(self) -> bool:
        return self.kind == "virtual"


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
    #: Vorlage für neu hinzukommende Geräte — und die Einstellungen des
    #: einen Decks in Configs, die noch keine ``decks`` kennen.
    device: DeviceSettings = Field(default_factory=DeviceSettings)
    #: Seriennummer → Bindung. Wird beim ersten Start aus ``device`` und dem
    #: aktiven Profil erzeugt.
    decks: dict[str, DeckBinding] = Field(default_factory=dict)
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

    def page(self, page_id: str | None = None, profile_id: str | None = None) -> Page:
        profile = self.profile(profile_id) if profile_id else self.active_profile()
        if page_id and page_id in profile.pages:
            return profile.pages[page_id]
        return profile.root_page()

    def profile(self, profile_id: str | None) -> Profile:
        """Ein bestimmtes Profil — mit Rückfall auf das aktive.

        Der Rückfall ist kein Kaschieren: Ein Deck kann auf ein Profil
        zeigen, das jemand gelöscht hat. Dann ist ein sichtbares Ersatzprofil
        deutlich besser als ein schwarzes Gerät.
        """
        if profile_id and profile_id in self.profiles:
            return self.profiles[profile_id]
        return self.active_profile()

    # -- Deck-Bindungen ----------------------------------------------------

    def decks_in_order(self) -> list[DeckBinding]:
        return sorted(self.decks.values(), key=lambda b: (b.order, b.name, b.serial))

    def ensure_decks(self) -> None:
        """Legt beim ersten Start die Bindung für das eine Deck an.

        Configs aus der Zeit vor mehreren Geräten haben genau ein Profil und
        keine Bindung. Die bekommen hier einen Platzhalter ohne
        Seriennummer — das erste angeschlossene Deck übernimmt ihn.
        """
        if self.decks:
            return
        profile = self.active_profile()
        self.decks[""] = DeckBinding(
            serial="", profile_id=profile.id, device=self.device.model_copy(deep=True)
        )

    def new_profile_for_deck(self, name: str) -> Profile:
        """Ein frisches, leeres Profil für ein neu hinzugekommenes Gerät."""
        profile = _make_default_profile()
        profile.name = name or "Deck"
        self.profiles[profile.id] = profile
        return profile


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
        self._rotate_backup()
        tmp = self.path.with_suffix(".tmp")
        payload = self.config.model_dump(mode="json", exclude_none=False)
        tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.path)

    def _rotate_backup(self) -> None:
        """Legt den bisherigen Stand beiseite, bevor er überschrieben wird.

        Eine Belegung ist Handarbeit von Stunden und steht in genau einer
        Datei. Wer sie überschreibt — ein Fehlgriff, ein Import, ein Testlauf
        ohne eigenes ``XDG_CONFIG_HOME`` — hat sie sonst ersatzlos verloren.
        Deshalb wandert vor jedem Schreiben eine Kopie in den Verlauf.

        Höchstens einmal je Stunde, damit häufiges Speichern (jeder Regler am
        Deck ruft ``save``) den Verlauf nicht in Minuten leerdrückt.
        """
        if not self.path.is_file():
            return
        ordner = paths.BACKUP_DIR
        ordner.mkdir(parents=True, exist_ok=True)

        stempel = time.strftime("%Y%m%d-%H", time.localtime())
        ziel = ordner / f"config-{stempel}.json"
        if ziel.exists():
            return  # für diese Stunde ist der Ausgangsstand schon gesichert

        try:
            shutil.copy2(self.path, ziel)
        except OSError:
            log.warning("Sicherung der Config nicht möglich", exc_info=True)
            return

        # Verlauf begrenzen: die jüngsten behalten, ältere gehen.
        alle = sorted(ordner.glob("config-*.json"))
        for veraltet in alle[:-BACKUP_KEEP]:
            veraltet.unlink(missing_ok=True)

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
