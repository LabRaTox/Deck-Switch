import { useEffect, useState } from "react";

/**
 * Zahlenfeld mit Grenzen.
 *
 * Geklemmt wird erst beim Verlassen des Feldes oder mit Enter. Wer „60“
 * in ein Feld mit Minimum 10 tippt, kommt sonst nie an: Aus der „6“ würde
 * sofort eine 10, und die „0“ hängte sich dahinter. Liegt die Eingabe
 * schon unterwegs im erlaubten Bereich, geht sie gleich weiter.
 */
export function NumberField({
  label,
  value,
  min,
  max,
  step = 1,
  help,
  onChange,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step?: number;
  help?: string;
  onChange: (value: number) => void;
}) {
  const [text, setText] = useState(String(value));
  const [aktiv, setAktiv] = useState(false);

  // Von außen geänderte Werte übernehmen, aber nicht mitten ins Tippen.
  useEffect(() => {
    if (!aktiv) setText(String(value));
  }, [value, aktiv]);

  const uebernimm = () => {
    const zahl = Number(text);
    const wert =
      text.trim() === "" || Number.isNaN(zahl) ? value : Math.min(max, Math.max(min, zahl));
    setText(String(wert));
    if (wert !== value) onChange(wert);
  };

  return (
    <div className="field">
      <label>{label}</label>
      <input
        type="number"
        value={text}
        min={min}
        max={max}
        step={step}
        onFocus={() => setAktiv(true)}
        onBlur={() => {
          setAktiv(false);
          uebernimm();
        }}
        onKeyDown={(event) => {
          if (event.key === "Enter") uebernimm();
        }}
        onChange={(event) => {
          const roh = event.target.value;
          setText(roh);
          const zahl = Number(roh);
          if (roh.trim() !== "" && !Number.isNaN(zahl) && zahl >= min && zahl <= max) {
            onChange(zahl);
          }
        }}
      />
      {help && <small className="help">{help}</small>}
    </div>
  );
}
