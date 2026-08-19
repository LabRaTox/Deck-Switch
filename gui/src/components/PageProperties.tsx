import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { api } from "../api/client";
import { localized } from "../i18n";
import { useStore } from "../store";
import type { DeckInfo, WallpaperEntry } from "../types";
import { HotkeyInput } from "./HotkeyInput";

/**
 * Eigenschaften der aktuellen Seite — sichtbar, solange keine Taste
 * ausgewählt ist.
 *
 * Hier steht, was nicht an einer einzelnen Taste hängt: das Hintergrundbild
 * des Touchstrips (das gehört bewusst zur *Seite* — wer eine Ordnerseite für
 * OBS und eine für Discord hat, will die auseinanderhalten können) und, bei
 * einem virtuellen Deck, dessen Raster. Letzteres steht hier und nicht in
 * den Einstellungen, weil man beim Bauen des Rasters das Deck davor sehen
 * will.
 */
export function PageProperties() {
  const { t, i18n } = useTranslation();
  const page = useStore((s) => s.currentPage());
  const deck = useStore((s) => s.activeDeckInfo());
  const patchTouchWallpaper = useStore((s) => s.patchTouchWallpaper);

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

  // Gezielt diese eine Seite ändern statt die ganze Config zurückzuschicken:
  // Deren Stand wäre womöglich älter als das, was inzwischen am Gerät
  // passiert ist.
  const patchPaper = (change: Partial<typeof paper>) =>
    patchTouchWallpaper(page.id, change);

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

      <VirtualDeckSection />

      {/* Ein Overlay hat keinen durchgehenden Touchstrip — dort wäre
          ein Streifenbild eine Einstellung ohne Wirkung. */}
      {deck?.kind === "hardware" && (
        <>
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
      )}
    </>
  );
}


/**
 * Raster und Overlay des virtuellen Decks — nur sichtbar, wenn das
 * bearbeitete Deck auch eines ist.
 *
 * Die Werte wirken sofort: Das Backend vermisst das Gerät neu und zeichnet
 * alles, ein laufendes Overlay zieht binnen eines Augenblicks nach.
 */
function VirtualDeckSection() {
  const { t } = useTranslation();
  const deck = useStore((s) => s.activeDeckInfo());
  const setGrid = useStore((s) => s.setDeckGrid);
  const toggleOverlay = useStore((s) => s.toggleOverlay);

  // Raster und Kachelgröße gelten für jedes Deck ohne Gehäuse — ob es auf
  // dem eigenen Bildschirm liegt oder im Browser eines anderen Rechners,
  // ändert daran nichts.
  const ohneGeraet = deck?.kind === "virtual" || deck?.kind === "network";
  if (!deck || !ohneGeraet) return null;
  const istOverlay = deck.kind === "virtual";

  const felder = [
    { schluessel: "columns" as const, label: t("decks.columns"), min: 1, max: 16, wert: deck.columns },
    { schluessel: "rows" as const, label: t("decks.rows"), min: 1, max: 8, wert: deck.rows },
    { schluessel: "dials" as const, label: t("decks.dials"), min: 0, max: 8, wert: deck.dials },
  ];

  return (
    <>
      <h3 className="section-title">
        {istOverlay ? t("decks.virtualSection") : t("decks.networkSection")}
      </h3>
      <p className="hint">{istOverlay ? t("decks.virtualHint") : t("decks.networkHint")}</p>

      <div className="field-row">
        {felder.map((feld) => (
          <div className="field" key={feld.schluessel}>
            <label htmlFor={`grid-${feld.schluessel}`}>{feld.label}</label>
            <input
              id={`grid-${feld.schluessel}`}
              type="number"
              min={feld.min}
              max={feld.max}
              value={feld.wert}
              onChange={(event) =>
                void setGrid(deck.id, { [feld.schluessel]: Number(event.target.value) })
              }
            />
          </div>
        ))}
      </div>

      {/* Stufenlos: Die Kachelgröße ist eine Frage des Augenmaßes, keine
          von Rasterschritten — man zieht, bis es passt. */}
      <div className="field">
        <label htmlFor="grid-tile_size">
          {t("decks.tileSize")} ({deck.tile_size} px)
        </label>
        <div className="slider-row">
          <input
            id="grid-tile_size"
            type="range"
            min={48}
            max={256}
            step={1}
            value={deck.tile_size}
            onChange={(event) =>
              void setGrid(deck.id, { tile_size: Number(event.target.value) })
            }
          />
          <input
            type="number"
            min={48}
            max={256}
            value={deck.tile_size}
            onChange={(event) =>
              void setGrid(deck.id, { tile_size: Number(event.target.value) })
            }
          />
        </div>
      </div>

      {istOverlay && (
      <>
      <label className="checkbox">
        <input
          type="checkbox"
          checked={deck.overlay_transparent ?? false}
          onChange={(event) =>
            void setGrid(deck.id, { overlay_transparent: event.target.checked })
          }
        />
        <span>{t("decks.transparent")}</span>
      </label>
      <small className="help">{t("decks.transparentHint")}</small>

      <label className="checkbox">
        <input
          type="checkbox"
          checked={deck.hide_empty ?? false}
          onChange={(event) => void setGrid(deck.id, { hide_empty: event.target.checked })}
        />
        <span>{t("decks.hideEmpty")}</span>
      </label>
      <small className="help">{t("decks.hideEmptyHint")}</small>

      {/* Ein Deck ohne Gehäuse hat keinen Griff: Wer nur ein virtuelles
          Deck hat, käme sonst nur über die Oberfläche daran. */}
      <div className="field">
        <label htmlFor="overlay-hotkey">{t("decks.hotkey")}</label>
        <HotkeyInput
          id="overlay-hotkey"
          value={deck.overlay_hotkey ?? ""}
          placeholder="Strg+Alt+D"
          warning={deck.hotkey_reason || null}
          onChange={(wert) => void setGrid(deck.id, { overlay_hotkey: wert })}
        />
        <small className="help">{t("decks.hotkeyHint")}</small>
      </div>

      <div className="row">
        <button
          type="button"
          className={deck.overlay_visible ? "btn primary" : "btn"}
          disabled={deck.overlay_available === false}
          title={deck.overlay_reason || ""}
          onClick={() => void toggleOverlay(deck.id, null)}
        >
          {deck.overlay_visible ? t("decks.overlayHide") : t("decks.overlayShow")}
        </button>
      </div>
      {deck.overlay_available === false && (
        <small className="help error-text">{deck.overlay_reason}</small>
      )}
      </>
      )}

      {!istOverlay && <NetzZugang deck={deck} />}
    </>
  );
}

