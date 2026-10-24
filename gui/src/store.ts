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
  StoreAccount,
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
  /** Version des Backends. Leer, solange nichts geladen wurde. */
  version: string;
  plugins: PluginInfo[];
  errors: BackendError[];
  backgroundPresets: BackgroundPreset[];
  currentPageId: string;
  selection: Selection | null;
  /** Erhöht sich bei jeder Änderung und bricht damit den Bild-Cache auf. */
  previewVersion: number;
  /**
   * Stand je Kachel, Schlüssel ``seite|art|index``. Ändert sich nur eine
   * Belegung, lädt nur deren Vorschau neu statt das ganze Raster.
   */
  kachelStand: Record<string, number>;
  view: "editor" | "plugins" | "settings";
  /**
   * Wer im Store angemeldet ist und was dort auf Prüfung wartet.
   *
   * Steht hier und nicht in der Store-Ansicht, weil mehrere Stellen es
   * brauchen: die Kopfzeile für die Zahl, das Einreichen für die Frage, ob
   * überhaupt jemand angemeldet ist. Wer erst hineinklicken muss, um zu
   * erfahren, dass etwas liegt, erfährt es zu spät.
   */
  storeKonto: StoreAccount | null;

  load: () => Promise<void>;
  /** Neu laden, aber gebündelt: Mehrere Anlässe kurz hintereinander laden einmal. */
  ladeBald: () => void;
  /** Deckliste übernehmen, wie sie das Backend von sich aus meldet. */
  setDecks: (decks: DeckInfo[]) => void;
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
      /** Das Overlay schließt sich nach einem Klick auf eine Kachel. */
      overlay_close_on_click?: boolean;
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
  bumpTile: (pageId: string, inputType: InputType, index: number) => void;

  currentPage: () => Page | null;
  slotAt: (selection: Selection | null) => Slot | null;

  /** ``false``, wenn das Backend die Belegung nicht angenommen hat. */
  setSlot: (inputType: InputType, index: number, slot: Slot | null) => Promise<boolean>;
  updateSelectedSlot: (mutate: (slot: Slot) => Slot) => Promise<boolean>;
  moveSlot: (from: Selection, to: Selection) => Promise<void>;

  /** Zwischenablage für Belegungen — überlebt Seiten- und Ansichtswechsel. */
  clipboard: Slot | null;
  copySlot: (from: Selection) => void;
  cutSlot: (from: Selection) => Promise<void>;
  pasteSlot: (to: Selection) => Promise<void>;
  /** Passt das Kopierte auf diese Eingabeart? Steuert den Menüeintrag. */
  canPasteInto: (inputType: InputType) => boolean;

  navigate: (pageId: string) => Promise<void>;
  createPage: (name: string, parentId: string | null) => Promise<Page | null>;
  renamePage: (pageId: string, name: string) => Promise<void>;
  /** Hängt die Seite an ``parentId`` und setzt sie dort auf ``index``. */
  movePage: (pageId: string, parentId: string | null, index: number) => Promise<void>;
  deletePage: (pageId: string) => Promise<void>;

  patchConfig: (mutate: (config: Config) => Config) => Promise<void>;
  /** App-Einstellungen gezielt ändern, ohne die ganze Config zu schicken. */
  patchAppSettings: (patch: { language?: "de" | "en" }) => Promise<void>;
  /** Hintergrundbild des Touchstrips dieser Seite. */
  patchTouchWallpaper: (pageId: string, patch: Partial<TouchWallpaper>) => Promise<void>;
  setPluginConfig: (pluginId: string, config: Record<string, unknown>) => Promise<void>;
  setPluginEnabled: (pluginId: string, enabled: boolean) => Promise<void>;
  reloadPlugins: () => Promise<{ neu: string[]; weg: string[]; geaendert: string[] }>;
  refreshStoreKonto: () => Promise<void>;
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

// --------------------------------------------------------------------------
// Schreiben ans Backend
// --------------------------------------------------------------------------

/**
 * Eine Spur je Ziel (Kachel, Deck, Seite). Pro Spur ist höchstens ein
 * Request unterwegs; was währenddessen kommt, ersetzt den Wartenden. So
 * kommen die Werte in der richtigen Reihenfolge an, ein Regler erzeugt
 * keine Flut, und der letzte Stand wird in jedem Fall geschickt.
 */
