/**
 * Mehrsprachigkeit der Oberfläche.
 *
 * Von Anfang an eingebaut statt nachgerüstet: kein sichtbarer Text steht
 * hart im Code. Plugin-Manifeste liefern ihre Texte selbst mit — dafür gibt
 * es `localized()`.
 */

import i18n from "i18next";
import { initReactI18next } from "react-i18next";

import de from "./de.json";
import en from "./en.json";

export const SUPPORTED_LANGUAGES = ["de", "en"] as const;
export type Language = (typeof SUPPORTED_LANGUAGES)[number];

/** Wo die zuletzt gewählte Sprache liegt, für den Start vor der Config. */
const SPRACHE_MERKEN = "deckswitch-sprache";

/**
 * Die Sprache für die ersten Augenblicke. Die eigentliche Einstellung kommt
 * mit der Config. Bis dahin, und wenn das Backend gar nicht antwortet, gilt
 * die zuletzt benutzte oder die des Systems.
 */
function startSprache(): Language {
  try {
    const gemerkt = window.localStorage.getItem(SPRACHE_MERKEN);
    if (gemerkt === "de" || gemerkt === "en") return gemerkt;
  } catch {
    /* Kein Speicher, dann eben die Systemsprache */
  }
  return navigator.language?.toLowerCase().startsWith("de") ? "de" : "en";
}

void i18n.use(initReactI18next).init({
  resources: {
    de: { translation: de },
    en: { translation: en },
  },
  lng: startSprache(),
  fallbackLng: "en",
  interpolation: { escapeValue: false },
});

i18n.on("languageChanged", (sprache) => {
  try {
    window.localStorage.setItem(SPRACHE_MERKEN, sprache);
  } catch {
    /* Ohne Speicher gilt beim nächsten Start die Systemsprache */
  }
});

export default i18n;

/**
 * Löst einen Manifest-Text auf, der entweder ein String oder ein
 * Locale-Mapping (`{"de": …, "en": …}`) ist.
 */
export function localized(
  value: string | Record<string, string> | null | undefined,
  language: string = i18n.language,
): string {
  if (value == null) return "";
  if (typeof value === "string") return value;
  return value[language] ?? value.en ?? Object.values(value)[0] ?? "";
}
