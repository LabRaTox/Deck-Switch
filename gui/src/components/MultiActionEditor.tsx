import { useState, type DragEvent } from "react";
import { useTranslation } from "react-i18next";

import { localized } from "../i18n";
import { useStore } from "../store";
import type { InputType, Step } from "../types";
import { DRAG_MIME, type ActionDragPayload } from "./ActionLibrary";
import { ActionPicker, defaultAction } from "./ActionPicker";
import { SettingsForm } from "./SettingsForm";

/**
 * Eigener Typ fürs Umsortieren innerhalb der Liste.
 *
 * Bewusst über ``dataTransfer`` und nicht über eine Ref: Nur so lässt sich
 * beim Überfahren schon unterscheiden, ob da ein Schritt umsortiert oder
 * eine neue Aktion aus der Bibliothek abgelegt wird — und nur so kommt der
 * Drop auch in einer WebView an, die ohne gesetzte Daten keinen zulässt.
 */
const STEP_MIME = "application/x-streamdeck-step";

interface Props {
  steps: Step[];
  inputType: InputType;
  onChange: (steps: Step[]) => void;
  /** Überschrift — der Umschalter hat zwei Ketten und braucht zwei Namen. */
  title?: string;
}

/**
 * Die Schrittliste einer Multi-Aktion.
 *
 * Zwei Sorten Schritte: eine Aktion oder eine Pause. Die Pause ist bewusst
 * ein eigener Eintrag und keine Eigenschaft der Aktion davor — so lässt sie
 * sich verschieben, mehrfach einsetzen und einzeln abschalten.
 *
 * Sortiert wird per Ziehen; ohne Maus geht dasselbe mit Alt + ↑↓, wie im
 * Seitenbaum.
 */
