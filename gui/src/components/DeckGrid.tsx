import { useState } from "react";
import { useTranslation } from "react-i18next";

import { api } from "../api/client";
import { localized } from "../i18n";
import { useStore } from "../store";
import type { ActionDescriptor, InputType, PluginInfo, Slot } from "../types";
import { DRAG_MIME, type ActionDragPayload } from "./ActionLibrary";
import { ContextMenu, type MenuItem } from "./ContextMenu";

const SLOT_MIME = "application/x-streamdeck-slot";

/**
 * Erzeugt eine frische Belegung aus einer Aktion.
 *
 * Icons bleiben absichtlich leer: das Backend greift dann auf `default_icon`
 * aus dem Manifest zurück. Erst wenn der User bewusst ein Icon wählt, wird
 * das hier hart eingetragen.
 */
export function makeSlot(
  plugin: PluginInfo,
  action: ActionDescriptor,
  language: string,
): Slot {
  const settings: Record<string, unknown> = {};
  for (const field of action.settings_schema) {
    if (field.default !== null && field.default !== undefined) {
      settings[field.key] = field.default;
    }
  }

  return {
    plugin_id: plugin.id,
    action_id: action.id,
    settings,
    appearance: {
      icon_by_state: {},
      icon_size: 55,
      label_text: localized(action.default_label, language),
      label_size: 16,
      label_color: "#ffffff",
      label_position: "bottom",
      show_label: true,
      background: {
        kind: "solid",
        color: "#000000",
        color2: "#1a1a1a",
        direction: "vertical",
        intensity: 12,
        accent: null,
        upload: null,
      },
    },
    long_press: null,
  };
}

/**
 * Die Deck-Ansicht: 4×2 Tasten oben, darunter der durchgehende Touchstrip
 * mit den vier Dial-Segmenten — im selben Seitenverhältnis wie das Gerät.
 */
export function DeckGrid() {
  const { t } = useTranslation();
  const device = useStore((s) => s.device);

  // Ohne verbundenes Gerät die Geometrie des Stream Deck+ annehmen — damit
  // sich Belegungen auch vorbereiten lassen, wenn das Deck gerade absteckt.
  const keyCount = device?.key_count || 8;
  const columns = device?.key_columns || 4;
  const dialCount = device?.dial_count ?? 4;

  // Die Kacheln schrumpfen mit der Spaltenzahl: acht Spalten (XL) passen
  // sonst nicht in die mittlere Spalte des Editors.
  const tileSize = columns >= 8 ? 76 : columns >= 5 ? 96 : 118;

  return (
    <div className="deck">
      <section className="deck-section">
        <h3>{t("grid.keys")}</h3>
        <div
          className="key-grid"
          style={{
            gridTemplateColumns: `repeat(${columns}, ${tileSize}px)`,
          }}
        >
          {Array.from({ length: keyCount }, (_, index) => (
            <SlotTile key={index} inputType="key" index={index} size={tileSize} />
          ))}
        </div>
      </section>

      {/* Dials und Touchstrip gibt es nur beim Plus — bei allen anderen
          Modellen entfällt der ganze Abschnitt, statt leer dazustehen. */}
      {dialCount > 0 && (
        <section className="deck-section">
          <h3>{t("grid.dials")}</h3>
          <div className="dial-strip">
            {Array.from({ length: dialCount }, (_, index) => (
              <SlotTile key={index} inputType="dial" index={index} />
            ))}
          </div>
          <div className="dial-knobs">
            {Array.from({ length: dialCount }, (_, index) => (
              <span key={index} className="knob" aria-hidden="true" />
            ))}
          </div>
        </section>
      )}
    </div>
  );
}

