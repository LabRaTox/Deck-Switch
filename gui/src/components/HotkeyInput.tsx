import { useState, type KeyboardEvent } from "react";
import { useTranslation } from "react-i18next";

/**
 * Tastenkombination aufnehmen.
 *
 * Aufnehmen statt tippen, weil niemand die Schreibweise raten soll. Der
 * Browser bekommt allerdings nicht jede Kombination zu sehen — Strg+W
 * schließt den Tab, bevor die Seite etwas merkt. Deshalb bleibt das Feld
 * zusätzlich von Hand beschreibbar.
 *
 * Das Feld weiß nicht, wofür die Kombination gedacht ist: Sie kann von
 * einer Taste *gesendet* werden (dafür braucht es ein Eingabegerät) oder
 * als globaler Kurzbefehl *empfangen* (dafür braucht es Plasma). Was im
 * Einzelfall gerade fehlt, kommt darum von außen als ``warning``.
 */
export function HotkeyInput({
  id,
  value,
  placeholder,
  warning,
  onChange,
}: {
  id: string;
  value: string;
  placeholder?: string;
  warning?: string | null;
  onChange: (value: string) => void;
}) {
  const { t } = useTranslation();
  const [recording, setRecording] = useState(false);

  const capture = (event: KeyboardEvent<HTMLInputElement>) => {
    if (!recording) return;
    event.preventDefault();
    event.stopPropagation();

    if (event.key === "Escape") {
      setRecording(false);
      return;
    }

    const parts: string[] = [];
    if (event.ctrlKey) parts.push("ctrl");
    if (event.shiftKey) parts.push("shift");
    if (event.altKey) parts.push(event.getModifierState("AltGraph") ? "altgr" : "alt");
    if (event.metaKey) parts.push("super");

    const main = mainKey(event);
    if (!main) return; // reiner Modifier — auf die eigentliche Taste warten
    parts.push(main);
    onChange(parts.join("+"));
    setRecording(false);
  };

  return (
    <div className="hotkey-input">
      <input
        id={id}
        type="text"
        value={recording ? "" : value}
        placeholder={recording ? t("hotkey.pressNow") : placeholder}
        className={recording ? "recording" : ""}
        onKeyDown={capture}
        onChange={(event) => onChange(event.target.value)}
        onBlur={() => setRecording(false)}
      />
      <button
        type="button"
        className={recording ? "btn small active" : "btn small"}
        onClick={() => setRecording((on) => !on)}
      >
        {recording ? t("hotkey.cancel") : t("hotkey.record")}
      </button>
      {warning && <small className="help error-text">{warning}</small>}
    </div>
  );
}

/** Taste ohne Modifier — aus ``code``, damit die Belegung egal bleibt. */
function mainKey(event: KeyboardEvent<HTMLInputElement>): string {
  const code = event.code;
  if (/^(Control|Shift|Alt|Meta)/.test(code)) return "";
  if (code.startsWith("Key")) return code.slice(3).toLowerCase();
  if (code.startsWith("Digit")) return code.slice(5);
  if (code.startsWith("Numpad")) return `kp${code.slice(6).toLowerCase()}`;
  if (/^F\d+$/.test(code)) return code.toLowerCase();

  const named: Record<string, string> = {
    Space: "space",
    Enter: "enter",
    Tab: "tab",
    Backspace: "backspace",
    Delete: "delete",
    Escape: "escape",
    ArrowUp: "up",
    ArrowDown: "down",
    ArrowLeft: "left",
    ArrowRight: "right",
    Home: "home",
    End: "end",
    PageUp: "pageup",
    PageDown: "pagedown",
    Insert: "insert",
    PrintScreen: "print",
  };
  return named[code] ?? event.key.toLowerCase();
}
