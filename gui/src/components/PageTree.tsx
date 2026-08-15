import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type MutableRefObject,
} from "react";
import { useTranslation } from "react-i18next";

import {
  activeProfile,
  nodesByParent,
  pagePath,
  pageSubtreeIds,
  pageTree,
  type PageNode,
} from "../lib/pages";
import { useStore } from "../store";
import { UiIcon } from "./UiIcon";

/**
 * Seitenbaum links neben dem Deck.
 *
 * Ordner sind keine eigene Entität, sondern Seiten mit Elternteil. Damit man
 * das sieht, sind Unterseiten nicht bloß eingerückt, sondern stecken in einem
 * eigenen Rahmen unter ihrer Seite; der Zweig, in dem die geöffnete Seite
 * liegt, ist zusätzlich in der Akzentfarbe markiert.
 *
 * Sortiert wird per Drag & Drop oder mit Alt + Pfeiltasten; beides landet auf
 * derselben Store-Aktion ``movePage(seite, elternteil, index)``.
 */

/** Wohin eine gezogene Seite relativ zur Zeile unter dem Zeiger fällt. */
type DropWhere = "before" | "after" | "into";

interface DropTarget {
  id: string;
  where: DropWhere;
}

const COLLAPSED_KEY = "deckswitch.pages.collapsed";
const PANEL_KEY = "deckswitch.pages.panel";
const DRAG_TYPE = "application/x-deckswitch-page";

