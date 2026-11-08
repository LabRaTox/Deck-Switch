import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { useTranslation } from "react-i18next";

/**
 * Tastenkombination aufnehmen.
 *
 * Aufnehmen statt tippen, weil niemand die Schreibweise raten soll. Der
 * Browser bekommt allerdings nicht jede Kombination zu sehen, Strg+W
 * schließt den Tab, bevor die Seite etwas merkt. Deshalb bleibt das Feld
 * zusätzlich von Hand beschreibbar.
 *
 * Das Feld weiß nicht, wofür die Kombination gedacht ist: Sie kann von
 * einer Taste *gesendet* werden (dafür braucht es ein Eingabegerät) oder
 * als globaler Kurzbefehl *empfangen* (dafür braucht es Plasma). Was im
 * Einzelfall gerade fehlt, kommt darum von außen als ``warning``.
 *
 * Gespeichert wird das **Zeichen**, das die Taste auf der eingestellten
 * Belegung schreibt, nicht ihre Position. So liest das Backend jede
 * Kombination: „ctrl+z" ist die Taste, die hier ein Z schreibt. Auf einer
 * deutschen Tastatur liegt die an der Stelle, die ``event.code`` als
 * ``KeyY`` meldet.
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
  const layoutMap = useRef<Map<string, string> | null>(null);

  // Die Belegungstabelle liefert das Grundzeichen einer Taste, auch wenn
  // Shift oder AltGr gerade etwas anderes daraus machen. Nicht jede
  // Engine kennt sie; dann bleibt es bei ``event.key``.
  useEffect(() => {
    if (!recording || layoutMap.current) return;
    const keyboard = (navigator as Navigator & { keyboard?: KeyboardApi }).keyboard;
    if (!keyboard?.getLayoutMap) return;
    keyboard
      .getLayoutMap()
      .then((map) => {
        layoutMap.current = new Map(map);
      })
      .catch(() => undefined);
  }, [recording]);

  const capture = (event: KeyboardEvent<HTMLInputElement>) => {
    if (!recording) return;
    event.preventDefault();
    event.stopPropagation();

    if (event.key === "Escape") {
      setRecording(false);
      return;
    }

    const main = mainKey(event, layoutMap.current);
    if (!main) return; // reiner Modifier, auf die eigentliche Taste warten

    const altGr = event.getModifierState("AltGraph");
    const parts: string[] = [];
    if (event.ctrlKey) parts.push("ctrl");
    if (event.shiftKey) parts.push("shift");
    if (altGr) {
      // Ohne Grundzeichen steckt AltGr schon im aufgenommenen Zeichen
      // („@" statt „altgr+q"). Doppelt genannt hieße es AltGr zweimal.
      if (!main.altGrInKey) parts.push("altgr");
    } else if (event.altKey) {
      parts.push("alt");
    }
    if (event.metaKey) parts.push("super");

    parts.push(main.key);
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

/** Ausschnitt aus der Keyboard-API, soweit er hier gebraucht wird. */
type KeyboardApi = {
  getLayoutMap?: () => Promise<Iterable<[string, string]>>;
};

/** Tasten ohne Zeichen. Ihr Name hängt nicht an der Belegung. */
const NAMED: Record<string, string> = {
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
  Pause: "pause",
  ContextMenu: "menu",
  CapsLock: "capslock",
  NumLock: "numlock",
  ScrollLock: "scrolllock",
};

/**
 * Zeichen, die in einer Kombination selbst Trennzeichen wären. Das
 * Backend kennt sie auch unter diesem Namen.
 */
const SPELLED: Record<string, string> = { "+": "plus", " ": "space" };

/** Genau ein sichtbares Zeichen? ``"Dead"`` oder ``"Unidentified"`` nicht. */
function isPrintable(key: string): boolean {
  return [...key].length === 1 && key.trim() !== "";
}

/**
 * Die Haupttaste ohne Modifier.
 *
 * ``altGrInKey`` sagt, ob das Zeichen AltGr schon enthält: Ohne
 * Belegungstabelle lässt sich aus „@" nicht zurückrechnen, auf welcher
 * Taste es liegt. Das Backend sucht die Taste dann selbst über die
 * Belegung, und AltGr kommt dabei von allein mit.
 */
function mainKey(
  event: KeyboardEvent<HTMLInputElement>,
  layoutMap: Map<string, string> | null,
): { key: string; altGrInKey: boolean } | null {
  const code = event.code;
  if (/^(Control|Shift|Alt|Meta|OS)/.test(code)) return null;
  if (/^(Control|Shift|Alt|AltGraph|Meta|OS)$/.test(event.key)) return null;
  const plain = (key: string) => ({ key, altGrInKey: false });

  if (code.startsWith("Numpad")) return plain(`kp${code.slice(6).toLowerCase()}`);
  if (/^F\d+$/.test(code)) return plain(code.toLowerCase());
  if (NAMED[code]) return plain(NAMED[code]);

  const spell = (char: string) => SPELLED[char] ?? char.toLowerCase();

  // Grundzeichen aus der Belegung: das beste, was es gibt.
  const base = layoutMap?.get(code);
  if (base && isPrintable(base)) return plain(spell(base));

  const altGr = event.getModifierState("AltGraph");
  const key = event.key;
  if (isPrintable(key)) {
    // Shift macht aus der Ziffernreihe Satzzeichen. Die Ziffer selbst ist
    // das verständlichere Grundzeichen, das Backend findet sie über die
    // Belegung auf derselben Taste.
    if (event.shiftKey && !altGr && code.startsWith("Digit")) return plain(code.slice(5));
    return { key: spell(key), altGrInKey: altGr };
  }

  // Tote Tasten und Unbekanntes: wenigstens die Position, wie bisher.
  if (code.startsWith("Key")) return plain(code.slice(3).toLowerCase());
  if (code.startsWith("Digit")) return plain(code.slice(5));
  return key && key !== "Unidentified" && key !== "Dead" ? plain(key.toLowerCase()) : null;
}
