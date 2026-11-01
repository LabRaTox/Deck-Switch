import { useTranslation } from "react-i18next";

import { API_BASE } from "../api/client";
import { useStore } from "../store";

/** Die Beschreibungen stehen unter `about.<schluessel>`. */
const PROJEKTE = [
  {
    name: (
      <>
        EDGE<span className="wordmark-slash">//</span>DASH
      </>
    ),
    logo: "/edgedash.svg",
    schluessel: "edgedash",
    url: "https://github.com/LabRaTox/EdgeDisplayWidgets",
  },
  {
    name: "Nephthys",
    logo: "/nephthys.svg",
    schluessel: "nephthys",
    url: "https://nephthys.app",
  },
];

/** Die Beschreibungen stehen unter `about.credit.<schluessel>`. */
const CREDITS = [
  {
    name: "python-elgato-streamdeck",
    schluessel: "streamdeck",
    url: "https://github.com/abcminiuser/python-elgato-streamdeck",
  },
  { name: "FastAPI", schluessel: "fastapi", url: "https://fastapi.tiangolo.com" },
  { name: "Tauri", schluessel: "tauri", url: "https://tauri.app" },
  { name: "Tabler Icons", schluessel: "tabler", url: "https://tabler.io/icons" },
];

/**
 * Die Seite „Über“, erreichbar über das Menü „Hilfe“.
 *
 * Die Version kommt vom Backend und nicht aus dem Bau der Oberfläche: Wer
 * eine Fehlermeldung schickt, soll die Version dessen nennen, was die Arbeit
 * macht.
 */
export function AboutView() {
  const { t } = useTranslation();
  const version = useStore((s) => s.version);

  return (
    <div className="page-view about-view">
      <div>
        <h2>{t("about.title")}</h2>
        <p className="help">{t("about.description")}</p>
      </div>

      <section className="settings-card">
        <dl className="about-liste">
          <dt>{t("about.version")}</dt>
          <dd>{version || t("about.unknown")}</dd>
          <dt>API</dt>
          <dd>{API_BASE}</dd>
        </dl>
      </section>

      <section className="settings-card">
        <h3>{t("about.siblings")}</h3>
        {PROJEKTE.map((projekt) => (
          <a
            key={projekt.url}
            className="about-projekt"
            href={projekt.url}
            target="_blank"
            rel="noreferrer noopener"
          >
            <img src={projekt.logo} alt="" />
            <span>
              <strong>{projekt.name}</strong>
              <span className="help">{t(`about.${projekt.schluessel}`)}</span>
              <span className="help">{projekt.url}</span>
            </span>
          </a>
        ))}
      </section>

      <section className="settings-card">
        <h3>{t("about.credits")}</h3>
        <dl className="about-liste">
          {CREDITS.map((eintrag) => (
            <div key={eintrag.name} style={{ display: "contents" }}>
              <dt>{eintrag.name}</dt>
              <dd>
                {t(`about.credit.${eintrag.schluessel}`)} ·{" "}
                <a href={eintrag.url} target="_blank" rel="noreferrer noopener">
                  {eintrag.url}
                </a>
              </dd>
            </div>
          ))}
        </dl>
      </section>
    </div>
  );
}
