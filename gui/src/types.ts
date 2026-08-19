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
}

export interface AppSettings {
  language: "de" | "en";
  active_iconset: string;
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
  options: { value: unknown; label: LocalizedText }[];
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
}

export interface Manifest {
  id: string;
  name: LocalizedText;
  version: string;
  type: "action" | "iconset" | "screensaver" | "wallpaper";
  description: LocalizedText;
  author: string;
  accent: string;
  /** Dateiname eines 256×256-Symbols im Plugin-Ordner. */
  icon?: string | null;
  config_schema: SettingsField[];
  actions: ActionDescriptor[];
  license: string;
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
