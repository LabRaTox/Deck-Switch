import { useEffect } from "react";
import { useTranslation } from "react-i18next";

import { connectEvents } from "./api/client";
import { ActionLibrary } from "./components/ActionLibrary";
import { DeckGrid } from "./components/DeckGrid";
import { ErrorBanner } from "./components/ErrorBanner";
import { Inspector } from "./components/Inspector";
import { InstallRequestBanner } from "./components/PluginInstaller";
import { PageCrumbs, PageTree } from "./components/PageTree";
import { PluginsView } from "./components/PluginsView";
import { SettingsView } from "./components/SettingsView";
import { TopBar } from "./components/TopBar";
import { Wordmark } from "./components/Wordmark";
import i18n from "./i18n";
import { useStore } from "./store";
import type { BackendError, DeviceInfo } from "./types";

export default function App() {
  const { t } = useTranslation();
  const view = useStore((s) => s.view);
  const ready = useStore((s) => s.ready);
  const online = useStore((s) => s.online);
  const language = useStore((s) => s.config?.app.language);

  useEffect(() => {
    void useStore.getState().load();

    // Alles, was das Backend von sich aus meldet, landet hier: Gerät
    // verbunden/getrennt, Seitenwechsel, Plugin-Fehler, Zustände von außen.
    const disconnect = connectEvents(
      (event) => {
        const store = useStore.getState();
        switch (event.type) {
          case "device_state": {
            store.setOnline(true);
            // Nur das Deck übernehmen, das der Editor gerade zeigt — genau
            // wie bei `page_changed` darunter. Ohne diese Prüfung überschrieb
            // jede Meldung eines *anderen* Decks die Ansicht: Man bearbeitete
            // ein 3×2-Overlay, das Stream Deck+ meldete nebenbei seinen
            // Zustand (Verbindung, Helligkeit, Leerlauf-Dimmen), und das
            // Raster sprang auf dessen 4×2 um, während die Eigenschaften
            // rechts beim bearbeiteten Deck blieben. Am 2026-08-22 mit drei
            // Decks gleichzeitig aufgefallen.
            const info = event.data as unknown as DeviceInfo;
            const gemeint = String((info as { id?: string }).id ?? "");
            if (gemeint && gemeint !== store.activeDeck) {
              // Fremdes Deck: Der Zustand gehört trotzdem in die Deckliste,
              // damit Verbindungspunkte und Namen stimmen.
              useStore.setState({
                decks: store.decks.map((deck) =>
                  deck.id === gemeint ? { ...deck, ...info } : deck,
                ),
              });
              break;
            }
            useStore.setState({ device: info });
            break;
          }
          case "page_changed": {
            // Nur das Deck, das der Editor gerade zeigt. Blättert ein
            // anderes weiter — jemand drückt einen Ordner am Gerät, oder
            // ein Overlay wechselt die Seite —, hat das hier nichts zu
            // suchen: Dessen Seiten-ID gibt es im bearbeiteten Profil gar
            // nicht, und die Ansicht stünde vor einer leeren Seite.
            const gemeint = String(event.data.deck ?? "");
            if (gemeint && gemeint !== store.activeDeck) {
              store.bumpPreview();
              break;
            }
            useStore.setState({
              currentPageId: String(event.data.page_id ?? ""),
              selection: null,
            });
            store.bumpPreview();
            break;
          }
          case "config_changed":
            void store.load();
            break;
          case "plugin_error":
            if (event.data.cleared) useStore.setState({ errors: [] });
            else store.pushError(event.data as unknown as BackendError);
            store.bumpPreview();
            break;
          case "plugin_state":
            store.bumpPreview();
            // Verbindungszustand eines Plugins hat sich geändert (OBS
            // gestartet, Discord getrennt) — Statusanzeige nachziehen.
            if (event.data.plugin_id) void store.refreshPlugins();
            break;
          case "install_request":
            // Über streamdeck:// angefragte Installation — wird nur
            // angezeigt, nie automatisch ausgeführt.
            store.addInstallRequest(event.data as never);
            break;
          case "hello":
            store.setOnline(true);
            void store.loadInstallRequests();
            break;
        }
      },
      (isOnline) => {
        useStore.getState().setOnline(isOnline);
        if (isOnline) void useStore.getState().load();
      },
    );
    return disconnect;
  }, []);

  // Sprache folgt der Konfiguration im Backend — damit gilt die Einstellung
  // auch nach einem Neustart der GUI.
  useEffect(() => {
    if (language && i18n.language !== language) void i18n.changeLanguage(language);
  }, [language]);

  if (!ready) {
    return (
      <div className="boot">
        <div className="boot-card">
          <h1><Wordmark /></h1>
          <p>{online ? t("common.loading") : t("device.backendOffline")}</p>
          <code>{t("device.backendOfflineHint")}</code>
        </div>
      </div>
    );
  }

  return (
    <div className="app">
      <TopBar />
      <InstallRequestBanner />
      <ErrorBanner />
      {view === "editor" && (
        <div className="editor">
          <ActionLibrary />
          <main className="stage">
            <PageTree />
            <div className="stage-main">
              <PageCrumbs />
              <DeckGrid />
            </div>
          </main>
          <Inspector />
        </div>
      )}
      {view === "plugins" && <PluginsView />}
      {view === "settings" && <SettingsView />}
    </div>
  );
}