function SlotTile({
  inputType,
  index,
  size,
}: {
  inputType: InputType;
  index: number;
  /** Kantenlänge einer Taste in Pixeln; Dials rechnen mit ihrem Seitenverhältnis. */
  size?: number;
}) {
  const { t, i18n } = useTranslation();
  const [dropActive, setDropActive] = useState(false);
  const [menuAt, setMenuAt] = useState<{ x: number; y: number } | null>(null);

  const pageId = useStore((s) => s.currentPageId);
  const previewVersion = useStore((s) => s.previewVersion);
  const selection = useStore((s) => s.selection);
  const select = useStore((s) => s.select);
  const plugins = useStore((s) => s.plugins);
  const setSlot = useStore((s) => s.setSlot);
  const moveSlot = useStore((s) => s.moveSlot);
  const copySlot = useStore((s) => s.copySlot);
  const cutSlot = useStore((s) => s.cutSlot);
  const pasteSlot = useStore((s) => s.pasteSlot);
  const canPasteInto = useStore((s) => s.canPasteInto);
  const clipboard = useStore((s) => s.clipboard);
  const slot = useStore((s) =>
    s.slotAt({ inputType, index }),
  );

  const selected = selection?.inputType === inputType && selection.index === index;
  const plugin = plugins.find((p) => p.id === slot?.plugin_id);
  const action = plugin?.manifest.actions.find((a) => a.id === slot?.action_id);

  const handleDrop = async (event: React.DragEvent) => {
    event.preventDefault();
    setDropActive(false);

    const slotPayload = event.dataTransfer.getData(SLOT_MIME);
    if (slotPayload) {
      const from = JSON.parse(slotPayload) as { inputType: InputType; index: number };
      await moveSlot(from, { inputType, index });
      return;
    }

    const actionPayload = event.dataTransfer.getData(DRAG_MIME);
    if (!actionPayload) return;
    const { plugin_id, action_id } = JSON.parse(actionPayload) as ActionDragPayload;

    const targetPlugin = plugins.find((p) => p.id === plugin_id);
    const targetAction = targetPlugin?.manifest.actions.find((a) => a.id === action_id);
    if (!targetPlugin || !targetAction) return;
    // Aktionen, die diese Eingabeart nicht können, gar nicht erst ablegen.
    if (!targetAction.inputs.includes(inputType)) return;

    await setSlot(inputType, index, makeSlot(targetPlugin, targetAction, i18n.language));
    select({ inputType, index });
  };

  const accepts = (event: React.DragEvent) => {
    const types = Array.from(event.dataTransfer.types);
    return types.includes(DRAG_MIME) || types.includes(SLOT_MIME);
  };

  const here = { inputType, index };
  const pasteFits = canPasteInto(inputType);

  const menuItems: MenuItem[] = [
    {
      key: "copy",
      label: t("grid.copy"),
      disabled: !slot,
      onSelect: () => copySlot(here),
    },
    {
      key: "cut",
      label: t("grid.cut"),
      disabled: !slot,
      onSelect: () => void cutSlot(here),
    },
    {
      key: "paste",
      label: t("grid.paste"),
      disabled: !clipboard || !pasteFits,
      // Gesperrt heißt hier zweierlei — leere Ablage oder unpassende
      // Eingabeart. Ohne Begründung rätselt man, welches davon zutrifft.
      hint: !clipboard
        ? t("grid.pasteEmpty")
        : t("grid.pasteWrongInput", {
            input: t(inputType === "key" ? "grid.aKey" : "grid.aDial"),
          }),
      onSelect: () => void pasteSlot(here),
    },
    {
      key: "delete",
      label: t("grid.delete"),
      disabled: !slot,
      danger: true,
      separated: true,
      onSelect: () => void setSlot(inputType, index, null),
    },
  ];

  return (
    <div
      className={[
        "tile",
        inputType,
        selected ? "selected" : "",
        dropActive ? "drop" : "",
        slot ? "filled" : "empty",
      ]
        .filter(Boolean)
        .join(" ")}
      onClick={() => select({ inputType, index })}
      onContextMenu={(event) => {
        event.preventDefault();
        // Auswählen wie beim Linksklick — das Menü wirkt auf *diese* Kachel,
        // und der Inspektor soll dazu passen.
        select({ inputType, index });
        setMenuAt({ x: event.clientX, y: event.clientY });
      }}
      onDragOver={(event) => {
        if (!accepts(event)) return;
        event.preventDefault();
        event.dataTransfer.dropEffect = event.dataTransfer.types.includes(SLOT_MIME)
          ? "move"
          : "copy";
        setDropActive(true);
      }}
      onDragLeave={() => setDropActive(false)}
      onDrop={(event) => void handleDrop(event)}
      draggable={Boolean(slot)}
      onDragStart={(event) => {
        if (!slot) return;
        event.dataTransfer.setData(SLOT_MIME, JSON.stringify({ inputType, index }));
        event.dataTransfer.effectAllowed = "move";
      }}
      style={size && inputType === "key" ? { width: size, height: size } : undefined}
      title={
        slot && action
          ? `${localized(plugin?.manifest.name, i18n.language)} · ${localized(action.name, i18n.language)}`
          : t("grid.empty")
      }
    >
      {slot ? (
        <img
          className="tile-preview"
          src={api.previewUrl(pageId, inputType, index, previewVersion)}
          alt=""
          draggable={false}
        />
      ) : (
        <span className="tile-placeholder">{dropActive ? t("grid.dropHere") : "+"}</span>
      )}

      {slot && (
        <div className="tile-actions">
          <button
            type="button"
            title={t("grid.test")}
            onClick={(event) => {
              event.stopPropagation();
              void api.triggerSlot(pageId, inputType, index).catch(() => undefined);
            }}
          >
            ▶
          </button>
          <button
            type="button"
            title={t("grid.clear")}
            onClick={(event) => {
              event.stopPropagation();
              void setSlot(inputType, index, null);
            }}
          >
            ✕
          </button>
        </div>
      )}

      <span className="tile-index">{index + 1}</span>

      {menuAt && (
        <ContextMenu
          x={menuAt.x}
          y={menuAt.y}
          items={menuItems}
          onClose={() => setMenuAt(null)}
        />
      )}
    </div>
  );
}
