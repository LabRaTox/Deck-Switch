import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { api } from "../api/client";
import type { StorePlugin } from "../types";
import { Bewertung } from "./Bewertung";
import { type Angaben, DetailAngaben } from "./DetailAngaben";
import { PfadText } from "./PfadText";
import { storeAenderungen, storeBeschreibung, storeName } from "./storeTexte";
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
  const { t, i18n } = useTranslation();
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

  const angaben: Angaben = {
    type: t(`plugins.types.${plugin.kind}`),
    category: t(`plugins.categories.${plugin.category}`),
    version: neueste.version,
    author: plugin.author,
    license: plugin.license,
    downloads: String(neueste.downloads),
    released: new Date(neueste.released_at).toLocaleDateString(),
    size: `${Math.max(1, Math.round(neueste.size / 1024))} KB`,
    minApp: neueste.min_app_version,
    // Ältere Stores liefern beides nicht, dann fällt die Zeile weg.
    actions: neueste.actions != null ? String(neueste.actions) : null,
    dials: neueste.dials != null ? t(neueste.dials ? "common.yes" : "common.no") : null,
    source: t("store.tag"),
    // Der Store legt das Feld `support` aus dem Manifest als `source_url` ab.
    support: plugin.source_url,
  };

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
          <span className="detail-icon platzhalter">
            {storeName(plugin, i18n.language).slice(0, 1).toUpperCase()}
          </span>
        )}
        <div>
          <small className="detail-kategorie">{t(`plugins.categories.${plugin.category}`)}</small>
          <h2>{storeName(plugin, i18n.language)}</h2>
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
          <p className="detail-text">
            <PfadText text={storeBeschreibung(plugin, i18n.language)} />
          </p>

          {/* Vor der Installation, nicht danach: Was ein Plugin tut, soll man
              wissen, bevor es auf dem Rechner liegt. */}
          {neueste.warnings.length > 0 && <Warnungen warnungen={neueste.warnings} />}

          {storeAenderungen(neueste, i18n.language) && (
            <>
              <h3>{t("plugins.whatsNew")}</h3>
              <p className="detail-text">{storeAenderungen(neueste, i18n.language)}</p>
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
                    {v.note && <span className="hint"> · {v.note}</span>}
                  </li>
                ))}
              </ul>
            </>
          )}
        </div>

        <aside className="detail-angaben">
          <h3>{t("plugins.details")}</h3>
          <DetailAngaben angaben={angaben} />
          <Bewertung slug={plugin.slug} />
        </aside>
      </div>
    </div>
  );
}
