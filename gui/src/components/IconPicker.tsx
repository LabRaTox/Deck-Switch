import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { api } from "../api/client";
import { useStore } from "../store";
import type { IconRef } from "../types";
import { IconGlyph } from "./IconGlyph";
import { Modal } from "./Modal";

interface Props {
  value: IconRef | undefined;
  onChange: (icon: IconRef | undefined) => void;
  onClose: () => void;
  title?: string;
}

/**
 * Icon-Auswahl: Iconsets aus den installierten Iconset-Plugins plus eigene
 * Uploads. Die Priorität (Upload → Iconset → Platzhalter) setzt das Backend
 * um; hier wird nur ausgewählt.
 */
export function IconPicker({ value, onChange, onClose, title }: Props) {
  const { t } = useTranslation();
  const activeSet = useStore((s) => s.config?.app.active_iconset ?? "iconset-tabler");

  const [sets, setSets] = useState<{ id: string; name: string; count: number }[]>([]);
  const [setId, setSetId] = useState(value?.set_id ?? activeSet);
  const [query, setQuery] = useState("");
  const [icons, setIcons] = useState<string[]>([]);
  const [total, setTotal] = useState(0);
  const [uploads, setUploads] = useState<{ filename: string; url: string }[]>([]);
  const [color, setColor] = useState(value?.color ?? "#ffffff");
  const [uploadError, setUploadError] = useState("");
  const fileInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    api
      .iconSets()
      .then((result) => {
        setSets(result);
        if (!result.some((entry) => entry.id === setId) && result.length > 0) {
          setSetId(result[0].id);
        }
      })
      .catch(() => undefined);
    api.uploads().then(setUploads).catch(() => undefined);
  }, []);

  // Suche entprellen — 5000 Icons filtert man nicht bei jedem Tastenanschlag.
  useEffect(() => {
    if (!setId) return;
    let cancelled = false;
    const timer = window.setTimeout(() => {
      api
        .icons(setId, query, 300)
        .then((result) => {
          if (cancelled) return;
          setIcons(result.icons);
          setTotal(result.total);
        })
        .catch(() => undefined);
    }, 180);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [setId, query]);

  const pickFromSet = (name: string) => {
    onChange({ kind: "iconset", set_id: setId, name, color, upload: null });
    onClose();
  };

  const pickUpload = (filename: string) => {
    onChange({ kind: "upload", upload: filename, color, set_id: null, name: null });
    onClose();
  };

  const handleFiles = async (files: FileList | null) => {
    if (!files?.length) return;
    setUploadError("");
    try {
      const result = await api.upload(files[0]);
      setUploads((current) => [...current, result]);
      pickUpload(result.filename);
    } catch (error) {
      setUploadError(
        t("icons.uploadFailed", {
          error: error instanceof Error ? error.message : String(error),
        }),
      );
    }
  };

  return (
    <Modal title={title ?? t("icons.title")} onClose={onClose} className="icon-picker" width={880}>
      <div className="icon-picker-controls">
        <select value={setId} onChange={(event) => setSetId(event.target.value)}>
          {sets.map((entry) => (
            <option key={entry.id} value={entry.id}>
              {entry.name} ({entry.count})
            </option>
          ))}
        </select>

        <input
          className="search"
          type="search"
          value={query}
          placeholder={t("icons.search")}
          onChange={(event) => setQuery(event.target.value)}
        />

        <label className="color-input" title={t("icons.color")}>
          <input
            type="color"
            value={color}
            onChange={(event) => setColor(event.target.value)}
          />
        </label>

        <button
          type="button"
          className="btn small"
          onClick={() => {
            onChange(undefined);
            onClose();
          }}
        >
          {t("icons.none")}
        </button>
      </div>

      <p className="hint">{t("icons.showing", { shown: icons.length, total })}</p>

      <div className="icon-grid">
        {icons.map((name) => (
          <button
            key={name}
            type="button"
            className={
              value?.kind === "iconset" && value.name === name && value.set_id === setId
                ? "icon-cell active"
                : "icon-cell"
            }
            title={name}
            onClick={() => pickFromSet(name)}
          >
            <IconGlyph src={api.iconUrl(setId, name)} color={color} alt={name} />
          </button>
        ))}
      </div>

      <section className="uploads">
        <h3>{t("icons.uploads")}</h3>
        <div
          className="dropzone"
          onClick={() => fileInput.current?.click()}
          onDragOver={(event) => event.preventDefault()}
          onDrop={(event) => {
            event.preventDefault();
            void handleFiles(event.dataTransfer.files);
          }}
        >
          {t("icons.dropOrClick")}
          <input
            ref={fileInput}
            type="file"
            accept=".png,.jpg,.jpeg,.svg,.webp,.gif"
            hidden
            onChange={(event) => void handleFiles(event.target.files)}
          />
        </div>
        {uploadError && <p className="error-text">{uploadError}</p>}

        <div className="icon-grid uploads-grid">
          {uploads.map((entry) => (
            <button
              key={entry.filename}
              type="button"
              className={
                value?.kind === "upload" && value.upload === entry.filename
                  ? "icon-cell active"
                  : "icon-cell"
              }
              title={entry.filename}
              onClick={() => pickUpload(entry.filename)}
            >
              <IconGlyph
                src={api.uploadUrl(entry.filename)}
                mask={false}
                alt={entry.filename}
              />
            </button>
          ))}
        </div>
      </section>
    </Modal>
  );
}
