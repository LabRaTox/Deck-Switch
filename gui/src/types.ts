/** Datenmodell des Backends, 1:1 gespiegelt (siehe backend/streamdeck_app/config.py). */

export type InputType = "key" | "dial";

/** Ein Text im Manifest ist entweder ein String oder ein Locale-Mapping. */
export type LocalizedText = string | Record<string, string>;

export interface IconRef {
  kind: "iconset" | "upload" | "none";
  set_id?: string | null;
  name?: string | null;
  upload?: string | null;
  color?: string | null;
}

export interface Background {
  kind: "solid" | "gradient" | "noise" | "accent" | "image" | "transparent";
  color: string;
  color2: string;
  direction: "vertical" | "horizontal";
  intensity: number;
  accent?: string | null;
  upload?: string | null;
  /** Einpassung eines Hintergrundbildes. */
  fit: "cover" | "contain" | "stretch";
  /** Deckkraft des Bildes in Prozent. */
  opacity: number;
}

export interface Appearance {
  icon_by_state: Record<string, IconRef>;
  icon_size: number;
  label_text: string;
  label_size: number;
  label_color: string;
  label_position: "bottom" | "top" | "center";
  show_label: boolean;
  /** Schriftfamilie wie fontconfig sie kennt; leer = Standard. */
  label_font: string;
  label_bold: boolean;
  label_italic: boolean;
  label_underline: boolean;
  label_align: "center" | "left" | "right";
  background: Background;
}

/** Ein Schritt einer Multi-Aktion: eine Aktion oder eine Pause. */
export interface Step {
  id: string;
  kind: "action" | "delay";
  plugin_id: string;
  action_id: string;
  settings: Record<string, unknown>;
  delay_ms: number;
  enabled: boolean;
}

export interface Slot {
  plugin_id: string;
  action_id: string;
  settings: Record<string, unknown>;
  appearance: Appearance;
  /** Zweite Aktion beim Halten. */
  long_press?: Slot | null;
  /** Dritte Aktion beim Doppeldruck. */
  double_press?: Slot | null;
  /** Nur Dials: Aktion beim Drehen gegen den Uhrzeigersinn. */
  turn_left?: Slot | null;
  /** Nur Dials: Aktion beim Drehen im Uhrzeigersinn. */
  turn_right?: Slot | null;
  /** Nach wie vielen Rasten eine Drehrichtung auslöst. */
  turn_every: number;
  /** Schritte einer Multi-Aktion (Plugin „multi“). */
  steps: Step[];
  /** Zweite Kette des Umschalters. */
  steps_off: Step[];
  repeat: boolean;
  toggled: boolean;
  /** Weitere Belegungen desselben Dials — Eintrag 2..n eines Stacks. */
  stack: Slot[];
}

export interface TouchWallpaper {
  enabled: boolean;
  source: string;
  fit: "cover" | "contain";
  /** Deckkraft in Prozent — darunter tritt das Bild hinter die Belegungen zurück. */
  opacity: number;
}

export interface Page {
  id: string;
  name: string;
  parent_id: string | null;
  /** Position unter den Geschwistern — kleiner Wert zuerst. */
  order: number;
  keys: Record<string, Slot>;
  dials: Record<string, Slot>;
  /** Hintergrundbild des Touchstrips — je Seite ein eigenes. */
  touch_wallpaper: TouchWallpaper;
}

/** Ein Profil, wie es die Verwaltung auflistet. */
export interface ProfileInfo {
  id: string;
  name: string;
  pages: number;
  /** Namen der Decks, die es gerade zeigen — Warnung vor dem Löschen. */
  decks: string[];
  active: boolean;
  /** Programme, bei denen dieses Profil von selbst nach vorn kommt. */
  auto_apps: string[];
}

export interface Profile {
  id: string;
  name: string;
  root_page_id: string;
  pages: Record<string, Page>;
}

export interface Screensaver {
  enabled: boolean;
  /** `upload:<dateiname>` oder `plugin:<id>`; leer = nichts gewählt. */
  source: string;
  after_s: number;
  brightness: number;
  fit: "cover" | "contain";
}

/** Ein wählbarer Bildschirmschoner — hochgeladen oder aus einem Plugin. */
export interface ScreensaverEntry {
  source: string;
  kind: "upload" | "plugin";
  name: string | Record<string, string>;
  description: string | Record<string, string>;
  animated: boolean;
  preview_url: string;
}

