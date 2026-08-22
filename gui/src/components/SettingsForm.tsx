import { useEffect, useRef, useState } from "react";

import { api } from "../api/client";
import { localized } from "../i18n";
import { useTranslation } from "react-i18next";
import type { SettingsField } from "../types";
import { HotkeyInput } from "./HotkeyInput";
import { PfadText } from "./PfadText";

interface Props {
  pluginId: string;
  schema: SettingsField[];
  values: Record<string, unknown>;
  onChange: (key: string, value: unknown) => void;
}

/**
 * Baut ein Formular allein aus dem Schema im Plugin-Manifest.
 *
 * Dadurch muss die GUI kein einziges Plugin namentlich kennen — ein
 * nachinstalliertes Drittanbieter-Plugin bekommt genau dieselbe
 * Bedienoberfläche wie die eingebauten.
 */
export function SettingsForm({ pluginId, schema, values, onChange }: Props) {
  const { i18n } = useTranslation();

  const visible = schema.filter((field) => {
    if (!field.depends_on) return true;
    return Object.entries(field.depends_on).every(
      ([key, expected]) => values[key] === expected,
    );
  });

  if (visible.length === 0) return null;

  return (
    <div className="settings-form">
      {visible.map((field) => (
        <Field
          key={field.key}
          pluginId={pluginId}
          field={field}
          value={values[field.key] ?? field.default}
          // Werte der Felder, von denen die Auswahlliste abhängt: ändert
          // sich eines davon, lädt das Feld seine Optionen neu.
          dependencies={(field.options_depend_on ?? [])
            .map((key) => String(values[key] ?? ""))
            .join(" ")}
          context={values}
          onChange={(value) => onChange(field.key, value)}
          language={i18n.language}
        />
      ))}
    </div>
  );
}

function Field({
  pluginId,
  field,
  value,
  dependencies,
  context,
  onChange,
  language,
}: {
  pluginId: string;
  field: SettingsField;
  value: unknown;
  dependencies: string;
  context: Record<string, unknown>;
  onChange: (value: unknown) => void;
  language: string;
}) {
  const { t } = useTranslation();
  const label = localized(field.label, language) || field.key;
  const help = localized(field.help, language);
  const placeholder = localized(field.placeholder, language);

  const [options, setOptions] = useState(
    field.options.map((option) => ({
      value: option.value,
      label: localized(option.label, language),
      unavailable: option.unavailable ?? null,
    })),
  );
  const [loadingOptions, setLoadingOptions] = useState(false);

  // Dynamische Optionen (Audio-Geräte, OBS-Szenen, Discord-Kanäle …) kommen
  // erst zur Laufzeit vom Plugin. `dependencies` steckt in der Abhängigkeits-
  // liste, damit die Liste neu geladen wird, sobald sich das übergeordnete
  // Feld ändert — etwa die Filter, wenn eine andere Quelle gewählt wird.
  const contextRef = useRef(context);
  contextRef.current = context;

  useEffect(() => {
    if (!field.options_source) return;
    let cancelled = false;
    setLoadingOptions(true);
    api
      .pluginOptions(pluginId, field.options_source, contextRef.current)
      .then((result) => {
        // Dynamische Listen kommen vom Plugin, nicht aus dem Manifest —
        // Anforderungen an die Sitzung gibt es dort nicht.
        if (!cancelled)
          setOptions(result.map((o) => ({ ...o, unavailable: null })));
      })
      .catch(() => undefined)
      .finally(() => {
        if (!cancelled) setLoadingOptions(false);
      });
    return () => {
      cancelled = true;
    };
  }, [pluginId, field.options_source, dependencies]);

  const id = `${pluginId}-${field.key}`;

  return (
    <div className={`field field-${field.type}`}>
      {field.type !== "bool" && <label htmlFor={id}>{label}</label>}

      {field.type === "bool" ? (
        <label className="checkbox" htmlFor={id}>
          <input
            id={id}
            type="checkbox"
            checked={Boolean(value)}
            onChange={(event) => onChange(event.target.checked)}
          />
          <span>{label}</span>
        </label>
      ) : field.type === "select" ? (
        <select
          id={id}
          value={String(value ?? "")}
          onChange={(event) => {
            const picked = options.find((o) => String(o.value) === event.target.value);
            onChange(picked ? picked.value : event.target.value);
          }}
        >
          <option value="">{loadingOptions ? "…" : "—"}</option>
          {options
            // Was diese Sitzung nicht hergibt, gehört nicht zur Auswahl.
            // Die *gewählte* bleibt aber stehen, auch wenn sie hier nichts
            // bewirkt: Sonst stünde in einer bestehenden Belegung plötzlich
            // „—", und beim nächsten Speichern wäre sie still gelöscht.
            .filter(
              (option) =>
                !option.unavailable || String(option.value) === String(value ?? ""),
            )
            .map((option) => (
              <option key={String(option.value)} value={String(option.value)}>
                {option.unavailable
                  ? t("settings.optionUnavailable", { label: option.label })
                  : option.label}
              </option>
            ))}
        </select>
      ) : field.type === "number" ? (
        <input
          id={id}
          type="number"
          value={value === undefined || value === null ? "" : Number(value)}
          min={field.min ?? undefined}
          max={field.max ?? undefined}
          step={field.step ?? 1}
          onChange={(event) =>
            onChange(event.target.value === "" ? null : Number(event.target.value))
          }
        />
      ) : field.type === "color" ? (
        <div className="color-input">
          <input
            id={id}
            type="color"
            value={String(value ?? "#ffffff")}
            onChange={(event) => onChange(event.target.value)}
          />
          <input
            type="text"
            value={String(value ?? "")}
            onChange={(event) => onChange(event.target.value)}
          />
        </div>
      ) : field.type === "hotkey" ? (
        <SendableHotkey
          id={id}
          value={String(value ?? "")}
          placeholder={placeholder}
          onChange={onChange}
        />
      ) : field.type === "file" ? (
        <FileInput id={id} value={String(value ?? "")} onChange={onChange} />
      ) : field.type === "password" ? (
        <input
          id={id}
          type="password"
          value={String(value ?? "")}
          placeholder={placeholder}
          autoComplete="off"
          onChange={(event) => onChange(event.target.value)}
        />
      ) : (
        <input
          id={id}
          type="text"
          value={String(value ?? "")}
          placeholder={placeholder}
          onChange={(event) => onChange(event.target.value)}
        />
      )}

      {help && (
        <small className="help">
          <PfadText text={help} />
        </small>
      )}
    </div>
  );
}