interface Spur {
  naechste: (() => Promise<void>) | null;
  wartende: { resolve: () => void; reject: (fehler: unknown) => void }[];
  laeuft: boolean;
  uhr: number | null;
}

const spuren = new Map<string, Spur>();

/** Mindestabstand zwischen zwei Requests derselben Spur. */
const SPUR_ABSTAND_MS = 80;

/** Steigt mit jeder optimistischen Änderung an der lokalen Config. */
let lokalerStand = 0;
/** Ein Laden kam, während noch geschrieben wurde — danach nachholen. */
let ladenNachSchreiben = false;
let ladeNummer = 0;
let ladeUhr: number | null = null;

function geaendert(): void {
  lokalerStand += 1;
}

function schreibtNoch(): boolean {
  return spuren.size > 0;
}

function schreibe(schluessel: string, aufgabe: () => Promise<void>): Promise<void> {
  let spur = spuren.get(schluessel);
  if (!spur) {
    spur = { naechste: null, wartende: [], laeuft: false, uhr: null };
    spuren.set(schluessel, spur);
  }
  spur.naechste = aufgabe;
  const fertig = new Promise<void>((resolve, reject) => {
    spur.wartende.push({ resolve, reject });
  });
  if (!spur.laeuft && spur.uhr === null) {
    const diese = spur;
    diese.uhr = window.setTimeout(() => void abarbeiten(schluessel, diese), 0);
  }
  return fertig;
}

async function abarbeiten(schluessel: string, spur: Spur): Promise<void> {
  spur.uhr = null;
  if (spur.laeuft || !spur.naechste) return;
  const aufgabe = spur.naechste;
  const wartende = spur.wartende;
  spur.naechste = null;
  spur.wartende = [];
  spur.laeuft = true;
  try {
    await aufgabe();
    for (const w of wartende) w.resolve();
  } catch (fehler) {
    // Was jetzt lokal steht, stimmt womöglich nicht mehr. Statt einen alten
    // Schnappschuss zurückzuspielen, wird nach dem Schreiben neu geladen.
    ladenNachSchreiben = true;
    for (const w of wartende) w.reject(fehler);
  } finally {
    spur.laeuft = false;
    if (spur.naechste) {
      spur.uhr = window.setTimeout(() => void abarbeiten(schluessel, spur), SPUR_ABSTAND_MS);
    } else {
      spuren.delete(schluessel);
      if (!schreibtNoch() && ladenNachSchreiben) {
        ladenNachSchreiben = false;
        useStore.getState().ladeBald();
      }
    }
  }
}

/**
 * Eigene Änderungen, deren Meldung über den WebSocket noch aussteht.
 *
 * Das Backend meldet jede gespeicherte Belegung zurück. Für die eigene
 * neu zu laden, wäre überflüssig und überschriebe, was gerade getippt wird.
 */
const erwarteteEchos = new Map<string, number>();

function echoErwarten(schluessel: string): void {
  erwarteteEchos.set(schluessel, (erwarteteEchos.get(schluessel) ?? 0) + 1);
}

function echoVergessen(schluessel: string): void {
  const anzahl = (erwarteteEchos.get(schluessel) ?? 0) - 1;
  if (anzahl > 0) erwarteteEchos.set(schluessel, anzahl);
  else erwarteteEchos.delete(schluessel);
}

/** War diese Meldung die eigene? Zählt sie dabei ab. */
export function istEigenesEcho(schluessel: string): boolean {
  if (!erwarteteEchos.has(schluessel)) return false;
  echoVergessen(schluessel);
  return true;
}

/** Nach einem Verbindungsabriss kommen ausstehende Meldungen nie mehr an. */
export function echosVergessen(): void {
  erwarteteEchos.clear();
}

export function slotEcho(deck: string, pageId: string, inputType: string, index: number): string {
  return `slot|${deck}|${pageId}|${inputType}|${index}`;
}

export function seitenEcho(pageId: string): string {
  return `page|${pageId}`;
}

function kachelSchluessel(pageId: string, inputType: string, index: number): string {
  return `${pageId}|${inputType}|${index}`;
}

/** Versionsangabe für eine Vorschau-Adresse: global plus je Kachel. */
export function vorschauStand(
  s: Pick<StoreState, "previewVersion" | "kachelStand">,
  pageId: string,
  inputType: string,
  index: number,
): string {
  return `${s.previewVersion}.${s.kachelStand[kachelSchluessel(pageId, inputType, index)] ?? 0}`;
}

