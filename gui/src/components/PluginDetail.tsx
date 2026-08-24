import { useState } from "react";
import { useTranslation } from "react-i18next";

import { api } from "../api/client";
import { localized } from "../i18n";
import type { PluginInfo, StorePlugin } from "../types";
import { Bewertung } from "./Bewertung";
import { UiIcon } from "./UiIcon";

/**
 * Die Detailseite eines Plugins.
 *
 * Sie tritt an die Stelle der Kachelliste, statt als Fenster darüber zu
 * liegen: Bilder, Beschreibung und Angaben brauchen die volle Breite, und
 * ein Fenster, das man erst wieder schließen muss, steht dem im Weg. Der
 * Weg zurück steht oben — dieselbe Bewegung wie im Browser.
 *
 * Die Angaben rechts stehen bewusst als Tabelle und nicht im Fließtext:
 * Man sucht darin einen einzelnen Wert („braucht das Dials?"), und dafür
 * ist eine Liste mit festen Zeilen schneller zu lesen als ein Absatz.
 */
export function PluginDetail({
  plugin,
  storeEintrag,
  onBack,
}: {
  plugin: PluginInfo;
  /**
   * Derselbe Plugin im Katalog, sofern es ihn dort gibt. Damit stehen auch
   * bei einem installierten Plugin die Downloadzahl und die Bewertung da —
   * die verschwanden bisher in dem Moment, in dem man es installiert hat,
   * also genau dann, wenn man eine Meinung dazu bekommt.
   */
  storeEintrag?: StorePlugin | null;
  onBack: () => void;
}) {
  const { t, i18n } = useTranslation();
  const [grosses, setGrosses] = useState(0);

  const manifest = plugin.manifest;
  const bilder = manifest.screenshots ?? [];
  const beschreibung = localized(manifest.description, i18n.language);
  const changelog = localized(manifest.changelog, i18n.language);

  /** Kann das Plugin Dials? Steht in den Aktionen, nicht im Manifestkopf. */
  const mitDials = manifest.actions.some((a) => a.inputs.includes("dial"));

  const angaben: { schluessel: string; wert: string | null }[] = [
    { schluessel: "type", wert: t(`plugins.types.${manifest.type}`) },
    {
      schluessel: "category",
      wert: t(`plugins.categories.${manifest.category ?? "other"}`),
    },
    { schluessel: "version", wert: manifest.version },
    { schluessel: "author", wert: manifest.author || null },
    { schluessel: "license", wert: manifest.license || null },
    {
      schluessel: "downloads",
      wert: storeEintrag ? String(storeEintrag.latest.downloads) : null,
    },
    {
      schluessel: "actions",
      // Bei einem Schoner stünde hier dauerhaft „0 Aktionen".
      // Nur die Zahl: Die Zeile heißt schon „Aktionen", und „15 Aktionen"
      // daneben sagt dasselbe zweimal.
      wert: manifest.type === "action" ? String(manifest.actions.length) : null,
    },
    {
      schluessel: "dials",
      wert:
        manifest.type === "action" ? t(mitDials ? "common.yes" : "common.no") : null,
    },
    { schluessel: "source", wert: t(plugin.builtin ? "plugins.builtin" : "plugins.installed") },
  ];

  return (
    <div className="plugin-detail">
      <button type="button" className="btn small zurueck" onClick={onBack}>
        <UiIcon name="chevron-right" size={14} className="zurueck-pfeil" />
        {t("plugins.backToList")}
      </button>

      <header className="detail-kopf">
        {plugin.has_icon ? (
          // Ohne Akzentfarbe dahinter: Ein Plugin bringt sein eigenes Logo
          // mit, und das steht für sich. Ein farbiges Quadrat darunter machte
          // aus dem OBS-Zeichen eine rote Kachel und schluckte die weißen
          // Flächen im Spotify-Zeichen.
          <img
            className="detail-icon"
            src={api.pluginIconUrl(plugin.id, manifest.version)}
            alt=""
          />
        ) : (
          <span className="detail-icon platzhalter" style={{ background: manifest.accent }}>
            {localized(manifest.name, i18n.language).slice(0, 1)}
          </span>
        )}
        <div>
          <small className="detail-kategorie">
            {t(`plugins.categories.${manifest.category ?? "other"}`)}
          </small>
          <h2>{localized(manifest.name, i18n.language)}</h2>
          {manifest.author && (
            <small className="detail-autor">
              {t("plugins.by", { author: manifest.author })}
            </small>
          )}
        </div>
      </header>

      <div className="detail-spalten">
        <div className="detail-haupt">
          {bilder.length > 0 && (
            <div className="detail-bilder">
              <img
                className="detail-bild-gross"
                src={api.pluginScreenshotUrl(plugin.id, grosses, manifest.version)}
                alt=""
              />
              {/* Die Reihe darunter nur, wenn es etwas zu wechseln gibt. */}
              {bilder.length > 1 && (
                <div className="detail-bild-reihe">
                  {bilder.map((_, i) => (
                    <button
                      key={i}
                      type="button"
                      className={i === grosses ? "detail-bild-klein aktiv" : "detail-bild-klein"}
                      onClick={() => setGrosses(i)}
                    >
                      <img src={api.pluginScreenshotUrl(plugin.id, i, manifest.version)} alt="" />
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}

          <h3>{t("plugins.overview")}</h3>
          <p className="detail-text">{beschreibung || t("plugins.noDescription")}</p>

          {changelog && (
            <>
              <h3>{t("plugins.whatsNew")}</h3>
              <p className="detail-text">{changelog}</p>
            </>
          )}

          {plugin.error && <p className="error-text">{plugin.error}</p>}
        </div>

        <aside className="detail-angaben">
          <h3>{t("plugins.details")}</h3>
          <dl>
            {angaben
              .filter((eintrag) => eintrag.wert)
              .map((eintrag) => (
                <div key={eintrag.schluessel} className="detail-zeile">
                  <dt>{t(`plugins.detail.${eintrag.schluessel}`)}</dt>
                  <dd>{eintrag.wert}</dd>
                </div>
              ))}
            {manifest.support && (
              <div className="detail-zeile">
                <dt>{t("plugins.detail.support")}</dt>
                <dd>
                  {/* Eine fremde Adresse aus einem Manifest: neues Fenster,
                      und ohne Zugriff auf das aufrufende — sonst könnte die
                      Zielseite hierher zurückgreifen. */}
                  <a href={manifest.support} target="_blank" rel="noreferrer noopener">
                    {t("plugins.detail.openSupport")}
                  </a>
                </dd>
              </div>
            )}
          </dl>
          {storeEintrag && <Bewertung slug={storeEintrag.slug} />}
        </aside>
      </div>
    </div>
  );
}
