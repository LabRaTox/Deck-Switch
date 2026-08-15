import { useState } from "react";
import { useTranslation } from "react-i18next";

import { api } from "../api/client";
import { localized } from "../i18n";
import { useStore } from "../store";
import type { ActionDescriptor, IconRef, PluginInfo, Slot } from "../types";
import { BackgroundEditor } from "./BackgroundEditor";
import { IconGlyph } from "./IconGlyph";
import { IconPicker } from "./IconPicker";
import { PageProperties } from "./PageProperties";
import { SettingsForm } from "./SettingsForm";

/**
 * Rechte Spalte: alle Eigenschaften der ausgewählten Taste bzw. des
 * ausgewählten Dials — Aktion, Aussehen, plugin-eigene Einstellungen und
 * die Zweitbelegung für langen Druck.
 */
export function Inspector() {
  const { t, i18n } = useTranslation();
  const selection = useStore((s) => s.selection);
  const slot = useStore((s) => s.slotAt(s.selection));
  const plugins = useStore((s) => s.plugins);
  const pageId = useStore((s) => s.currentPageId);
  const previewVersion = useStore((s) => s.previewVersion);
  const updateSlot = useStore((s) => s.updateSelectedSlot);
  const setSlot = useStore((s) => s.setSlot);
  const longPressMs = useStore((s) => s.config?.device.long_press_ms ?? 500);
  const activeIconset = useStore(
    (s) => s.config?.app.active_iconset ?? "iconset-tabler",
  );

  const [iconState, setIconState] = useState<string | null>(null);

  // Ohne Auswahl gehören die Eigenschaften der *Seite* — dort steht, was
  // nicht an einer einzelnen Taste hängt.
  if (!selection) {
    return (
      <aside className="inspector">
        <div className="panel-head">
          <h2>{t("inspector.pageTitle")}</h2>
        </div>
        <PageProperties />
      </aside>
    );
  }

  if (!slot) {
    return (
      <aside className="inspector">
        <div className="panel-head">
          <h2>{t("inspector.title")}</h2>
          <span className="badge">
            {selection.inputType === "key" ? "Taste" : "Dial"} {selection.index + 1}
          </span>
        </div>
        <p className="empty-note">{t("inspector.empty")}</p>
        <p className="hint">{t("library.dragHint")}</p>
      </aside>
    );
  }

  const plugin = plugins.find((p) => p.id === slot.plugin_id);
  const action = plugin?.manifest.actions.find((a) => a.id === slot.action_id);
  const states = action?.states.length ? action.states : [{ id: "default", name: "" }];

  const appearance = slot.appearance;

  return (
    <aside className="inspector">
      <div className="panel-head">
        <h2>{t("inspector.title")}</h2>
        <span className="badge">
          {selection.inputType === "key" ? "Taste" : "Dial"} {selection.index + 1}
        </span>
      </div>

      <div className="inspector-scroll">
        <section className="inspector-hero">
          <img
            className="hero-preview"
            src={api.previewUrl(pageId, selection.inputType, selection.index, previewVersion)}
            alt={t("inspector.preview")}
          />
          <div className="hero-text">
            <strong>{localized(action?.name, i18n.language) || slot.action_id}</strong>
            <small>{localized(plugin?.manifest.name, i18n.language) || slot.plugin_id}</small>
            {plugin && !plugin.loaded && (
              <small className="error-text">{plugin.error ?? t("plugins.loadError")}</small>
            )}
          </div>
          <button
            type="button"
            className="btn small danger"
            onClick={() => void setSlot(selection.inputType, selection.index, null)}
          >
            {t("inspector.remove")}
          </button>
        </section>

        {/* ---------------- Aussehen ---------------- */}
        <section className="inspector-section">
          <h3>{t("inspector.appearance")}</h3>

          <div className="icon-states">
            {states.map((state) => {
              const icon = appearance.icon_by_state[state.id];
              return (
                <button
                  key={state.id}
                  type="button"
                  className="icon-slot"
                  onClick={() => setIconState(state.id)}
                  title={
                    state.id === "default"
                      ? t("inspector.icon")
                      : t("inspector.iconState", {
                          state: localized(state.name, i18n.language) || state.id,
                        })
                  }
                >
                  <span className="icon-slot-preview">
                    {icon ? (
                      <IconGlyph
                        src={iconPreviewUrl(icon)}
                        color={icon.color}
                        mask={icon.kind !== "upload"}
                        size={30}
                      />
                    ) : action?.default_icon ? (
                      // Kein eigenes Icon gewählt: das Manifest-Icon
                      // abgeschwächt zeigen — es ist ja geerbt, nicht gesetzt.
                      <IconGlyph
                        className="inherited"
                        src={api.iconUrl(
                          activeIconset,
                          stateIcon(action, state.id) ?? action.default_icon,
                        )}
                        size={30}
                      />
                    ) : (
                      <span className="icon-slot-empty">+</span>
                    )}
                  </span>
                  <small>{localized(state.name, i18n.language) || state.id}</small>
                </button>
              );
            })}
          </div>

          <div className="field">
            <label htmlFor="icon-size">
              {t("inspector.iconSize")} ({appearance.icon_size}%)
            </label>
            <input
              id="icon-size"
              type="range"
              min={10}
              max={100}
              value={appearance.icon_size}
              onChange={(event) =>
                void updateSlot((draft) => {
                  draft.appearance.icon_size = Number(event.target.value);
                  return draft;
                })
              }
            />
          </div>

          <div className="field">
            <label className="checkbox">
              <input
                type="checkbox"
                checked={appearance.show_label}
                onChange={(event) =>
                  void updateSlot((draft) => {
                    draft.appearance.show_label = event.target.checked;
                    return draft;
                  })
                }
              />
              <span>{t("inspector.showLabel")}</span>
            </label>
          </div>

          {appearance.show_label && (
            <>
              <div className="field">
                <label htmlFor="label-text">{t("inspector.labelText")}</label>
                <input
                  id="label-text"
                  type="text"
                  value={appearance.label_text}
                  onChange={(event) =>
                    void updateSlot((draft) => {
                      draft.appearance.label_text = event.target.value;
                      return draft;
                    })
                  }
                />
              </div>

              <div className="field-row">
                <div className="field">
                  <label htmlFor="label-size">{t("inspector.labelSize")}</label>
                  <input
                    id="label-size"
                    type="number"
                    min={6}
                    max={64}
                    value={appearance.label_size}
                    onChange={(event) =>
                      void updateSlot((draft) => {
                        draft.appearance.label_size = Number(event.target.value);
                        return draft;
                      })
                    }
                  />
                </div>

                <div className="field">
                  <label htmlFor="label-color">{t("inspector.labelColor")}</label>
                  <input
                    id="label-color"
                    type="color"
                    value={appearance.label_color}
                    onChange={(event) =>
                      void updateSlot((draft) => {
                        draft.appearance.label_color = event.target.value;
                        return draft;
                      })
                    }
                  />
                </div>

                <div className="field">
                  <label htmlFor="label-position">{t("inspector.labelPosition")}</label>
                  <select
                    id="label-position"
                    value={appearance.label_position}
                    onChange={(event) =>
                      void updateSlot((draft) => {
                        draft.appearance.label_position = event.target
                          .value as Slot["appearance"]["label_position"];
                        return draft;
                      })
                    }
                  >
                    <option value="bottom">{t("inspector.labelPositions.bottom")}</option>
                    <option value="top">{t("inspector.labelPositions.top")}</option>
                    <option value="center">{t("inspector.labelPositions.center")}</option>
                  </select>
                </div>
              </div>
            </>
          )}

          <h4>{t("inspector.background")}</h4>
          <BackgroundEditor
            value={appearance.background}
            onChange={(background) =>
              void updateSlot((draft) => {
                draft.appearance.background = background;
                return draft;
              })
            }
          />
        </section>

        {/* ---------------- Plugin-Einstellungen ---------------- */}
        {action && action.settings_schema.length > 0 && (
          <section className="inspector-section">
            <h3>{t("inspector.settings")}</h3>
            <SettingsForm
              pluginId={slot.plugin_id}
              schema={action.settings_schema}
              values={slot.settings}
              onChange={(key, value) =>
                void updateSlot((draft) => {
                  draft.settings[key] = value;
                  return draft;
                })
              }
            />
          </section>
        )}

        {/* ---------------- Lang drücken ---------------- */}
        {selection.inputType === "key" && (
          <LongPressSection
            slot={slot}
            plugins={plugins}
            longPressMs={longPressMs}
            onChange={(longPress) =>
              void updateSlot((draft) => {
                draft.long_press = longPress;
                return draft;
              })
            }
          />
        )}
      </div>

      {iconState !== null && (
        <IconPicker
          value={appearance.icon_by_state[iconState]}
          title={
            iconState === "default"
              ? t("inspector.icon")
              : t("inspector.iconState", { state: iconState })
          }
          onClose={() => setIconState(null)}
          onChange={(icon) =>
            void updateSlot((draft) => {
              if (icon) draft.appearance.icon_by_state[iconState] = icon;
              else delete draft.appearance.icon_by_state[iconState];
              return draft;
            })
          }
        />
      )}
    </aside>
  );
}