/**
 * Zugang zu einem Netz-Deck: Passwort, Schalter, Adresse.
 *
 * Ohne Passwort wird das Deck gar nicht erst angeboten — das steht hier
 * deutlich, denn es ist der Unterschied zwischen „nur ich" und „jeder im
 * Netz".
 */
function NetzZugang({ deck }: { deck: DeckInfo }) {
  const { t } = useTranslation();
  const setPassword = useStore((s) => s.setDeckPassword);
  const setGrid = useStore((s) => s.setDeckGrid);
  const [eingabe, setEingabe] = useState("");
  const [busy, setBusy] = useState(false);

  const speichern = async (wert: string) => {
    setBusy(true);
    try {
      await setPassword(deck.id, wert);
      setEingabe("");
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <h3 className="section-title">{t("decks.networkAccess")}</h3>

      <div className="field">
        <label htmlFor="net-password">{t("decks.password")}</label>
        <div className="slider-row">
          <input
            id="net-password"
            type="password"
            autoComplete="new-password"
            placeholder={deck.has_password ? t("decks.passwordSet") : t("decks.passwordNone")}
            value={eingabe}
            onChange={(event) => setEingabe(event.target.value)}
          />
          <button
            type="button"
            className="btn"
            disabled={busy || eingabe.length < 4}
            onClick={() => void speichern(eingabe)}
          >
            {t("decks.passwordSave")}
          </button>
        </div>
      </div>
      <small className="help">{t("decks.passwordHint")}</small>

      {deck.has_password && (
        <div className="row">
          <button
            type="button"
            className="btn small danger"
            disabled={busy}
            onClick={() => {
              if (window.confirm(t("decks.passwordClearConfirm"))) void speichern("");
            }}
          >
            {t("decks.passwordClear")}
          </button>
        </div>
      )}

      <label className="checkbox">
        <input
          type="checkbox"
          checked={deck.network_enabled ?? false}
          disabled={!deck.has_password}
          onChange={(event) =>
            void setGrid(deck.id, { network_enabled: event.target.checked })
          }
        />
        <span>{t("decks.networkEnabled")}</span>
      </label>
      <small className="help">{t("decks.networkEnabledHint")}</small>

      {/* Die Adresse gibt es nur, solange wirklich gelauscht wird — eine
          Adresse anzuzeigen, hinter der nichts steht, wäre irreführend. */}
      {deck.network_urls && deck.network_urls.length > 0 ? (
        <>
          <h4 className="section-title">{t("decks.networkAddress")}</h4>
          <ul className="net-urls">
            {deck.network_urls.map((url) => (
              <li key={url}>
                <code>{url}</code>
                <button
                  type="button"
                  className="btn small"
                  onClick={() => void navigator.clipboard?.writeText(url)}
                >
                  {t("decks.copy")}
                </button>
              </li>
            ))}
          </ul>
          <small className="help">{t("decks.networkAddressHint")}</small>
        </>
      ) : (
        <small className="help">
          {deck.has_password ? t("decks.networkOff") : t("decks.networkNoPassword")}
        </small>
      )}
    </>
  );
}
