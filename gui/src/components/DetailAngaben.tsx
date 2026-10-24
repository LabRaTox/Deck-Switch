import { useTranslation } from "react-i18next";

/** Was in der Detailansicht unter „Angaben“ stehen kann. Fehlt ein Wert, fällt die Zeile weg. */
export type Angaben = {
  type?: string | null;
  category?: string | null;
  version?: string | null;
  author?: string | null;
  license?: string | null;
  downloads?: string | null;
  released?: string | null;
  size?: string | null;
  minApp?: string | null;
  actions?: string | null;
  dials?: string | null;
  source?: string | null;
  support?: string | null;
};

/** Die Reihenfolge gilt für installierte Plugins und für Plugins im Store gleich. */
const REIHENFOLGE: (keyof Omit<Angaben, "support">)[] = [
  "type",
  "category",
  "version",
  "author",
  "license",
  "downloads",
  "released",
  "size",
  "minApp",
  "actions",
  "dials",
  "source",
];

/**
 * Der Kasten „Angaben“ einer Detailansicht.
 *
 * Installierte Plugins und Plugins im Store benutzen beide diese
 * Komponente, damit dieselben Angaben in derselben Reihenfolge stehen.
 */
export function DetailAngaben({ angaben }: { angaben: Angaben }) {
  const { t } = useTranslation();
  return (
    <dl>
      {REIHENFOLGE.filter((schluessel) => angaben[schluessel]).map((schluessel) => (
        <div key={schluessel} className="detail-zeile">
          <dt>{t(`plugins.detail.${schluessel}`)}</dt>
          <dd>{angaben[schluessel]}</dd>
        </div>
      ))}
      {angaben.support && (
        <div className="detail-zeile">
          <dt>{t("plugins.detail.support")}</dt>
          <dd>
            {/* Eine fremde Adresse aus einem Manifest: neues Fenster, ohne
                Zugriff auf das aufrufende. Sonst könnte die Zielseite
                hierher zurückgreifen. */}
            <a href={angaben.support} target="_blank" rel="noreferrer noopener">
              {t("plugins.detail.openSupport")}
            </a>
          </dd>
        </div>
      )}
    </dl>
  );
}