/** Ein wählbares Touchstrip-Hintergrundbild. */
export interface WallpaperEntry {
  source: string;
  kind: "upload" | "plugin";
  name: string | Record<string, string>;
  description: string | Record<string, string>;
  preview_url: string;
}

export interface DeviceSettings {
  brightness: number;
  idle_dim_after_s: number;
  idle_brightness: number;
  long_press_ms: number;
  /** Fenster, in dem ein zweiter Druck als Doppeldruck zählt. */
  double_press_ms: number;
  tick_interval_s: number;
  swipe_switches_page: boolean;
  swipe_min_distance: number;
  swipe_wraps: boolean;
  /** Animierte Tastenbilder abspielen. */
  animations: boolean;
  animation_fps: number;
  screensaver: Screensaver;
}

/** Ein Gerät und was daran hängt — je Deck ein Profil. */
export interface DeckBinding {
  serial: string;
  name: string;
  deck_type: string;
  profile_id: string;
  device: DeviceSettings;
  order: number;
}

/** Zustand eines Decks, wie ihn das Backend meldet (DeviceInfo + Bindung). */
export interface DeckInfo extends DeviceInfo {
  id: string;
  name: string;
  profile_id: string;
  current_page_id: string;
  screensaver?: boolean;
  settings: DeviceSettings;
  order: number;
  /** `hardware` hängt am USB, `virtual` liegt als Overlay auf dem Bildschirm. */
  kind: "hardware" | "virtual" | "network";
  columns: number;
  rows: number;
  dials: number;
  tile_size: number;
  /** Overlay ohne eigenen Grund — nur die Kacheln schweben. */
  overlay_transparent?: boolean;
  /** Unbelegte Kacheln gar nicht erst zeigen. */
  hide_empty?: boolean;
  /** Nur bei virtuellen Decks: ob das Overlay gerade zu sehen ist. */
  overlay_visible?: boolean;
  /** Nur bei Netz-Decks: ob ein Passwort gesetzt ist (nie das Passwort selbst). */
  has_password?: boolean;
  network_enabled?: boolean;
  network_port?: number;
  /** Adressen, unter denen das Deck gerade im Netz erreichbar ist. */
  network_urls?: string[];
  network_running?: boolean;
  overlay_available?: boolean;
  overlay_reason?: string;
  /** Globaler Kurzbefehl, der das Overlay holt. Leer = keiner. */
  overlay_hotkey?: string;
  /** Warum der Kurzbefehl gerade *nicht* wirkt. Leer = er wirkt. */
  hotkey_reason?: string;
  /**
   * Womit der Kurzbefehl tatsächlich ausgelöst wird. Nur gesetzt, wenn der
   * Desktop das selbst entschieden hat (Portal-Weg) und es von der
   * eingetippten Kombination abweichen kann.
   */
  hotkey_effective?: string;
}

export interface AppSettings {
  language: "de" | "en";
  host: string;
  port: number;
  plugin_order: string[];
}

export interface Config {
  version: number;
  app: AppSettings;
  /** Vorlage für neue Geräte; die geltenden Werte stehen je Deck. */
  device: DeviceSettings;
  decks: Record<string, DeckBinding>;
  active_profile_id: string;
  profiles: Record<string, Profile>;
  plugin_settings: Record<string, Record<string, unknown>>;
  disabled_plugins: string[];
}

export interface SettingsField {
  key: string;
  label: LocalizedText;
  type:
    | "text"
    | "number"
    | "bool"
    | "select"
    | "color"
    | "path"
    | "file"
    | "password"
    | "hotkey";
  default?: unknown;
  placeholder?: LocalizedText;
  help?: LocalizedText;
  options: {
    value: unknown;
    label: LocalizedText;
    /** Was die Sitzung können muss, damit dieser Auswahlwert etwas bewirkt. */
    requires?: string[];
    /** Gesetzt, wenn diese Sitzung ihn nicht hergibt. */
    unavailable?: { missing: string[]; reason: string } | null;
  }[];
  options_source?: string | null;
  options_depend_on?: string[];
  min?: number | null;
  max?: number | null;
  step?: number | null;
  depends_on?: Record<string, unknown> | null;
}

export interface ActionState {
  id: string;
  name: LocalizedText;
  default_icon?: string | null;
}