export function PageTree() {
  const { t } = useTranslation();
  const config = useStore((s) => s.config);
  const currentPageId = useStore((s) => s.currentPageId);
  const createPage = useStore((s) => s.createPage);
  const movePage = useStore((s) => s.movePage);

  const [collapsed, setCollapsed] = useState<Set<string>>(loadCollapsed);
  const [panelOpen, setPanelOpen] = useState(
    () => localStorage.getItem(PANEL_KEY) !== "closed",
  );
  // Zwei Ebenen für dieselbe Information: Refs treiben die Logik, State nur
  // die Optik. Ein ``dragover`` kann unmittelbar auf ``dragstart`` folgen —
  // ein State-Wert wäre in dessen Handler noch der alte aus dem letzten
  // Render, und der Zug fiele lautlos aus.
  const dragRef = useRef<string | null>(null);
  const dropRef = useRef<DropTarget | null>(null);
  const [dragId, setDragIdState] = useState<string | null>(null);
  const [drop, setDropState] = useState<DropTarget | null>(null);

  const setDragId = useCallback((id: string | null) => {
    dragRef.current = id;
    setDragIdState(id);
  }, []);

  const setDrop = useCallback((target: DropTarget | null) => {
    dropRef.current = target;
    setDropState(target);
  }, []);

  const rootId = activeProfile(config)?.root_page_id ?? "";

  const nodeList = useMemo(() => pageTree(config), [config]);
  const byParent = useMemo(() => nodesByParent(nodeList), [nodeList]);
  const nodes = useMemo(
    () => new Map(nodeList.map((node) => [node.page.id, node])),
    [nodeList],
  );

  /** Alle Vorfahren der geöffneten Seite — markieren den aktiven Zweig. */
  const activePath = useMemo(
    () => new Set(pagePath(config, currentPageId).map((page) => page.id)),
    [config, currentPageId],
  );

  // Beim Verschieben wandert die Zeile im DOM und verliert dabei den Fokus.
  // Ohne Nachfassen ließe sich Alt + ↓ kein zweites Mal drücken. Der Griff
  // nach dem Fokus greift nur, wenn ihn gerade niemand sonst hat.
  const focusRef = useRef<string | null>(null);
  useEffect(() => {
    const id = focusRef.current;
    if (!id) return;
    if (document.activeElement && document.activeElement !== document.body) return;
    document
      .querySelector<HTMLButtonElement>(`[data-page-id="${id}"] .pagerow-name`)
      ?.focus();
  });

  useEffect(() => {
    localStorage.setItem(COLLAPSED_KEY, JSON.stringify([...collapsed]));
  }, [collapsed]);

  useEffect(() => {
    localStorage.setItem(PANEL_KEY, panelOpen ? "open" : "closed");
  }, [panelOpen]);

  // Die aktuelle Seite darf nie in einem zugeklappten Zweig verschwinden —
  // sonst zeigt der Baum nicht mehr, wo man gerade ist.
  useEffect(() => {
    setCollapsed((previous) => {
      const hidden = [...activePath].filter(
        (id) => id !== currentPageId && previous.has(id),
      );
      if (!hidden.length) return previous;
      const next = new Set(previous);
      for (const id of hidden) next.delete(id);
      return next;
    });
  }, [activePath, currentPageId]);

  const toggle = (pageId: string) =>
    setCollapsed((previous) => {
      const next = new Set(previous);
      if (!next.delete(pageId)) next.add(pageId);
      return next;
    });

  const expand = useCallback(
    (pageId: string) =>
      setCollapsed((previous) => {
        if (!previous.has(pageId)) return previous;
        const next = new Set(previous);
        next.delete(pageId);
        return next;
      }),
    [],
  );

  /**
   * Zielindex unter den Geschwistern.
   *
   * Das Backend nimmt die Seite erst aus der Liste und fügt sie dann an
   * ``index`` ein. Kommt sie aus derselben Liste und stand vor dem Ziel,
   * rutscht das Ziel um eine Position nach vorn — genau das rechnet der
   * Abzug hier heraus.
   */
  const indexFor = useCallback(
    (moved: PageNode, target: PageNode, where: DropWhere): [string | null, number] => {
      if (where === "into") return [target.page.id, target.childCount];
      const sameParent = moved.page.parent_id === target.page.parent_id;
      const base = target.index - (sameParent && moved.index < target.index ? 1 : 0);
      return [target.page.parent_id, where === "before" ? base : base + 1];
    },
    [],
  );

  /** Darf ``moved`` unter ``parentId`` liegen? Verhindert Ringschlüsse. */
  const canNest = useCallback(
    (movedId: string, parentId: string | null) => {
      if (parentId === null) return true;
      if (movedId === rootId) return false; // Startseite bleibt Wurzel
      return !pageSubtreeIds(config, movedId).has(parentId);
    },
    [config, rootId],
  );

  const applyDrop = useCallback(
    async (movedId: string, target: DropTarget) => {
      const moved = nodes.get(movedId);
      const node = nodes.get(target.id);
      if (!moved || !node || moved.page.id === node.page.id) return;

      const [parentId, index] = indexFor(moved, node, target.where);
      if (!canNest(movedId, parentId)) return;
      if (target.where === "into") expand(node.page.id);
      await movePage(movedId, parentId, index);
    },
    [canNest, expand, indexFor, movePage, nodes],
  );

  /** Alt + Pfeiltasten — dieselben Bewegungen ohne Maus. */
  const moveByKey = useCallback(
    async (node: PageNode, key: string) => {
      const parentId = node.page.parent_id;
      const siblings = byParent.get(parentId) ?? [];
      if (key === "ArrowUp" && node.index > 0) {
        await movePage(node.page.id, parentId, node.index - 1);
      } else if (key === "ArrowDown" && node.index < node.siblingCount - 1) {
        await movePage(node.page.id, parentId, node.index + 1);
      } else if (key === "ArrowRight" && node.index > 0) {
        // Unter die Seite darüber hängen — der klassische Einrück-Schritt.
        const above = siblings[node.index - 1];
        if (above && canNest(node.page.id, above.page.id)) {
          expand(above.page.id);
          await movePage(node.page.id, above.page.id, above.childCount);
        }
      } else if (key === "ArrowLeft" && parentId) {
        const parent = nodes.get(parentId);
        if (parent) await movePage(node.page.id, parent.page.parent_id, parent.index + 1);
      }
    },
    [byParent, canNest, expand, movePage, nodes],
  );

  if (!panelOpen) {
    return (
      <div className="pagetree collapsed">
        <button
          type="button"
          className="icon-btn"
          title={t("pages.showPanel")}
          onClick={() => setPanelOpen(true)}
        >
          <UiIcon name="sidebar-expand" size={17} />
        </button>
        <span className="pagetree-rail-label">{t("pages.title")}</span>
      </div>
    );
  }

  const context: BranchContext = {
    byParent,
    collapsed,
    rootId,
    activePath,
    dragId,
    drop,
    dragRef,
    dropRef,
    focusRef,
    setDragId,
    setDrop,
    toggle,
    expand,
    applyDrop,
    moveByKey,
    canNest,
    indexFor,
    nodes,
  };

  return (
    <div className="pagetree">
      <header className="pagetree-head">
        <span className="pagetree-title">{t("pages.title")}</span>
        <button
          type="button"
          className="icon-btn"
          title={t("pages.add")}
          onClick={() => void createPage(t("pages.newName"), null)}
        >
          <UiIcon name="plus" size={16} />
        </button>
        <button
          type="button"
          className="icon-btn"
          title={t("pages.hidePanel")}
          onClick={() => setPanelOpen(false)}
        >
          <UiIcon name="sidebar-collapse" size={17} />
        </button>
      </header>

      <div
        className="pagetree-list"
        onDragLeave={(event) => {
          if (!event.currentTarget.contains(event.relatedTarget as Node)) setDrop(null);
        }}
      >
        <Branch parentId={null} context={context} />
      </div>

      <div className="pagetree-hint">
        <p>
          <UiIcon name="arrows-move" size={14} />
          <span>{t("pages.dragHint")}</span>
        </p>
        <p>
          <kbd>Alt</kbd>
          <span className="hint-keys">
            <UiIcon name="arrow-up" size={13} />
            <UiIcon name="arrow-down" size={13} />
          </span>
          <span>{t("pages.moveKeys")}</span>
        </p>
        <p>
          <kbd>Alt</kbd>
          <span className="hint-keys">
            <UiIcon name="arrow-left" size={13} />
            <UiIcon name="arrow-right" size={13} />
          </span>
          <span>{t("pages.indentKeys")}</span>
        </p>
      </div>
    </div>
  );
}

