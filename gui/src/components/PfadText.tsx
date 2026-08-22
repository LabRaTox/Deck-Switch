import { Fragment } from "react";

import { UiIcon } from "./UiIcon";

/**
 * Text mit Pfaden darin — „Einstellungen → Decks".
 *
 * Der Pfeil steht in den Texten als gewöhnliches Zeichen (U+2192), damit
 * Übersetzungen und Plugin-Manifeste einfache Zeichenketten bleiben. Er
 * *dargestellt* wird er aber als Icon: Der Schriftpfeil sitzt je nach
 * Schnitt zu hoch, ist zu dünn und passt nicht zum übrigen Erscheinungsbild.
 *
 * Kommt kein Pfeil vor, gibt die Komponente den Text unverändert aus — sie
 * lässt sich also bedenkenlos über jeden Hinweistext legen.
 */
export function PfadText({ text }: { text: string }) {
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
