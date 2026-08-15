import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { api } from "../api/client";
import { SUPPORTED_LANGUAGES } from "../i18n";
import { useStore } from "../store";
import { ScreensaverCard } from "./ScreensaverCard";
import type { AutostartStatus } from "../types";

/** App- und Geräteeinstellungen sowie Export/Import der Belegung. */
export function SettingsView() {
  const { t } = useTranslation();
  const config = useStore((s) => s.config);
  const patchConfig = useStore((s) => s.patchConfig);
  const load = useStore((s) => s.load);

  const [sets, setSets] = useState<{ id: string; name: string; count: number }[]>([]);
  const [importMerge, setImportMerge] = useState(false);
  const [message, setMessage] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    api.iconSets().then(setSets).catch(() => undefined);
  }, []);

  if (!config) return null;

  const importFile = async (file: File) => {
    try {
      const payload = JSON.parse(await file.text());
      if (!importMerge && !window.confirm(t("settings.importConfirm"))) return;
      await api.importConfig(payload, importMerge);
      await load();
      setMessage({ kind: "ok", text: t("settings.importDone") });
    } catch (error) {
      setMessage({
        kind: "error",
        text: t("settings.importFailed", {
          error: error instanceof Error ? error.message : String(error),
        }),
      });
    }
  };

  return (
    <div className="page-view">
      <div className="page-head">
        <h2>{t("settings.title")}</h2>
      </div>

      <section className="settings-card">
        <h3>{t("settings.general")}</h3>

        <div className="field">
          <label htmlFor="language">{t("settings.language")}</label>
          <select
            id="language"
            value={config.app.language}
            onChange={(event) =>
              void patchConfig((draft) => {
                draft.app.language = event.target.value as "de" | "en";
                return draft;
              })
            }
          >
            {SUPPORTED_LANGUAGES.map((language) => (
              <option key={language} value={language}>
                {t(`settings.languages.${language}`)}
              </option>
            ))}
          </select>
        </div>

        <div className="field">
          <label htmlFor="iconset">{t("settings.iconset")}</label>
          <select
            id="iconset"
            value={config.app.active_iconset}
            onChange={(event) =>
              void patchConfig((draft) => {
                draft.app.active_iconset = event.target.value;
                return draft;
              })
            }
          >
            {sets.map((entry) => (
              <option key={entry.id} value={entry.id}>
                {entry.name} ({entry.count})
              </option>
            ))}
          </select>
        </div>

        <AutostartField />
      </section>

      <section className="settings-card">
        <h3>{t("settings.device")}</h3>

        <NumberField
          label={`${t("settings.brightness")} (%)`}
          value={config.device.brightness}
          min={5}
          max={100}
          onChange={(value) => {
            void patchConfig((draft) => {
              draft.device.brightness = value;
              return draft;
            });
            void api.setBrightness(value).catch(() => undefined);
          }}
        />

        <NumberField
          label={`${t("settings.idleDim")} (${t("settings.seconds")})`}
          help={t("settings.idleDimHint")}
          value={config.device.idle_dim_after_s}
          min={0}
          max={7200}
          onChange={(value) =>
            void patchConfig((draft) => {
              draft.device.idle_dim_after_s = value;
              return draft;
            })
          }
        />

        <NumberField
          label={`${t("settings.idleBrightness")} (%)`}
          value={config.device.idle_brightness}
          min={0}
          max={100}
          onChange={(value) =>
            void patchConfig((draft) => {
              draft.device.idle_brightness = value;
              return draft;
            })
          }
        />

        <NumberField
          label={`${t("settings.longPressMs")} (${t("settings.milliseconds")})`}
          value={config.device.long_press_ms}
          min={150}
          max={3000}
          step={50}
          onChange={(value) =>
            void patchConfig((draft) => {
              draft.device.long_press_ms = value;
              return draft;
            })
          }
        />

        <NumberField
          label={`${t("settings.tickInterval")} (${t("settings.seconds")})`}
          value={config.device.tick_interval_s}
          min={0.2}
          max={10}
          step={0.1}
          onChange={(value) =>
            void patchConfig((draft) => {
              draft.device.tick_interval_s = value;
              return draft;
            })
          }
        />
      </section>

      <ScreensaverCard />

      <section className="settings-card">
        <h3>{t("settings.touchstrip")}</h3>

        <label className="checkbox">
          <input
            type="checkbox"
            checked={config.device.swipe_switches_page}
            onChange={(event) =>
              void patchConfig((draft) => {
                draft.device.swipe_switches_page = event.target.checked;
                return draft;
              })
            }
          />
          <span>{t("settings.swipeSwitchesPage")}</span>
        </label>
        <small className="help">{t("settings.swipeHint")}</small>

        {config.device.swipe_switches_page && (
          <>
            <NumberField
              label={`${t("settings.swipeDistance")} (${t("settings.pixels")})`}
              value={config.device.swipe_min_distance}
              min={20}
              max={400}
              step={10}
              onChange={(value) =>
                void patchConfig((draft) => {
                  draft.device.swipe_min_distance = value;
                  return draft;
                })
              }
            />

            <label className="checkbox">
              <input
                type="checkbox"
                checked={config.device.swipe_wraps}
                onChange={(event) =>
                  void patchConfig((draft) => {
                    draft.device.swipe_wraps = event.target.checked;
                    return draft;
                  })
                }
              />
              <span>{t("settings.swipeWraps")}</span>
            </label>
          </>
        )}
      </section>

      <section className="settings-card">
        <h3>{t("settings.backup")}</h3>

        <div className="row">
          <a className="btn" href={api.exportUrl()} download="streamdeck-config.json">
            {t("settings.export")}
          </a>
          <button type="button" className="btn" onClick={() => fileInput.current?.click()}>
            {t("settings.import")}
          </button>
          <input
            ref={fileInput}
            type="file"
            accept="application/json,.json"
            hidden
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (file) void importFile(file);
              event.target.value = "";
            }}
          />
        </div>
        <small className="help">{t("settings.exportHint")}</small>

        <label className="checkbox">
          <input
            type="checkbox"
            checked={importMerge}
            onChange={(event) => setImportMerge(event.target.checked)}
          />
          <span>{t("settings.importMerge")}</span>
        </label>

        {message && (
          <p className={message.kind === "ok" ? "saved-hint" : "error-text"}>
            {message.text}
          </p>
        )}
      </section>
    </div>
  );
}

