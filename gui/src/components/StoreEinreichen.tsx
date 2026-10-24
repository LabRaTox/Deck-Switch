import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { api } from "../api/client";
import { useAblegefeld } from "../lib/abgelegt";
import { vergleicheVersionen } from "../lib/versionen";
import { useStore } from "../store";
import type { StoreMinePlugin, StoreMineVersion, StoreUploadResult } from "../types";
import { Modal } from "./Modal";

/** Fassungen von der höchsten Nummer zur niedrigsten, wie im Store. */
function nachNummer(versionen: StoreMineVersion[]): StoreMineVersion[] {
  return [...versionen].sort((a, b) => vergleicheVersionen(b.version, a.version));
}

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
  const [auswahl, setAuswahl] = useState("");

  // Ohne eigene Wahl steht das erste Plugin rechts, damit die Seite nicht
  // leer aussieht. Verschwindet das gewählte (zurückgezogen und gelöscht),
  // rückt ebenfalls das erste nach.
  const gewaehlt = meine?.find((p) => p.slug === auswahl) ?? meine?.[0] ?? null;

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
      const antwort = await api.storeUploadArchive(datei);
      setErgebnis(antwort);
      // Rechts steht danach das Plugin, das gerade eingereicht wurde.
      setAuswahl(antwort.slug);
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
    <Modal title={t("store.submitTitle")} onClose={onClose} width={960}>
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
      <Ablegefeld
        laeuft={!!laeuft}
        onDatei={(datei) => void reicheEin(datei)}
        onFehler={setFehler}
      />
      <p className="hint">{t("store.submitFormats")}</p>

      <h4>{t("store.mineTitle")}</h4>
      {meine === null ? (
        <p className="hint">{t("store.loading")}</p>
      ) : meine.length === 0 ? (
        <p className="hint">{t("store.mineEmpty")}</p>
      ) : (
        <div className="einreichen-raster">
          <ul className="einreichen-liste">
            {meine.map((plugin) => {
              const neueste = nachNummer(plugin.versions)[0];
              const wartend = plugin.versions.filter((v) => v.status === "pending").length;
              return (
                <li key={plugin.slug}>
                  <button
                    type="button"
                    className={plugin.slug === gewaehlt?.slug ? "einreichen-eintrag aktiv" : "einreichen-eintrag"}
                    onClick={() => setAuswahl(plugin.slug)}
                  >
                    <span className="einreichen-eintrag-name">
                      <strong>{plugin.name}</strong>
                      <span className="hint">{plugin.slug}</span>
                    </span>
                    <span className="einreichen-eintrag-stand">
                      {plugin.removedAt ? (
                        <span className="zustand blocked">{t("store.mineBlocked")}</span>
                      ) : (
                        neueste && (
                          <>
                            <span className="code">{neueste.version}</span>
                            <span className={`zustand ${neueste.status}`}>
                              {t(`store.status.${neueste.status}`)}
                            </span>
                          </>
                        )
                      )}
                      {wartend > 0 && neueste?.status !== "pending" && (
                        <span className="zustand pending">{t("store.mineWaiting", { count: wartend })}</span>
                      )}
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>

          <div className="einreichen-detail">
            {gewaehlt ? (
              <Fassungen plugin={gewaehlt} onZurueck={(v) => void nimmZurueck(gewaehlt, v)} />
            ) : (
              <p className="hint">{t("store.mineSelect")}</p>
            )}
          </div>
        </div>
      )}
    </Modal>
  );
}

/**
 * Die Fassungen eines eigenen Plugins, rechts neben der Liste.
 *
 * Feste Spalten, damit Datum und Downloads bei jeder Fassung an derselben
 * Stelle stehen. Die Notiz der Moderation bekommt eine eigene Zeile darunter,
 * sonst schöbe ein langer Text alle anderen Spalten zur Seite.
 */
function Fassungen({
  plugin,
  onZurueck,
}: {
  plugin: StoreMinePlugin;
  onZurueck: (version: StoreMineVersion) => void;
}) {
  const { t } = useTranslation();
  const versionen = nachNummer(plugin.versions);

  return (
    <>
      <div className="store-meine-kopf">
        <strong>{plugin.name}</strong>
        <span className="hint">{plugin.slug}</span>
        {plugin.removedAt ? (
          <span className="zustand blocked">{t("store.mineBlocked")}</span>
        ) : (
          plugin.visibility !== "listed" && (
            <span className="tag-store">{t(`store.visibility.${plugin.visibility}`)}</span>
          )
        )}
      </div>
      {plugin.removedAt && plugin.removedReason && <p className="error-note">{plugin.removedReason}</p>}

      {versionen.length === 0 ? (
        <p className="hint">{t("store.mineNoVersions")}</p>
      ) : (
        <table className="store-fassungen fest">
          <colgroup>
            <col style={{ width: "16%" }} />
            <col style={{ width: "26%" }} />
            <col style={{ width: "20%" }} />
            <col style={{ width: "14%" }} />
            <col />
          </colgroup>
          <thead>
            <tr>
              <th>{t("store.mineColVersion")}</th>
              <th>{t("store.mineColStatus")}</th>
              <th>{t("store.mineColDate")}</th>
              <th>{t("store.mineColDownloads")}</th>
              <th />
            </tr>
          </thead>
          {versionen.map((v) => {
            // Der Text der Moderation steht hier und nirgends sonst: Eine
            // Ablehnung ohne Begründung nimmt der Store gar nicht erst an.
            const notiz = v.reviewNote || v.stateNote || "";
            return (
              <tbody key={v.version}>
                <tr>
                  <td className="code">{v.version}</td>
                  <td>
                    <span className={`zustand ${v.status}`}>{t(`store.status.${v.status}`)}</span>
                  </td>
                  <td className="hint">{new Date(v.reviewedAt ?? v.submittedAt).toLocaleDateString()}</td>
                  <td className="hint">{v.downloadCount} ×</td>
                  <td className="store-fassung-knopf">
                    {/* Gesperrtes und schon Zurückgezogenes lässt der Store
                        nicht mehr anfassen, dann steht hier auch kein Knopf,
                        der nur eine Fehlermeldung brächte. */}
                    {(v.status === "pending" || v.status === "rejected" || v.status === "approved") && (
                      <button type="button" className="btn small danger" onClick={() => onZurueck(v)}>
                        {t(v.status === "approved" ? "store.withdraw" : "store.delete")}
                      </button>
                    )}
                  </td>
                </tr>
                {notiz && (
                  <tr className="store-fassung-notiz">
                    <td colSpan={5} className="hint">
                      {notiz}
                    </td>
                  </tr>
                )}
              </tbody>
            );
          })}
        </table>
      )}
    </>
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
  onFehler,
}: {
  laeuft: boolean;
  onDatei: (datei: File) => void;
  onFehler: (text: string) => void;
}) {
  const { t } = useTranslation();
  const feld = useRef<HTMLInputElement>(null);

  function nimm(dateien: ArrayLike<File> | null) {
    const datei = dateien?.[0];
    if (datei) onDatei(datei);
  }

  const ablegen = useAblegefeld({ onDateien: nimm, onFehler });

  return (
    <div
      ref={ablegen.ref}
      className={ablegen.ueber ? "ablegefeld ueber" : "ablegefeld"}
      {...ablegen.props}
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
