import { useTranslation } from "react-i18next";

import { localized } from "../i18n";
import { useStore } from "../store";
import type { Background } from "../types";

interface Props {
  value: Background;
  onChange: (background: Background) => void;
}

const KINDS: Background["kind"][] = [
  "transparent",
  "solid",
  "gradient",
  "noise",
  "accent",
];

/**
 * Hintergrund einer Kachel — vor allem für die Touchstrip-Segmente gedacht,
 * die sonst schlicht schwarz wären. Gezeichnet wird zuerst der Hintergrund,
 * darüber legt die Aktion ihr Icon bzw. ihren Balken.
 */
export function BackgroundEditor({ value, onChange }: Props) {
  const { t, i18n } = useTranslation();
  const presets = useStore((s) => s.backgroundPresets);

  const patch = (changes: Partial<Background>) => onChange({ ...value, ...changes });

  return (
    <div className="background-editor">
      <div className="preset-row">
        {presets.map((preset) => (
          <button
            key={preset.id}
            type="button"
            className="preset"
            title={localized(preset.name, i18n.language)}
            onClick={() => patch(preset.background)}
            style={presetStyle(preset.background)}
          >
            <span>{localized(preset.name, i18n.language)}</span>
          </button>
        ))}
      </div>

      <div className="field">
        <label htmlFor="bg-kind">{t("background.kind")}</label>
        <select
          id="bg-kind"
          value={value.kind}
          onChange={(event) => patch({ kind: event.target.value as Background["kind"] })}
        >
          {KINDS.map((kind) => (
            <option key={kind} value={kind}>
              {t(`background.kinds.${kind}`)}
            </option>
          ))}
        </select>
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
    default:
      return { background: background.color ?? "#000000" };
  }
}
