import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { api, SYSTEM_ICONSET } from "../api/client";
import { localized } from "../i18n";
import { useStore } from "../store";
import type { ActionDescriptor, IconRef, InputType, Slot, Step } from "../types";
import { ActionPicker, defaultAction } from "./ActionPicker";
import { BackgroundEditor } from "./BackgroundEditor";
import { IconGlyph } from "./IconGlyph";
import { IconPicker } from "./IconPicker";
import { KeyCreator } from "./KeyCreator";
import { MultiActionEditor } from "./MultiActionEditor";
import { PageProperties } from "./PageProperties";
import { SettingsForm } from "./SettingsForm";

/**
 * Die Wege, eine Belegung auszulösen.
 *
 * Eine Taste kennt drei (Elgato nennt das „Key Logic“), ein Dial ebenfalls
 * drei — nur andere: drücken und je Drehrichtung einen. Die Oberfläche ist
 * für beide dieselbe, nur die Reiter wechseln.
 */
type Branch = "press" | "double" | "long" | "left" | "right";

const KEY_BRANCHES: Branch[] = ["press", "double", "long"];
const DIAL_BRANCHES: Branch[] = ["press", "left", "right"];

/**
 * Rechte Spalte: alle Eigenschaften der ausgewählten Taste bzw. des
 * ausgewählten Dials — Aktion, Aussehen, plugin-eigene Einstellungen, die
 * Zweitbelegungen für Doppeldruck und Halten, die Schritte einer
 * Multi-Aktion und der Stack eines Dials.
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
  const settings = useStore((s) => s.deckSettings());
  const activeIconset = SYSTEM_ICONSET;

  const [iconState, setIconState] = useState<string | null>(null);
  const [branch, setBranch] = useState<Branch>("press");
  const [stackIndex, setStackIndex] = useState(0);
  const [creatorOpen, setCreatorOpen] = useState(false);

  // Auswahl gewechselt: Zweig und Stack-Eintrag zurücksetzen, sonst
  // bearbeitet man unbemerkt den Halten-Zweig der neuen Taste.
  useEffect(() => {
    setBranch("press");
    setStackIndex(0);
  }, [selection?.inputType, selection?.index, pageId]);

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

  const inputType: InputType = selection.inputType;
  const isDial = inputType === "dial";

  // Bei einem Dial-Stack bearbeitet die ganze Spalte den ausgewählten
  // Eintrag — der Stack ist eine Liste vollwertiger Belegungen.
  const entries: Slot[] = [slot, ...(slot.stack ?? [])];
  const position = Math.min(stackIndex, entries.length - 1);
  const editing = entries[position] ?? slot;

  /** Schreibt eine Änderung in den gerade bearbeiteten Stack-Eintrag. */
  const updateEntry = (mutate: (draft: Slot) => Slot) =>
    void updateSlot((draft) => {
      if (position === 0) return mutate(draft);
      const entry = draft.stack?.[position - 1];
      if (entry) draft.stack[position - 1] = mutate(entry);
      return draft;
    });

  const branchSlot: Slot | null =
    branch === "press"
      ? editing
      : branch === "double"
        ? (editing.double_press ?? null)
        : branch === "long"
          ? (editing.long_press ?? null)
          : branch === "left"
            ? (editing.turn_left ?? null)
            : (editing.turn_right ?? null);

  const setBranchSlot = (value: Slot | null) =>
    updateEntry((draft) => {
      if (branch === "double") draft.double_press = value;
      else if (branch === "long") draft.long_press = value;
      else if (branch === "left") draft.turn_left = value;
      else if (branch === "right") draft.turn_right = value;
      return draft;
    });

  const branchFilled = (entry: Branch) =>
    entry === "press" ||
    (entry === "double" && Boolean(editing.double_press)) ||
    (entry === "long" && Boolean(editing.long_press)) ||
    (entry === "left" && Boolean(editing.turn_left)) ||
    (entry === "right" && Boolean(editing.turn_right));

  const turnsAssigned = Boolean(editing.turn_left || editing.turn_right);

  const plugin = plugins.find((p) => p.id === editing.plugin_id);
  const action = plugin?.manifest.actions.find((a) => a.id === editing.action_id);
  const states = action?.states.length ? action.states : [{ id: "default", name: "" }];
  const appearance = editing.appearance;

  const branchPlugin = plugins.find((p) => p.id === branchSlot?.plugin_id);
  const branchAction = branchPlugin?.manifest.actions.find(
    (a) => a.id === branchSlot?.action_id,
  );

  const isMulti = editing.plugin_id === "multi";
  const isSwitch = isMulti && editing.action_id === "switch";

  return (
    <aside className="inspector">
      <div className="panel-head">
        <h2>{t("inspector.title")}</h2>
        <span className="badge">
          {inputType === "key" ? "Taste" : "Dial"} {selection.index + 1}
        </span>
      </div>

      <div className="inspector-scroll">
        <section className="inspector-hero">
          <img
            className="hero-preview"
            src={api.previewUrl(
              pageId,
              inputType,
              selection.index,
              previewVersion,
              position,
            )}
            alt={t("inspector.preview")}
          />
          <div className="hero-text">
            <strong>{localized(action?.name, i18n.language) || editing.action_id}</strong>
            <small>
              {localized(plugin?.manifest.name, i18n.language) || editing.plugin_id}
            </small>
            {plugin && !plugin.loaded && (
              <small className="error-text">{plugin.error ?? t("plugins.loadError")}</small>
            )}
            {/* Die Aktion liegt auf der Taste, diese Sitzung gibt sie aber
                nicht her. Ausblenden wäre hier falsch — die Belegung ist
                echt und soll nach einem Desktop-Wechsel wieder wirken. */}
            {action?.unavailable && (
              <small className="error-text">
                {t("inspector.unavailable", { reason: action.unavailable.reason })}
              </small>
            )}
          </div>
          <button
            type="button"
            className="btn small danger"
            onClick={() => void setSlot(inputType, selection.index, null)}
          >
            {t("inspector.remove")}
          </button>
        </section>

        {/* ---------------- Dial-Stack ---------------- */}
        {isDial && (
          <StackSection
            entries={entries}
            position={position}
            pageId={pageId}
            index={selection.index}
            onSelect={setStackIndex}
            onChange={(stack) =>
              void updateSlot((draft) => {
                draft.stack = stack;
                return draft;
              })
            }
          />
        )}

        {/* ---------------- Tasten- bzw. Dial-Logik ---------------- */}
        <section className="inspector-section">
          <h3>{t(isDial ? "inspector.dialLogic" : "inspector.keyLogic")}</h3>
          <p className="hint">
            {isDial
              ? t("inspector.dialLogicHint")
              : t("inspector.keyLogicHint", {
                  long: settings?.long_press_ms ?? 500,
                  double: settings?.double_press_ms ?? 280,
                })}
          </p>

          <div className="branch-tabs">
            {(isDial ? DIAL_BRANCHES : KEY_BRANCHES).map((entry) => {
              const filled = branchFilled(entry);
              return (
                <button
                  key={entry}
                  type="button"
                  className={`branch-tab${branch === entry ? " active" : ""}${
                    filled ? " filled" : ""
                  }`}
                  onClick={() => setBranch(entry)}
                >
                  {t(`inspector.branches.${entry}`)}
                  {filled && entry !== "press" && <span className="dot" />}
                </button>
              );
            })}
          </div>

          {/* Die Empfindlichkeit gehört dem ganzen Dial, nicht einer
              Richtung — deshalb steht sie über den Reitern, sobald
              überhaupt eine Richtung belegt ist. */}
          {isDial && turnsAssigned && (
            <div className="field">
              <label htmlFor="turn-every">{t("inspector.turnEvery")}</label>
              <input
                id="turn-every"
                type="number"
                min={1}
                max={10}
                value={editing.turn_every ?? 2}
                onChange={(event) =>
                  updateEntry((draft) => {
                    draft.turn_every = Math.max(1, Number(event.target.value));
                    return draft;
                  })
                }
              />
              <small className="help">{t("inspector.turnEveryHint")}</small>
            </div>
          )}

            {branch !== "press" && !branchSlot && (
              <button
                type="button"
                className="btn"
                onClick={() => {
                  const first = defaultAction(plugins, inputType);
                  if (!first) return;
                  setBranchSlot({
                    plugin_id: first.plugin_id,
                    action_id: first.action_id,
                    settings: {},
                    appearance: editing.appearance,
                    long_press: null,
                    double_press: null,
                    turn_left: null,
                    turn_right: null,
                    turn_every: 2,
                    steps: [],
                    steps_off: [],
                    repeat: false,
                    toggled: false,
                    stack: [],
                  });
                }}
              >
                + {t(`inspector.add.${branch}`)}
              </button>
            )}

            {branch !== "press" && branchSlot && (
              <>
                <ActionPicker
                  pluginId={branchSlot.plugin_id}
                  actionId={branchSlot.action_id}
                  inputType={inputType}
                  onChange={(pluginId, actionId) =>
                    setBranchSlot({
                      ...branchSlot,
                      plugin_id: pluginId,
                      action_id: actionId,
                      settings: {},
                    })
                  }
                />
                {branchAction && branchAction.settings_schema.length > 0 && (
                  <SettingsForm
                    pluginId={branchSlot.plugin_id}
                    schema={branchAction.settings_schema}
                    values={branchSlot.settings}
                    onChange={(key, value) =>
                      setBranchSlot({
                        ...branchSlot,
                        settings: { ...branchSlot.settings, [key]: value },
                      })
                    }
                  />
                )}
              <button
                type="button"
                className="btn small danger"
                onClick={() => setBranchSlot(null)}
              >
                {t(`inspector.remove_${branch}`)}
              </button>
            </>
          )}
        </section>

        {/* ---------------- Multi-Aktion ---------------- */}
        {isMulti && branch === "press" && (
          <section className="inspector-section">
            <h3>{t("multi.title")}</h3>
            <MultiActionEditor
              steps={editing.steps ?? []}
              inputType={inputType}
              title={isSwitch ? t("multi.chainOn") : undefined}
              onChange={(steps) =>
                updateEntry((draft) => {
                  draft.steps = steps;
                  return draft;
                })
              }
            />
            {isSwitch && (
              <MultiActionEditor
                steps={editing.steps_off ?? []}
                inputType={inputType}
                title={t("multi.chainOff")}
                onChange={(steps) =>
                  updateEntry((draft) => {
                    draft.steps_off = steps;
                    return draft;
                  })
                }
              />
            )}
          </section>
        )}

        {/* ---------------- Aussehen ---------------- */}
        {branch === "press" && (
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

            <button
              type="button"
              className="btn small"
              onClick={() => setCreatorOpen(true)}
            >
              {t("creator.open")}
            </button>

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
                  updateEntry((draft) => {
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
                    updateEntry((draft) => {
                      draft.appearance.show_label = event.target.checked;
                      return draft;
                    })
                  }
                />
                <span>{t("inspector.showLabel")}</span>
              </label>
            </div>

            {appearance.show_label && (
              <LabelEditor
                appearance={appearance}
                onPatch={(mutate) => updateEntry(mutate)}
              />
            )}

            <h4>{t("inspector.background")}</h4>
            <BackgroundEditor
              value={appearance.background}
              onChange={(background) =>
                updateEntry((draft) => {
                  draft.appearance.background = background;
                  return draft;
                })
              }
            />
          </section>
        )}

        {/* ---------------- Plugin-Einstellungen ---------------- */}
        {branch === "press" && action && action.settings_schema.length > 0 && (
          <section className="inspector-section">
            <h3>{t("inspector.settings")}</h3>
            <SettingsForm
              pluginId={editing.plugin_id}
              schema={action.settings_schema}
              values={editing.settings}
              onChange={(key, value) =>
                updateEntry((draft) => {
                  draft.settings[key] = value;
                  return draft;
                })
              }
            />
          </section>
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
            updateEntry((draft) => {
              if (icon) draft.appearance.icon_by_state[iconState] = icon;
              else delete draft.appearance.icon_by_state[iconState];
              return draft;
            })
          }
        />
      )}

      {creatorOpen && (
        <KeyCreator
          appearance={appearance}
          onClose={() => setCreatorOpen(false)}
          onApply={(filename, mode) =>
            updateEntry((draft) => {
              if (mode === "background") {
                draft.appearance.background = {
                  ...draft.appearance.background,
                  kind: "image",
                  upload: filename,
                  fit: "cover",
                  opacity: 100,
                };
                // Das fertige Bild bringt Symbol und Text schon mit —
                // beides zusätzlich darüberzulegen wäre doppelt. „none"
                // unterdrückt auch das Symbol aus dem Manifest.
                draft.appearance.icon_by_state = {
                  default: { kind: "none", upload: null, name: null, color: null },
                };
                draft.appearance.show_label = false;
              } else {
                draft.appearance.icon_by_state.default = {
                  kind: "upload",
                  upload: filename,
                  color: null,
                };
              }
              return draft;
            })
          }
        />
      )}
    </aside>
  );
}

