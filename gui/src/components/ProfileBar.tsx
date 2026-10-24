import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { api } from "../api/client";
import { useStore } from "../store";
import type { ProfileInfo, ProgramInfo } from "../types";
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

      {verwalten && (
        <ProfileVerwaltung
          anfangsProfil={aktuell}
          onClose={() => setVerwalten(false)}
        />
      )}
    </div>
  );
}

/**
 * Verwaltung als geteilte Ansicht: links die Namen aller Profile, rechts das
 * gewählte. Auf diese Weise bleibt die Liste auch bei vielen Profilen ein
 * Griff breit, und die Details eines Profils haben Platz.
 */
function ProfileVerwaltung({
  anfangsProfil,
  onClose,
}: {
  /** Welches Profil anfangs gewählt ist — das des bearbeiteten Decks. */
  anfangsProfil?: string;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const load = useStore((s) => s.load);
  const [liste, setListe] = useState<ProfileInfo[] | null>(null);
  const [programme, setProgramme] = useState<ProgramInfo[]>([]);
  const [gewaehlt, setGewaehlt] = useState(anfangsProfil ?? "");
  const [automatik, setAutomatik] = useState<{
    available: boolean;
    reason: string;
    window: { app: string; title: string };
  } | null>(null);
  const [fehler, setFehler] = useState("");
  const [hinweis, setHinweis] = useState("");
  const datei = useRef<HTMLInputElement>(null);
  const [neuerName, setNeuerName] = useState("");
  const [kopieVon, setKopieVon] = useState("");

  async function lade() {
    // Gleichzeitig und unabhängig: Die Programmliste braucht am längsten,
    // und scheitert die Automatik, sollen Profile und Programme trotzdem
    // stehen.
    const [profile, automatik, programme] = await Promise.allSettled([
      api.profiles(),
      api.smartProfileStatus(),
      api.programs(),
    ]);
    if (profile.status === "fulfilled") setListe(profile.value);
    if (automatik.status === "fulfilled") setAutomatik(automatik.value);
    if (programme.status === "fulfilled") setProgramme(programme.value);
    const gescheitert = [profile, automatik, programme].find(
      (ergebnis) => ergebnis.status === "rejected",
    );
    if (gescheitert) {
      const exc = gescheitert.reason;
      setFehler(exc instanceof Error ? exc.message : String(exc));
    }
  }

  useEffect(() => {
    void lade();
  }, []);

  // Das gewählte Profil kann weg sein — gelöscht etwa. Dann zeigt die Liste
  // eben das erste, still steht die Auswahl nie ins Leere.
  useEffect(() => {
    if (liste && liste.length > 0 && !liste.some((p) => p.id === gewaehlt)) {
      setGewaehlt(liste[0].id);
    }
  }, [liste, gewaehlt]);

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

  const gewaehltes = (liste ?? []).find((p) => p.id === gewaehlt) ?? null;

  return (
    <Modal title={t("profiles.manage")} width={780} height={600} onClose={onClose}>
      {fehler && <p className="error-note">{fehler}</p>}
      {hinweis && <p className="hint">{hinweis}</p>}
      <p className="hint">{t("profiles.intro")}</p>

      <div className="profil-split">
        <ul className="profil-liste" aria-label={t("profiles.selectProfile")}>
          {(liste ?? []).map((p) => (
            <li key={p.id}>
              <button
                type="button"
                className={p.id === gewaehlt ? "active" : ""}
                aria-current={p.id === gewaehlt ? "true" : undefined}
                onClick={() => setGewaehlt(p.id)}
              >
                <span>{p.name}</span>
                <small title={t("profiles.pages", { count: p.pages })}>
                  {p.pages}
                </small>
              </button>
            </li>
          ))}
        </ul>

        {gewaehltes && (
          <ProfilDetails
            key={gewaehltes.id}
            profil={gewaehltes}
            programme={programme}
            fenster={automatik?.window.app || ""}
            automatikAus={
              automatik && !automatik.available ? automatik.reason : ""
            }
            gesamt={(liste ?? []).length}
            arbeite={fuehreAus}
          />
        )}
      </div>

      <h4 className="section-title">{t("profiles.newSection")}</h4>
      <div className="profil-neu">
        <button
          type="button"
          className="btn small"
          onClick={() => datei.current?.click()}
        >
          {t("profiles.import")}
        </button>
        {/* Ein importiertes Profil kommt immer hinzu und ersetzt nie eines —
            deshalb braucht es hier keine Rückfrage. */}
        <input
          ref={datei}
          type="file"
          accept="application/zip,.zip"
          hidden
          onChange={(event) => {
            const gewaehltDatei = event.target.files?.[0];
            event.target.value = "";
            if (!gewaehltDatei) return;
            void fuehreAus(async () => {
              const neu = await api.importProfile(gewaehltDatei);
              setHinweis(t("profiles.importDone", { name: neu.name }));
            });
          }}
        />
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

/**
 * Das gewählte Profil im rechten Teil: Name und Zahlen oben, darunter die
 * Programme der Automatik, darunter die Tätigkeiten.
 */
function ProfilDetails({
  profil,
  programme,
  fenster,
  automatikAus,
  gesamt,
  arbeite,
}: {
  profil: ProfileInfo;
  programme: ProgramInfo[];
  /** Fensterklasse des gerade vorderen Fensters, leer ohne Automatik. */
  fenster: string;
  /** Warum die Automatik gerade nicht greift, leer wenn sie läuft. */
  automatikAus: string;
  /** Zahl aller Profile — das letzte lässt sich nicht löschen. */
  gesamt: number;
  arbeite: (arbeit: () => Promise<unknown>) => void;
}) {
  const { t, i18n } = useTranslation();
  const [manuell, setManuell] = useState("");

  const setzeApps = (apps: string[]) =>
    arbeite(() => api.setProfileApps(profil.id, apps));

  const fuegeHinzu = (name: string) => {
    const wert = name.trim();
    if (!wert) return;
    if (!profil.auto_apps.some((app) => app.toLowerCase() === wert.toLowerCase())) {
      setzeApps([...profil.auto_apps, wert]);
    }
  };

  // Schon gewählte Programme verschwinden aus der Auswahl. Der Programmname
  // steht mit am Eintrag, wenn er vom Anzeigenamen abweicht: Gewählt wird
  // immer der Programmname, denn den vergleicht die Automatik.
  const wahlbar = programme.filter(
    (p) =>
      !profil.auto_apps.some((app) => app.toLowerCase() === p.exec.toLowerCase()),
  );

  return (
    <div className="profil-details">
      <div className="profil-kopf">
        <input
          defaultValue={profil.name}
          onBlur={(event) => {
            const name = event.target.value.trim();
            if (name && name !== profil.name) {
              void arbeite(() => api.renameProfile(profil.id, name));
            }
          }}
        />
        <span className="hint">
          {t("profiles.pages", { count: profil.pages })}
          {profil.decks.length > 0 &&
            ` · ${t("profiles.inUse", { decks: profil.decks.join(", ") })}`}
        </span>
      </div>

      <div className="profil-auto">
        <label>{t("profiles.autoTitle")}</label>

        {profil.auto_apps.length > 0 && (
          <div className="profil-chips">
            {profil.auto_apps.map((app) => (
              <span className="profil-chip" key={app}>
                {app}
                <button
                  type="button"
                  title={t("profiles.removeProgram")}
                  onClick={() =>
                    setzeApps(profil.auto_apps.filter((app2) => app2 !== app))
                  }
                >
                  ✕
                </button>
              </span>
            ))}
          </div>
        )}

        <div className="profil-auswahl">
          {wahlbar.length > 0 ? (
            <select
              value=""
              title={t("profiles.addProgramHint")}
              aria-label={t("profiles.addProgram")}
              onChange={(event) => {
                if (event.target.value) fuegeHinzu(event.target.value);
              }}
            >
              <option value="">{t("profiles.addProgram")}</option>
              {wahlbar.map((p) => {
                const name =
                  i18n.language.startsWith("de") && p.name_de ? p.name_de : p.name;
                const anzeige =
                  name.toLowerCase() === p.exec.toLowerCase()
                    ? name
                    : `${name} (${p.exec})`;
                return (
                  <option key={`${p.name}:${p.exec}`} value={p.exec}>
                    {anzeige}
                  </option>
                );
              })}
            </select>
          ) : (
            <small className="help">{t("profiles.noPrograms")}</small>
          )}
          <input
            value={manuell}
            placeholder={t("profiles.programPlaceholder")}
            title={t("profiles.autoHelp")}
            onChange={(event) => setManuell(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                fuegeHinzu(manuell);
                setManuell("");
              }
            }}
          />
          {fenster && (
            <button
              type="button"
              className="btn small"
              onClick={() => fuegeHinzu(fenster)}
            >
              {t("profiles.addCurrent", { app: fenster })}
            </button>
          )}
        </div>
        <small className="help">
          {t("profiles.autoHelp")}
          {automatikAus && ` ${t("profiles.autoOff", { reason: automatikAus })}`}
        </small>
      </div>

      <div className="profil-aktionen">
        <button
          type="button"
          className="btn small"
          onClick={() =>
            void arbeite(() => api.createProfile(`${profil.name} (2)`, profil.id))
          }
        >
          {t("profiles.duplicate")}
        </button>
        <a className="btn small" href={api.profileExportUrl(profil.id)}>
          {t("profiles.export")}
        </a>
        <button
          type="button"
          className="btn small danger"
          disabled={gesamt <= 1}
          onClick={() => {
            // Ein Profil zu löschen heißt, alle seine Seiten zu löschen.
            // Das ist mehr, als der Knopf vermuten lässt.
            const frage = profil.decks.length
              ? t("profiles.deleteInUse", {
                  name: profil.name,
                  decks: profil.decks.join(", "),
                })
              : t("profiles.deleteConfirm", {
                  name: profil.name,
                  count: profil.pages,
                });
            if (window.confirm(frage)) void arbeite(() => api.deleteProfile(profil.id));
          }}
        >
          {t("profiles.delete")}
        </button>
      </div>
    </div>
  );
}
