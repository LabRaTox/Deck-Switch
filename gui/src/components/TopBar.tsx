import { useTranslation } from "react-i18next";

import { api } from "../api/client";
import { useStore } from "../store";
import { Wordmark } from "./Wordmark";

/** Kopfzeile: Ansichtswechsel, Deckauswahl, Gerätestatus und Helligkeit. */
export function TopBar() {
  const { t } = useTranslation();
  const view = useStore((s) => s.view);
  const setView = useStore((s) => s.setView);
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

  return (
    <header className="topbar">
      <div className="topbar-brand">
        <img className="logo" src="/icon.svg" alt="" aria-hidden="true" />
        <Wordmark />
      </div>

      <nav className="topbar-nav">
        {(["editor", "plugins", "settings"] as const).map((entry) => (
          <button
            key={entry}
            type="button"
            className={view === entry ? "nav-tab active" : "nav-tab"}
            onClick={() => setView(entry)}
          >
            {t(`app.${entry}`)}
          </button>
        ))}
      </nav>

      <div className="topbar-right">
        {/* Bei einem einzelnen Deck wäre die Auswahl nur im Weg. */}
        {decks.length > 1 && (
          <div className="deck-switch" role="group" aria-label={t("decks.switch")}>
            {decks.map((deck) => (
              <button
                key={deck.id}
                type="button"
                className={`deck-chip${deck.id === activeDeck ? " active" : ""}${
                  deck.connected ? "" : " offline"
                }`}
                title={
                  deck.connected
                    ? `${deck.deck_type} · ${deck.serial}`
                    : t("decks.notConnected")
                }
                onClick={() => void selectDeck(deck.id)}
              >
                <span className="dot" />
                {deck.name || deck.deck_type}
              </button>
            ))}
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
              // Optimistisch setzen, damit der Regler flüssig bleibt.
              void patchDeckSettings((current) => ({ ...current, brightness: value }));
              void api.setBrightness(value).catch(() => undefined);
            }}
          />
          <output>{virtuell ? "—" : `${brightness}%`}</output>
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
