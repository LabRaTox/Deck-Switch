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

void i18n.use(initReactI18next).init({
  resources: {
    de: { translation: de },
    en: { translation: en },
  },
  lng: "de",
  fallbackLng: "en",
  interpolation: { escapeValue: false },
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
