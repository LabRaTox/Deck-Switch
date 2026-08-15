/**
 * Zentraler Zustand der GUI.
 *
 * Änderungen gehen sofort ans Backend (die Spec verlangt ausdrücklich kein
 * "speichern → neu starten"). Die lokale Kopie wird dabei optimistisch
 * aktualisiert, damit die Oberfläche nicht bei jedem Tastendruck flackert;
 * bei einem Fehler holen wir den echten Zustand zurück.
 */

import { create } from "zustand";
import { api } from "./api/client";
import type {
  BackendError,
  Config,
  DeviceInfo,
  InputType,
  Page,
  PluginInfo,
  InstallRequest,
  BackgroundPreset,
  Selection,
  Slot,
} from "./types";

interface StoreState {
  ready: boolean;
  online: boolean;
  device: DeviceInfo | null;
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

function activeProfile(config: Config) {
  return config.profiles[config.active_profile_id];
}

export const useStore = create<StoreState>((set, get) => ({
  ready: false,
  online: false,
  device: null,
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
    set({
      ready: true,
      device: state.device,
      config: state.config,
      plugins: state.plugins,
      errors: state.errors,
      backgroundPresets: state.backgrounds,
      currentPageId: state.current_page_id,
      previewVersion: get().previewVersion + 1,
    });
  },

  setOnline: (online) => set({ online }),
  setView: (view) => set({ view }),
  select: (selection) => set({ selection }),
  bumpPreview: () => set((s) => ({ previewVersion: s.previewVersion + 1 })),

  currentPage: () => {
    const { config, currentPageId } = get();
    if (!config) return null;
    const profile = activeProfile(config);
    return profile?.pages[currentPageId] ?? null;
  },

  slotAt: (selection) => {
    if (!selection) return null;
    const page = get().currentPage();
    if (!page) return null;
    const mapping = selection.inputType === "key" ? page.keys : page.dials;
    return mapping[String(selection.index)] ?? null;
  },

  setSlot: async (inputType, index, slot) => {
    const { config, currentPageId } = get();
    if (!config) return;

    const previous = structuredClone(config);
    const profile = activeProfile(config);
    const page = profile.pages[currentPageId];
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
      activeProfile(config).pages[page.id] = page;
      set({ config: { ...config } });
    }
    return page;
  },

  renamePage: async (pageId, name) => {
    await api.updatePage(pageId, { name });
    const config = get().config;
    if (config) {
      const page = activeProfile(config).pages[pageId];
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
    const profile = activeProfile(config);
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
        const profileNow = activeProfile(fresh);
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
      for (const id of deleted) delete activeProfile(config).pages[id];
      set({ config: { ...config } });
    }
    if (deleted.includes(get().currentPageId) && config) {
      await get().navigate(activeProfile(config).root_page_id);
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
