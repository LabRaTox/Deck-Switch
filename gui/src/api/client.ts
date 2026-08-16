/**
 * Zugriff auf das lokale Backend.
 *
 * Absolute Basis-URL statt Vite-Proxy: derselbe Code läuft damit im
 * Browser (Dev-Server auf 5173), im Tauri-Fenster und im gebauten Build,
 * ohne Sonderfälle.
 */

import type {
  AppSettings,
  InstallRequest,
  AutostartStatus,
  BackendError,
  BackendState,
  Config,
  DeckInfo,
  DeviceSettings,
  InputStatus,
  Page,
  PluginInfo,
  ScreensaverEntry,
  Slot,
  TouchWallpaper,
  WallpaperEntry,
} from "../types";

const DEFAULT_BASE = "http://127.0.0.1:8770";

/** Ports, unter denen *nicht* das Backend, sondern der Vite-Dev-Server läuft. */
const DEV_SERVER_PORTS = new Set(["5173", "5174", "4173"]);

function resolveBase(): string {
  const configured = import.meta.env.VITE_BACKEND_URL as string | undefined;
  if (configured) return configured;

  // Wird die GUI vom Backend selbst ausgeliefert, ist dessen Origin per
  // Definition die richtige Adresse — auch wenn der Port abweicht.
  if (typeof window !== "undefined" && window.location.protocol.startsWith("http")) {
    const { port, origin } = window.location;
    if (!DEV_SERVER_PORTS.has(port)) return origin;
  }
  return DEFAULT_BASE;
}

export const API_BASE: string = resolveBase();

/**
 * Das Deck, das die GUI gerade bearbeitet.
 *
 * Seiten, Belegungen und Vorschauen gibt es je Gerät — jedes Deck hat sein
 * eigenes Profil. Statt diese Kennung durch jeden einzelnen Aufruf zu
 * reichen, steht sie hier: Die Oberfläche bearbeitet immer genau ein Deck,
 * und der Store setzt sie beim Umschalten.
 */
let activeDeck = "";

export function setActiveDeck(key: string): void {
  activeDeck = key ?? "";
}

export function getActiveDeck(): string {
  return activeDeck;
}

/** Hängt das aktive Deck an eine Adresse — als erster oder weiterer Parameter. */
function withDeck(path: string): string {
  if (!activeDeck) return path;
  const separator = path.includes("?") ? "&" : "?";
  return `${path}${separator}deck=${encodeURIComponent(activeDeck)}`;
}

export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
      ...init,
    });
  } catch {
    throw new ApiError(`Backend nicht erreichbar (${API_BASE})`, 0);
  }

  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = body?.detail ?? detail;
    } catch {
      /* Antwort war kein JSON — Statustext genügt */
    }
    throw new ApiError(String(detail), response.status);
  }

  if (response.status === 204) return undefined as T;
  const text = await response.text();
  return (text ? JSON.parse(text) : undefined) as T;
}

