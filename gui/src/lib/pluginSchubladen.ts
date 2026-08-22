/**
 * Die Schubladen, nach denen Plugins sortiert sind.
 *
 * Stehen hier und nicht in einer der beiden Ansichten: Der Store und die
 * Liste der installierten Plugins benutzen dieselben — und wenn sie
 * auseinanderliefen, fände man dort eine Kategorie, die es hier nicht gibt.
 */

import type { PluginCategory } from "../types";

/**
 * Die Reiter oben — nach Art des Plugins, nicht nach Thema.
 *
 * Das ist die grobe Trennung: Ein Iconset liefert Symbole, ein Schoner malt
 * über das ganze Deck, ein Action-Plugin belegt Tasten. Die feine Sortierung
 * nach Thema macht das Menü links.
 */
export const TYPEN = ["action", "iconset", "screensaver", "wallpaper"] as const;
export type PluginTyp = (typeof TYPEN)[number];

/**
 * Die Themen, in der Reihenfolge des Menüs.
 *
 * `system` steht vorn und nicht alphabetisch zwischen „Streaming" und
 * „Video": Dort stecken Seiten, Helligkeit und Tastendrücke — die Bedienung
 * des Decks selbst, nicht die Zutaten für den nächsten Stream. `other`
 * bleibt hinten, wo Nachzügler ohne Angabe landen.
 */
export const KATEGORIEN: PluginCategory[] = [
  "system",
  "audio",
  "business",
  "creative",
  "development",
  "engagement",
  "finance",
  "gaming",
  "lighting",
  "monitoring",
  "music",
  "productivity",
  "screensaver",
  "smarthome",
  "social",
  "streaming",
  "utilities",
  "video",
  "other",
];
