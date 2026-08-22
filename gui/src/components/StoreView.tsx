import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { api } from "../api/client";
import { useStore } from "../store";
import type { StoreAccount, StoreLoginStart, StorePlugin, StoreWarnung } from "../types";

/**
 * Die Teile, die der Store zur Plugin-Ansicht beisteuert.
 *
 * Keine eigene Seite: Installiert und Store stehen in *einer* Liste — wer
 * ein Plugin sucht, sucht ein Plugin, und ob es schon auf dem Rechner liegt,
 * ist eine Eigenschaft und kein eigener Ort.
 *
 * Alles Netz-Bezogene läuft über das lokale Backend und nicht von hier aus
 * direkt zum Store: Dort liegt das Anmeldetoken, dort wird die Prüfsumme
 * geprüft, und dort gehört beides auch hin.
 */

/** Eine Kachel für etwas, das es nur im Store gibt. */
export function StoreKarte({
  plugin,
  laeuft,
  onInstallieren,
}: {
  plugin: StorePlugin;
  laeuft: boolean;
  onInstallieren: () => void;
}) {
  const { t } = useTranslation();

  return (
    <div className="plugin-card store">
      <div className="plugin-head">
        <div className="plugin-title">
          <span className="plugin-name">{plugin.name}</span>
          <span className="plugin-meta">
            {plugin.latest.version} · {t("store.byAuthor", { author: plugin.author })}
          </span>
        </div>
        <span className="tag-store">{t("store.tag")}</span>
      </div>

      <p className="plugin-card-summary">{plugin.summary}</p>
      <p className="hint">
        {plugin.latest.downloads} ×{plugin.rating.up > 0 && ` · ♥ ${plugin.rating.up}`}
        {plugin.license && ` · ${plugin.license}`}
      </p>

      {/* Vor der Installation, nicht danach: Was ein Plugin tut, soll man
          wissen, bevor es auf dem Rechner liegt. */}
      {plugin.latest.warnings.length > 0 && <Warnungen warnungen={plugin.latest.warnings} />}

      <div className="row">
        <button
          type="button"
          className="btn primary"
          disabled={laeuft}
          onClick={onInstallieren}
        >
          {laeuft ? t("store.installing") : t("store.install")}
        </button>
        {plugin.source_url && (
          <a className="btn" href={plugin.source_url} target="_blank" rel="noreferrer noopener">
            {t("store.source")}
          </a>
        )}
      </div>
    </div>
  );
}

/** Was die Durchsicht gefunden hat — zugeklappt, aber da. */
export function Warnungen({ warnungen }: { warnungen: StoreWarnung[] }) {
  const { t } = useTranslation();
  return (
    <details className="store-warnungen">
      <summary>{t("store.warnings", { count: warnungen.length })}</summary>
      <ul>
        {warnungen.map((w, i) => (
          <li key={i}>
            <code>{w.kind}</code> {w.value}
            <span className="hint">
              {" "}
              ({w.file}
              {w.line ? `:${w.line}` : ""})
            </span>
          </li>
        ))}
      </ul>
    </details>
  );
}

/**
 * Der Hinweis für die, die prüfen dürfen.
 *
 * Ganz oben und nicht in einer Ecke: Wer ihn übersieht, erfährt von einer
 * wartenden Einreichung erst, wenn er von sich aus nachsieht.
 */
export function StoreHinweis() {
  const { t } = useTranslation();
  const pending = useStore((s) => s.storePending);
  if (!pending || pending.submissions + pending.reports === 0) return null;

  return (
    <div className="store-hinweis">
      <span>
        {pending.submissions > 0 &&
          t("store.pendingSubmissions", { count: pending.submissions })}
        {pending.submissions > 0 && pending.reports > 0 && " · "}
        {pending.reports > 0 && t("store.pendingReports", { count: pending.reports })}
      </span>
      <a className="btn" href={pending.url} target="_blank" rel="noreferrer noopener">
        {t("store.openReview")}
      </a>
    </div>
  );
}