export const api = {
  state: () => request<BackendState>("/api/state"),

  /** Ganze Config ersetzen — nur für den Import gedacht. */
  putConfig: (config: Config) =>
    request<Config>("/api/config", { method: "PUT", body: JSON.stringify(config) }),

  /**
   * App-Einstellungen gezielt ändern.
   *
   * Statt die ganze Config zurückzuschicken: Deren Stand ist womöglich
   * älter als das, was inzwischen am Gerät oder von einem anderen Fenster
   * aus passiert ist — das würde sonst stillschweigend überschrieben.
   */
  patchAppSettings: (patch: { language?: string; active_iconset?: string }) =>
    request<AppSettings>("/api/config/app", {
      method: "PATCH",
      body: JSON.stringify(patch),
    }),

  setBrightness: (value: number) =>
    request<{ brightness: number }>(withDeck("/api/device/brightness"), {
      method: "POST",
      body: JSON.stringify({ value }),
    }),

  reconnect: () =>
    request<{ ok: boolean }>(withDeck("/api/device/reconnect"), { method: "POST" }),

  // -- Decks --------------------------------------------------------------

  decks: () => request<DeckInfo[]>("/api/decks"),

  updateDeck: (
    key: string,
    patch: {
      name?: string;
      order?: number;
      profile_id?: string;
      device?: DeviceSettings;
      columns?: number;
      rows?: number;
      dials?: number;
      tile_size?: number;
      overlay_transparent?: boolean;
      hide_empty?: boolean;
    },
  ) =>
    request<DeckInfo>(`/api/decks/${encodeURIComponent(key)}`, {
      method: "PATCH",
      body: JSON.stringify(patch),
    }),

  /** Legt ein virtuelles Deck an — ein Overlay statt Hardware. */
  createVirtualDeck: (payload: {
    name: string;
    columns: number;
    rows: number;
    dials: number;
  }) =>
    request<DeckInfo>("/api/decks/virtual", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  /** Legt ein Netz-Deck an — bedient wird es im Browser eines anderen Rechners. */
  createNetworkDeck: (payload: {
    name: string;
    columns: number;
    rows: number;
    dials: number;
  }) =>
    request<DeckInfo>("/api/decks/network", {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  /** Passwort eines Netz-Decks setzen. Leer entfernt es und sperrt das Deck. */
  setDeckPassword: (key: string, password: string) =>
    request<{ has_password: boolean; urls: string[] }>(
      `/api/decks/${encodeURIComponent(key)}/password`,
      { method: "POST", body: JSON.stringify({ password }) },
    ),

  /** Overlay zeigen, verstecken oder umschalten (`visible: null`). */
  setOverlay: (key: string, visible: boolean | null, atCursor = true) =>
    request<{ visible: boolean }>(`/api/decks/${encodeURIComponent(key)}/overlay`, {
      method: "POST",
      body: JSON.stringify({ visible, at_cursor: atCursor }),
    }),

  /** Bindung eines nicht mehr vorhandenen Decks entfernen. */
  forgetDeck: (key: string) =>
    request<{ forgotten: string }>(`/api/decks/${encodeURIComponent(key)}`, {
      method: "DELETE",
    }),

  // -- Schriften und Eingabe ----------------------------------------------

  fonts: () => request<string[]>("/api/fonts"),

  inputStatus: () => request<InputStatus>("/api/input/status"),

  // -- Bildschirmschoner --------------------------------------------------

  screensavers: () => request<ScreensaverEntry[]>("/api/screensavers"),

  /** Zeigt, wie der Schoner nach dem Zerschneiden auf dem Deck ankommt. */
  screensaverPreviewUrl: (source: string) =>
    API_BASE +
    withDeck(`/api/screensavers/preview?source=${encodeURIComponent(source)}`),

  testScreensaver: () =>
    request<{ ok: boolean }>(withDeck("/api/screensavers/test"), { method: "POST" }),

  // -- Touchstrip-Hintergrundbild -----------------------------------------

  wallpapers: () => request<WallpaperEntry[]>("/api/wallpapers"),

  /**
   * Vorschau des Streifens. Einpassung und Deckkraft stehen in der URL —
   * damit lädt der Browser bei jeder Änderung ein neues Bild statt das
   * gecachte zu zeigen, und die Vorschau rechnet beides schon mit ein.
   */
  wallpaperPreviewUrl: (source: string, fit: string, opacity: number) =>
    API_BASE +
    withDeck(
      `/api/wallpapers/preview?source=${encodeURIComponent(source)}` +
        `&fit=${encodeURIComponent(fit)}&opacity=${opacity}`,
    ),

  // -- Autostart ----------------------------------------------------------

  autostart: () => request<AutostartStatus>("/api/autostart"),

  /** Wirkt erst beim nächsten Login — der laufende Dienst bleibt unberührt. */
  setAutostart: (enabled: boolean) =>
    request<AutostartStatus>("/api/autostart", {
      method: "POST",
      body: JSON.stringify({ enabled }),
    }),

  // -- Seiten -------------------------------------------------------------

  pages: () =>
    request<{
      deck: string;
      profile_id: string;
      root_page_id: string;
      current_page_id: string;
      pages: Record<string, Page>;
    }>(withDeck("/api/pages")),

  createPage: (name: string, parentId: string | null) =>
    request<Page>(withDeck("/api/pages"), {
      method: "POST",
      body: JSON.stringify({ name, parent_id: parentId }),
    }),

  updatePage: (
    pageId: string,
    patch: { name?: string; parent_id?: string; touch_wallpaper?: TouchWallpaper },
  ) =>
    request<Page>(withDeck(`/api/pages/${pageId}`), {
      method: "PATCH",
      body: JSON.stringify(patch),
    }),

  /** Neue Position: Elternteil + Index unter den Geschwistern (beides immer). */
  movePage: (pageId: string, parentId: string | null, index: number) =>
    request<{ pages: Record<string, Page> }>(withDeck(`/api/pages/${pageId}/move`), {
      method: "POST",
      body: JSON.stringify({ parent_id: parentId, index }),
    }),

  deletePage: (pageId: string) =>
    request<{ deleted: string[] }>(withDeck(`/api/pages/${pageId}`), {
      method: "DELETE",
    }),

  navigate: (pageId: string) =>
    request<{ current_page_id: string }>(withDeck(`/api/navigate/${pageId}`), {
      method: "POST",
    }),

  // -- Belegungen ---------------------------------------------------------

  putSlot: (pageId: string, inputType: string, index: number, slot: Slot | null) =>
    request<{ ok: boolean }>(
      withDeck(`/api/pages/${pageId}/slots/${inputType}/${index}`),
      {
        method: "PUT",
        body: JSON.stringify({ slot }),
      },
    ),

  triggerSlot: (pageId: string, inputType: string, index: number) =>
    request<{ ok: boolean }>(
      withDeck(`/api/pages/${pageId}/slots/${inputType}/${index}/trigger`),
      { method: "POST" },
    ),

  /** Dial-Stack weiterschalten — dasselbe wie langes Drücken am Gerät. */
  cycleStack: (pageId: string, index: number) =>
    request<{ stack_index: number }>(
      withDeck(`/api/pages/${pageId}/slots/dial/${index}/cycle`),
      { method: "POST" },
    ),

  // -- Plugins ------------------------------------------------------------

  plugins: () => request<PluginInfo[]>("/api/plugins"),

  /** Symbol eines Plugins — nur aufrufen, wenn `has_icon` gesetzt ist. */
  pluginIconUrl: (pluginId: string) => `${API_BASE}/api/plugins/${pluginId}/icon`,

  /**
   * Auswahlliste eines Feldes. ``context`` sind die übrigen Einstellungen
   * derselben Belegung — damit kann ein Plugin abhängige Listen liefern
   * (die Filter *dieser* Quelle, die Quellen *dieser* Szene).
   */
  pluginOptions: (
    pluginId: string,
    source: string,
    context: Record<string, unknown> = {},
  ) =>
    request<{ value: unknown; label: string }[]>(
      withDeck(`/api/plugins/${pluginId}/options/${source}`),
      { method: "POST", body: JSON.stringify(context) },
    ),

  putPluginConfig: (pluginId: string, config: Record<string, unknown>) =>
    request<Record<string, unknown>>(`/api/plugins/${pluginId}/config`, {
      method: "PUT",
      body: JSON.stringify(config),
    }),

  pluginCommand: (pluginId: string, command: string, payload: unknown = {}) =>
    request<Record<string, unknown>>(
      `/api/plugins/${pluginId}/command/${command}`,
      { method: "POST", body: JSON.stringify(payload) },
    ),

  setPluginEnabled: (pluginId: string, enabled: boolean) =>
    request<{ enabled: boolean }>(`/api/plugins/${pluginId}/enabled`, {
      method: "POST",
      body: JSON.stringify({ enabled }),
    }),

  installFromUrl: (url: string) =>
    request<{ installed: string; version: string }>("/api/plugins/install-url", {
      method: "POST",
      body: JSON.stringify({ url }),
    }),

  installRequests: () => request<InstallRequest[]>("/api/plugins/install-requests"),

  confirmInstallRequest: (requestId: string) =>
    request<{ installed: string; version: string }>(
      `/api/plugins/install-requests/${requestId}`,
      { method: "POST" },
    ),

  dismissInstallRequest: (requestId: string) =>
    request<{ dismissed: string }>(`/api/plugins/install-requests/${requestId}`, {
      method: "DELETE",
    }),

  installPlugin: async (file: File) => {
    const form = new FormData();
    form.append("file", file);
    const response = await fetch(`${API_BASE}/api/plugins/install`, {
      method: "POST",
      body: form,
    });
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new ApiError(body?.detail ?? "Installation fehlgeschlagen", response.status);
    }
    return (await response.json()) as { installed: string; version: string };
  },

  uninstallPlugin: (pluginId: string) =>
    request<{ uninstalled: string; slots_removed: number }>(
      `/api/plugins/${pluginId}`,
      { method: "DELETE" },
    ),

  setPluginOrder: (order: string[]) =>
    request<{ order: string[] }>("/api/plugins/order", {
      method: "PUT",
      body: JSON.stringify({ order }),
    }),

  reloadPlugins: () =>
    request<{ plugins: PluginInfo[] }>("/api/plugins/reload", { method: "POST" }),

  // -- Icons und Uploads --------------------------------------------------

  iconSets: () =>
    request<{ id: string; name: string; license: string; count: number }[]>(
      "/api/icons/sets",
    ),

  icons: (setId: string, query = "", limit = 400) =>
    request<{ set_id: string; total: number; icons: string[] }>(
      `/api/icons/sets/${setId}?query=${encodeURIComponent(query)}&limit=${limit}`,
    ),

  iconUrl: (setId: string, name: string) =>
    `${API_BASE}/api/icons/svg/${setId}/${encodeURIComponent(name)}`,

  uploadUrl: (filename: string) => `${API_BASE}/api/uploads/${filename}`,

  uploads: () =>
    request<{ filename: string; url: string; size: number }[]>("/api/uploads"),

  // `kind` bestimmt die Ablage: Touchstrip-Streifen liegen getrennt von den
  // Kachelbildern, damit sie nicht in der Icon-Auswahl auftauchen.
  upload: async (file: File, kind: "icon" | "wallpaper" = "icon") => {
    const form = new FormData();
    form.append("file", file);
    const response = await fetch(`${API_BASE}/api/uploads?kind=${kind}`, {
      method: "POST",
      body: form,
    });
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new ApiError(body?.detail ?? "Upload fehlgeschlagen", response.status);
    }
    return (await response.json()) as { filename: string; url: string };
  },

  // -- Vorschau -----------------------------------------------------------

  /** Vom Backend gerendert — die Vorschau kann gar nicht abweichen. */
  previewUrl: (
    pageId: string,
    inputType: string,
    index: number,
    version = 0,
    /** Bei einem Dial-Stack: welcher Eintrag gezeigt werden soll. */
    entry?: number,
  ) =>
    API_BASE +
    withDeck(
      `/api/preview/${pageId}/${inputType}/${index}.png?v=${version}` +
        (entry ? `&entry=${entry}` : ""),
    ),

  // -- Fehler, Export, Import ---------------------------------------------

  errors: () => request<BackendError[]>("/api/errors"),

  clearErrors: () => request<{ ok: boolean }>("/api/errors", { method: "DELETE" }),

  exportUrl: () => `${API_BASE}/api/export`,

  importConfig: (payload: unknown, mergeProfiles: boolean) =>
    request<Config>(`/api/import?merge_profiles=${mergeProfiles}`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
};

// --------------------------------------------------------------------------
// WebSocket
// --------------------------------------------------------------------------

export interface BackendEvent {
  type: string;
  data: Record<string, unknown>;
}

/**
 * Hält die WebSocket-Verbindung offen und baut sie mit wachsendem Abstand
 * wieder auf — das Backend darf neu starten, ohne dass man F5 drücken muss.
 */
export function connectEvents(
  onEvent: (event: BackendEvent) => void,
  onStatus?: (online: boolean) => void,
): () => void {
  let socket: WebSocket | null = null;
  let timer: number | undefined;
  let delay = 1000;
  let closed = false;

  const open = () => {
    if (closed) return;
    const url = API_BASE.replace(/^http/, "ws") + "/ws";
    socket = new WebSocket(url);

    socket.onopen = () => {
      delay = 1000;
      onStatus?.(true);
    };
    socket.onmessage = (message) => {
      try {
        onEvent(JSON.parse(message.data));
      } catch {
        /* fehlerhafte Nachricht ignorieren */
      }
    };
    socket.onclose = () => {
      onStatus?.(false);
      if (closed) return;
      timer = window.setTimeout(open, delay);
      delay = Math.min(delay * 2, 15000);
    };
    socket.onerror = () => socket?.close();
  };

  open();
  return () => {
    closed = true;
    window.clearTimeout(timer);
    socket?.close();
  };
}
