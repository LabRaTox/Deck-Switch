import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { api } from "../api/client";
import { localized } from "../i18n";
import { useStore } from "../store";
import type { ScreensaverEntry } from "../types";

/**
 * Bildschirmschoner-Einstellungen.
 *
 * Bewusst kein Plugin und keine Aktion: Ein Schoner gehört keiner Taste,
 * sondern dem ganzen Gerät. Die Auswahl mischt hochgeladene Bilder und
 * Schoner-Plugins in einer Liste — für den Benutzer ist das dasselbe.
 */
export function ScreensaverCard() {
  const { t, i18n } = useTranslation();
  const config = useStore((s) => s.config);
  const patchConfig = useStore((s) => s.patchConfig);

  const [entries, setEntries] = useState<ScreensaverEntry[]>([]);
  const [message, setMessage] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);

  const load = () => api.screensavers().then(setEntries).catch(() => undefined);
  useEffect(() => {
    void load();
  }, []);

  if (!config) return null;
  const saver = config.device.screensaver;

  const patchSaver = (change: Partial<typeof saver>) =>
    patchConfig((draft) => {
      draft.device.screensaver = { ...draft.device.screensaver, ...change };
      return draft;
    });

  const upload = async (file: File) => {
    setBusy(true);
    setMessage(null);
    try {
      const { filename } = await api.upload(file);
      await load();
      // Frisch Hochgeladenes gleich auswählen — alles andere wäre ein
      // zweiter Handgriff für etwas, das ohnehin gemeint war.
      await patchSaver({ source: `upload:${filename}`, enabled: true });
      setMessage({ kind: "ok", text: t("screensaver.uploaded") });
    } catch (error) {
      setMessage({
        kind: "error",
        text: t("screensaver.uploadFailed", {
          error: error instanceof Error ? error.message : String(error),
        }),
      });
    } finally {
      setBusy(false);
    }
  };

  const selected = entries.find((entry) => entry.source === saver.source);

  return (
    <section className="settings-card">
      <h3>{t("screensaver.title")}</h3>

      <label className="checkbox">
        <input
          type="checkbox"
          checked={saver.enabled}
          onChange={(event) => void patchSaver({ enabled: event.target.checked })}
        />
        <span>{t("screensaver.enable")}</span>
      </label>
      <small className="help">{t("screensaver.hint")}</small>

      {saver.enabled && (
        <>
          <div className="field">
            <label htmlFor="screensaver-source">{t("screensaver.source")}</label>
            <select
              id="screensaver-source"
              value={saver.source}
              onChange={(event) => void patchSaver({ source: event.target.value })}
            >
              <option value="">{t("screensaver.none")}</option>
              {entries.map((entry) => (
                <option key={entry.source} value={entry.source}>
                  {localized(entry.name, i18n.language)}
                  {entry.kind === "plugin" ? ` (${t("screensaver.fromPlugin")})` : ""}
                  {entry.animated ? " ●" : ""}
                </option>
              ))}
            </select>
          </div>

          <div className="row">
            <button
              type="button"
              className="btn"
              disabled={busy}
              onClick={() => fileInput.current?.click()}
            >
              {t("screensaver.upload")}
            </button>
            <input
              ref={fileInput}
              type="file"
              accept="image/png,image/jpeg,image/gif,image/webp,image/bmp"
              hidden
              onChange={(event) => {
                const file = event.target.files?.[0];
                if (file) void upload(file);
                event.target.value = "";
              }}
            />
            <button
              type="button"
              className="btn"
              disabled={!saver.source}
              onClick={() =>
                void api
                  .testScreensaver()
                  .then(() => setMessage({ kind: "ok", text: t("screensaver.testing") }))
                  .catch((error) =>
                    setMessage({
                      kind: "error",
                      text: error instanceof Error ? error.message : String(error),
                    }),
                  )
              }
            >
              {t("screensaver.test")}
            </button>
          </div>

          {selected && (
            <div className="screensaver-preview">
              <img
                src={api.screensaverPreviewUrl(selected.source)}
                alt={t("screensaver.previewAlt")}
              />
              <small className="help">{t("screensaver.previewHint")}</small>
            </div>
          )}

          <div className="field">
            <label htmlFor="screensaver-fit">{t("screensaver.fit")}</label>
            <select
              id="screensaver-fit"
              value={saver.fit}
              onChange={(event) =>
                void patchSaver({ fit: event.target.value as "cover" | "contain" })
              }
            >
              <option value="cover">{t("screensaver.fitCover")}</option>
              <option value="contain">{t("screensaver.fitContain")}</option>
            </select>
          </div>

          <NumberField
            label={`${t("screensaver.after")} (${t("settings.seconds")})`}
            help={t("screensaver.afterHint")}
            value={saver.after_s}
            min={10}
            max={7200}
            step={10}
            onChange={(value) => void patchSaver({ after_s: value })}
          />

          <NumberField
            label={`${t("screensaver.brightness")} (%)`}
            value={saver.brightness}
            min={0}
            max={100}
            onChange={(value) => void patchSaver({ brightness: value })}
          />
        </>
      )}

      {message && (
        <p className={message.kind === "ok" ? "saved-hint" : "error-text"}>{message.text}</p>
      )}
    </section>
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
