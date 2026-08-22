import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { api } from "../api/client";
import { localized } from "../i18n";
import { useStore } from "../store";
import type { StoreMinePlugin, StoreUploadResult } from "../types";
import { Modal } from "./Modal";

/**
 * Einreichen und nachsehen, was daraus geworden ist.
 *
 * Beides in einem Fenster, weil es dieselbe Frage ist: Was habe ich in den
 * Store gegeben, und wo steht es? Wer nur eines von beidem sieht, reicht im
 * Zweifel zweimal ein.
 *
 * Gepackt wird im Backend, nicht hier: Dort liegt der Plugin-Ordner, dort
 * weiß man, was hineingehört — und ein Archiv, das die Oberfläche baut,
 * müsste erst durch den Browser wandern, um denselben Weg zurückzunehmen.
 */
export function StoreEinreichen({ onClose }: { onClose: () => void }) {
  const { t, i18n } = useTranslation();
  const installiert = useStore((s) => s.plugins);
  const konto = useStore((s) => s.storeKonto);

  const [meine, setMeine] = useState<StoreMinePlugin[] | null>(null);
  const [fehler, setFehler] = useState("");
  const [laeuft, setLaeuft] = useState("");
  const [ergebnis, setErgebnis] = useState<StoreUploadResult | null>(null);

  const lade = useCallback(async () => {
    try {
      setMeine((await api.storeMine()).plugins);
    } catch (exc) {
      setMeine([]);
      setFehler(exc instanceof Error ? exc.message : String(exc));
    }
  }, []);

  useEffect(() => {
    if (konto?.user) void lade();
  }, [konto?.user, lade]);

  /**
   * Einreichen kann nur, was selbst installiert und nicht mitgeliefert ist.
   *
   * Ein eingebautes Plugin gehört schon zur App — es im Store einzureichen
   * ginge schief, denn seine Kennung ist dort für die App reserviert.
   */
  const einreichbar = installiert.filter((p) => !p.builtin);

  async function reicheEin(pluginId: string) {
    setLaeuft(pluginId);
    setFehler("");
    setErgebnis(null);
    try {
      setErgebnis(await api.storeUpload(pluginId));
      await lade();
    } catch (exc) {
      setFehler(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setLaeuft("");
    }
  }

  if (!konto?.user) {
    return (
      <Modal title={t("store.submitTitle")} onClose={onClose}>
        <p className="hint">{t("store.submitNeedsLogin")}</p>
      </Modal>
    );
  }

  return (
    <Modal title={t("store.submitTitle")} onClose={onClose}>
      {fehler && <p className="error-note">{fehler}</p>}

      {ergebnis && (
        <div className={ergebnis.status === "approved" ? "store-quittung gut" : "store-quittung"}>
          <strong>
            {ergebnis.slug} {ergebnis.version}
          </strong>
          <p>{ergebnis.message}</p>
          {/* Was die Durchsicht gefunden hat, erfährt der Autor sofort — er
              soll nicht erst aus einer Ablehnung schließen müssen, dass
              jemand etwas gefunden hat. */}
          {ergebnis.warnings > 0 && (
            <p className="hint">{t("store.submitFindings", { count: ergebnis.warnings })}</p>
          )}
        </div>
      )}

      <h4>{t("store.submitPick")}</h4>
      {einreichbar.length === 0 ? (
        <p className="hint">{t("store.submitNothing")}</p>
      ) : (
        <ul className="store-einreichen">
          {einreichbar.map((plugin) => (
            <li key={plugin.id}>
              <div>
                <strong>{localized(plugin.manifest.name, i18n.language)}</strong>
                <span className="hint">
                  {" "}
                  {plugin.id} · {plugin.manifest.version}
                </span>
              </div>
              <button
                type="button"
                className="btn"
                disabled={laeuft === plugin.id}
                onClick={() => void reicheEin(plugin.id)}
              >
                {laeuft === plugin.id ? t("store.submitting") : t("store.submit")}
              </button>
            </li>
          ))}
        </ul>
      )}

      <h4>{t("store.mineTitle")}</h4>
      {meine === null ? (
        <p className="hint">{t("store.loading")}</p>
      ) : meine.length === 0 ? (
        <p className="hint">{t("store.mineEmpty")}</p>
      ) : (
        <ul className="store-meine">
          {meine.map((plugin) => (
            <li key={plugin.slug}>
              <div className="store-meine-kopf">
                <strong>{plugin.name}</strong>
                <span className="hint">{plugin.slug}</span>
                {plugin.visibility !== "listed" && (
                  <span className="tag-store">{t(`store.visibility.${plugin.visibility}`)}</span>
                )}
              </div>
              <table className="store-fassungen">
                <tbody>
                  {plugin.versions.map((v) => (
                    <tr key={v.version}>
                      <td className="code">{v.version}</td>
                      <td>
                        <span className={`zustand ${v.status}`}>
                          {t(`store.status.${v.status}`)}
                        </span>
                      </td>
                      <td className="hint">
                        {new Date(v.reviewedAt ?? v.submittedAt).toLocaleDateString()}
                      </td>
                      <td className="hint">
                        {/* Der Text der Moderation steht hier und nirgends
                            sonst: Eine Ablehnung ohne Begründung nimmt der
                            Store gar nicht erst an. */}
                        {v.reviewNote || v.stateNote || ""}
                      </td>
                      <td className="hint">{v.downloadCount} ×</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </li>
          ))}
        </ul>
      )}
    </Modal>
  );
}