/** Was jede Zeile vom Baum-Zustand braucht — spart ein Dutzend Props je Ebene. */
interface BranchContext {
  byParent: Map<string | null, PageNode[]>;
  collapsed: Set<string>;
  rootId: string;
  activePath: Set<string>;
  /** Nur für die Optik — die Handler entscheiden über die Refs. */
  dragId: string | null;
  drop: DropTarget | null;
  dragRef: MutableRefObject<string | null>;
  dropRef: MutableRefObject<DropTarget | null>;
  /** Zeile, die den Fokus nach einem Umbau zurückbekommen soll. */
  focusRef: MutableRefObject<string | null>;
  setDragId: (id: string | null) => void;
  setDrop: (target: DropTarget | null) => void;
  toggle: (pageId: string) => void;
  expand: (pageId: string) => void;
  applyDrop: (movedId: string, target: DropTarget) => Promise<void>;
  moveByKey: (node: PageNode, key: string) => Promise<void>;
  canNest: (movedId: string, parentId: string | null) => boolean;
  indexFor: (
    moved: PageNode,
    target: PageNode,
    where: DropWhere,
  ) => [string | null, number];
  nodes: Map<string, PageNode>;
}

/** Eine Ebene: die Geschwister und — eingerahmt — deren Unterseiten. */
function Branch({
  parentId,
  context,
}: {
  parentId: string | null;
  context: BranchContext;
}) {
  const children = context.byParent.get(parentId) ?? [];
  if (!children.length) return null;

  return (
    <>
      {children.map((node) => (
        <div key={node.page.id} className="pagegroup">
          <Row node={node} context={context} />
          {node.childCount > 0 && !context.collapsed.has(node.page.id) && (
            <div
              className={
                context.activePath.has(node.page.id)
                  ? "pagebranch in-path"
                  : "pagebranch"
              }
            >
              <Branch parentId={node.page.id} context={context} />
            </div>
          )}
        </div>
      ))}
    </>
  );
}

