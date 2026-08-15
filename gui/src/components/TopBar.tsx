import { useTranslation } from "react-i18next";

import { api } from "../api/client";
import { useStore } from "../store";
import { Wordmark } from "./Wordmark";

/** Kopfzeile: Ansichtswechsel, Gerätestatus und Helligkeit. */
export function TopBar() {
  const { t } = useTranslation();
  const view = useStore((s) => s.view);
  const setView = useStore((s) => s.setView);
  const device = useStore((s) => s.device);
  const online = useStore((s) => s.online);
  const brightness = useStore((s) => s.config?.device.brightness ?? 70);
  const patchConfig = useStore((s) => s.patchConfig);

  const connected = Boolean(device?.connected);

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
        <label className="brightness" title={t("device.brightness")}>
          <span aria-hidden="true">☀</span>
          <input
            type="range"
            min={5}
            max={100}
            value={brightness}
            disabled={!connected}
            onChange={(event) => {
              const value = Number(event.target.value);
              // Optimistisch setzen, damit der Regler flüssig bleibt.
              void patchConfig((config) => {
                config.device.brightness = value;
                return config;
              });
              void api.setBrightness(value).catch(() => undefined);
            }}
          />
          <output>{brightness}%</output>
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
