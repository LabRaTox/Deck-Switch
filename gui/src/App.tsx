import { useEffect } from "react";
import { useTranslation } from "react-i18next";

import { connectEvents } from "./api/client";
import { ActionLibrary } from "./components/ActionLibrary";
import { DeckGrid } from "./components/DeckGrid";
import { ErrorBanner } from "./components/ErrorBanner";
import { Inspector } from "./components/Inspector";
import { InstallRequestBanner } from "./components/PluginInstaller";
import { PageCrumbs, PageTree } from "./components/PageTree";
import { AboutView } from "./components/AboutView";
import { PluginsView } from "./components/PluginsView";
import { SettingsView } from "./components/SettingsView";
import { TopBar } from "./components/TopBar";
import { Wordmark } from "./components/Wordmark";
import i18n from "./i18n";
import { echosVergessen, istEigenesEcho, seitenEcho, slotEcho, useStore } from "./store";
import type { BackendError, DeckInfo, DeviceInfo, PluginInfo } from "./types";

/** Config-Änderungen, bei denen sich an den Plugins nichts ändert. */
const GRUENDE_OHNE_PLUGINS = new Set([
  "slot_changed",
  "brightness",
  "page_created",
  "page_deleted",
  "page_moved",
  "page_updated",
  "profile_changed",
  "profile_created",
  "profile_deleted",
  "profile_switched",
]);

export default function App() {
  const { t } = useTranslation();
  const view = useStore((s) => s.view);
  const ready = useStore((s) => s.ready);
  const online = useStore((s) => s.online);
  const language = useStore((s) => s.config?.app.language);

  useEffect(() => {
    // Den Stand lädt das Öffnen der Ereignisverbindung weiter unten, beim
    // Start wie nach jedem Abriss. Ein zusätzliches Laden hier holte alles
    // doppelt.
    //
    // Einmal beim Start und dann alle fünf Minuten: Eine wartende Einreichung
    // ist nichts, was auf die Sekunde ankommt — aber sie soll auffallen, ohne
    // dass jemand die App neu startet.
    void useStore.getState().refreshStoreKonto();
    const pruefungen = window.setInterval(
      () => void useStore.getState().refreshStoreKonto(),
      5 * 60 * 1000,
    );

    const kachelTakt = new Map<string, number>();
    let verbindung = 0;

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
            // Der Zustand gehört in jedem Fall in die Deckliste, damit
            // Verbindungspunkte und Namen stimmen.
            const decks = gemeint
              ? store.decks.map((deck) => (deck.id === gemeint ? { ...deck, ...info } : deck))
              : store.decks;
            if (gemeint && gemeint !== store.activeDeck) {
              useStore.setState({ decks });
              break;
            }
            useStore.setState({ decks, device: info });
            break;
          }
          case "decks_changed":
            // Deck angesteckt oder vergessen, Overlay per Kurzbefehl
            // umgeschaltet: Das kommt nur hier an, nicht als Config-Änderung.
            if (Array.isArray(event.data.decks)) {
              store.setDecks(event.data.decks as DeckInfo[]);
            }
            break;
          case "deck_state": {
            // Ein Dial-Stack hat am Gerät weitergeschaltet.
            if (String(event.data.deck ?? "") !== store.activeDeck) break;
            const seite = String(event.data.page_id ?? "");
            const dial = Number(event.data.dial);
            if (seite && Number.isInteger(dial)) store.bumpTile(seite, "dial", dial);
            break;
          }
          case "page_changed": {
            // Nur das Deck, das der Editor gerade zeigt. Blättert ein
            // anderes weiter — jemand drückt einen Ordner am Gerät, oder
            // ein Overlay wechselt die Seite —, hat das hier nichts zu
            // suchen: Dessen Seiten-ID gibt es im bearbeiteten Profil gar
            // nicht, und die Ansicht stünde vor einer leeren Seite.
            const gemeint = String(event.data.deck ?? "");
            if (gemeint && gemeint !== store.activeDeck) break;
            useStore.setState({
              currentPageId: String(event.data.page_id ?? ""),
              selection: null,
            });
            store.bumpPreview();
            break;
          }
          case "config_changed": {
            // Die eigenen Änderungen meldet das Backend auch zurück. Die
            // stehen lokal schon, ein Neuladen brächte nur Last und könnte
            // überschreiben, was gerade getippt wird.
            const grund = String(event.data.reason ?? "");
            const seite = String(event.data.page_id ?? "");
            if (
              grund === "slot_changed" &&
              istEigenesEcho(
                slotEcho(
                  String(event.data.deck ?? ""),
                  seite,
                  String(event.data.input_type ?? ""),
                  Number(event.data.index),
                ),
              )
            ) {
              break;
            }
            if (grund === "page_updated" && istEigenesEcho(seitenEcho(seite))) break;
            // Nur was die Plugins selbst betrifft, braucht deren Liste neu.
            store.ladeBald(!GRUENDE_OHNE_PLUGINS.has(grund));
            break;
          }
          case "plugin_error":
            if (event.data.cleared) useStore.setState({ errors: [] });
            else store.pushError(event.data as unknown as BackendError);
            store.bumpPreview();
            break;
          case "plugin_state": {
            // Ein Plugin meldet einen neuen Zustand (OBS gestartet, Discord
            // getrennt, Lautstärke von außen geändert). Neu gezeichnet werden
            // nur die Kacheln, die es benutzen. Bringt die Meldung einen
            // Status mit, wird nur dieser übernommen.
            const pluginId = String(event.data.plugin_id ?? "");
            if (!pluginId) break;
            // Beim Ziehen eines Lautstärkereglers kommen Dutzende Meldungen
            // in der Sekunde. Gesammelt wird je Plugin eine Auffrischung.
            if (!kachelTakt.has(pluginId)) {
              kachelTakt.set(
                pluginId,
                window.setTimeout(() => {
                  kachelTakt.delete(pluginId);
                  useStore.getState().bumpPluginTiles(pluginId);
                }, 150),
              );
            }
            if ("status" in event.data) {
              store.setPluginStatus(pluginId, event.data.status as PluginInfo["status"]);
            }
            break;
          }
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
        if (isOnline) {
          // Was vor dem Abriss unterwegs war, wird nie mehr gemeldet.
          echosVergessen();
          // Geladen wird, bis ein Laden gelingt. Gezählt wird der Erfolg,
          // nicht das eigene Versprechen: Ein Laden kann auch von einem
          // späteren verdrängt werden, das dann scheitert. Eine neue
          // Verbindung beendet die Versuche der alten.
          const meine = ++verbindung;
          const seit = Date.now();
          const versuche = (abstand: number) => {
            void useStore
              .getState()
              .load()
              .catch(() => undefined)
              .finally(() => {
                const s = useStore.getState();
                if (meine !== verbindung || !s.online || s.zuletztGeladen >= seit) return;
                window.setTimeout(() => versuche(Math.min(abstand * 2, 15000)), abstand);
              });
          };
          versuche(2000);
        }
      },
    );
    return () => {
      window.clearInterval(pruefungen);
      kachelTakt.forEach((zeitgeber) => window.clearTimeout(zeitgeber));
      disconnect();
    };
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
          {!online && <code>{t("device.backendOfflineHint")}</code>}
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
      {view === "about" && <AboutView />}
    </div>
  );
}
