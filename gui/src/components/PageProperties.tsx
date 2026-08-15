import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { api } from "../api/client";
import { localized } from "../i18n";
import { useStore } from "../store";
import type { WallpaperEntry } from "../types";

/**
 * Eigenschaften der aktuellen Seite — sichtbar, solange keine Taste
 * ausgewählt ist.
 *
 * Bisher steht hier nur das Hintergrundbild des Touchstrips. Es gehört
 * bewusst zur Seite und nicht zum Gerät: Wer eine Ordnerseite für OBS und
 * eine für Discord hat, will die auch auseinanderhalten können.
 */
export function PageProperties() {
  const { t, i18n } = useTranslation();
  const page = useStore((s) => s.currentPage());
  const patchConfig = useStore((s) => s.patchConfig);

  const [entries, setEntries] = useState<WallpaperEntry[]>([]);
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);

  const load = () => api.wallpapers().then(setEntries).catch(() => undefined);
  useEffect(() => {
    void load();
  }, []);

  if (!page) return null;
  const paper = page.touch_wallpaper;

  const patchPaper = (change: Partial<typeof paper>) =>
    patchConfig((draft) => {
      const target = draft.profiles[draft.active_profile_id]?.pages[page.id];
      if (target) {
        target.touch_wallpaper = { ...target.touch_wallpaper, ...change };
      }
      return draft;
    });

  const upload = async (file: File) => {
    setBusy(true);
    setMessage(null);
    try {
      const { filename } = await api.upload(file, "wallpaper");
      await load();
      await patchPaper({ source: `upload:${filename}`, enabled: true });
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <p className="hint">{t("inspector.pageHint", { name: page.name })}</p>

      <h3 className="section-title">{t("wallpaper.title")}</h3>

      <label className="checkbox">
        <input
          type="checkbox"
          checked={paper.enabled}
          onChange={(event) => void patchPaper({ enabled: event.target.checked })}
        />
        <span>{t("wallpaper.enable")}</span>
      </label>
      <small className="help">{t("wallpaper.hint")}</small>

      {paper.enabled && (
        <>
          <div className="field">
            <label htmlFor="page-wallpaper">{t("wallpaper.source")}</label>
            <select
              id="page-wallpaper"
              value={paper.source}
              onChange={(event) => void patchPaper({ source: event.target.value })}
            >
              <option value="">{t("wallpaper.none")}</option>
              {entries.map((entry) => (
                <option key={entry.source} value={entry.source}>
                  {localized(entry.name, i18n.language)}
                  {entry.kind === "plugin" ? ` (${t("wallpaper.fromPlugin")})` : ""}
                </option>
              ))}
            </select>
          </div>

          {paper.source && (
            <div className="wallpaper-preview">
              <img
                src={api.wallpaperPreviewUrl(paper.source, paper.fit, paper.opacity)}
                alt={t("wallpaper.previewAlt")}
              />
              <small className="help">{t("wallpaper.previewHint")}</small>
            </div>
          )}

          <div className="row">
            <button
              type="button"
              className="btn small"
              disabled={busy}
              onClick={() => fileInput.current?.click()}
            >
              {t("wallpaper.upload")}
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
          </div>

          <div className="field">
            <label htmlFor="page-wallpaper-fit">{t("wallpaper.fit")}</label>
            <select
              id="page-wallpaper-fit"
              value={paper.fit}
              onChange={(event) =>
                void patchPaper({ fit: event.target.value as "cover" | "contain" })
              }
            >
              <option value="cover">{t("wallpaper.fitCover")}</option>
              <option value="contain">{t("wallpaper.fitContain")}</option>
            </select>
            <small className="help">{t("wallpaper.sizeHint")}</small>
          </div>

          <div className="field">
            <label htmlFor="page-wallpaper-opacity">{t("wallpaper.opacity")} (%)</label>
            <input
              id="page-wallpaper-opacity"
              type="number"
              value={paper.opacity}
              min={5}
              max={100}
              step={5}
              onChange={(event) => {
                const next = Number(event.target.value);
                if (!Number.isNaN(next)) {
                  void patchPaper({ opacity: Math.min(100, Math.max(5, next)) });
                }
              }}
            />
            <small className="help">{t("wallpaper.opacityHint")}</small>
          </div>

          <p className="help">{t("wallpaper.slotHint")}</p>
        </>
      )}

      {message && <p className="error-text">{message}</p>}
    </>
  );
}
