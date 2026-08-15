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
          case "device_state":
            store.setOnline(true);
            useStore.setState({ device: event.data as unknown as DeviceInfo });
            break;
          case "page_changed":
            useStore.setState({
              currentPageId: String(event.data.page_id ?? ""),
              selection: null,
            });
            store.bumpPreview();
            break;
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
