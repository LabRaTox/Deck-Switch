/**
 * Zentraler Zustand der GUI.
 *
 * Änderungen gehen sofort ans Backend (die Spec verlangt ausdrücklich kein
 * "speichern → neu starten"). Die lokale Kopie wird dabei optimistisch
 * aktualisiert, damit die Oberfläche nicht bei jedem Tastendruck flackert;
 * bei einem Fehler holen wir den echten Zustand zurück.
 */

import { create } from "zustand";
import { api, setActiveDeck } from "./api/client";
import type {
  BackendError,
  Config,
  Profile,
  DeckInfo,
  DeviceInfo,
  DeviceSettings,
  InputType,
  Page,
  PluginInfo,
  InstallRequest,
  BackgroundPreset,
  Selection,
  Slot,
  TouchWallpaper,
} from "./types";

interface StoreState {
  ready: boolean;
  online: boolean;
  device: DeviceInfo | null;
  /** Alle bekannten Decks — auch gerade nicht angeschlossene. */
  decks: DeckInfo[];
  /** Das Deck, das der Editor gerade bearbeitet. */
  activeDeck: string;
  config: Config | null;
  plugins: PluginInfo[];
  errors: BackendError[];
  backgroundPresets: BackgroundPreset[];
  currentPageId: string;
  selection: Selection | null;
  /** Erhöht sich bei jeder Änderung und bricht damit den Bild-Cache auf. */
  previewVersion: number;
  view: "editor" | "plugins" | "settings";

  load: () => Promise<void>;
  setOnline: (online: boolean) => void;
  selectDeck: (key: string) => Promise<void>;
  activeDeckInfo: () => DeckInfo | null;
  deckSettings: () => DeviceSettings | null;
  patchDeckSettings: (mutate: (settings: DeviceSettings) => DeviceSettings) => Promise<void>;
  renameDeck: (key: string, name: string) => Promise<void>;
  forgetDeck: (key: string) => Promise<void>;
  /** Legt ein virtuelles Deck an (Overlay statt Hardware). */
  createNetworkDeck: (payload: {
    name: string;
    columns: number;
    rows: number;
    dials: number;
  }) => Promise<void>;
  setDeckPassword: (key: string, password: string) => Promise<void>;
  createVirtualDeck: (payload: {
    name: string;
    columns: number;
    rows: number;
    dials: number;
  }) => Promise<void>;
  /** Raster eines virtuellen Decks ändern. */
  setDeckGrid: (
    key: string,
    grid: {
      columns?: number;
      rows?: number;
      dials?: number;
      tile_size?: number;
      overlay_transparent?: boolean;
      hide_empty?: boolean;
      /** Globaler Kurzbefehl fürs Overlay. Leerer Text nimmt ihn weg. */
      overlay_hotkey?: string;
      /** Nur bei Netz-Decks: ob sie im Netz angeboten werden. */
      network_enabled?: boolean;
    },
  ) => Promise<void>;
  /** Overlay zeigen/verstecken. `null` schaltet um. */
  toggleOverlay: (key: string, visible: boolean | null) => Promise<void>;
  setView: (view: StoreState["view"]) => void;
  select: (selection: Selection | null) => void;
  bumpPreview: () => void;

  currentPage: () => Page | null;
  slotAt: (selection: Selection | null) => Slot | null;

  setSlot: (inputType: InputType, index: number, slot: Slot | null) => Promise<void>;
  updateSelectedSlot: (mutate: (slot: Slot) => Slot) => Promise<void>;
  moveSlot: (from: Selection, to: Selection) => Promise<void>;

  /** Zwischenablage für Belegungen — überlebt Seiten- und Ansichtswechsel. */
  clipboard: Slot | null;
  copySlot: (from: Selection) => void;
  cutSlot: (from: Selection) => Promise<void>;
  pasteSlot: (to: Selection) => Promise<void>;
  /** Passt das Kopierte auf diese Eingabeart? Steuert den Menüeintrag. */
  canPasteInto: (inputType: InputType) => boolean;

  navigate: (pageId: string) => Promise<void>;
  createPage: (name: string, parentId: string | null) => Promise<Page>;
  renamePage: (pageId: string, name: string) => Promise<void>;
  /** Hängt die Seite an ``parentId`` und setzt sie dort auf ``index``. */
  movePage: (pageId: string, parentId: string | null, index: number) => Promise<void>;
  deletePage: (pageId: string) => Promise<void>;

