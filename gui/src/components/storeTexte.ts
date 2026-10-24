import { localized } from "../i18n";
import type { StorePlugin, StoreVersion } from "../types";

/*
 * Texte aus dem Store in der Sprache der Oberfläche.
 *
 * Der Store liefert Name, Kurzsatz, Beschreibung und Änderungen in allen
 * Sprachen, die das Manifest mitbringt (`i18n`, `changelog_i18n`). Fehlen
 * diese Felder, weil der Store älter ist, bleiben die einfachen Felder.
 */

export function storeName(plugin: StorePlugin, sprache?: string): string {
  return localized(plugin.i18n?.name, sprache) || plugin.name;
}

export function storeKurz(plugin: StorePlugin, sprache?: string): string {
  return localized(plugin.i18n?.summary, sprache) || plugin.summary;
}

export function storeBeschreibung(plugin: StorePlugin, sprache?: string): string {
  return (
    localized(plugin.i18n?.description, sprache) ||
    plugin.description ||
    storeKurz(plugin, sprache)
  );
}

export function storeAenderungen(version: StoreVersion, sprache?: string): string {
  return localized(version.changelog_i18n, sprache) || version.changelog || "";
}
