import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { useStore } from "../store";

const GITHUB_URL = "https://github.com/LabRaTox/Deck-Switch";
const DISCORD_URL = "https://discord.gg/2ckNnCZ4wq";

/**
 * Das Menü „Hilfe“ in der Kopfzeile.
 *
 * Auf per Klick, zu per Klick daneben oder Escape. Die beiden Links gehen wie
 * alle `target="_blank"`-Links über `leiteLinksNachAussen` in den Browser.
 */
export function HilfeMenue() {
  const { t } = useTranslation();
  const view = useStore((s) => s.view);
  const setView = useStore((s) => s.setView);
  const [offen, setOffen] = useState(false);
  const wurzel = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!offen) return;
    const beiKlick = (event: PointerEvent) => {
      if (!wurzel.current?.contains(event.target as Node)) setOffen(false);
    };
    const beiTaste = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOffen(false);
    };
    document.addEventListener("pointerdown", beiKlick);
    document.addEventListener("keydown", beiTaste);
    return () => {
      document.removeEventListener("pointerdown", beiKlick);
      document.removeEventListener("keydown", beiTaste);
    };
  }, [offen]);

  return (
    <div className="hilfe-menue" ref={wurzel}>
      <button
        type="button"
        className={view === "about" || offen ? "nav-tab active" : "nav-tab"}
        aria-expanded={offen}
        onClick={() => setOffen((jetzt) => !jetzt)}
      >
        {t("app.help")}
      </button>
      {offen && (
        <div className="hilfe-eintraege">
          <a
            href={GITHUB_URL}
            target="_blank"
            rel="noreferrer noopener"
            onClick={() => setOffen(false)}
          >
            {t("help.github")}
          </a>
          <a
            href={DISCORD_URL}
            target="_blank"
            rel="noreferrer noopener"
            onClick={() => setOffen(false)}
          >
            {t("help.discord")}
          </a>
          <button
            type="button"
            onClick={() => {
              setView("about");
              setOffen(false);
            }}
          >
            {t("help.about")}
          </button>
        </div>
      )}
    </div>
  );
}