function Row({ node, context }: { node: PageNode; context: BranchContext }) {
  const { t } = useTranslation();
  const currentPageId = useStore((s) => s.currentPageId);
  const navigate = useStore((s) => s.navigate);
  const createPage = useStore((s) => s.createPage);
  const renamePage = useStore((s) => s.renamePage);
  const deletePage = useStore((s) => s.deletePage);

  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");

  const { page } = node;
  const { drop, dragId } = context;
  const isDropTarget = drop?.id === page.id;
  const isCollapsed = context.collapsed.has(page.id);

  const startRename = () => {
    setDraft(page.name);
    setEditing(true);
  };

  const commitRename = async () => {
    const name = draft.trim();
    setEditing(false);
    if (name && name !== page.name) await renamePage(page.id, name);
  };

  return (
    <div
      className={[
        "pagerow",
        page.id === currentPageId ? "active" : "",
        node.childCount > 0 ? "has-children" : "",
        dragId === page.id ? "dragging" : "",
        isDropTarget ? `drop-${drop.where}` : "",
      ]
        .filter(Boolean)
        .join(" ")}
      data-page-id={page.id}
      draggable={!editing}
      onDragStart={(event) => {
        context.setDragId(page.id);
        event.dataTransfer.effectAllowed = "move";
        event.dataTransfer.setData(DRAG_TYPE, page.id);
      }}
      onDragEnd={() => {
        context.setDragId(null);
        context.setDrop(null);
      }}
      onDragOver={(event) => {
        const moving = context.dragRef.current;
        if (!moving || moving === page.id) return;
        const moved = context.nodes.get(moving);
        if (!moved) return;
        const box = event.currentTarget.getBoundingClientRect();
        const ratio = (event.clientY - box.top) / box.height;
        // Oberes und unteres Viertel sortieren, die Mitte schachtelt ein.
        const where: DropWhere = ratio < 0.25 ? "before" : ratio > 0.75 ? "after" : "into";
        const [parentId] = context.indexFor(moved, node, where);
        if (!context.canNest(moving, parentId)) return;
        event.preventDefault();
        event.dataTransfer.dropEffect = "move";
        const current = context.dropRef.current;
        if (current?.id !== page.id || current.where !== where) {
          context.setDrop({ id: page.id, where });
        }
      }}
      onDrop={(event) => {
        event.preventDefault();
        const moving = context.dragRef.current ?? event.dataTransfer.getData(DRAG_TYPE);
        const target = context.dropRef.current;
        context.setDragId(null);
        context.setDrop(null);
        if (moving && target) void context.applyDrop(moving, target);
      }}
    >
      {node.childCount > 0 ? (
        <button
          type="button"
          className="pagerow-twist"
          title={isCollapsed ? t("pages.expand") : t("pages.collapse")}
          onClick={() => context.toggle(page.id)}
        >
          <UiIcon name={isCollapsed ? "chevron-right" : "chevron-down"} size={14} />
        </button>
      ) : (
        <span className="pagerow-twist empty" aria-hidden />
      )}

      {editing ? (
        <input
          autoFocus
          className="pagerow-input"
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          onBlur={() => void commitRename()}
          onKeyDown={(event) => {
            if (event.key === "Enter") void commitRename();
            if (event.key === "Escape") setEditing(false);
          }}
        />
      ) : (
        <button
          type="button"
          className="pagerow-name"
          onClick={() => void navigate(page.id)}
          onDoubleClick={startRename}
          onFocus={() => {
            context.focusRef.current = page.id;
          }}
          onKeyDown={(event) => {
            if (event.key === "F2") {
              startRename();
              return;
            }
            if (!event.altKey || !event.key.startsWith("Arrow")) return;
            event.preventDefault();
            void context.moveByKey(node, event.key);
          }}
          title={t("pages.rowHint")}
        >
          <span className="pagerow-label">
            {page.id === context.rootId ? page.name || t("pages.root") : page.name}
          </span>
          {node.childCount > 0 && isCollapsed && (
            <span className="pagerow-count">{node.childCount}</span>
          )}
        </button>
      )}

      <span className="pagerow-actions">
        <button
          type="button"
          className="icon-btn"
          title={t("pages.addSub")}
          onClick={() => {
            context.expand(page.id);
            void createPage(t("pages.newName"), page.id);
          }}
        >
          <UiIcon name="corner-down-right" size={15} />
        </button>
        {page.id !== context.rootId && (
          <button
            type="button"
            className="icon-btn danger"
            title={t("pages.delete")}
            onClick={() => {
              if (window.confirm(t("pages.deleteConfirm", { name: page.name }))) {
                void deletePage(page.id);
              }
            }}
          >
            <UiIcon name="trash" size={15} />
          </button>
        )}
      </span>
    </div>
  );
}

function loadCollapsed(): Set<string> {
  try {
    const raw = localStorage.getItem(COLLAPSED_KEY);
    return new Set<string>(raw ? JSON.parse(raw) : []);
  } catch {
    return new Set();
  }
}

/** Brotkrume über dem Deck: welcher Zweig gerade offen ist. */
export function PageCrumbs() {
  const { t } = useTranslation();
  const config = useStore((s) => s.config);
  const currentPageId = useStore((s) => s.currentPageId);
  const navigate = useStore((s) => s.navigate);
  const rootId = activeProfile(config)?.root_page_id ?? "";

  const path = useMemo(() => pagePath(config, currentPageId), [config, currentPageId]);
  if (!path.length) return null;

  return (
    <nav className="crumbs" aria-label={t("pages.title")}>
      {path.map((page, position) => (
        <span key={page.id} className="crumb">
          {position > 0 && (
            <UiIcon name="chevron-right" size={13} className="crumb-sep" />
          )}
          <button
            type="button"
            className={page.id === currentPageId ? "crumb-btn current" : "crumb-btn"}
            onClick={() => void navigate(page.id)}
          >
            {page.id === rootId ? page.name || t("pages.root") : page.name}
          </button>
        </span>
      ))}
    </nav>
  );
}