export interface ActionDescriptor {
  id: string;
  name: LocalizedText;
  description: LocalizedText;
  inputs: InputType[];
  default_icon?: string | null;
  default_label: LocalizedText;
  states: ActionState[];
  settings_schema: SettingsField[];
  accent?: string | null;
  /** Was die Sitzung können muss, damit die Aktion etwas bewirkt. */
  requires?: string[];
  /**
   * Gesetzt, wenn diese Sitzung die Aktion nicht hergibt. Die Bibliothek
   * blendet sie dann aus — auf einer schon belegten Taste bleibt sie
   * sichtbar und zeigt den Grund an.
   */
  unavailable?: { missing: string[]; reason: string } | null;
}

/** Schubladen der Plugin-Übersicht — dieselbe Liste wie im Backend. */
export type PluginCategory =
  | "system"
  | "audio"
  | "business"
  | "creative"
  | "development"
  | "engagement"
  | "finance"
  | "gaming"
  | "lighting"
  | "monitoring"
  | "music"
  | "productivity"
  | "screensaver"
  | "smarthome"
  | "social"
  | "streaming"
  | "utilities"
  | "video"
  | "other";

export interface Manifest {
  id: string;
  name: LocalizedText;
  version: string;
  type: "action" | "iconset" | "screensaver" | "wallpaper";
  description: LocalizedText;
  author: string;
  accent: string;
  /** Wohin das Plugin in der Übersicht gehört. */
  category?: PluginCategory;
  /** Bis zu drei Bilder für die Detailansicht (Dateinamen im Plugin-Ordner). */
  screenshots?: string[];
  /** Projektseite, Forum oder Fehlerberichte. */
  support?: string;
  /** Was sich zuletzt geändert hat. */
  changelog?: LocalizedText;
  /** Dateiname eines 256×256-Symbols im Plugin-Ordner. */
  icon?: string | null;
  config_schema: SettingsField[];
  actions: ActionDescriptor[];
  license: string;
}

/** Eine Fähigkeit der laufenden Sitzung. */
export interface Capability {
  id: string;
  available: boolean;
  /** Womit sie umgesetzt wird — "spectacle", "portal", "kwin". */
  provider: string;
  /** Warum nicht, in einem Satz. Leer, wenn verfügbar. */
  reason: string;
}

export interface SessionInfo {
  /** "kde", "gnome", "hyprland", … oder "" wenn unbekannt. */
  desktop: string;
  /** "wayland", "x11" oder "". */
  display_server: string;
}

export interface SessionCapabilities {
  session: SessionInfo;
  capabilities: Capability[];
}

/** Verbindungszustand — nur bei Plugins, die von etwas Externem abhängen. */
export interface PluginStatus {
  connected: boolean;
  detail?: string;
}

export interface PluginInfo {
  id: string;
  manifest: Manifest;
  /** Ob die Symboldatei tatsächlich existiert — vom Backend geprüft. */
  has_icon: boolean;
  builtin: boolean;
  enabled: boolean;
  loaded: boolean;
  error: string | null;
  config: Record<string, unknown>;
  status: PluginStatus | null;
}

/** Über einen streamdeck://-Link angefragte Installation. */
export interface InstallRequest {
  id: string;
  url: string;
  origin: string;
  created_at: number;
  /** Angekündigte Prüfsumme. Leer = niemand hat gesagt, was ankommen soll. */
  sha256?: string;
}

export interface DeviceInfo {
  connected: boolean;
  deck_type: string;
  serial: string;
  firmware: string;
  key_count: number;
  dial_count: number;
  key_size: [number, number];
  touchscreen_size: [number, number];
  segment_size: [number, number];
  /** Anordnung der Tasten — 2×4 beim Plus, 4×8 beim XL, 2×3 beim Mini. */
  key_rows: number;
  key_columns: number;
  /** Das Pedal hat keine Displays. */
  has_displays: boolean;
  has_dials: boolean;
  has_touchscreen: boolean;
  error: string | null;
  dimmed?: boolean;
}

export interface BackendError {
  plugin_id: string;
  message: string;
  level: string;
  source: string;
  count?: number;
  time: number;
}

export interface BackgroundPreset {
  id: string;
  name: LocalizedText;
  background: Partial<Background>;
}

export interface BackendState {
  /** Version des Backends — die einzige, die die Oberfläche kennt. */
  version: string;
  device: DeviceInfo;
  decks: DeckInfo[];
  active_deck: string;
  config: Config;
  current_page_id: string;
  plugins: PluginInfo[];
  errors: BackendError[];
  backgrounds: BackgroundPreset[];
}

