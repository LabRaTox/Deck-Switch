import type { PluginAbhaengigkeiten } from "../types";

/** Was ein Plugin braucht, als eine Zeile; Systempakete sind gekennzeichnet. */
export function abhaengigkeitenText(
  bedarf: PluginAbhaengigkeiten | null | undefined,
  systemKennung: string,
): string | null {
  // Ein von Hand abgelegtes Plugin ist nie durch die Prüfung gelaufen.
  const python = Array.isArray(bedarf?.python) ? bedarf.python : [];
  const roh = Array.isArray(bedarf?.system) ? bedarf.system : [];
  const system = roh.map((eintrag) => {
    const name =
      typeof eintrag === "string" ? eintrag : [...new Set(Object.values(eintrag))].join(" / ");
    return `${name} (${systemKennung})`;
  });
  return [...python, ...system].join(", ") || null;
}