/** Beschriftung samt Schriftschnitt — Elgatos „Title“-Bereich. */
function LabelEditor({
  appearance,
  onPatch,
}: {
  appearance: Slot["appearance"];
  onPatch: (mutate: (draft: Slot) => Slot) => void;
}) {
  const { t } = useTranslation();
  const [fonts, setFonts] = useState<string[]>([]);

  useEffect(() => {
    let cancelled = false;
    api
      .fonts()
      .then((list) => {
        if (!cancelled) setFonts(list);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <>
      <div className="field">
        <label htmlFor="label-text">{t("inspector.labelText")}</label>
        <input
          id="label-text"
          type="text"
          value={appearance.label_text}
          onChange={(event) =>
            onPatch((draft) => {
              draft.appearance.label_text = event.target.value;
              return draft;
            })
          }
        />
      </div>

      <div className="field">
        <label htmlFor="label-font">{t("inspector.labelFont")}</label>
        <select
          id="label-font"
          value={appearance.label_font}
          onChange={(event) =>
            onPatch((draft) => {
              draft.appearance.label_font = event.target.value;
              return draft;
            })
          }
        >
          <option value="">{t("inspector.labelFontDefault")}</option>
          {fonts.map((family) => (
            <option key={family} value={family}>
              {family}
            </option>
          ))}
        </select>
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
              onPatch((draft) => {
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
              onPatch((draft) => {
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
              onPatch((draft) => {
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

      <div className="field-row">
        <div className="field">
          <label htmlFor="label-align">{t("inspector.labelAlign")}</label>
          <select
            id="label-align"
            value={appearance.label_align}
            onChange={(event) =>
              onPatch((draft) => {
                draft.appearance.label_align = event.target
                  .value as Slot["appearance"]["label_align"];
                return draft;
              })
            }
          >
            <option value="center">{t("inspector.labelAligns.center")}</option>
            <option value="left">{t("inspector.labelAligns.left")}</option>
            <option value="right">{t("inspector.labelAligns.right")}</option>
          </select>
        </div>

        <div className="field style-toggles">
          <label>{t("inspector.labelStyle")}</label>
          <div className="toggle-row">
            {(
              [
                ["label_bold", "B", "bold"],
                ["label_italic", "I", "italic"],
                ["label_underline", "U", "underline"],
              ] as const
            ).map(([key, glyph, name]) => (
              <button
                key={key}
                type="button"
                className={`style-toggle ${name}${appearance[key] ? " active" : ""}`}
                title={t(`inspector.labelStyles.${name}`)}
                aria-pressed={appearance[key]}
                onClick={() =>
                  onPatch((draft) => {
                    draft.appearance[key] = !draft.appearance[key];
                    return draft;
                  })
                }
              >
                {glyph}
              </button>
            ))}
          </div>
        </div>
      </div>
    </>
  );
}

/** Die Einträge eines Dial-Stacks — mehrere Belegungen auf einem Dial. */
function StackSection({
  entries,
  position,
  pageId,
  index,
  onSelect,
  onChange,
}: {
  entries: Slot[];
  position: number;
  pageId: string;
  index: number;
  onSelect: (position: number) => void;
  onChange: (stack: Slot[]) => void;
}) {
  const { t, i18n } = useTranslation();
  const plugins = useStore((s) => s.plugins);
  const bumpPreview = useStore((s) => s.bumpPreview);

  const name = (entry: Slot) => {
    const plugin = plugins.find((p) => p.id === entry.plugin_id);
    const action = plugin?.manifest.actions.find((a) => a.id === entry.action_id);
    return (
      entry.appearance.label_text ||
      localized(action?.name, i18n.language) ||
      entry.action_id
    );
  };

  const addEntry = () => {
    const first = defaultAction(plugins, "dial");
    if (!first) return;
    onChange([
      ...entries.slice(1),
      {
        plugin_id: first.plugin_id,
        action_id: first.action_id,
        settings: {},
        appearance: structuredClone(entries[0].appearance),
        long_press: null,
        double_press: null,
        turn_left: null,
        turn_right: null,
        turn_every: 2,
        steps: [],
        steps_off: [],
        repeat: false,
        toggled: false,
        stack: [],
      },
    ]);
    onSelect(entries.length);
  };

  return (
    <section className="inspector-section">
      <h3>{t("stack.title")}</h3>
      <p className="hint">{t("stack.hint")}</p>

      <ol className="stack-list">
        {entries.map((entry, entryIndex) => (
          <li key={entryIndex} className={entryIndex === position ? "active" : ""}>
            <button type="button" className="stack-entry" onClick={() => onSelect(entryIndex)}>
              <span className="stack-number">{entryIndex + 1}</span>
              <span className="stack-name">{name(entry)}</span>
            </button>
            {entryIndex > 0 && (
              <button
                type="button"
                className="btn tiny danger"
                title={t("common.remove")}
                onClick={() => {
                  onChange(entries.slice(1).filter((_, i) => i !== entryIndex - 1));
                  onSelect(Math.max(0, position - 1));
                }}
              >
                ✕
              </button>
            )}
          </li>
        ))}
      </ol>

      <div className="step-actions">
        <button type="button" className="btn small" onClick={addEntry}>
          + {t("stack.add")}
        </button>
        {entries.length > 1 && (
          <button
            type="button"
            className="btn small"
            onClick={() => {
              void api
                .cycleStack(pageId, index)
                .then(() => bumpPreview())
                .catch(() => undefined);
            }}
          >
            {t("stack.cycle")}
          </button>
        )}
      </div>
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

export type { Branch, Step };
