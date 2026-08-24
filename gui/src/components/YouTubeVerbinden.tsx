/**
 * Der Weg, sich bei YouTube anzumelden.
 *
 * Derselbe Gerätecode wie bei Twitch: Das Plugin holt einen Code, hier
 * steht er, eingetippt wird er bei Google. Danach fragt diese Ansicht so
 * lange nach, bis das Plugin sagt, dass es geklappt hat.
 *
 * Das Nachfragen läuft im Takt, den Google vorgibt — schneller zu fragen
 * beantwortet es mit „slow_down" statt mit einem Token.
 */

import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { api } from "../api/client";
import { useStore } from "../store";

interface Stand {
  angemeldet?: boolean;
  konto?: string;
  fehler?: string;
}

interface Code {
  code: string;
  url: string;
  interval: number;
}

export function YouTubeVerbinden({ vorher }: { vorher?: () => Promise<void> }) {
  const { t } = useTranslation();
  // Nach dem An- und Abmelden ändert sich, was die Plugin-Karte über ihren
  // Zustand sagt. Ohne dieses Auffrischen stünde dort weiter „nicht mit
  // Twitch verbunden", bis jemand die Seite neu lädt.
  const ladePluginListe = useStore((s) => s.refreshPlugins);
  const [stand, setStand] = useState<Stand>({});
  const [code, setCode] = useState<Code | null>(null);
  const [laeuft, setLaeuft] = useState(false);
  const [fehler, setFehler] = useState("");
  const uhr = useRef<number | null>(null);

  useEffect(() => {
    api
      .pluginCommand("youtube", "status")
      .then((ergebnis) => setStand(ergebnis as unknown as Stand))
      .catch(() => undefined);
    // Ohne dieses Aufräumen liefe die Nachfrage weiter, wenn das Fenster
    // zugeht — und schriebe in eine Ansicht, die es nicht mehr gibt.
    return () => {
      if (uhr.current) window.clearTimeout(uhr.current);
    };
  }, []);

  function beende() {
    if (uhr.current) window.clearTimeout(uhr.current);
    uhr.current = null;
  }

  async function verbinden() {
    setFehler("");
    setLaeuft(true);
    try {
      // Erst übernehmen, was im Formular steht: Das Plugin liest seine
      // Zugangsdaten aus der Konfiguration, nicht aus den Eingabefeldern.
      // Ohne diesen Schritt scheitert das Verbinden an Werten, die der
      // Benutzer vor sich sieht — und das ist nicht zu erklären.
      await vorher?.();
      const gestartet = (await api.pluginCommand("youtube", "verbinden")) as unknown as Code;
      setCode(gestartet);
      frage(Math.max(3, gestartet.interval || 5));
    } catch (exc: unknown) {
      setFehler(exc instanceof Error ? exc.message : String(exc));
      setLaeuft(false);
    }
  }

  function frage(sekunden: number) {
    uhr.current = window.setTimeout(async () => {
      try {
        const antwort = (await api.pluginCommand("youtube", "nachfragen")) as unknown as Stand & {
          wartet?: boolean;
        };
        if (antwort.angemeldet) {
          beende();
          setCode(null);
          setLaeuft(false);
          setStand(antwort);
          void ladePluginListe();
          return;
        }
        frage(sekunden);
      } catch (exc: unknown) {
        beende();
        setLaeuft(false);
        setCode(null);
        setFehler(exc instanceof Error ? exc.message : String(exc));
      }
    }, sekunden * 1000);
  }

  async function abmelden() {
    beende();
    setCode(null);
    setLaeuft(false);
    try {
      await api.pluginCommand("youtube", "abmelden");
      setStand({ angemeldet: false });
      void ladePluginListe();
    } catch (exc: unknown) {
      setFehler(exc instanceof Error ? exc.message : String(exc));
    }
  }

  if (stand.angemeldet) {
    return (
      <div className="youtube-verbinden">
        <span className="saved-hint">{t("plugins.youtubeConnected", { user: stand.konto })}</span>
        <button type="button" className="btn small" onClick={() => void abmelden()}>
          {t("plugins.youtubeForget")}
        </button>
      </div>
    );
  }

  return (
    <div className="youtube-verbinden">
      {!code && (
        <button
          type="button"
          className="btn primary"
          disabled={laeuft}
          onClick={() => void verbinden()}
        >
          {laeuft ? t("plugins.youtubeConnecting") : t("plugins.youtubeConnect")}
        </button>
      )}

      {code && (
        <div className="youtube-code">
          <p>{t("plugins.youtubeEnterCode")}</p>
          <strong>{code.code}</strong>
          {/* Fremde Adresse: eigenes Fenster, ohne Zugriff auf dieses. */}
          <a href={code.url} target="_blank" rel="noreferrer noopener">
            {t("plugins.youtubeOpenPage")}
          </a>
          <span className="hint">{t("plugins.youtubeWaiting")}</span>
          <button
            type="button"
            className="btn small"
            onClick={() => {
              beende();
              setCode(null);
              setLaeuft(false);
            }}
          >
            {t("common.cancel")}
          </button>
        </div>
      )}

      {(fehler || stand.fehler) && <span className="error-text">{fehler || stand.fehler}</span>}
    </div>
  );
}
