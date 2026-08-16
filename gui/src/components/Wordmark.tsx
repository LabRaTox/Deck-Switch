/**
 * Die Wortmarke DECK//SWITCH.
 *
 * Die beiden Schrägstriche stehen in der Akzentfarbe, die Wörter in der
 * Textfarbe. Bewusst als Markup und nicht als Bilddatei: So bleibt der
 * Name auswählbar, skaliert mit der Schriftgröße und passt sich einer
 * geänderten Akzentfarbe von selbst an.
 *
 * Der Name der Anwendung steht trotzdem in der Übersetzungsdatei — für
 * Fließtext, Fenstertitel und alles, wo keine Auszeichnung möglich ist.
 */
export function Wordmark({ className = "" }: { className?: string }) {
  return (
    <span className={`wordmark ${className}`.trim()}>
      DECK
      <span className="wordmark-slash" aria-hidden="true">
        //
      </span>
      SWITCH
    </span>
  );
}
