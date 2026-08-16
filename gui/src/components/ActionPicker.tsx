import { useTranslation } from "react-i18next";

import { localized } from "../i18n";
import { useStore } from "../store";
import type { ActionDescriptor, InputType, PluginInfo } from "../types";

interface Props {
  pluginId: string;
  actionId: string;
  /** Nur Aktionen anbieten, die auf diese Eingabeart passen. */
  inputType: InputType;
  onChange: (pluginId: string, actionId: string) => void;
  /** Plugins, die hier nichts zu suchen haben (etwa „multi“ in Ketten). */
  exclude?: string[];
  compact?: boolean;
}

/**
 * Plugin- und Aktionsauswahl als Paar.
 *
 * Bewusst an einer Stelle: Dieselbe Auswahl braucht der Doppeldruck, das
 * Halten, jeder Schritt einer Multi-Aktion und jeder Eintrag eines
 * Dial-Stacks. Vier Kopien davon wären vier Gelegenheiten, die Filterung
 * nach Eingabeart zu vergessen.
 */
export function ActionPicker({
  pluginId,
  actionId,
  inputType,
  onChange,
  exclude = [],
  compact = false,
}: Props) {
  const { t, i18n } = useTranslation();
  const plugins = useStore((s) => s.plugins);

  const usable = plugins.filter(
    (plugin) =>
      plugin.manifest.type === "action" &&
      plugin.enabled &&
      !exclude.includes(plugin.id) &&
      plugin.manifest.actions.some((action) => action.inputs.includes(inputType)),
  );

  const selectedPlugin = usable.find((plugin) => plugin.id === pluginId);
  const actions = (selectedPlugin?.manifest.actions ?? []).filter((action) =>
    action.inputs.includes(inputType),
  );

  return (
    <div className={compact ? "action-picker compact" : "action-picker"}>
      <div className="field">
        <label>{t("inspector.plugin")}</label>
        <select
          value={pluginId}
          onChange={(event) => {
            const plugin = usable.find((entry) => entry.id === event.target.value);
            const first = firstAction(plugin, inputType);
            if (plugin && first) onChange(plugin.id, first.id);
          }}
        >
          {!selectedPlugin && <option value={pluginId}>{pluginId || "—"}</option>}
          {usable.map((plugin) => (
            <option key={plugin.id} value={plugin.id}>
              {localized(plugin.manifest.name, i18n.language)}
            </option>
          ))}
        </select>
      </div>

      <div className="field">
        <label>{t("inspector.action")}</label>
        <select
          value={actionId}
          onChange={(event) => onChange(pluginId, event.target.value)}
        >
          {!actions.some((action) => action.id === actionId) && (
            <option value={actionId}>{actionId || "—"}</option>
          )}
          {actions.map((action) => (
            <option key={action.id} value={action.id}>
              {localized(action.name, i18n.language)}
            </option>
          ))}
        </select>
      </div>
    </div>
  );
}

export function firstAction(
  plugin: PluginInfo | undefined,
  inputType: InputType,
): ActionDescriptor | undefined {
  return plugin?.manifest.actions.find((action) => action.inputs.includes(inputType));
}

/** Erstes brauchbares Plugin samt Aktion — für frisch angelegte Einträge. */
export function defaultAction(
  plugins: PluginInfo[],
  inputType: InputType,
  exclude: string[] = [],
): { plugin_id: string; action_id: string } | null {
  for (const plugin of plugins) {
    if (plugin.manifest.type !== "action" || !plugin.enabled) continue;
    if (exclude.includes(plugin.id)) continue;
    const action = firstAction(plugin, inputType);
    if (action) return { plugin_id: plugin.id, action_id: action.id };
  }
  return null;
}