  patchConfig: (mutate: (config: Config) => Config) => Promise<void>;
  /** App-Einstellungen gezielt ändern, ohne die ganze Config zu schicken. */
  patchAppSettings: (patch: { language?: "de" | "en"; active_iconset?: string }) => Promise<void>;
  /** Hintergrundbild des Touchstrips dieser Seite. */
  patchTouchWallpaper: (pageId: string, patch: Partial<TouchWallpaper>) => Promise<void>;
  setPluginConfig: (pluginId: string, config: Record<string, unknown>) => Promise<void>;
  setPluginEnabled: (pluginId: string, enabled: boolean) => Promise<void>;
  reloadPlugins: () => Promise<void>;
  setPluginOrder: (order: string[]) => Promise<void>;
  uninstallPlugin: (pluginId: string) => Promise<void>;
  installRequests: InstallRequest[];
  loadInstallRequests: () => Promise<void>;
  addInstallRequest: (request: InstallRequest) => void;
  confirmInstallRequest: (requestId: string) => Promise<void>;
  dismissInstallRequest: (requestId: string) => Promise<void>;
  refreshPlugins: () => Promise<void>;
  clearErrors: () => Promise<void>;
  pushError: (error: BackendError) => void;
}

/**
 * Das Profil des Decks, das gerade bearbeitet wird.
 *
 * Jedes Deck hat ein eigenes — deshalb reicht ``active_profile_id`` allein
 * nicht mehr aus, sobald zwei Geräte angeschlossen sind.
 */
function activeProfile(config: Config, deckKey: string): Profile | undefined {
  const profileId = config.decks?.[deckKey]?.profile_id ?? config.active_profile_id;
  return config.profiles[profileId] ?? config.profiles[config.active_profile_id];
}

