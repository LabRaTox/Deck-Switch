import { useState } from "react";
import { useTranslation } from "react-i18next";

import { useStore } from "../store";
import { UiIcon } from "./UiIcon";

/**
 * Macht Fehler sichtbar, statt sie im Terminal-Log verschwinden zu lassen:
 * Gerät weg, Plugin beim Laden gescheitert, Render-Ausnahme.
 */
export function ErrorBanner() {
  const { t } = useTranslation();
  const errors = useStore((s) => s.errors);
  const clearErrors = useStore((s) => s.clearErrors);
  const [expanded, setExpanded] = useState(false);

  const relevant = errors.filter((e) => e.level !== "info");
  if (relevant.length === 0) return null;

  const latest = relevant[relevant.length - 1];

  return (
    <div className={`error-banner ${latest.level}`}>
      <button
        type="button"
        className="error-summary"
        onClick={() => setExpanded((value) => !value)}
      >
        <span aria-hidden="true">⚠</span>
        <span className="error-count">
          {t("errors.count", { count: relevant.length })}
        </span>
        <span className="error-latest">
          {latest.plugin_id ? `${latest.plugin_id}: ` : ""}
          {latest.message}
        </span>
        <UiIcon
          name={expanded ? "chevron-up" : "chevron-down"}
          size={14}
          className="chevron"
        />
      </button>

      <button type="button" className="btn small" onClick={() => void clearErrors()}>
        {t("errors.clear")}
      </button>

      {expanded && (
        <ul className="error-list">
          {[...relevant].reverse().map((error, index) => (
            <li key={`${error.plugin_id}-${error.message}-${index}`}>
              <time>{new Date(error.time * 1000).toLocaleTimeString()}</time>
              <span className="error-source">{error.plugin_id || error.source}</span>
              <span>
                {error.message}
                {(error.count ?? 1) > 1 && (
                  <span className="error-repeat">{error.count}×</span>
                )}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
