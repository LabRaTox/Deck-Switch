import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { api } from "../api/client";
import { useStore } from "../store";
import type { StoreAccount, StoreLoginStart, StorePlugin } from "../types";

/**
 * Der Plugin-Store in der App.
 *
 * Stöbern, installieren, anmelden, einreichen. Alles Netz-Bezogene läuft über
 * das lokale Backend und nicht von hier aus direkt zum Store: Dort liegt das
 * Anmeldetoken, dort wird die Prüfsumme geprüft, und dort gehört beides auch
 * hin — die Oberfläche soll nichts hüten müssen.
 */
export function StoreView() {
  const { t } = useTranslation();
  const reloadPlugins = useStore((s) => s.reloadPlugins);
  const installiert = useStore((s) => s.plugins);

  const [konto, setKonto] = useState<StoreAccount | null>(null);
  const [plugins, setPlugins] = useState<StorePlugin[] | null>(null);
  const [suche, setSuche] = useState("");
  const [fehler, setFehler] = useState("");
  const [laeuft, setLaeuft] = useState("");
  const [meldung, setMeldung] = useState("");

  const ladeKonto = useCallback(async () => {
    try {
      setKonto(await api.storeAccount());
    } catch {
      // Kein Konto zu haben ist kein Fehler — der Katalog steht auch ohne.
      setKonto(null);
    }
  }, []);

  const ladeKatalog = useCallback(async (q: string) => {
    setFehler("");
    try {
      const antwort = await api.storeCatalog("", q);
      setPlugins(antwort.plugins);
    } catch (exc) {
      setPlugins([]);
      setFehler(exc instanceof Error ? exc.message : String(exc));
    }
  }, []);

  useEffect(() => {
    void ladeKonto();
    void ladeKatalog("");
  }, [ladeKonto, ladeKatalog]);

  async function installiere(plugin: StorePlugin) {
    setLaeuft(plugin.slug);
    setFehler("");
    setMeldung("");
    try {
      const ergebnis = await api.storeInstall(plugin.slug);
      await reloadPlugins();
      setMeldung(t("store.installed", { name: plugin.name, version: ergebnis.version }));
    } catch (exc) {
      setFehler(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setLaeuft("");
    }
  }

  const istInstalliert = (slug: string) => installiert.some((p) => p.id === slug);

  return (
    <div className="page-view">
      <div className="page-head">
        <h2>{t("store.title")}</h2>
        <Anmeldung konto={konto} onAendern={ladeKonto} />
      </div>

      {/* Der Hinweis für die, die prüfen. Er steht ganz oben und nicht in
          einer Ecke: Wer ihn übersieht, erfährt von einer wartenden
          Einreichung erst, wenn er von sich aus nachsieht. */}
      {konto?.pending && konto.pending.submissions + konto.pending.reports > 0 && (
        <div className="store-hinweis">
          <span>
            {konto.pending.submissions > 0 &&
              t("store.pendingSubmissions", { count: konto.pending.submissions })}
            {konto.pending.submissions > 0 && konto.pending.reports > 0 && " · "}
            {konto.pending.reports > 0 &&
              t("store.pendingReports", { count: konto.pending.reports })}
          </span>
          <a
            className="btn"
            href={konto.pending.url}
            target="_blank"
            rel="noreferrer noopener"
          >
            {t("store.openReview")}
          </a>
        </div>
      )}

      <form
        className="row"
        style={{ margin: "0 0 16px" }}
        onSubmit={(ereignis) => {
          ereignis.preventDefault();
          void ladeKatalog(suche);
        }}
      >
        <input
          type="search"
          value={suche}
          placeholder={t("store.search")}
          onChange={(ereignis) => setSuche(ereignis.target.value)}
        />
        <button type="submit" className="btn">
          {t("store.searchButton")}
        </button>
      </form>

      {fehler && <p className="error-note">{fehler}</p>}
      {meldung && <p className="hint">{meldung}</p>}

      {plugins === null ? (
        <p className="hint">{t("store.loading")}</p>
      ) : plugins.length === 0 ? (
        <p className="empty-note">{t("store.empty")}</p>
      ) : (
        <div className="plugin-list">
          {plugins.map((plugin) => (
            <StoreKarte
              key={plugin.slug}
              plugin={plugin}
              schonDa={istInstalliert(plugin.slug)}
              laeuft={laeuft === plugin.slug}
              onInstallieren={() => void installiere(plugin)}
            />
          ))}
        </div>
      )}
    </div>
  );
}

/** Eine Kachel im Katalog — mit dem, was die Durchsicht gefunden hat. */
function StoreKarte({
  plugin,
  schonDa,
  laeuft,
  onInstallieren,
}: {
  plugin: StorePlugin;
  schonDa: boolean;
  laeuft: boolean;
  onInstallieren: () => void;
}) {
  const { t } = useTranslation();
  const warnungen = plugin.latest.warnings;

  return (
    <article className="plugin-card">
      <div className="plugin-card-head">
        <h3>{plugin.name}</h3>
        <span className="plugin-card-version">{plugin.latest.version}</span>
      </div>
      <p className="plugin-card-summary">{plugin.summary}</p>
      <p className="hint">
        {t("store.byAuthor", { author: plugin.author })} · {plugin.latest.downloads} ×
        {plugin.rating.up > 0 && ` · ♥ ${plugin.rating.up}`}
      </p>

      {/* Vor der Installation, nicht danach: Was das Plugin tut, soll man
          wissen, bevor es auf dem Rechner liegt. */}
      {warnungen.length > 0 && (
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
      )}

      <div className="row">
        <button
          type="button"
          className="btn primary"
          disabled={laeuft || schonDa}
          onClick={onInstallieren}
        >
          {schonDa
            ? t("store.alreadyInstalled")
            : laeuft
              ? t("store.installing")
              : t("store.install")}
        </button>
      </div>
    </article>
  );
}

/**
 * Die Anmeldung — Device Flow.
 *
 * Die App hat keine Rückruf-Adresse: Sie läuft auf ``127.0.0.1``, und ein
 * eigener kleiner Server dafür wäre eine offene Tür im Netz. Also zeigt sie
 * einen Code, und der Benutzer tippt ihn bei GitHub ein.
 */
function Anmeldung({
  konto,
  onAendern,
}: {
  konto: StoreAccount | null;
  onAendern: () => Promise<void>;
}) {
  const { t } = useTranslation();
  const [start, setStart] = useState<StoreLoginStart | null>(null);
  const [fehler, setFehler] = useState("");
  const abfrage = useRef<number | null>(null);

  // Ohne dieses Aufräumen liefe die Nachfrage weiter, wenn die Ansicht
  // gewechselt wird — und schriebe irgendwann in eine Komponente, die es
  // nicht mehr gibt.
  useEffect(() => () => {
    if (abfrage.current) window.clearInterval(abfrage.current);
  }, []);

  async function anmelden() {
    setFehler("");
    try {
      const begonnen = await api.storeLogin();
      setStart(begonnen);

      abfrage.current = window.setInterval(async () => {
        try {
          const antwort = await api.storeLoginPoll(begonnen.device_code);
          if (antwort.status === "ok") {
            if (abfrage.current) window.clearInterval(abfrage.current);
            abfrage.current = null;
            setStart(null);
            await onAendern();
          }
        } catch (exc) {
          if (abfrage.current) window.clearInterval(abfrage.current);
          abfrage.current = null;
          setStart(null);
          setFehler(exc instanceof Error ? exc.message : String(exc));
        }
        // GitHub bremst, wer zu oft fragt — das Intervall kommt von dort.
      }, Math.max(begonnen.interval, 5) * 1000);
    } catch (exc) {
      setFehler(exc instanceof Error ? exc.message : String(exc));
    }
  }

  async function abmelden() {
    await api.storeLogout();
    await onAendern();
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