/**
 * Schalter für den systemd-User-Dienst.
 *
 * Der Zustand kommt vom Backend, nicht aus der Config — maßgeblich ist, was
 * ``systemctl --user is-enabled`` sagt. Sonst würde die GUI „an“ anzeigen,
 * während der Dienst längst per Kommandozeile abgeschaltet wurde.
 */
function AutostartField() {
  const { t } = useTranslation();
  const [status, setStatus] = useState<AutostartStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.autostart().then(setStatus).catch(() => undefined);
  }, []);

  // Solange der Zustand unbekannt ist, gar nichts zeigen — ein Schalter, der
  // kurz auf „aus“ steht und dann springt, sieht nach einem Fehler aus.
  if (!status) return null;

  const toggle = async (enabled: boolean) => {
    setBusy(true);
    setError(null);
    try {
      setStatus(await api.setAutostart(enabled));
    } catch (cause) {
      setError(
        t("settings.autostartFailed", {
          error: cause instanceof Error ? cause.message : String(cause),
        }),
      );
      // Zurück auf den tatsächlichen Zustand — der Wunsch ist nicht die Lage.
      await api.autostart().then(setStatus).catch(() => undefined);
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <label className="checkbox">
        <input
          type="checkbox"
          checked={status.enabled}
          disabled={!status.supported || busy}
          onChange={(event) => void toggle(event.target.checked)}
        />
        <span>{t("settings.autostart")}</span>
      </label>
      <small className="help">
        {status.supported
          ? t("settings.autostartHint")
          : t("settings.autostartUnavailable", { reason: status.reason })}
      </small>
      {error && <p className="error-text">{error}</p>}
    </>
  );
}

function NumberField({
  label,
  value,
  min,
  max,
  step = 1,
  help,
  onChange,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step?: number;
  help?: string;
  onChange: (value: number) => void;
}) {
  return (
    <div className="field">
      <label>{label}</label>
      <input
        type="number"
        value={value}
        min={min}
        max={max}
        step={step}
        onChange={(event) => {
          const next = Number(event.target.value);
          if (!Number.isNaN(next)) onChange(Math.min(max, Math.max(min, next)));
        }}
      />
      {help && <small className="help">{help}</small>}
    </div>
  );
}
