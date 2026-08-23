import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { api } from "../api/client";
import { useStore } from "../store";
import type { ProfileInfo } from "../types";
import { Modal } from "./Modal";
import { UiIcon } from "./UiIcon";

/**
 * Profilwahl über dem Seitenbaum.
 *
 * Ein Profil ist ein eigener Satz Seiten. Welches ein Deck zeigt, hängt am
 * Deck und nicht an der Anwendung — bei zwei Geräten kann jedes ein anderes
 * zeigen. Deshalb steht die Wahl hier und nicht in den Einstellungen: Man
 * wechselt sie beim Bauen, nicht beim Einrichten.
 */
export function ProfileBar() {
  const { t } = useTranslation();
  const config = useStore((s) => s.config);
  const activeDeck = useStore((s) => s.activeDeck);
  const load = useStore((s) => s.load);
  const [verwalten, setVerwalten] = useState(false);

  if (!config) return null;
  const aktuell =
    config.decks?.[activeDeck]?.profile_id ?? config.active_profile_id;
  const profile = Object.values(config.profiles);

  async function wechsle(id: string) {
    if (!id || id === aktuell) return;
    await api.updateDeck(activeDeck, { profile_id: id });
    await load();
  }

  return (
    <div className="profilbar">
      <label className="profilbar-label" htmlFor="profilwahl">
        {t("profiles.title")}
      </label>
      <select
        id="profilwahl"
        value={aktuell}
        onChange={(event) => void wechsle(event.target.value)}
      >
        {profile.map((p) => (
          <option key={p.id} value={p.id}>
            {p.name}
          </option>
        ))}
      </select>
      <button
        type="button"
        className="icon-btn"
        title={t("profiles.manage")}
        onClick={() => setVerwalten(true)}
      >
        <UiIcon name="adjustments" size={16} />
      </button>

      {verwalten && <ProfileVerwaltung onClose={() => setVerwalten(false)} />}
    </div>
  );
}

/** Anlegen, kopieren, umbenennen, löschen — alles an einem Ort. */
function ProfileVerwaltung({ onClose }: { onClose: () => void }) {
  const { t } = useTranslation();
  const load = useStore((s) => s.load);
  const [liste, setListe] = useState<ProfileInfo[] | null>(null);
  const [automatik, setAutomatik] = useState<{
    available: boolean;
    reason: string;
    window: { app: string; title: string };
  } | null>(null);
  const [fehler, setFehler] = useState("");
  const [neuerName, setNeuerName] = useState("");
  const [kopieVon, setKopieVon] = useState("");

  async function lade() {
    try {
      setListe(await api.profiles());
      setAutomatik(await api.smartProfileStatus());
    } catch (exc) {
      setFehler(exc instanceof Error ? exc.message : String(exc));
    }
  }

  useEffect(() => {
    void lade();
  }, []);

  async function fuehreAus(arbeit: () => Promise<unknown>) {
    setFehler("");
    try {
      await arbeit();
      await lade();
      await load();
    } catch (exc) {
      setFehler(exc instanceof Error ? exc.message : String(exc));
    }
  }

  return (
    <Modal title={t("profiles.manage")} width={560} onClose={onClose}>
      {fehler && <p className="error-note">{fehler}</p>}

      <ul className="profilliste">
        {(liste ?? []).map((p) => (
          <li key={p.id}>
            <input
              defaultValue={p.name}
              onBlur={(event) => {
                const name = event.target.value.trim();
                if (name && name !== p.name) void fuehreAus(() => api.renameProfile(p.id, name));
              }}
            />
            <span className="hint">
              {t("profiles.pages", { count: p.pages })}
              {p.decks.length > 0 && ` · ${t("profiles.inUse", { decks: p.decks.join(", ") })}`}
            </span>
            <input
              className="profil-apps"
              defaultValue={p.auto_apps.join(", ")}
              placeholder={t("profiles.autoPlaceholder")}
              title={t("profiles.autoHelp")}
              onBlur={(event) => {
                const apps = event.target.value.split(",").map((m) => m.trim()).filter(Boolean);
                if (apps.join("\u0000") !== p.auto_apps.join("\u0000")) {
                  void fuehreAus(() => api.setProfileApps(p.id, apps));
                }
              }}
            />
            <button
              type="button"
              className="btn small"
              onClick={() => void fuehreAus(() => api.createProfile(`${p.name} (2)`, p.id))}
            >
              {t("profiles.duplicate")}
            </button>
            <button
              type="button"
              className="btn small danger"
              disabled={(liste ?? []).length <= 1}
              onClick={() => {
                // Ein Profil zu löschen heißt, alle seine Seiten zu löschen.
                // Das ist mehr, als der Knopf vermuten lässt.
                const frage = p.decks.length
                  ? t("profiles.deleteInUse", { name: p.name, decks: p.decks.join(", ") })
                  : t("profiles.deleteConfirm", { name: p.name, count: p.pages });
                if (window.confirm(frage)) void fuehreAus(() => api.deleteProfile(p.id));
              }}
            >
              {t("profiles.delete")}
            </button>
          </li>
        ))}
      </ul>

      <p className="hint">
        {t("profiles.autoHelp")}
        {automatik && !automatik.available && automatik.reason
          ? ` — ${t("profiles.autoOff", { reason: automatik.reason })}`
          : ""}
        {automatik?.available && automatik.window.app
          ? ` — ${t("profiles.autoSeen", { app: automatik.window.app })}`
          : ""}
      </p>

      <div className="profil-neu">
        <input
          value={neuerName}
          placeholder={t("profiles.newName")}
          onChange={(event) => setNeuerName(event.target.value)}
        />
        <select value={kopieVon} onChange={(event) => setKopieVon(event.target.value)}>
          <option value="">{t("profiles.empty")}</option>
          {(liste ?? []).map((p) => (
            <option key={p.id} value={p.id}>
              {t("profiles.copyOf", { name: p.name })}
            </option>
          ))}
        </select>
        <button
          type="button"
          className="btn primary"
          onClick={() =>
            void fuehreAus(async () => {
              await api.createProfile(neuerName.trim(), kopieVon);
              setNeuerName("");
            })
          }
        >
          {t("profiles.add")}
        </button>
      </div>
    </Modal>
  );
}
