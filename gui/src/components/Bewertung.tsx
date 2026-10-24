/**
 * Wie ein Plugin ankommt — und die Möglichkeit, das selbst zu sagen.
 *
 * Steht in beiden Detailansichten: bei einem Plugin aus dem Store und bei
 * einem, das schon installiert ist. Gerade das installierte ist der Moment,
 * in dem jemand eine Meinung hat — nach ein paar Wochen Benutzen, nicht
 * beim Überfliegen der Liste.
 *
 * Zwei Daumen statt fünf Sternen: Bei Sternen grübelt man über den
 * Unterschied zwischen drei und vier, und am Ende steht bei allem 4,2.
 */

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { api, ApiError } from "../api/client";
import { useStore } from "../store";
import type { StoreBewertung } from "../types";
import { UiIcon } from "./UiIcon";

export function Bewertung({ slug }: { slug: string }) {
  const { t } = useTranslation();
  const konto = useStore((s) => s.storeKonto);
  const angemeldet = Boolean(konto?.user);

  const [stand, setStand] = useState<StoreBewertung | null>(null);
  const [fehler, setFehler] = useState("");
  const [laeuft, setLaeuft] = useState(false);
  const [kommentar, setKommentar] = useState("");
  const [schreibt, setSchreibt] = useState(false);
  // Ein Daumen nach unten braucht eine Begründung. Bis sie dasteht, ist die
  // Stimme nur vorgemerkt und noch nicht abgeschickt.
  const [runterVorgemerkt, setRunterVorgemerkt] = useState(false);

  useEffect(() => {
    let abgemeldet = false;
    setStand(null);
    setFehler("");
    api
      .storeBewertung(slug)
      .then((daten) => {
        if (abgemeldet) return;
        setStand(daten);
        setKommentar(daten.comment ?? "");
      })
      // Ein Plugin, das es im Store nicht (mehr) gibt, ist kein Fehler der
      // Ansicht — dann gibt es eben nichts zu zeigen.
      .catch((exc: unknown) => {
        if (!abgemeldet) setFehler(exc instanceof ApiError ? exc.message : String(exc));
      });
    return () => {
      abgemeldet = true;
    };
  }, [slug]);

  async function stimme(wert: 1 | -1) {
    if (!stand || laeuft) return;
    if (wert === -1 && stand.mine !== -1 && !kommentar.trim()) {
      setRunterVorgemerkt(true);
      setSchreibt(true);
      setFehler("");
      return;
    }
    setLaeuft(true);
    setFehler("");
    try {
      // Noch einmal dieselbe Richtung heißt: Meinung zurückgezogen.
      const neu =
        stand.mine === wert
          ? await api.storeBewertungLoeschen(slug)
          : await api.storeBewerten(slug, wert, kommentar);
      setStand(neu);
      setKommentar(neu.comment ?? "");
      setRunterVorgemerkt(false);
      if (neu.mine === null) setSchreibt(false);
    } catch (exc: unknown) {
      setFehler(exc instanceof ApiError ? exc.message : String(exc));
    } finally {
      setLaeuft(false);
    }
  }

  async function kommentarSpeichern() {
    const wert = runterVorgemerkt ? -1 : stand?.mine;
    if (!wert || laeuft) return;
    if (wert === -1 && !kommentar.trim()) {
      setFehler(t("store.ratingDownNeedsReason"));
      return;
    }
    setLaeuft(true);
    setFehler("");
    try {
      const neu = await api.storeBewerten(slug, wert as 1 | -1, kommentar);
      setStand(neu);
      setRunterVorgemerkt(false);
      setSchreibt(false);
    } catch (exc: unknown) {
      setFehler(exc instanceof ApiError ? exc.message : String(exc));
    } finally {
      setLaeuft(false);
    }
  }

  if (fehler && !stand) {
    return null;
  }
  if (!stand) {
    return <p className="hint">{t("store.ratingLoading")}</p>;
  }

  const fremde = stand.comments.filter((k) => k.author !== konto?.user?.handle);
  // Das eigene Plugin bewertet man nicht, der Store lehnt es ab.
  const eigenes = Boolean(stand.own);
  const darfStimmen = angemeldet && !eigenes;

  return (
    <section className="bewertung">
      <h4>{t("store.rating")}</h4>

      <div className="bewertung-knoepfe">
        <button
          type="button"
          className={`btn daumen${stand.mine === 1 ? " aktiv" : ""}`}
          disabled={!darfStimmen || laeuft}
          title={eigenes ? t("store.ratingOwn") : angemeldet ? t("store.ratingUpHint") : t("store.ratingNeedsLogin")}
          onClick={() => void stimme(1)}
        >
          <UiIcon name="thumb-up" size={16} />
          {stand.up}
        </button>
        <button
          type="button"
          className={`btn daumen runter${stand.mine === -1 || runterVorgemerkt ? " aktiv" : ""}`}
          disabled={!darfStimmen || laeuft}
          title={eigenes ? t("store.ratingOwn") : angemeldet ? t("store.ratingDownHint") : t("store.ratingNeedsLogin")}
          onClick={() => void stimme(-1)}
        >
          <UiIcon name="thumb-down" size={16} />
          {stand.down}
        </button>

        {!angemeldet && <span className="hint">{t("store.ratingNeedsLogin")}</span>}
        {eigenes && <span className="hint">{t("store.ratingOwn")}</span>}
        {darfStimmen && stand.mine !== null && !schreibt && (
          <button type="button" className="btn ghost" onClick={() => setSchreibt(true)}>
            {stand.comment ? t("store.ratingEditComment") : t("store.ratingAddComment")}
          </button>
        )}
      </div>

      {darfStimmen && (stand.mine !== null || runterVorgemerkt) && schreibt && (
        <div className="bewertung-schreiben">
          {runterVorgemerkt && <p className="hint">{t("store.ratingDownNeedsReason")}</p>}
          <textarea
            value={kommentar}
            maxLength={500}
            rows={3}
            placeholder={t("store.ratingCommentPlaceholder")}
            onChange={(event) => setKommentar(event.target.value)}
          />
          <div className="row">
            <button
              type="button"
              className="btn primary"
              disabled={laeuft}
              onClick={() => void kommentarSpeichern()}
            >
              {t("common.save")}
            </button>
            <button
              type="button"
              className="btn"
              onClick={() => {
                setKommentar(stand.comment ?? "");
                setRunterVorgemerkt(false);
                setSchreibt(false);
              }}
            >
              {t("common.cancel")}
            </button>
          </div>
        </div>
      )}

      {fehler && <p className="fehler">{fehler}</p>}

      {stand.comment && !schreibt && (
        <blockquote className="bewertung-eigen">
          <UiIcon name={stand.mine === -1 ? "thumb-down" : "thumb-up"} size={14} />
          {stand.comment}
          <small>{t("store.ratingYours")}</small>
        </blockquote>
      )}

      {fremde.length > 0 && (
        <ul className="bewertung-liste">
          {fremde.map((k, i) => (
            <li key={i}>
              <UiIcon name={k.value === -1 ? "thumb-down" : "thumb-up"} size={14} />
              <span>{k.comment}</span>
              <small>
                {k.author} · {new Date(k.at).toLocaleDateString()}
              </small>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