export const useStore = create<StoreState>((set, get) => ({
  ready: false,
  online: false,
  device: null,
  decks: [],
  activeDeck: "",
  config: null,
  version: "",
  plugins: [],
  errors: [],
  backgroundPresets: [],
  currentPageId: "",
  selection: null,
  previewVersion: 0,
  kachelStand: {},
  view: "editor",

  load: async () => {
    const nummer = ++ladeNummer;
    const standVorher = lokalerStand;
    const state = await api.state();
    // Ein späteres Laden ist schon unterwegs: Dessen Antwort ist die neuere.
    if (nummer !== ladeNummer) return;
    const decks = state.decks ?? [];

    // Die Config nur übernehmen, wenn lokal nichts Neueres steht. Sonst
    // spränge ein Feld auf einen älteren Stand zurück, während man tippt.
    const configSicher = standVorher === lokalerStand && !schreibtNoch();
    if (!configSicher) {
      if (schreibtNoch()) ladenNachSchreiben = true;
      else get().ladeBald();
    }

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
      ...(configSicher || !get().config
        ? { config: state.config, previewVersion: get().previewVersion + 1 }
        : {}),
      version: state.version ?? "",
      plugins: state.plugins,
      errors: state.errors,
      backgroundPresets: state.backgrounds,
      currentPageId,
    });
  },

  ladeBald: () => {
    if (ladeUhr !== null) window.clearTimeout(ladeUhr);
    ladeUhr = window.setTimeout(() => {
      ladeUhr = null;
      void get()
        .load()
        .catch(() => undefined);
    }, 150);
  },

  setDecks: (decks) => {
    const { activeDeck, config } = get();
    const aktiv = decks.find((deck) => deck.id === activeDeck);
    set(aktiv ? { decks, device: aktiv } : { decks });
    // Ein neues Deck bringt eine eigene Bindung samt Profil mit, ein
    // verschwundenes nimmt die bearbeitete Ansicht mit: beides steht nur in
    // der vollständigen Config.
    const unbekannt = decks.some((deck) => !config?.decks?.[deck.id]);
    if (!aktiv || unbekannt) get().ladeBald();
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
    // Optimistisch, damit Regler flüssig bleiben. Die Geräteeinstellungen
    // ändern kein Tastenbild, die Vorschau bleibt also stehen.
    const optimistic = structuredClone(config);
    optimistic.decks[activeDeck].device = next;
    geaendert();
    set({ config: optimistic });

    const deck = activeDeck;
    try {
      await schreibe(`deck|${deck}`, async () => {
        // Geschickt wird, was beim Abschicken gilt: Bei einem Regler ist
        // das der jüngste Wert, nicht der, der die Spur geöffnet hat.
        const stand = get().config?.decks?.[deck]?.device ?? next;
        await api.updateDeck(deck, { device: stand });
      });
    } catch (error) {
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
  bumpTile: (pageId, inputType, index) =>
    set((s) => {
      const schluessel = kachelSchluessel(pageId, inputType, index);
      return {
        kachelStand: { ...s.kachelStand, [schluessel]: (s.kachelStand[schluessel] ?? 0) + 1 },
      };
    }),

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
    const { config, activeDeck } = get();
    if (!config) return false;

    // Über ``currentPage()`` und nicht über die gemerkte ID: Nach einem
    // Deckwechsel kann die ID zu einem fremden Profil gehören — dann würde
    // hier ins Leere geschrieben.
    const page = get().currentPage();
    if (!page) return false;
    const pageId = page.id;

    const mapping = inputType === "key" ? page.keys : page.dials;
    if (slot) mapping[String(index)] = slot;
    else delete mapping[String(index)];
    geaendert();
    set({ config: { ...config } });

    // Deck und Seite stehen fest, bevor geschickt wird: Bis die Spur dran
    // ist, kann der Editor schon woanders stehen.
    const echo = slotEcho(activeDeck, pageId, inputType, index);
    try {
      await schreibe(echo, async () => {
        echoErwarten(echo);
        try {
          await api.putSlot(pageId, inputType, index, slot, activeDeck);
        } catch (error) {
          echoVergessen(echo);
          throw error;
        }
        // Erst jetzt neu zeichnen lassen: Vorher lieferte das Backend
        // noch das alte Bild.
        get().bumpTile(pageId, inputType, index);
      });
      return true;
    } catch (error) {
      get().pushError(toError(error, "slot"));
      return false;
    }
  },

  updateSelectedSlot: async (mutate) => {
    const { selection } = get();
    const slot = get().slotAt(selection);
    if (!selection || !slot) return false;
    return get().setSlot(selection.inputType, selection.index, mutate(structuredClone(slot)));
  },

  moveSlot: async (from, to) => {
    if (from.inputType === to.inputType && from.index === to.index) return;
    const source = get().slotAt(from);
    if (!source) return;
    const target = get().slotAt(to);

    // Tauschen statt überschreiben — beim Umsortieren die freundlichere Geste.
    // Scheitert eine Hälfte, lädt die Schreibspur den echten Stand nach.
    await Promise.all([
      get().setSlot(to.inputType, to.index, source),
      get().setSlot(from.inputType, from.index, target),
    ]);
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
    let page: Page;
    try {
      page = await api.createPage(name, parentId);
    } catch (error) {
      get().pushError(toError(error, "pages"));
      return null;
    }
    const config = get().config;
    if (config) {
      const profile = activeProfile(config, get().activeDeck);
      if (profile) profile.pages[page.id] = page;
      geaendert();
      set({ config: { ...config } });
    }
    return page;
  },

  renamePage: async (pageId, name) => {
    try {
      await api.updatePage(pageId, { name });
    } catch (error) {
      get().pushError(toError(error, "pages"));
      return;
    }
    const config = get().config;
    if (config) {
      const page = activeProfile(config, get().activeDeck)?.pages[pageId];
      if (page) page.name = name;
      geaendert();
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
    geaendert();
    set({ config });

    try {
      const { pages } = await api.movePage(pageId, parentId, index);
      const fresh = get().config;
      if (fresh) {
        const profileNow = activeProfile(fresh, get().activeDeck);
        if (profileNow) profileNow.pages = pages;
        geaendert();
        set({ config: { ...fresh }, previewVersion: get().previewVersion + 1 });
      }
    } catch (error) {
      get().pushError(toError(error, "pages"));
      get().ladeBald();
    }
  },

  deletePage: async (pageId) => {
    let deleted: string[];
    try {
      ({ deleted } = await api.deletePage(pageId));
    } catch (error) {
      get().pushError(toError(error, "pages"));
      return;
    }
    const config = get().config;
    if (config) {
      const profile = activeProfile(config, get().activeDeck);
      for (const id of deleted) delete profile?.pages[id];
      geaendert();
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
    geaendert();
    set({ config: next, previewVersion: get().previewVersion + 1 });
    try {
      await api.putConfig(next);
    } catch (error) {
      get().pushError(toError(error, "config"));
      get().ladeBald();
    }
  },

  patchAppSettings: async (patch) => {
    const config = get().config;
    if (!config) return;
    const optimistic = structuredClone(config);
    Object.assign(optimistic.app, patch);
    geaendert();
    set({ config: optimistic, previewVersion: get().previewVersion + 1 });
    try {
      await api.patchAppSettings(patch);
    } catch (error) {
      get().pushError(toError(error, "config"));
      get().ladeBald();
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
    const deck = get().activeDeck;
    const target = activeProfile(optimistic, deck)?.pages[pageId];
    if (target) target.touch_wallpaper = next;
    geaendert();
    set({ config: optimistic, previewVersion: get().previewVersion + 1 });

    const echo = seitenEcho(pageId);
    try {
      await schreibe(echo, async () => {
        echoErwarten(echo);
        try {
          await api.updatePage(pageId, { touch_wallpaper: next }, deck);
        } catch (error) {
          echoVergessen(echo);
          throw error;
        }
      });
    } catch (error) {
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
    try {
      await api.setPluginEnabled(pluginId, enabled);
      await get().load();
    } catch (error) {
      get().pushError(toError(error, "plugins"));
    }
  },

  reloadPlugins: async () => {
    const ergebnis = await api.reloadPlugins();
    await get().load();
    return ergebnis;
  },

  storeKonto: null,

  refreshStoreKonto: async () => {
    try {
      set({ storeKonto: await api.storeAccount() });
    } catch {
      // Der Store kann aus sein oder nicht erreichbar — beides ist kein
      // Grund, in der Oberfläche einen Fehler zu zeigen. Die eigenen
      // Plugins stehen auch ohne ihn.
      set({ storeKonto: null });
    }
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
    try {
      await api.clearErrors();
      set({ errors: [] });
    } catch (error) {
      get().pushError(toError(error, "errors"));
    }
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
