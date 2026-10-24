import { useTranslation } from "react-i18next";

import { api } from "../api/client";
import { useStore } from "../store";
import type { DeckInfo } from "../types";
import { Wordmark } from "./Wordmark";

/** Kopfzeile: Ansichtswechsel, Deckauswahl, Gerätestatus und Helligkeit. */
export function TopBar() {
  const { t } = useTranslation();
  const view = useStore((s) => s.view);
  const setView = useStore((s) => s.setView);
  const storeKonto = useStore((s) => s.storeKonto);
  const device = useStore((s) => s.device);
  const decks = useStore((s) => s.decks);
  const activeDeck = useStore((s) => s.activeDeck);
  const selectDeck = useStore((s) => s.selectDeck);
  const online = useStore((s) => s.online);
  const settings = useStore((s) => s.deckSettings());
  const patchDeckSettings = useStore((s) => s.patchDeckSettings);

  const connected = Boolean(device?.connected);
  const brightness = settings?.brightness ?? 70;
  // Über die Deckliste und nicht über ``device``: Dort steht die Bauart.
  // Weder ein Overlay noch ein Netz-Deck hat eine Hintergrundbeleuchtung —
  // der Regler hätte nichts zu regeln, und ein wirkungsloses Bedienelement
  // ist schlimmer als keins.
  const bauart = decks.find((deck) => deck.id === activeDeck)?.kind;
  const virtuell = bauart === "virtual" || bauart === "network";

  // Decks je Bauart bündeln, in der Reihenfolge, in der sie schon sortiert
  // sind. Eine Art mit einem Deck bleibt ein griffiger Schalter, eine mit
  // mehreren wird zum Dropdown — sonst füllt die Kopfzeile sich mit der
  // Zahl der Decks statt mit Nutzen.
  const arten: { kind: DeckInfo["kind"]; label: string; decks: DeckInfo[] }[] = [];
  for (const deck of decks) {
    let art = arten.find((einzelne) => einzelne.kind === deck.kind);
    if (!art) {
      art = { kind: deck.kind, label: t(`decks.group_${deck.kind}`), decks: [] };
      arten.push(art);
    }
    art.decks.push(deck);
  }

  return (
    <header className="topbar">
      <div className="topbar-brand">
        <img className="logo" src="/icon.svg" alt="" aria-hidden="true" />
        <Wordmark />
      </div>

      <nav className="topbar-nav">
        {(["editor", "plugins", "settings"] as const).map((entry) => {
          // Die Zahl am Reiter „Plugins": offene Einreichungen und Meldungen
          // im Store. Sie steht nur, wenn der Angemeldete prüfen darf — für
          // alle anderen ist das nichts, was sie angeht.
          const offen =
            entry === "plugins" && storeKonto?.pending
              ? storeKonto.pending.submissions + storeKonto.pending.reports
              : 0;
          return (
            <button
              key={entry}
              type="button"
              className={view === entry ? "nav-tab active" : "nav-tab"}
              onClick={() => setView(entry)}
            >
              {t(`app.${entry}`)}
              {offen > 0 && (
                <span className="nav-tab-zahl" title={t("store.pendingBadge")}>
                  {offen}
                </span>
              )}
            </button>
          );
        })}
      </nav>

      <div className="topbar-right">
        {/* Bei einem einzelnen Deck wäre die Auswahl nur im Weg. */}
        {decks.length > 1 && (
          <div className="deck-switch" role="group" aria-label={t("decks.switch")}>
            {arten.map((art) =>
              art.decks.length === 1 ? (
                <button
                  key={art.decks[0].id}
                  type="button"
                  className={`deck-chip${art.decks[0].id === activeDeck ? " active" : ""}${
                    art.decks[0].connected ? "" : " offline"
                  }`}
                  title={
                    art.decks[0].connected
                      ? `${art.decks[0].deck_type} · ${art.decks[0].serial}`
                      : t("decks.notConnected")
                  }
                  onClick={() => void selectDeck(art.decks[0].id)}
                >
                  <span className="dot" />
                  {art.decks[0].name || art.decks[0].deck_type}
                </button>
              ) : (
                // Mehrere einer Art: Die Auswahl zeigt das aktive Deck, oder
                // den Namen der Art, wenn gerade ein anderes aktiv ist.
                (() => {
                  const aktiv = art.decks.find((deck) => deck.id === activeDeck);
                  // Grau nur, wenn das Gezeigte nicht verbunden ist: das aktive
                  // Deck, oder ohne aktives jedes Deck der Art.
                  const offline = aktiv
                    ? !aktiv.connected
                    : art.decks.every((deck) => !deck.connected);
                  return (
                    <div
                      key={art.kind}
                      className={`deck-chip deck-select${aktiv ? " active" : ""}${
                        offline ? " offline" : ""
                      }`}
                      title={art.label}
                    >
                      <span className="dot" />
                      <select
                        value={aktiv ? activeDeck : ""}
                        aria-label={art.label}
                        onChange={(event) => {
                          if (event.target.value) void selectDeck(event.target.value);
                        }}
                      >
                        <option value="" disabled>
                          {art.label}
                        </option>
                        {art.decks.map((deck) => (
                          <option key={deck.id} value={deck.id}>
                            {deck.name || deck.deck_type}
                            {deck.connected ? "" : ` · ${t("decks.notConnected")}`}
                          </option>
                        ))}
                      </select>
                    </div>
                  );
                })()
              ),
            )}
          </div>
        )}

        <label
          className={virtuell ? "brightness disabled" : "brightness"}
          title={virtuell ? t("device.brightnessVirtual") : t("device.brightness")}
        >
          <span aria-hidden="true">☀</span>
          <input
            type="range"
            min={5}
            max={100}
            value={brightness}
            disabled={!connected || virtuell}
            onChange={(event) => {
              const value = Number(event.target.value);
              // Optimistisch setzen, damit der Regler flüssig bleibt. Die
              // Schreibspur bündelt das Ziehen; das Deck übernimmt die
              // Helligkeit mit den Geräteeinstellungen.
              void patchDeckSettings((current) => ({ ...current, brightness: value }));
            }}
          />
          <output>{virtuell ? "---" : `${brightness}%`}</output>
        </label>

        <div
          className={connected ? "device-status ok" : "device-status bad"}
          title={device?.error ?? ""}
        >
          <span className="dot" />
          <div className="device-text">
            <strong>
              {!online
                ? t("device.backendOffline")
                : connected
                  ? device?.deck_type || t("device.connected")
                  : t("device.searching")}
            </strong>
            {connected && device && (
              <small>
                {t("device.serial")}: {device.serial} · {t("device.firmware")}:{" "}
                {device.firmware}
                {device.dimmed ? ` · ${t("device.dimmed")}` : ""}
              </small>
            )}
            {!connected && device?.error && <small>{device.error}</small>}
          </div>
        </div>

        {!connected && online && (
          <button
            type="button"
            className="btn"
            onClick={() => void api.reconnect().catch(() => undefined)}
          >
            {t("device.reconnect")}
          </button>
        )}
      </div>
    </header>
  );
}
