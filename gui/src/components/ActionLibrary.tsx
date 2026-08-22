import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { api } from "../api/client";
import { localized } from "../i18n";
import { useStore } from "../store";
import type { ActionDescriptor, PluginInfo } from "../types";
import { IconGlyph } from "./IconGlyph";
import { UiIcon } from "./UiIcon";

/** Was beim Ziehen mitgegeben wird — passend zum Drop-Handler im Grid. */
export const DRAG_MIME = "application/x-streamdeck-action";

export interface ActionDragPayload {
  plugin_id: string;
  action_id: string;
}

/** Wo der Aufklapp-Zustand liegt: reine Ansichtssache, also lokal. */
const COLLAPSED_KEY = "streamdeck.library.collapsed";

function loadCollapsed(): Record<string, boolean> {
  try {
    return JSON.parse(window.localStorage.getItem(COLLAPSED_KEY) ?? "{}");
  } catch {
    return {};
  }
}

/**
 * Linke Spalte: alle Aktionen aller geladenen Plugins, nach Plugin gruppiert.
 * Von hier zieht man eine Aktion auf eine Taste oder einen Dial. Die
 * Reihenfolge der Gruppen kommt aus der Plugin-Liste (dort sortierbar).
 */
export function ActionLibrary() {
  const { t, i18n } = useTranslation();
  const plugins = useStore((s) => s.plugins);
  const [query, setQuery] = useState("");
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>(loadCollapsed);

  // Zugeklappte Gruppen überleben das Neuladen der Seite.
  useEffect(() => {
    try {
      window.localStorage.setItem(COLLAPSED_KEY, JSON.stringify(collapsed));
    } catch {
      /* privater Modus o. Ä. — dann eben nur für diese Sitzung */
    }
  }, [collapsed]);

  const groups = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return plugins
      .filter((plugin) => plugin.manifest.type === "action" && plugin.enabled)
      .map((plugin) => ({
        plugin,
        actions: plugin.manifest.actions.filter((action) => {
          // Was diese Sitzung nicht hergibt, gehört nicht in die
          // Bibliothek: Man könnte es ablegen, und die Taste bliebe stumm.
          // Auf einer bereits belegten Taste bleibt die Aktion sichtbar —
          // dort steht dann der Grund, siehe Inspector.
          if (action.unavailable) return false;
          if (!needle) return true;
          const haystack = [
            localized(action.name, i18n.language),
            localized(action.description, i18n.language),
            localized(plugin.manifest.name, i18n.language),
            action.id,
          ]
            .join(" ")
            .toLowerCase();
          return haystack.includes(needle);
        }),
      }))
      .filter((group) => group.actions.length > 0);
  }, [plugins, query, i18n.language]);

  return (
    <aside className="library">
      <div className="panel-head">
        <h2>{t("library.title")}</h2>
      </div>

      <input
        className="search"
        type="search"
        value={query}
        placeholder={t("library.search")}
        onChange={(event) => setQuery(event.target.value)}
      />

      <p className="hint">{t("library.dragHint")}</p>

      <div className="library-scroll">
        {groups.length === 0 && <p className="empty-note">{t("library.noResults")}</p>}

        {groups.map(({ plugin, actions }) => (
          <section key={plugin.id} className="library-group">
            <button
              type="button"
              className="library-group-head"
              onClick={() =>
                setCollapsed((state) => ({ ...state, [plugin.id]: !state[plugin.id] }))
              }
            >
              {/* Farbbalken = Zugehörigkeit, kein Status. Runde Punkte sind
                  in dieser Oberfläche ausschließlich Verbindungsanzeigen. */}
              <span className="accent-bar" style={{ background: plugin.manifest.accent }} />
              <strong>{localized(plugin.manifest.name, i18n.language)}</strong>
              {plugin.status && !plugin.status.connected && (
                <span
                  className="status-dot offline"
                  title={`${t("plugins.disconnected")}${
                    plugin.status.detail ? ` — ${plugin.status.detail}` : ""
                  }`}
                />
              )}
              <UiIcon
                name={collapsed[plugin.id] ? "chevron-right" : "chevron-down"}
                size={14}
                className="chevron"
              />
            </button>

            {!collapsed[plugin.id] &&
              actions.map((action) => (
                <ActionCard key={action.id} plugin={plugin} action={action} />
              ))}
          </section>
        ))}
      </div>
    </aside>
  );
}

function ActionCard({
  plugin,
  action,
}: {
  plugin: PluginInfo;
  action: ActionDescriptor;
}) {
  const { t, i18n } = useTranslation();
  const iconSet = useStore((s) => s.config?.app.active_iconset ?? "iconset-tabler");

  const onlyDial = action.inputs.length === 1 && action.inputs[0] === "dial";
  const onlyKey = action.inputs.length === 1 && action.inputs[0] === "key";

  return (
    <div
      className="action-card"
      draggable
      onDragStart={(event) => {
        const payload: ActionDragPayload = {
          plugin_id: plugin.id,
          action_id: action.id,
        };
        event.dataTransfer.setData(DRAG_MIME, JSON.stringify(payload));
        event.dataTransfer.effectAllowed = "copy";
      }}
      title={localized(action.description, i18n.language)}
    >
      <span className="action-icon">
        {action.default_icon ? (
          <IconGlyph src={api.iconUrl(iconSet, action.default_icon)} size={20} />
        ) : (
          <span className="action-icon-fallback" />
        )}
      </span>
      <span className="action-text">
        <strong>{localized(action.name, i18n.language)}</strong>
        {(onlyDial || onlyKey) && (
          <small>{onlyDial ? t("library.dialOnly") : t("library.keyOnly")}</small>
        )}
      </span>
    </div>
  );
}
