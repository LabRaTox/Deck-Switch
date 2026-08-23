import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { api } from "../api/client";
import type { StorePlugin } from "../types";
import { Bewertung } from "./Bewertung";
import { UiIcon } from "./UiIcon";
import { Warnungen } from "./StoreView";

/**
 * Die Detailseite eines Plugins, das nur im Store liegt.
 *
 * Aufgebaut wie die eines installierten Plugins — dieselbe Anordnung,
 * dieselben Klassen: Man soll nicht erst herausfinden müssen, wo man
 * gelandet ist, nur weil das Plugin noch nicht auf dem Rechner liegt. Was
 * hinzukommt, hat nur der Store: die Liste der Fassungen, die Funde der
 * Durchsicht und der Knopf zum Holen.
 *
 * Geladen wird erst hier und nicht schon für die Liste: Der Katalog liefert
 * je Plugin nur die neueste Fassung, alles Weitere kostet eine eigene Runde
 * übers Netz — und die lohnt nur für das eine, das jemand ansieht.
 */
export function StoreDetail({
  slug,
  /** Was schon in der Liste stand — damit sofort etwas dasteht. */
  bekannt,
  laeuft,
  onInstallieren,
  onBack,
}: {
  slug: string;
  bekannt: StorePlugin | null;
  laeuft: boolean;
  onInstallieren: (plugin: StorePlugin) => void;
  onBack: () => void;
}) {
  const { t } = useTranslation();
  const [plugin, setPlugin] = useState<StorePlugin | null>(bekannt);
  const [fehler, setFehler] = useState("");
  const [grosses, setGrosses] = useState(0);

  useEffect(() => {
    let abgebrochen = false;
    void (async () => {
      try {
        const daten = await api.storePlugin(slug);
        if (!abgebrochen) setPlugin(daten);
      } catch (exc) {
        if (!abgebrochen) setFehler(exc instanceof Error ? exc.message : String(exc));
      }
    })();
    return () => {
      abgebrochen = true;
    };
  }, [slug]);

  const zurueck = (
    <button type="button" className="btn small zurueck" onClick={onBack}>
      <UiIcon name="chevron-right" size={14} className="zurueck-pfeil" />
      {t("plugins.backToList")}
    </button>
  );

  if (!plugin) {
    return (
      <div className="plugin-detail">
        {zurueck}
        {fehler ? <p className="error-note">{fehler}</p> : <p className="hint">{t("store.loading")}</p>}
      </div>
    );
  }

  const neueste = plugin.latest;
  const bilder = neueste.screenshot_urls ?? [];
  const fassungen = plugin.versions ?? [];

  const angaben: { schluessel: string; wert: string | null }[] = [
    { schluessel: "type", wert: t(`plugins.types.${plugin.kind}`) },
    { schluessel: "category", wert: t(`plugins.categories.${plugin.category}`) },
    { schluessel: "version", wert: neueste.version },
    { schluessel: "author", wert: plugin.author },
    { schluessel: "license", wert: plugin.license },
    { schluessel: "downloads", wert: String(neueste.downloads) },
    { schluessel: "size", wert: `${Math.max(1, Math.round(neueste.size / 1024))} KB` },
    { schluessel: "released", wert: new Date(neueste.released_at).toLocaleDateString() },
    { schluessel: "minApp", wert: neueste.min_app_version },
  ];

  return (
    <div className="plugin-detail">
      {zurueck}

      <header className="detail-kopf">
        {neueste.icon_url ? (
          <img
            className="detail-icon"
            src={api.storeIconUrl(plugin.slug, neueste.version)}
            alt=""
          />
        ) : (
          <span className="detail-icon platzhalter">{plugin.name.slice(0, 1).toUpperCase()}</span>
        )}
        <div>
          <small className="detail-kategorie">{t(`plugins.categories.${plugin.category}`)}</small>
          <h2>{plugin.name}</h2>
          <small className="detail-autor">{t("plugins.by", { author: plugin.author })}</small>
        </div>
        <div className="detail-kopf-knoepfe">
          <button
            type="button"
            className="btn primary"
            disabled={laeuft}
            onClick={() => onInstallieren(plugin)}
          >
            {laeuft ? t("store.installing") : t("store.install")}
          </button>
          {plugin.source_url && (
            <a
              className="btn"
              href={plugin.source_url}
              target="_blank"
              rel="noreferrer noopener"
            >
              {t("store.source")}
            </a>
          )}
        </div>
      </header>

      {fehler && <p className="error-note">{fehler}</p>}

      <div className="detail-spalten">
        <div className="detail-haupt">
          {bilder.length > 0 && (
            <div className="detail-bilder">
              <img
                className="detail-bild-gross"
                src={api.storeScreenshotUrl(plugin.slug, neueste.version, grosses)}
                alt=""
              />
              {bilder.length > 1 && (
                <div className="detail-bild-reihe">
                  {bilder.map((_, i) => (
                    <button
                      key={i}
                      type="button"
                      className={i === grosses ? "detail-bild-klein aktiv" : "detail-bild-klein"}
                      onClick={() => setGrosses(i)}
                    >
                      <img
                        src={api.storeScreenshotUrl(plugin.slug, neueste.version, i)}
                        alt=""
                      />
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}

          <h3>{t("plugins.overview")}</h3>
          {/* Die lange Beschreibung steht nur in der Einzelansicht; bis sie
              da ist, steht die eine Zeile aus der Liste. */}
          <p className="detail-text">{plugin.description || plugin.summary}</p>

          {/* Vor der Installation, nicht danach: Was ein Plugin tut, soll man
              wissen, bevor es auf dem Rechner liegt. */}
          {neueste.warnings.length > 0 && <Warnungen warnungen={neueste.warnings} />}

          {neueste.changelog && (
            <>
              <h3>{t("plugins.whatsNew")}</h3>
              <p className="detail-text">{neueste.changelog}</p>
            </>
          )}

          {fassungen.length > 1 && (
            <>
              <h3>{t("store.versions")}</h3>
              <ul className="store-fassungen">
                {fassungen.map((v) => (
                  <li key={v.version}>
                    <strong>{v.version}</strong>
                    <span className="hint">
                      {new Date(v.released_at).toLocaleDateString()} · {v.downloads} ×
                      {/* Zurückgezogen heißt: nicht mehr im Katalog, aber wer
                          sie hat, behält sie. Das gehört dazu. */}
                      {v.state && v.state !== "approved"
                        ? ` · ${t(`store.status.${v.state}`)}`
                        : ""}
                    </span>
                    {v.note && <span className="hint"> — {v.note}</span>}
                  </li>
                ))}
              </ul>
            </>
          )}
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
          </dl>
          <Bewertung slug={plugin.slug} />
        </aside>
      </div>
    </div>
  );
}
