import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { api } from "../api/client";
import { localized } from "../i18n";
import { useStore } from "../store";
import type { Background } from "../types";

interface Props {
  value: Background;
  onChange: (background: Background) => void;
}

/**
 * Hintergrund einer Kachel — vor allem für die Touchstrip-Segmente gedacht,
 * die sonst schlicht schwarz wären. Gezeichnet wird zuerst der Hintergrund,
 * darüber legt die Aktion ihr Icon bzw. ihren Balken.
 */
export function BackgroundEditor({ value, onChange }: Props) {
  const { t, i18n } = useTranslation();
  const presets = useStore((s) => s.backgroundPresets);
  const [uploads, setUploads] = useState<{ filename: string; url: string }[]>([]);
  const [busy, setBusy] = useState(false);

  const patch = (changes: Partial<Background>) => onChange({ ...value, ...changes });

  // Die Bilderliste erst holen, wenn sie gebraucht wird — sonst lädt jede
  // ausgewählte Kachel sie mit, obwohl die meisten keinen Bildhintergrund
  // haben.
  useEffect(() => {
    if (value.kind !== "image") return;
    let cancelled = false;
    api
      .uploads()
      .then((list) => {
        if (!cancelled) setUploads(list);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [value.kind]);

  const aktiv = aktivesPreset(presets, value);

  return (
    <div className="background-editor">
      <div className="preset-row">
        {presets.map((preset) => (
          <button
            key={preset.id}
            type="button"
            className={preset.id === aktiv ? "preset aktiv" : "preset"}
            aria-pressed={preset.id === aktiv}
            title={localized(preset.name, i18n.language)}
            onClick={() => patch(preset.background)}
            style={presetStyle(preset.background)}
          >
            <span>{localized(preset.name, i18n.language)}</span>
          </button>
        ))}
      </div>

      {value.kind === "transparent" && (
        <small className="help">{t("background.transparentHint")}</small>
      )}

      {(value.kind === "solid" || value.kind === "gradient" || value.kind === "noise") && (
        <div className="field">
          <label htmlFor="bg-color">{t("background.color")}</label>
          <div className="color-input">
            <input
              id="bg-color"
              type="color"
              value={value.color}
              onChange={(event) => patch({ color: event.target.value })}
            />
            <input
              type="text"
              value={value.color}
              onChange={(event) => patch({ color: event.target.value })}
            />
          </div>
        </div>
      )}

      {value.kind === "gradient" && (
        <>
          <div className="field">
            <label htmlFor="bg-color2">{t("background.color2")}</label>
            <div className="color-input">
              <input
                id="bg-color2"
                type="color"
                value={value.color2}
                onChange={(event) => patch({ color2: event.target.value })}
              />
              <input
                type="text"
                value={value.color2}
                onChange={(event) => patch({ color2: event.target.value })}
              />
            </div>
          </div>
          <div className="field">
            <label htmlFor="bg-direction">{t("background.direction")}</label>
            <select
              id="bg-direction"
              value={value.direction}
              onChange={(event) =>
                patch({ direction: event.target.value as Background["direction"] })
              }
            >
              <option value="vertical">{t("background.directions.vertical")}</option>
              <option value="horizontal">{t("background.directions.horizontal")}</option>
            </select>
          </div>
        </>
      )}

      {value.kind === "noise" && (
        <div className="field">
          <label htmlFor="bg-intensity">
            {t("background.intensity")} ({value.intensity})
          </label>
          <input
            id="bg-intensity"
            type="range"
            min={0}
            max={100}
            value={value.intensity}
            onChange={(event) => patch({ intensity: Number(event.target.value) })}
          />
        </div>
      )}

      {value.kind === "image" && (
        <>
          <div className="field">
            <label htmlFor="bg-upload">{t("background.image")}</label>
            <select
              id="bg-upload"
              value={value.upload ?? ""}
              onChange={(event) => patch({ upload: event.target.value || null })}
            >
              <option value="">—</option>
              {uploads.map((entry) => (
                <option key={entry.filename} value={entry.filename}>
                  {entry.filename}
                </option>
              ))}
            </select>
          </div>

          <div className="field">
            <input
              type="file"
              accept="image/png,image/jpeg,image/webp,image/gif,image/svg+xml"
              disabled={busy}
              onChange={async (event) => {
                const file = event.target.files?.[0];
                if (!file) return;
                setBusy(true);
                try {
                  const { filename } = await api.upload(file, "icon");
                  setUploads(await api.uploads());
                  patch({ upload: filename });
                } finally {
                  setBusy(false);
                }
              }}
            />
            <small className="help">{t("background.imageHint")}</small>
          </div>

          {value.upload && (
            <img
              className="background-preview"
              src={api.uploadUrl(value.upload)}
              alt=""
            />
          )}

          <div className="field-row">
            <div className="field">
              <label htmlFor="bg-fit">{t("background.fit")}</label>
              <select
                id="bg-fit"
                value={value.fit}
                onChange={(event) =>
                  patch({ fit: event.target.value as Background["fit"] })
                }
              >
                <option value="cover">{t("background.fits.cover")}</option>
                <option value="contain">{t("background.fits.contain")}</option>
                <option value="stretch">{t("background.fits.stretch")}</option>
              </select>
            </div>

            <div className="field">
              <label htmlFor="bg-opacity">
                {t("background.opacity")} ({value.opacity}%)
              </label>
              <input
                id="bg-opacity"
                type="range"
                min={10}
                max={100}
                value={value.opacity}
                onChange={(event) => patch({ opacity: Number(event.target.value) })}
              />
            </div>
          </div>
        </>
      )}

      {value.kind === "accent" && (
        <div className="field">
          <label htmlFor="bg-accent">{t("background.accent")}</label>
          <div className="color-input">
            <input
              id="bg-accent"
              type="color"
              value={value.accent ?? "#3b82f6"}
              onChange={(event) => patch({ accent: event.target.value })}
            />
            <button
              type="button"
              className="btn small"
              onClick={() => patch({ accent: null })}
            >
              {t("common.default")}
            </button>
          </div>
          <small className="help">{t("background.accentHint")}</small>
        </div>
      )}
    </div>
  );
}

/**
 * Welche Kachel den aktuellen Hintergrund darstellt.
 *
 * Seit das Auswahlfeld „Art" weg ist, sind die Kacheln die einzige Anzeige
 * dafür, was eingestellt ist — und deshalb muss immer genau eine markiert
 * sein. Passt eine Kachel exakt (alle ihre Felder stimmen), gewinnt sie;
 * sonst reicht die gleiche Art. Zwei Kacheln teilen sich „einfarbig", und
 * wer die Farbe selbst ändert, soll trotzdem sehen, wo er gerade ist.
 */
function aktivesPreset(
  presets: { id: string; background: Partial<Background> }[],
  value: Background,
): string | undefined {
  const gleicheArt = presets.filter((p) => p.background.kind === value.kind);
  const genau = gleicheArt.find((p) =>
    Object.entries(p.background).every(
      ([feld, inhalt]) => inhalt === null || value[feld as keyof Background] === inhalt,
    ),
  );
  if (genau) return genau.id;
  // Keine Kachel trifft genau — jemand hat also selbst an den Farben
  // gedreht. Dann nur markieren, wenn die Art eindeutig zu einer Kachel
  // gehört. „Einfarbig" haben Dunkel und Graphit gemeinsam; dort raten
  // hieße, das Falsche zu behaupten, und lieber nichts markieren als die
  // verkehrte Kachel.
  return gleicheArt.length === 1 ? gleicheArt[0].id : undefined;
}

function presetStyle(background: Partial<Background>): React.CSSProperties {
  switch (background.kind) {
    case "transparent":
      // Schachbrett — das übliche Zeichen für „hier ist nichts“.
      return {
        backgroundImage:
          "linear-gradient(45deg, #3a3a44 25%, transparent 25% 75%, #3a3a44 75%)," +
          "linear-gradient(45deg, #3a3a44 25%, transparent 25% 75%, #3a3a44 75%)",
        backgroundSize: "12px 12px",
        backgroundPosition: "0 0, 6px 6px",
        backgroundColor: "#17171b",
      };
    case "gradient":
      return {
        background: `linear-gradient(${
          background.direction === "horizontal" ? "90deg" : "180deg"
        }, ${background.color ?? "#2a2a2e"}, ${background.color2 ?? "#0a0a0b"})`,
      };
    case "accent":
      return {
        background: `linear-gradient(180deg, ${background.accent ?? "#3b82f6"}55, #0a0a0c)`,
      };
    case "noise":
      return {
        background: background.color ?? "#141416",
        backgroundImage:
          "repeating-linear-gradient(45deg, #ffffff08 0 2px, transparent 2px 4px)",
      };
    case "image":
      return {
        background: "#111114",
        backgroundImage:
          "repeating-linear-gradient(135deg, #ffffff10 0 6px, transparent 6px 12px)",
      };
    default:
      return { background: background.color ?? "#000000" };
  }
}
