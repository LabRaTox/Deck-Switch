import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

export interface MenuItem {
  key: string;
  label: string;
  onSelect: () => void;
  disabled?: boolean;
  danger?: boolean;
  /** Erklärt beim Überfahren, warum ein Eintrag nicht wählbar ist. */
  hint?: string;
  /** Trennlinie *über* diesem Eintrag. */
  separated?: boolean;
}

const MARGIN = 8;

/**
 * Kontextmenü an der Mausposition.
 *
 * Hängt per Portal am `body`: Die Kacheln haben `overflow: hidden` und beim
 * Drop eine `transform` — beides würde ein Menü innerhalb der Kachel
 * abschneiden bzw. seinen Bezugsrahmen verschieben.
 */
export function ContextMenu({
  x,
  y,
  items,
  onClose,
}: {
  x: number;
  y: number;
  items: MenuItem[];
  onClose: () => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [position, setPosition] = useState({ left: x, top: y });

  // Vor dem ersten Zeichnen umklappen, damit das Menü nicht sichtbar
  // springt, wenn es am Rand aufgeht.
  useLayoutEffect(() => {
    const menu = ref.current;
    if (!menu) return;
    const { width, height } = menu.getBoundingClientRect();
    setPosition({
      left: Math.max(MARGIN, Math.min(x, window.innerWidth - width - MARGIN)),
      top: Math.max(MARGIN, Math.min(y, window.innerHeight - height - MARGIN)),
    });
  }, [x, y]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    // `mousedown` statt `click`: Sonst schließt derselbe Klick, der das Menü
    // geöffnet hat, es in manchen Browsern sofort wieder.
    const onPointerDown = (event: MouseEvent) => {
      if (!ref.current?.contains(event.target as Node)) onClose();
    };
    window.addEventListener("keydown", onKey);
    window.addEventListener("mousedown", onPointerDown);
    window.addEventListener("resize", onClose);
    // Beim Scrollen bliebe das Menü sonst an der alten Bildschirmstelle
    // stehen, während die Kachel darunter wegwandert.
    window.addEventListener("scroll", onClose, true);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("mousedown", onPointerDown);
      window.removeEventListener("resize", onClose);
      window.removeEventListener("scroll", onClose, true);
    };
  }, [onClose]);

  return createPortal(
    <div
      ref={ref}
      className="context-menu"
      style={{ left: position.left, top: position.top }}
      role="menu"
      // Rechtsklick *im* Menü soll nicht das Browsermenü aufziehen.
      onContextMenu={(event) => event.preventDefault()}
    >
      {items.map((item) => (
        <button
          key={item.key}
          type="button"
          role="menuitem"
          className={[item.danger ? "danger" : "", item.separated ? "separated" : ""]
            .filter(Boolean)
            .join(" ")}
          disabled={item.disabled}
          title={item.disabled ? item.hint : undefined}
          onClick={() => {
            item.onSelect();
            onClose();
          }}
        >
          {item.label}
        </button>
      ))}
    </div>,
    document.body,
  );
}
