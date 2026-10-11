import { isTauri } from "@tauri-apps/api/core";
import { openUrl } from "@tauri-apps/plugin-opener";

/**
 * Links mit `target="_blank"` im Standardbrowser öffnen.
 *
 * Im Tauri-Fenster führen sie sonst ins Leere: WebKitGTK verwirft die Bitte
 * um ein neues Fenster ohne jede Meldung, der Knopf tut einfach nichts. Statt
 * jeden Link einzeln umzubauen, fängt ein Handler am Dokument alle ab — auch
 * die, die später dazukommen.
 *
 * Nur Adressen nach draußen: Was aufs eigene Backend zeigt (Export,
 * Downloads), bleibt, wie es ist. Im gewöhnlichen Browser, etwa beim
 * Entwickeln mit Vite, tut der Handler nichts — dort gehen solche Links
 * ohnehin auf.
 */
export function leiteLinksNachAussen(): void {
  if (!isTauri()) return;
  document.addEventListener("click", (event) => {
    if (event.defaultPrevented || event.button !== 0) return;
    const link = (event.target as Element | null)?.closest?.("a[href]");
    if (!(link instanceof HTMLAnchorElement) || link.target !== "_blank") return;
    const ziel = new URL(link.href, window.location.href);
    if (!["http:", "https:", "mailto:"].includes(ziel.protocol)) return;
    if (["127.0.0.1", "localhost", "[::1]"].includes(ziel.hostname)) return;
    event.preventDefault();
    void openUrl(ziel.href).catch((fehler) => {
      console.error("Link ließ sich nicht öffnen:", ziel.href, fehler);
    });
  });
}
