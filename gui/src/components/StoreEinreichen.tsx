import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { api } from "../api/client";
import { useStore } from "../store";
import type { StoreMinePlugin, StoreMineVersion, StoreUploadResult } from "../types";
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
  const { t } = useTranslation();
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

  async function reicheEin(datei: File) {
    setLaeuft(datei.name);
    setFehler("");
    setErgebnis(null);
    try {
      setErgebnis(await api.storeUploadArchive(datei));
      await lade();
    } catch (exc) {
      setFehler(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setLaeuft("");
    }
  }

  async function nimmZurueck(plugin: StoreMinePlugin, version: StoreMineVersion) {
    // Zwei verschiedene Fragen, denn es sind zwei verschiedene Vorgänge: Was
    // freigegeben ist, hat womöglich schon jemand installiert.
    const frage =
      version.status === "approved"
        ? t("store.withdrawConfirm", { name: plugin.name, version: version.version })
        : t("store.deleteConfirm", { name: plugin.name, version: version.version });
    if (!window.confirm(frage)) return;

    setFehler("");
    try {
      await api.storeWithdraw(plugin.slug, version.version);
      await lade();
    } catch (exc) {
      setFehler(exc instanceof Error ? exc.message : String(exc));
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
      <Ablegefeld laeuft={!!laeuft} onDatei={(datei) => void reicheEin(datei)} />
      <p className="hint">{t("store.submitFormats")}</p>

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
                      <td className="store-fassung-knopf">
                        {/* Gesperrtes und schon Zurückgezogenes lässt der
                            Store nicht mehr anfassen — dann steht hier auch
                            kein Knopf, der nur eine Fehlermeldung brächte. */}
                        {(v.status === "pending" ||
                          v.status === "rejected" ||
                          v.status === "approved") && (
                          <button
                            type="button"
                            className="btn small danger"
                            onClick={() => void nimmZurueck(plugin, v)}
                          >
                            {t(v.status === "approved" ? "store.withdraw" : "store.delete")}
                          </button>
                        )}
                      </td>
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

/**
 * Das Feld, in das das Archiv wandert.
 *
 * Ziehen oder klicken — beides führt zum selben. Ein Fenster mit nur einem
 * Auswahlknopf sähe aus, als ginge Ziehen nicht, und genau das versucht jeder
 * zuerst.
 */
function Ablegefeld({
  laeuft,
  onDatei,
}: {
  laeuft: boolean;
  onDatei: (datei: File) => void;
}) {
  const { t } = useTranslation();
  const feld = useRef<HTMLInputElement>(null);
  const [ueber, setUeber] = useState(false);

  function nimm(dateien: FileList | null) {
    const datei = dateien?.[0];
    if (datei) onDatei(datei);
  }

  return (
    <div
      className={ueber ? "ablegefeld ueber" : "ablegefeld"}
      onDragOver={(e) => {
        e.preventDefault();
        setUeber(true);
      }}
      onDragLeave={() => setUeber(false)}
      onDrop={(e) => {
        e.preventDefault();
        setUeber(false);
        nimm(e.dataTransfer.files);
      }}
      onClick={() => feld.current?.click()}
    >
      <input
        ref={feld}
        type="file"
        accept=".zip,.tar,.tar.gz,.tgz,application/zip,application/x-tar,application/gzip"
        hidden
        onChange={(e) => {
          nimm(e.target.files);
          // Zurücksetzen, damit dieselbe Datei ein zweites Mal ausgewählt
          // werden kann — sonst löst der Browser kein Ereignis aus.
          e.target.value = "";
        }}
      />
      <strong>{laeuft ? t("store.submitting") : t("store.dropHere")}</strong>
      <span className="hint">{t("store.dropOrClick")}</span>
    </div>
  );
}