/** Zustand des systemd-User-Dienstes, der das Backend beim Login startet. */
export interface AutostartStatus {
  supported: boolean;
  enabled: boolean;
  unit_installed: boolean;
  unit_path: string;
  /** Gefüllt, wenn `supported` falsch ist — Klartext für die GUI. */
  reason: string | null;
}

/** Auswahl im Editor: eine Taste oder ein Dial auf der aktuellen Seite. */
export interface Selection {
  inputType: InputType;
  index: number;
}

/** Ob die App Tastendrücke schicken kann — und mit welcher Belegung. */
export interface InputStatus {
  available: boolean;
  reason: string;
  layout: string;
}

// -- Der Plugin-Store ------------------------------------------------------

/** Ein Befund der Durchsicht, wie ihn der Store mitschickt. */
export interface StoreWarnung {
  kind: string;
  value: string;
  file: string;
  line: number | null;
}

/** Eine Fassung im Katalog. */
export interface StoreVersion {
  version: string;
  sha256: string;
  size: number;
  changelog: string | null;
  min_app_version: string | null;
  downloads: number;
  released_at: string;
  download_url: string;
  /** Symbol dieser Fassung, wenn das Manifest eines nennt. */
  icon_url: string | null;
  /** Die Bilder der Detailansicht — höchstens drei. */
  screenshot_urls: string[];
  warnings: StoreWarnung[];
  /** Nur in der Einzelansicht: `approved` oder `withdrawn`. */
  state?: string;
  note?: string | null;
}

/** Ein Plugin im Katalog. */
export interface StorePlugin {
  slug: string;
  name: string;
  summary: string;
  kind: string;
  category: string;
  author: string;
  license: string | null;
  source_url: string | null;
  rating: { up: number; down: number };
  latest: StoreVersion;
  /** Nur in der Einzelansicht. */
  description?: string | null;
  versions?: StoreVersion[];
}

/** Ein Plugin, für das im Store eine neuere Fassung liegt. */
export interface StoreUpdate {
  slug: string;
  name: string;
  installed: string;
  available: string;
  changelog: string | null;
  size: number | null;
  released_at: string | null;
  min_app_version: string | null;
  /** `false`, wenn die neue Fassung eine neuere App verlangt als diese. */
  usable: boolean;
}

/** Eine Stimme mit Kommentar, so wie sie andere abgegeben haben. */
export interface StoreKommentar {
  value: number;
  comment: string | null;
  author: string;
  at: string;
}

/**
 * Die Bewertung eines Plugins.
 *
 * `mine` ist die eigene Stimme — `null`, wenn man nicht abgestimmt hat oder
 * gar nicht angemeldet ist.
 */
export interface StoreBewertung {
  up: number;
  down: number;
  mine: number | null;
  comment: string | null;
  comments: StoreKommentar[];
}

/** Wer im Store angemeldet ist. */
export interface StoreUser {
  id: number;
  handle: string;
  permissions: string[];
  banned: boolean;
}

/**
 * Was auf Prüfung wartet — nur gefüllt, wenn der Angemeldete prüfen darf.
 * Die allermeisten Benutzer sehen hier `null`.
 */
export interface StorePending {
  submissions: number;
  reports: number;
  url: string;
}

export interface StoreAccount {
  user: StoreUser | null;
  pending: StorePending | null;
  store_url: string;
}

/** Eine Fassung in der Übersicht der eigenen Einreichungen. */
export interface StoreMineVersion {
  version: string;
  /** pending | approved | rejected | withdrawn | blocked */
  status: string;
  /** Warum zurückgezogen oder gesperrt. */
  stateNote: string | null;
  /** Was die Moderation dazugeschrieben hat — auch bei einer Ablehnung. */
  reviewNote: string | null;
  submittedAt: string;
  reviewedAt: string | null;
  downloadCount: number;
}

/** Ein eigenes Plugin im Store, mit allen Fassungen. */
export interface StoreMinePlugin {
  id: number;
  slug: string;
  name: string;
  kind: string;
  visibility: string;
  removedAt: string | null;
  versions: StoreMineVersion[];
}

/** Schritt 1 der Anmeldung: der Code, den der Benutzer eintippt. */
export interface StoreLoginStart {
  device_code: string;
  user_code: string;
  verification_uri: string;
  expires_in: number;
  interval: number;
}

/** Was beim Hochladen herauskommt. */
export interface StoreUploadResult {
  slug: string;
  version: string;
  sha256: string;
  status: string;
  findings: number;
  warnings: number;
  message: string;
}