/**
 * Die Anmeldung — Device Flow.
 *
 * Die App hat keine Rückruf-Adresse: Sie läuft auf `127.0.0.1`, und ein
 * eigener kleiner Server dafür wäre eine offene Tür im Netz. Also zeigt sie
 * einen Code, und der Benutzer tippt ihn bei GitHub ein.
 */
export function StoreAnmeldung() {
  const { t } = useTranslation();
  const refreshStorePending = useStore((s) => s.refreshStorePending);

  const [konto, setKonto] = useState<StoreAccount | null>(null);
  const [start, setStart] = useState<StoreLoginStart | null>(null);
  const [fehler, setFehler] = useState("");
  const abfrage = useRef<number | null>(null);

  const ladeKonto = useCallback(async () => {
    try {
      setKonto(await api.storeAccount());
    } catch {
      // Kein Konto zu haben ist kein Fehler — der Katalog steht auch ohne.
      setKonto(null);
    }
    await refreshStorePending();
  }, [refreshStorePending]);

  useEffect(() => {
    void ladeKonto();
  }, [ladeKonto]);

  // Ohne dieses Aufräumen liefe die Nachfrage weiter, wenn die Ansicht
  // gewechselt wird — und schriebe irgendwann in eine Komponente, die es
  // nicht mehr gibt.
  useEffect(
    () => () => {
      if (abfrage.current) window.clearTimeout(abfrage.current);
    },
    [],
  );

  function beende() {
    if (abfrage.current) window.clearTimeout(abfrage.current);
    abfrage.current = null;
  }

  async function anmelden() {
    setFehler("");
    beende();
    try {
      const begonnen = await api.storeLogin();
      setStart(begonnen);

      // Kein festes Intervall, sondern ein Kreislauf, der sich selbst neu
      // stellt. Der Grund ist `slow_down`: GitHub verlangt dann einen um
      // fünf Sekunden größeren Abstand und antwortet sonst bis zum Ablauf
      // des Codes dasselbe — die Anmeldung wäre längst durch, und die App
      // zeigte weiter den Code.
      let abstand = Math.max(begonnen.interval, 5) * 1000;

      const nachfragen = async () => {
        try {
          const antwort = await api.storeLoginPoll(begonnen.device_code);
          if (antwort.status === "ok") {
            beende();
            setStart(null);
            await ladeKonto();
            return;
          }
          if (antwort.status === "slow_down") {
            abstand += (antwort.backoff ?? 5) * 1000;
          }
          abfrage.current = window.setTimeout(() => void nachfragen(), abstand);
        } catch (exc) {
          beende();
          setStart(null);
          setFehler(exc instanceof Error ? exc.message : String(exc));
        }
      };

      abfrage.current = window.setTimeout(() => void nachfragen(), abstand);
    } catch (exc) {
      setFehler(exc instanceof Error ? exc.message : String(exc));
    }
  }

  async function abmelden() {
    await api.storeLogout();
    await ladeKonto();
  }

  if (start) {
    return (
      <div className="store-anmeldung">
        <span className="hint">{t("store.enterCode")}</span>
        <code className="store-code">{start.user_code}</code>
        <a className="btn" href={start.verification_uri} target="_blank" rel="noreferrer noopener">
          {t("store.openGithub")}
        </a>
      </div>
    );
  }

  if (konto?.user) {
    return (
      <div className="store-anmeldung">
        <span className="hint">{konto.user.handle}</span>
        <button type="button" className="btn" onClick={() => void abmelden()}>
          {t("store.logout")}
        </button>
      </div>
    );
  }

  return (
    <div className="store-anmeldung">
      {fehler && <span className="error-note">{fehler}</span>}
      <button type="button" className="btn" onClick={() => void anmelden()}>
        {t("store.login")}
      </button>
    </div>
  );
}
