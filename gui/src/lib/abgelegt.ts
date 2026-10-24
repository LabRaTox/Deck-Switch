import { invoke, isTauri } from "@tauri-apps/api/core";
import { getCurrentWebview } from "@tauri-apps/api/webview";
import { useEffect, useRef, useState, type DragEvent } from "react";

import i18n from "../i18n";

/**
 * Ablegefelder für Dateien aus dem Dateimanager, im Browser und im Fenster.
 *
 * Im Browser steckt die Datei in `dataTransfer.files`. Im Tauri-Fenster
 * kommt sie dort nicht an: Beim Ziehen aus dem Dateimanager meldet
 * WebKitGTK `files` leer und kündigt nur `text/uri-list` an (gemessen mit
 * Dolphin unter Plasma 6). Eine Datei ließ sich daraus nicht gewinnen.
 * Im Fenster übernimmt deshalb Tauri das Ablegen. Es meldet die Pfade samt
 * Mausposition; die Position sagt, welches Feld gemeint ist, und das Fenster
 * liest die Datei über `lies_abgelegte_datei` ein.
 */

type Feld = {
  element: HTMLElement;
  setUeber: (ueber: boolean) => void;
  onDateien: (dateien: File[]) => void;
  onFehler: (text: string) => void;
};

const felder = new Set<Feld>();
let tauriLauscht = false;

/**
 * Das Ablegefeld unter einer Position, die Tauri in physischen Pixeln meldet.
 *
 * Bei Bildschirm-Skalierung kann die Umrechnung danebenliegen. Ist nur ein
 * Ablegefeld angemeldet, ist es das gemeinte, auch ohne Treffer.
 */
function feldAn(position: { x: number; y: number }): Feld | null {
  const skala = window.devicePixelRatio || 1;
  const element = document.elementFromPoint(position.x / skala, position.y / skala);
  if (element) {
    for (const feld of felder) {
      if (feld.element.contains(element)) return feld;
    }
  }
  return felder.size === 1 ? [...felder][0] : null;
}

function lauscheAufTauri(): void {
  if (tauriLauscht) return;
  tauriLauscht = true;
  void getCurrentWebview()
    .onDragDropEvent(({ payload }) => {
      if (payload.type === "leave") {
        for (const feld of felder) feld.setUeber(false);
        return;
      }
      const ziel = feldAn(payload.position);
      for (const feld of felder) feld.setUeber(feld === ziel && payload.type !== "drop");
      if (payload.type !== "drop" || !ziel) return;
      ladePfade(payload.paths)
        .then((dateien) => {
          if (dateien.length > 0) ziel.onDateien(dateien);
          else ziel.onFehler(i18n.t("errors.dropMissing"));
        })
        .catch((fehler) => ziel.onFehler(fehlerText(fehler)));
    })
    .catch((fehler) => {
      tauriLauscht = false;
      console.error("Ablegen im Fenster nicht verfügbar:", fehler);
    });
}

async function ladePfade(pfade: string[]): Promise<File[]> {
  const dateien: File[] = [];
  for (const pfad of pfade) {
    const inhalt = await invoke<ArrayBuffer>("lies_abgelegte_datei", { pfad });
    const name = pfad.split("/").pop() || "datei";
    dateien.push(new File([inhalt], name, { type: typVon(name) }));
  }
  return dateien;
}

/**
 * Text zu einer Fehlerkennung aus dem Fenster.
 *
 * Das Fenster meldet nur Kennungen; die Sprache kennt die Oberfläche.
 */
function fehlerText(fehler: unknown): string {
  const kennung = fehler instanceof Error ? fehler.message : String(fehler);
  if (kennung === "not-dropped") return i18n.t("errors.dropNotAllowed");
  if (kennung === "not-a-file") return i18n.t("errors.dropNotAFile");
  if (kennung === "too-large") return i18n.t("errors.dropTooLarge", { mb: 64 });
  if (kennung.startsWith("io:")) return i18n.t("errors.dropRead", { detail: kennung.slice(3) });
  return kennung;
}

/** Medientyp nach Endung, wie ihn der Browser einer Datei mitgeben würde. */
function typVon(name: string): string {
  const endung = name.toLowerCase().split(".").pop() ?? "";
  const typen: Record<string, string> = {
    zip: "application/zip",
    tar: "application/x-tar",
    gz: "application/gzip",
    tgz: "application/gzip",
    png: "image/png",
    jpg: "image/jpeg",
    jpeg: "image/jpeg",
    gif: "image/gif",
    webp: "image/webp",
    svg: "image/svg+xml",
  };
  return typen[endung] ?? "application/octet-stream";
}

/**
 * Macht ein Element zum Ablegefeld.
 *
 * `ref` und die Handler aus `props` kommen an das Element, `ueber` sagt, ob
 * gerade etwas darüber gezogen wird. `onDateien` bekommt die abgelegten
 * Dateien, `onFehler` eine Meldung, wenn das Einlesen scheitert.
 */
export function useAblegefeld<T extends HTMLElement = HTMLDivElement>(opts: {
  onDateien: (dateien: File[]) => void;
  onFehler: (text: string) => void;
}) {
  const ref = useRef<T>(null);
  const [ueber, setUeber] = useState(false);
  // Die Rückrufe ändern sich mit jedem Rendern; angemeldet wird das Feld
  // aber nur einmal. Deshalb gehen die Aufrufe über diese Referenz.
  const aktuell = useRef(opts);
  aktuell.current = opts;

  useEffect(() => {
    const element = ref.current;
    if (!element || !isTauri()) return;
    const feld: Feld = {
      element,
      setUeber,
      onDateien: (dateien) => aktuell.current.onDateien(dateien),
      onFehler: (text) => aktuell.current.onFehler(text),
    };
    felder.add(feld);
    lauscheAufTauri();
    return () => {
      felder.delete(feld);
    };
  }, []);

  // Im Browser kommt die Datei über die gewöhnlichen Ereignisse.
  const props = {
    onDragOver: (event: DragEvent<T>) => {
      event.preventDefault();
      setUeber(true);
    },
    onDragLeave: () => setUeber(false),
    onDrop: (event: DragEvent<T>) => {
      event.preventDefault();
      setUeber(false);
      const dateien = Array.from(event.dataTransfer.files);
      if (dateien.length > 0) aktuell.current.onDateien(dateien);
    },
  };

  return { ref, ueber, props };
}
