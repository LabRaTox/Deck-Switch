/**
 * Icons der Oberfläche selbst — Chevrons, Plus, Papierkorb und Ähnliches.
 *
 * Die Pfade stammen aus Tabler Icons (MIT, Paweł Kuna), derselben Sammlung,
 * die auch als Iconset-Plugin unter ``backend/plugins/iconset-tabler``
 * mitgeliefert wird. Hier stehen sie trotzdem inline im Code und werden
 * nicht über ``/api/icons`` geholt: Bedienelemente dürfen nicht davon
 * abhängen, ob ein Plugin installiert, aktiviert und erreichbar ist — und
 * sie sollen ohne Netzrunde sofort da sein.
 *
 * Neues Icon nötig? Pfad aus der passenden Datei im Iconset kopieren und
 * hier eintragen; die Rahmenwerte (24er Raster, Strichstärke, runde Enden)
 * setzt die Komponente einheitlich.
 */

export type UiIconName = keyof typeof PATHS;

const PATHS = {
  "chevron-right": ["M9 6l6 6l-6 6"],
  "chevron-down": ["M6 9l6 6l6 -6"],
  "chevron-up": ["M6 15l6 -6l6 6"],
  plus: ["M12 5l0 14", "M5 12l14 0"],
  "arrow-up": ["M12 5l0 14", "M18 11l-6 -6", "M6 11l6 -6"],
  "arrow-down": ["M12 5l0 14", "M18 13l-6 6", "M6 13l6 6"],
  "arrow-left": ["M5 12l14 0", "M5 12l6 6", "M5 12l6 -6"],
  "arrow-right": ["M5 12l14 0", "M13 18l6 -6", "M13 6l6 6"],
  "arrows-move": [
    "M18 9l3 3l-3 3",
    "M15 12h6",
    "M6 9l-3 3l3 3",
    "M3 12h6",
    "M9 18l3 3l3 -3",
    "M12 15v6",
    "M15 6l-3 -3l-3 3",
    "M12 3v6",
  ],
  "corner-down-right": ["M6 6v6a3 3 0 0 0 3 3h10l-4 -4m0 8l4 -4"],
  trash: [
    "M4 7l16 0",
    "M10 11l0 6",
    "M14 11l0 6",
    "M5 7l1 12a2 2 0 0 0 2 2h8a2 2 0 0 0 2 -2l1 -12",
    "M9 7v-3a1 1 0 0 1 1 -1h4a1 1 0 0 1 1 1v3",
  ],
  "sidebar-collapse": [
    "M4 6a2 2 0 0 1 2 -2h12a2 2 0 0 1 2 2v12a2 2 0 0 1 -2 2h-12a2 2 0 0 1 -2 -2l0 -12",
    "M9 4v16",
    "M15 10l-2 2l2 2",
  ],
  // Regler — aus dem mitgelieferten Tabler-Satz übernommen
  // (adjustments-horizontal), damit die Oberfläche eine Handschrift hat.
  adjustments: [
    "M12 6a2 2 0 1 0 4 0a2 2 0 1 0 -4 0",
    "M4 6l8 0",
    "M16 6l4 0",
    "M6 12a2 2 0 1 0 4 0a2 2 0 1 0 -4 0",
    "M4 12l2 0",
    "M10 12l10 0",
    "M15 18a2 2 0 1 0 4 0a2 2 0 1 0 -4 0",
    "M4 18l11 0",
    "M19 18l1 0",
  ],
  "sidebar-expand": [
    "M4 6a2 2 0 0 1 2 -2h12a2 2 0 0 1 2 2v12a2 2 0 0 1 -2 2h-12a2 2 0 0 1 -2 -2l0 -12",
    "M9 4v16",
    "M14 10l2 2l-2 2",
  ],
} as const;

export function UiIcon({
  name,
  size = 16,
  /** Tabler zeichnet für 24 px; klein dargestellt wirkt 2 schnell klobig. */
  strokeWidth = 1.75,
  className,
}: {
  name: UiIconName;
  size?: number;
  strokeWidth?: number;
  className?: string;
}) {
  return (
    <svg
      className={className}
      xmlns="http://www.w3.org/2000/svg"
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      {PATHS[name].map((d) => (
        <path key={d} d={d} />
      ))}
    </svg>
  );
}