function LongPressSection({
  slot,
  plugins,
  longPressMs,
  onChange,
}: {
  slot: Slot;
  plugins: PluginInfo[];
  longPressMs: number;
  onChange: (slot: Slot | null) => void;
}) {
  const { t, i18n } = useTranslation();
  const longPress = slot.long_press ?? null;

  const actionPlugins = plugins.filter(
    (p) => p.manifest.type === "action" && p.enabled,
  );
  const selectedPlugin = actionPlugins.find((p) => p.id === longPress?.plugin_id);
  const selectedAction = selectedPlugin?.manifest.actions.find(
    (a) => a.id === longPress?.action_id,
  );

  return (
    <section className="inspector-section">
      <h3>{t("inspector.longPress")}</h3>
      <p className="hint">{t("inspector.longPressHint", { ms: longPressMs })}</p>

      {!longPress ? (
        <button
          type="button"
          className="btn"
          onClick={() => {
            const first = actionPlugins[0];
            const firstAction = first?.manifest.actions.find((a) =>
              a.inputs.includes("key"),
            );
            if (!first || !firstAction) return;
            onChange({
              plugin_id: first.id,
              action_id: firstAction.id,
              settings: {},
              appearance: slot.appearance,
              long_press: null,
            });
          }}
        >
          + {t("inspector.longPressAdd")}
        </button>
      ) : (
        <>
          <div className="field-row">
            <div className="field">
              <label htmlFor="lp-plugin">Plugin</label>
              <select
                id="lp-plugin"
                value={longPress.plugin_id}
                onChange={(event) => {
                  const plugin = actionPlugins.find((p) => p.id === event.target.value);
                  const action = plugin?.manifest.actions.find((a) =>
                    a.inputs.includes("key"),
                  );
                  if (!plugin || !action) return;
                  onChange({
                    ...longPress,
                    plugin_id: plugin.id,
                    action_id: action.id,
                    settings: {},
                  });
                }}
              >
                {actionPlugins.map((plugin) => (
                  <option key={plugin.id} value={plugin.id}>
                    {localized(plugin.manifest.name, i18n.language)}
                  </option>
                ))}
              </select>
            </div>

            <div className="field">
              <label htmlFor="lp-action">{t("inspector.action")}</label>
              <select
                id="lp-action"
                value={longPress.action_id}
                onChange={(event) =>
                  onChange({ ...longPress, action_id: event.target.value, settings: {} })
                }
              >
                {selectedPlugin?.manifest.actions
                  .filter((a) => a.inputs.includes("key"))
                  .map((action) => (
                    <option key={action.id} value={action.id}>
                      {localized(action.name, i18n.language)}
                    </option>
                  ))}
              </select>
            </div>
          </div>

          {selectedAction && selectedAction.settings_schema.length > 0 && (
            <SettingsForm
              pluginId={longPress.plugin_id}
              schema={selectedAction.settings_schema}
              values={longPress.settings}
              onChange={(key, value) =>
                onChange({
                  ...longPress,
                  settings: { ...longPress.settings, [key]: value },
                })
              }
            />
          )}

          <button type="button" className="btn small danger" onClick={() => onChange(null)}>
            {t("inspector.longPressRemove")}
          </button>
        </>
      )}
    </section>
  );
}

function stateIcon(action: ActionDescriptor, stateId: string): string | null {
  return action.states.find((s) => s.id === stateId)?.default_icon ?? null;
}

function iconPreviewUrl(icon: IconRef): string {
  if (icon.kind === "upload" && icon.upload) return api.uploadUrl(icon.upload);
  if (icon.kind === "iconset" && icon.name) {
    return api.iconUrl(icon.set_id ?? "iconset-tabler", icon.name);
  }
  return "";
}
