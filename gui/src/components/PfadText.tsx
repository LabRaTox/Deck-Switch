import { Fragment } from "react";

import { UiIcon } from "./UiIcon";

/**
 * Text mit Pfaden und Adressen darin — „Einstellungen → Decks", https://…
 *
 * Der Pfeil steht in den Texten als gewöhnliches Zeichen (U+2192), damit
 * Übersetzungen und Plugin-Manifeste einfache Zeichenketten bleiben. Er
 * *dargestellt* wird er aber als Icon: Der Schriftpfeil sitzt je nach
 * Schnitt zu hoch, ist zu dünn und passt nicht zum übrigen Erscheinungsbild.
 *
 * Adressen werden anklickbar. Aus demselben Grund: Ein Hinweis, der eine
 * Seite nennt, auf die man gehen soll, sollte nicht zum Abschreiben zwingen.
 * Erlaubt ist nur `https://` — ein Hinweistext ist kein Grund, beliebige
 * Ziele zu öffnen —, und geöffnet wird in einem eigenen Fenster ohne Zugriff
 * auf dieses.
 *
 * Kommt weder Pfeil noch Adresse vor, gibt die Komponente den Text
 * unverändert aus — sie lässt sich also bedenkenlos über jeden Hinweistext
 * legen.
 */

/** Adressen samt der Satzzeichen, die *nicht* mehr dazugehören. */
const ADRESSE = /(https:\/\/[^\s<>"']+[^\s<>"'.,;:!?)])/g;

function MitPfeilen({ text }: { text: string }) {
  if (!text.includes("→")) return <>{text}</>;
  const teile = text.split("→");
  return (
    <>
      {teile.map((teil, i) => (
        <Fragment key={i}>
          {i > 0 && <UiIcon name="arrow-right" size={13} className="pfad-pfeil" />}
          {teil}
        </Fragment>
      ))}
    </>
  );
}

export function PfadText({ text }: { text: string }) {
  const teile = text.split(ADRESSE);
  return (
    <>
      {teile.map((teil, i) =>
        // Kein ADRESSE.test() hier: Ein globales Muster merkt sich die
        // Fundstelle und antwortet beim nächsten Aufruf anders. Nach
        // ``split`` mit Fanggruppe sind die Treffer ohnehin eigene Stücke —
        // der Anfang genügt als Erkennung.
        teil.startsWith("https://") ? (
          <a key={i} href={teil} target="_blank" rel="noreferrer noopener">
            {teil.replace(/^https:\/\//, "")}
          </a>
        ) : (
          <MitPfeilen key={i} text={teil} />
        ),
      )}
    </>
  );
}
