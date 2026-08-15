import type { Config, Page, Profile } from "../types";

/** Eine Zeile im Seitenbaum — Seite plus alles, was die Darstellung braucht. */
export interface PageNode {
  page: Page;
  depth: number;
  /** Index unter den Geschwistern — Grundlage fürs Verschieben. */
  index: number;
  siblingCount: number;
  childCount: number;
}

/**
 * Der Baum als flache Liste in Anzeigereihenfolge: Wurzelseiten zuerst,
 * Unterseiten direkt unter ihrem Elternteil.
 *
 * Bewusst eine reine Funktion und kein Store-Selector: sie erzeugt bei jedem
 * Aufruf ein neues Array. Als Selector benutzt würde zustand den Zustand für
 * verändert halten und React in eine Endlosschleife schicken — deshalb hier
 * herausgezogen und in den Komponenten mit `useMemo` verwendet.
 */
export function pageTree(config: Config | null): PageNode[] {
  const profile = activeProfile(config);
  if (!profile) return [];

  const byParent = childrenByParent(profile);
  const nodes: PageNode[] = [];
  const seen = new Set<string>();

  const walk = (parentId: string | null, depth: number) => {
    const siblings = byParent.get(parentId) ?? [];
    siblings.forEach((page, index) => {
      if (seen.has(page.id)) return; // Ringschluss in einer kaputten Config
      seen.add(page.id);
      nodes.push({
        page,
        depth,
        index,
        siblingCount: siblings.length,
        childCount: (byParent.get(page.id) ?? []).length,
      });
      walk(page.id, depth + 1);
    });
  };
  walk(null, 0);

  // Verwaiste Seiten (kaputter Eltern-Verweis) trotzdem erreichbar lassen.
  for (const page of Object.values(profile.pages)) {
    if (seen.has(page.id)) continue;
    nodes.push({ page, depth: 0, index: nodes.length, siblingCount: 1, childCount: 0 });
  }
  return nodes;
}

/**
 * Dieselben Knoten nach Elternteil gebündelt — für die verschachtelte Anzeige.
 *
 * Zeigt ein ``parent_id`` ins Leere, landet die Seite auf der Wurzelebene:
 * unschön, aber sichtbar und damit reparierbar.
 */
export function nodesByParent(nodes: PageNode[]): Map<string | null, PageNode[]> {
  const known = new Set(nodes.map((node) => node.page.id));
  const byParent = new Map<string | null, PageNode[]>();
  for (const node of nodes) {
    const parent = node.page.parent_id;
    const key = parent && known.has(parent) ? parent : null;
    const siblings = byParent.get(key) ?? [];
    siblings.push(node);
    byParent.set(key, siblings);
  }
  return byParent;
}

/** Unterseiten eines Elternteils in ihrer Sortierreihenfolge. */
export function pageChildren(config: Config | null, parentId: string | null): Page[] {
  const profile = activeProfile(config);
  if (!profile) return [];
  return childrenByParent(profile).get(parentId) ?? [];
}

/** Eine Seite und alles darunter — verhindert Ringschlüsse beim Verschieben. */
export function pageSubtreeIds(config: Config | null, pageId: string): Set<string> {
  const profile = activeProfile(config);
  const result = new Set<string>([pageId]);
  if (!profile) return result;

  const byParent = childrenByParent(profile);
  const pending = [pageId];
  while (pending.length) {
    for (const child of byParent.get(pending.pop()!) ?? []) {
      if (result.has(child.id)) continue;
      result.add(child.id);
      pending.push(child.id);
    }
  }
  return result;
}

/** Kette von der Wurzel bis zur Seite — für die Brotkrume über dem Deck. */
export function pagePath(config: Config | null, pageId: string): Page[] {
  const profile = activeProfile(config);
  if (!profile) return [];

  const chain: Page[] = [];
  const seen = new Set<string>();
  let current: Page | undefined = profile.pages[pageId];
  while (current && !seen.has(current.id)) {
    seen.add(current.id);
    chain.unshift(current);
    current = current.parent_id ? profile.pages[current.parent_id] : undefined;
  }
  return chain;
}

export function activeProfile(config: Config | null): Profile | null {
  if (!config) return null;
  return config.profiles[config.active_profile_id] ?? null;
}

/**
 * Alle Seiten nach Elternteil gebündelt, jede Gruppe nach ``order`` sortiert.
 *
 * ``sort`` ist in JS stabil — Seiten mit gleichem ``order`` (Configs aus der
 * Zeit vor dem Feld) behalten damit ihre bisherige Reihenfolge.
 */
function childrenByParent(profile: Profile): Map<string | null, Page[]> {
  const byParent = new Map<string | null, Page[]>();
  for (const page of Object.values(profile.pages)) {
    const siblings = byParent.get(page.parent_id) ?? [];
    siblings.push(page);
    byParent.set(page.parent_id, siblings);
  }
  for (const siblings of byParent.values()) {
    siblings.sort((a, b) => (a.order ?? 0) - (b.order ?? 0));
  }
  return byParent;
}