export function MultiActionEditor({ steps, inputType, onChange, title }: Props) {
  const { t, i18n } = useTranslation();
  const plugins = useStore((s) => s.plugins);
  const [open, setOpen] = useState<string | null>(null);
  // Über welchem Schritt gerade geschwebt wird — davor wird eingefügt.
  const [dropBefore, setDropBefore] = useState<string | null>(null);
  const [dropEnd, setDropEnd] = useState(false);

  const patch = (id: string, changes: Partial<Step>) =>
    onChange(steps.map((step) => (step.id === id ? { ...step, ...changes } : step)));

  const remove = (id: string) => onChange(steps.filter((step) => step.id !== id));

  const move = (id: string, delta: number) => {
    const from = steps.findIndex((step) => step.id === id);
    const to = from + delta;
    if (from < 0 || to < 0 || to >= steps.length) return;
    const next = [...steps];
    const [entry] = next.splice(from, 1);
    next.splice(to, 0, entry);
    onChange(next);
  };

  /** Nimmt eine Aktion aus der Bibliothek an — passend zur Eingabeart. */
  const stepFromLibrary = (raw: string): Step | null => {
    const { plugin_id, action_id } = JSON.parse(raw) as ActionDragPayload;
    if (plugin_id === "multi") return null;
    const action = plugins
      .find((plugin) => plugin.id === plugin_id)
      ?.manifest.actions.find((entry) => entry.id === action_id);
    // Was diese Eingabeart nicht kann, gar nicht erst aufnehmen — auf einem
    // Dial wäre eine reine Tastenaktion sonst ein stiller Blindgänger.
    if (!action || !action.inputs.includes(inputType)) return null;
    return {
      id: newId(),
      kind: "action",
      plugin_id,
      action_id,
      settings: {},
      delay_ms: 200,
      enabled: true,
    };
  };

  const accepts = (event: DragEvent) => {
    const types = Array.from(event.dataTransfer.types);
    return types.includes(STEP_MIME) || types.includes(DRAG_MIME);
  };

  const allowDrop = (event: DragEvent, beforeId: string | null) => {
    if (!accepts(event)) return;
    event.preventDefault();
    event.stopPropagation();
    event.dataTransfer.dropEffect = event.dataTransfer.types.includes(STEP_MIME)
      ? "move"
      : "copy";
    setDropBefore(beforeId);
    setDropEnd(beforeId === null);
  };

  const clearDrop = () => {
    setDropBefore(null);
    setDropEnd(false);
  };

  /** ``beforeId = null`` heißt: ans Ende. */
  const handleDrop = (event: DragEvent, beforeId: string | null) => {
    if (!accepts(event)) return;
    event.preventDefault();
    event.stopPropagation();
    clearDrop();

    const target = beforeId ? steps.findIndex((step) => step.id === beforeId) : steps.length;

    const moving = event.dataTransfer.getData(STEP_MIME);
    if (moving) {
      const from = steps.findIndex((step) => step.id === moving);
      if (from < 0 || from === target) return;
      const next = [...steps];
      const [entry] = next.splice(from, 1);
      // Nach dem Herausnehmen rutscht alles dahinter eine Position vor.
      next.splice(from < target ? target - 1 : target, 0, entry);
      onChange(next);
      return;
    }

    const raw = event.dataTransfer.getData(DRAG_MIME);
    if (!raw) return;
    const fresh = stepFromLibrary(raw);
    if (!fresh) return;
    const next = [...steps];
    next.splice(target, 0, fresh);
    onChange(next);
    // Gleich aufklappen: Nach dem Ablegen will man die Einstellungen sehen.
    setOpen(fresh.id);
  };

  const addAction = () => {
    // „multi“ ist ausgenommen: Eine Kette in der Kette wäre eine Schleife,
    // die niemand mehr anhält — das Backend lehnt sie ohnehin ab.
    const first = defaultAction(plugins, inputType, ["multi"]);
    if (!first) return;
    onChange([
      ...steps,
      {
        id: newId(),
        kind: "action",
        plugin_id: first.plugin_id,
        action_id: first.action_id,
        settings: {},
        delay_ms: 200,
        enabled: true,
      },
    ]);
  };

  const addDelay = () =>
    onChange([
      ...steps,
      {
        id: newId(),
        kind: "delay",
        plugin_id: "",
        action_id: "",
        settings: {},
        delay_ms: 200,
        enabled: true,
      },
    ]);

  return (
    <div className="multi-editor">
      {title && <h4>{title}</h4>}

      <ol className="step-list">
        {steps.map((step, index) => {
          const plugin = plugins.find((entry) => entry.id === step.plugin_id);
          const action = plugin?.manifest.actions.find(
            (entry) => entry.id === step.action_id,
          );
          const expanded = open === step.id;

          return (
            <li
              key={step.id}
              className={
                `step${step.enabled ? "" : " disabled"}` +
                (dropBefore === step.id ? " drop-before" : "")
              }
              draggable
              onDragStart={(event) => {
                event.dataTransfer.setData(STEP_MIME, step.id);
                event.dataTransfer.effectAllowed = "move";
              }}
              onDragEnd={clearDrop}
              onDragOver={(event) => allowDrop(event, step.id)}
              onDrop={(event) => handleDrop(event, step.id)}
              onKeyDown={(event) => {
                if (!event.altKey) return;
                if (event.key === "ArrowUp") {
                  event.preventDefault();
                  move(step.id, -1);
                } else if (event.key === "ArrowDown") {
                  event.preventDefault();
                  move(step.id, 1);
                }
              }}
              tabIndex={0}
            >
              <div className="step-head">
                <span className="step-grip" aria-hidden="true">
                  ⠿
                </span>
                <span className="step-number">{index + 1}</span>

                {step.kind === "delay" ? (
                  <span className="step-title">
                    {t("multi.delay")} · {step.delay_ms} ms
                  </span>
                ) : (
                  <span className="step-title">
                    {localized(action?.name, i18n.language) || step.action_id}
                    <small>
                      {localized(plugin?.manifest.name, i18n.language) || step.plugin_id}
                    </small>
                  </span>
                )}

                <label className="checkbox" title={t("multi.enabled")}>
                  <input
                    type="checkbox"
                    checked={step.enabled}
                    onChange={(event) =>
                      patch(step.id, { enabled: event.target.checked })
                    }
                  />
                </label>

                <button
                  type="button"
                  className="btn tiny"
                  onClick={() => setOpen(expanded ? null : step.id)}
                  aria-expanded={expanded}
                >
                  {expanded ? "▾" : "▸"}
                </button>
                <button
                  type="button"
                  className="btn tiny danger"
                  onClick={() => remove(step.id)}
                  title={t("common.remove")}
                >
                  ✕
                </button>
              </div>

              {expanded && (
                <div className="step-body">
                  {step.kind === "delay" ? (
                    <div className="field">
                      <label>{t("multi.delayMs")}</label>
                      <input
                        type="number"
                        min={0}
                        max={600000}
                        step={50}
                        value={step.delay_ms}
                        onChange={(event) =>
                          patch(step.id, { delay_ms: Number(event.target.value) })
                        }
                      />
                    </div>
                  ) : (
                    <>
                      <ActionPicker
                        pluginId={step.plugin_id}
                        actionId={step.action_id}
                        inputType={inputType}
                        exclude={["multi"]}
                        compact
                        onChange={(pluginId, actionId) =>
                          patch(step.id, {
                            plugin_id: pluginId,
                            action_id: actionId,
                            // Einstellungen gehören zur Aktion — bei einem
                            // Wechsel wären sie sonst Reste der alten.
                            settings: {},
                          })
                        }
                      />
                      {action && action.settings_schema.length > 0 && (
                        <SettingsForm
                          pluginId={step.plugin_id}
                          schema={action.settings_schema}
                          values={step.settings}
                          onChange={(key, value) =>
                            patch(step.id, {
                              settings: { ...step.settings, [key]: value },
                            })
                          }
                        />
                      )}
                    </>
                  )}
                </div>
              )}
            </li>
          );
        })}
        {/* Immer sichtbar, nicht nur bei leerer Liste: Wer den zweiten
            Schritt anhängen will, braucht eine Fläche dafür. Auf einen
            Schritt gezogen wird *davor* eingefügt — ohne diese Zone gäbe
            es unter dem letzten Schritt schlicht kein Ziel. */}
        <li
          className={`step-drop${dropEnd ? " active" : ""}`}
          onDragOver={(event) => allowDrop(event, null)}
          onDragLeave={clearDrop}
          onDrop={(event) => handleDrop(event, null)}
        >
          {steps.length === 0 ? t("multi.empty") : t("multi.dropZone")}
        </li>
      </ol>

      <p className="hint">{t("multi.dropHint")}</p>

      <div className="step-actions">
        <button type="button" className="btn small" onClick={addAction}>
          + {t("multi.addAction")}
        </button>
        <button type="button" className="btn small" onClick={addDelay}>
          + {t("multi.addDelay")}
        </button>
      </div>
    </div>
  );
}

function newId(): string {
  return Math.random().toString(16).slice(2, 14);
}