/**
 * Kombination für eine Taste, die sie später *sendet*.
 *
 * Dafür braucht es ein virtuelles Eingabegerät. Ob es das gibt, muss man
 * sehen, bevor man eine Taste belegt und sich später wundert — deshalb
 * fragt dieses Feld beim Backend nach und reicht die Antwort ans
 * Aufnahmefeld durch.
 */
function SendableHotkey({
  id,
  value,
  placeholder,
  onChange,
}: {
  id: string;
  value: string;
  placeholder: string;
  onChange: (value: unknown) => void;
}) {
  const [status, setStatus] = useState<{ available: boolean; reason: string } | null>(
    null,
  );

  useEffect(() => {
    api
      .inputStatus()
      .then((result) => setStatus({ available: result.available, reason: result.reason }))
      .catch(() => undefined);
  }, []);

  return (
    <HotkeyInput
      id={id}
      value={value}
      placeholder={placeholder}
      warning={status && !status.available ? status.reason : null}
      onChange={onChange}
    />
  );
}

/** Pfad zu einer Datei — mit Dateiauswahl, wo der Browser sie hergibt. */
function FileInput({
  id,
  value,
  onChange,
}: {
  id: string;
  value: string;
  onChange: (value: unknown) => void;
}) {
  const { t } = useTranslation();
  return (
    <div className="file-input">
      <input
        id={id}
        type="text"
        value={value}
        placeholder="/pfad/zur/datei"
        onChange={(event) => onChange(event.target.value)}
      />
      <label className="btn small">
        {t("common.choose")}
        <input
          type="file"
          hidden
          onChange={(event) => {
            const file = event.target.files?.[0];
            // Der Browser gibt aus Sicherheitsgründen keinen Pfad heraus —
            // nur den Namen. Deshalb wird er an den zuletzt genutzten Ordner
            // gehängt, wenn schon einer eingetragen ist.
            if (!file) return;
            const folder = value.includes("/")
              ? value.slice(0, value.lastIndexOf("/") + 1)
              : "";
            onChange(`${folder}${file.name}`);
          }}
        />
      </label>
    </div>
  );
}
