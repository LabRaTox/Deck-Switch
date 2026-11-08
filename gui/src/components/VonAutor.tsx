import { useTranslation } from "react-i18next";

/**
 * „von <Autor>" auf einer Detailseite, der Name als Knopf: Ein Klick zeigt
 * alle Plugins dieses Autors in der Liste. Ohne `onAutor` ist es nur Text.
 * In den Karten der Liste bleibt der Name bewusst ohne Link.
 */
export function VonAutor({ autor, onAutor }: { autor: string; onAutor?: (autor: string) => void }) {
  const { t } = useTranslation();
  if (!onAutor) return <>{t("plugins.by", { author: autor })}</>;
  // Der Satz kommt aus der Übersetzung, nur der Name darin wird zum Knopf.
  const [vorher = "", nachher = ""] = t("plugins.by", { author: "\u0001" }).split("\u0001");
  return (
    <>
      {vorher}
      <button
        type="button"
        className="autor-link"
        title={t("plugins.authorFilter", { author: autor })}
        onClick={() => onAutor(autor)}
      >
        {autor}
      </button>
      {nachher}
    </>
  );
}