export const useStore = create<StoreState>((set, get) => ({
  ready: false,
  online: false,
  device: null,
  decks: [],
  activeDeck: "",
  config: null,
  plugins: [],
  errors: [],
  backgroundPresets: [],
  currentPageId: "",
  selection: null,
  previewVersion: 0,
  view: "editor",

  load: async () => {
    const state = await api.state();
    const decks = state.decks ?? [];

    // Das bearbeitete Deck beibehalten, solange es noch da ist — ein
    // Neuladen wegen einer Config-Änderung darf die Ansicht nicht
    // wegspringen lassen.
    const previous = get().activeDeck;
    const active =
      decks.find((deck) => deck.id === previous)?.id ??
      state.active_deck ??
      decks[0]?.id ??
      "";
    setActiveDeck(active);

    const activeInfo = decks.find((deck) => deck.id === active);
    const currentPageId =
      previous === active && get().currentPageId
        ? get().currentPageId
        : (activeInfo?.current_page_id ?? state.current_page_id);

    set({
      ready: true,
      device: activeInfo ?? state.device,
      decks,
      activeDeck: active,
      config: state.config,
      plugins: state.plugins,
      errors: state.errors,
      backgroundPresets: state.backgrounds,
      currentPageId,
      previewVersion: get().previewVersion + 1,
    });
  },

  selectDeck: async (key) => {
    const deck = get().decks.find((entry) => entry.id === key);
    if (!deck) return;
    setActiveDeck(key);
    set({
      activeDeck: key,
      device: deck,
      currentPageId: deck.current_page_id,
      selection: null,
      previewVersion: get().previewVersion + 1,
    });

    // Nachfragen, auf welcher Seite das Deck *jetzt* steht: Der Stand in
    // der Deckliste ist der vom letzten Laden, und in der Zwischenzeit kann
    // am Gerät oder im Overlay geblättert worden sein. Der Editor soll
    // zeigen, was das Deck zeigt.
    try {
      const { current_page_id } = await api.pages();
      if (current_page_id && get().activeDeck === key) {
        set({ currentPageId: current_page_id });
      }
    } catch {
      /* Backend kurz weg — dann bleibt der gemerkte Stand */
    }
  },

  activeDeckInfo: () => {
    const { decks, activeDeck } = get();
    return decks.find((deck) => deck.id === activeDeck) ?? decks[0] ?? null;
  },

  deckSettings: () => {
    const { config, activeDeck } = get();
    return config?.decks?.[activeDeck]?.device ?? config?.device ?? null;
  },

  patchDeckSettings: async (mutate) => {
    const { config, activeDeck } = get();
    const current = config?.decks?.[activeDeck]?.device;
    if (!config || !current) return;

    const next = mutate(structuredClone(current));
    // Optimistisch, damit Regler flüssig bleiben.
    const optimistic = structuredClone(config);
    optimistic.decks[activeDeck].device = next;
    set({ config: optimistic, previewVersion: get().previewVersion + 1 });

    try {
      await api.updateDeck(activeDeck, { device: next });
    } catch (error) {
      set({ config });
      get().pushError(toError(error, "deck"));
    }
  },

  renameDeck: async (key, name) => {
    try {
      await api.updateDeck(key, { name });
      await get().load();
    } catch (error) {
      get().pushError(toError(error, "deck"));
    }
  },

  createVirtualDeck: async (payload) => {
    try {
      await api.createVirtualDeck(payload);
      await get().load();
    } catch (error) {
      get().pushError(toError(error, "deck"));
    }
  },

  createNetworkDeck: async (payload) => {
    try {
      await api.createNetworkDeck(payload);
      await get().load();
    } catch (error) {
      get().pushError(toError(error, "deck"));
    }
  },

  setDeckPassword: async (key, password) => {
    try {
      await api.setDeckPassword(key, password);
      set({ decks: await api.decks() });
    } catch (error) {
      get().pushError(toError(error, "deck"));
    }
  },

  setDeckGrid: async (key, grid) => {
    try {
      await api.updateDeck(key, grid);
      await get().load();
    } catch (error) {
      get().pushError(toError(error, "deck"));
    }
  },

  toggleOverlay: async (key, visible) => {
    try {
      await api.setOverlay(key, visible);
      set({ decks: await api.decks() });
    } catch (error) {
      get().pushError(toError(error, "overlay"));
    }
  },

  forgetDeck: async (key) => {
    try {
      await api.forgetDeck(key);
      await get().load();
    } catch (error) {
      get().pushError(toError(error, "deck"));
    }
  },

  setOnline: (online) => set({ online }),
  setView: (view) => set({ view }),
  select: (selection) => set({ selection }),
  bumpPreview: () => set((s) => ({ previewVersion: s.previewVersion + 1 })),

  currentPage: () => {
    const { config, currentPageId } = get();
    if (!config) return null;
    const profile = activeProfile(config, get().activeDeck);
    if (!profile) return null;
    // Gehört die gemerkte Seite nicht zu diesem Profil — etwa direkt nach
    // einem Deckwechsel oder nach dem Löschen —, auf die Startseite
    // zurückfallen statt eine leere Ansicht zu zeigen.
    return profile.pages[currentPageId] ?? profile.pages[profile.root_page_id] ?? null;
  },

  slotAt: (selection) => {
    if (!selection) return null;
    const page = get().currentPage();
    if (!page) return null;
    const mapping = selection.inputType === "key" ? page.keys : page.dials;
    return mapping[String(selection.index)] ?? null;
  },

  setSlot: async (inputType, index, slot) => {
    const { config } = get();
    if (!config) return;

    // Über ``currentPage()`` und nicht über die gemerkte ID: Nach einem
    // Deckwechsel kann die ID zu einem fremden Profil gehören — dann würde
    // hier ins Leere geschrieben.
    const page = get().currentPage();
    if (!page) return;
    const currentPageId = page.id;

    const previous = structuredClone(config);
    const mapping = inputType === "key" ? page.keys : page.dials;
    if (slot) mapping[String(index)] = slot;
    else delete mapping[String(index)];
    set({ config: { ...config }, previewVersion: get().previewVersion + 1 });

    try {
      await api.putSlot(currentPageId, inputType, index, slot);
    } catch (error) {
      set({ config: previous });
      get().pushError(toError(error, "slot"));
      throw error;
    }
  },

  updateSelectedSlot: async (mutate) => {
    const { selection } = get();
    const slot = get().slotAt(selection);
    if (!selection || !slot) return;
    await get().setSlot(selection.inputType, selection.index, mutate(structuredClone(slot)));
  },

  moveSlot: async (from, to) => {
    if (from.inputType === to.inputType && from.index === to.index) return;
    const source = get().slotAt(from);
    if (!source) return;
    const target = get().slotAt(to);

    // Tauschen statt überschreiben — beim Umsortieren die freundlichere Geste.
    await get().setSlot(to.inputType, to.index, source);
    await get().setSlot(from.inputType, from.index, target);
    set({ selection: to });
  },

  clipboard: null,

  copySlot: (from) => {
    const slot = get().slotAt(from);
    // Kopie ablegen, nicht die Referenz: Sonst würde jede spätere Änderung
    // an der Quellkachel auch das Kopierte verändern.
    if (slot) set({ clipboard: structuredClone(slot) });
  },

  cutSlot: async (from) => {
    const slot = get().slotAt(from);
    if (!slot) return;
    set({ clipboard: structuredClone(slot) });
    // Erst kopieren, dann löschen — scheitert das Backend, liegt die
    // Belegung wenigstens noch in der Zwischenablage.
    await get().setSlot(from.inputType, from.index, null);
  },

  pasteSlot: async (to) => {
    const { clipboard } = get();
    if (!clipboard || !get().canPasteInto(to.inputType)) return;
    // Auch hier klonen, damit mehrfaches Einfügen keine Kacheln koppelt.
    await get().setSlot(to.inputType, to.index, structuredClone(clipboard));
    set({ selection: to });
  },

  canPasteInto: (inputType) => {
    const { clipboard, plugins } = get();
    if (!clipboard) return false;
    const action = plugins
      .find((p) => p.id === clipboard.plugin_id)
      ?.manifest.actions.find((a) => a.id === clipboard.action_id);
    // Kennt die GUI die Aktion nicht — etwa weil das Plugin inzwischen
    // deaktiviert ist —, nicht im Weg stehen und das Backend entscheiden
    // lassen. Ein Eintrag, der grundlos gesperrt ist, ärgert mehr als eine
    // Fehlerkachel, die man sofort wieder löschen kann.
    return action ? action.inputs.includes(inputType) : true;
  },

  navigate: async (pageId) => {
    set({ currentPageId: pageId, selection: null });
    try {
      await api.navigate(pageId);
    } catch (error) {
      get().pushError(toError(error, "navigate"));
    }
    set((s) => ({ previewVersion: s.previewVersion + 1 }));
  },

  createPage: async (name, parentId) => {
    const page = await api.createPage(name, parentId);
    const config = get().config;
    if (config) {
      const profile = activeProfile(config, get().activeDeck);
      if (profile) profile.pages[page.id] = page;
      set({ config: { ...config } });
    }
    return page;
  },

  renamePage: async (pageId, name) => {
    await api.updatePage(pageId, { name });
    const config = get().config;
    if (config) {
      const page = activeProfile(config, get().activeDeck)?.pages[pageId];
      if (page) page.name = name;
      set({ config: { ...config }, previewVersion: get().previewVersion + 1 });
    }
  },

  movePage: async (pageId, parentId, index) => {
    const previous = get().config;
    if (!previous) return;

    // Optimistisch: Das Backend rechnet die ``order``-Werte ohnehin neu und
    // schickt sie zurück — bis dahin soll die Zeile aber sofort dort stehen,
    // wo sie hingezogen wurde, statt kurz zurückzuspringen.
    const config = structuredClone(previous);
    const profile = activeProfile(config, get().activeDeck);
    const page = profile?.pages[pageId];
    if (!page) return;

    const siblings = Object.values(profile.pages)
      .filter((p) => p.parent_id === parentId && p.id !== pageId)
      .sort((a, b) => (a.order ?? 0) - (b.order ?? 0));
    page.parent_id = parentId;
    siblings.splice(Math.max(0, Math.min(index, siblings.length)), 0, page);
    siblings.forEach((sibling, position) => {
      sibling.order = position;
    });
    set({ config });

    try {
      const { pages } = await api.movePage(pageId, parentId, index);
      const fresh = get().config;
      if (fresh) {
        const profileNow = activeProfile(fresh, get().activeDeck);
        if (profileNow) profileNow.pages = pages;
        set({ config: { ...fresh }, previewVersion: get().previewVersion + 1 });
      }
    } catch (error) {
      set({ config: previous });
      get().pushError(toError(error, "pages"));
    }
  },

  deletePage: async (pageId) => {
    const { deleted } = await api.deletePage(pageId);
    const config = get().config;
    if (config) {
      const profile = activeProfile(config, get().activeDeck);
      for (const id of deleted) delete profile?.pages[id];
      set({ config: { ...config } });
    }
    if (deleted.includes(get().currentPageId) && config) {
      const root = activeProfile(config, get().activeDeck)?.root_page_id;
      if (root) await get().navigate(root);
    }
  },

  patchConfig: async (mutate) => {
    const config = get().config;
    if (!config) return;
    const next = mutate(structuredClone(config));
    set({ config: next, previewVersion: get().previewVersion + 1 });
    try {
      await api.putConfig(next);
    } catch (error) {
      set({ config });
      get().pushError(toError(error, "config"));
    }
  },

  patchAppSettings: async (patch) => {
    const config = get().config;
    if (!config) return;
    const optimistic = structuredClone(config);
    Object.assign(optimistic.app, patch);
    set({ config: optimistic, previewVersion: get().previewVersion + 1 });
    try {
      await api.patchAppSettings(patch);
    } catch (error) {
      set({ config });
      get().pushError(toError(error, "config"));
    }
  },

  patchTouchWallpaper: async (pageId, patch) => {
    const config = get().config;
    if (!config) return;
    const profile = activeProfile(config, get().activeDeck);
    const page = profile?.pages[pageId];
    if (!page) return;

    const next = { ...page.touch_wallpaper, ...patch };
    const optimistic = structuredClone(config);
    const target = activeProfile(optimistic, get().activeDeck)?.pages[pageId];
    if (target) target.touch_wallpaper = next;
    set({ config: optimistic, previewVersion: get().previewVersion + 1 });

    try {
      await api.updatePage(pageId, { touch_wallpaper: next });
    } catch (error) {
      set({ config });
      get().pushError(toError(error, "pages"));
    }
  },

  setPluginConfig: async (pluginId, pluginConfig) => {
    await api.putPluginConfig(pluginId, pluginConfig);
    set((s) => ({
      plugins: s.plugins.map((p) =>
        p.id === pluginId ? { ...p, config: pluginConfig } : p,
      ),
      previewVersion: s.previewVersion + 1,
    }));
  },

  setPluginEnabled: async (pluginId, enabled) => {
    await api.setPluginEnabled(pluginId, enabled);
    await get().load();
  },

  reloadPlugins: async () => {
    await api.reloadPlugins();
    await get().load();
  },

  installRequests: [],

  loadInstallRequests: async () => {
    try {
      set({ installRequests: await api.installRequests() });
    } catch {
      /* Backend kurz weg */
    }
  },

  addInstallRequest: (request) =>
    set((s) =>
      s.installRequests.some((r) => r.id === request.id)
        ? s
        : { installRequests: [...s.installRequests, request] },
    ),

  confirmInstallRequest: async (requestId) => {
    try {
      await api.confirmInstallRequest(requestId);
      await get().load();
    } catch (error) {
      get().pushError(toError(error, "install"));
    }
    set((s) => ({ installRequests: s.installRequests.filter((r) => r.id !== requestId) }));
  },

  dismissInstallRequest: async (requestId) => {
    await api.dismissInstallRequest(requestId).catch(() => undefined);
    set((s) => ({ installRequests: s.installRequests.filter((r) => r.id !== requestId) }));
  },

  uninstallPlugin: async (pluginId) => {
    try {
      await api.uninstallPlugin(pluginId);
      await get().load();
    } catch (error) {
      get().pushError(toError(error, "uninstall"));
    }
  },

  setPluginOrder: async (order) => {
    // Optimistisch umsortieren, damit das Ziehen sofort sichtbar wird.
    const position = new Map(order.map((id, i) => [id, i]));
    set((s) => ({
      plugins: [...s.plugins].sort(
        (a, b) => (position.get(a.id) ?? 999) - (position.get(b.id) ?? 999),
      ),
    }));
    try {
      await api.setPluginOrder(order);
    } catch (error) {
      get().pushError(toError(error, "plugin_order"));
      await get().refreshPlugins();
    }
  },

  /** Nur die Plugin-Liste neu holen — für Statuswechsel, ohne alles zu laden. */
  refreshPlugins: async () => {
    try {
      set({ plugins: await api.plugins() });
    } catch {
      /* Backend kurz weg — der nächste Versuch holt es nach */
    }
  },

  clearErrors: async () => {
    await api.clearErrors();
    set({ errors: [] });
  },

  pushError: (error) =>
    set((s) => {
      // Wiederholt sich derselbe Fehler, schickt das Backend denselben
      // Eintrag mit erhöhtem Zähler — dann ersetzen statt anhängen, sonst
      // stapeln sich identische Zeilen mit 1×, 2×, 3× …
      const index = s.errors.findIndex(
        (e) => e.plugin_id === error.plugin_id && e.message === error.message,
      );
      if (index >= 0) {
        const errors = [...s.errors];
        errors[index] = error;
        return { errors };
      }
      return { errors: [...s.errors, error].slice(-50) };
    }),
}));

function toError(error: unknown, source: string): BackendError {
  return {
    plugin_id: "",
    message: error instanceof Error ? error.message : String(error),
    level: "error",
    source,
    time: Date.now() / 1000,
  };
}
