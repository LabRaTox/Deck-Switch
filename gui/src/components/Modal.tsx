import { useEffect, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

/**
 * Dialog über der Oberfläche: Klick auf den Hintergrund und Escape schließen,
 * das Scrollen der Seite dahinter wird angehalten.
 */
export function Modal({
  title,
  onClose,
  children,
  footer,
  className = "",
  width,
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
  className?: string;
  width?: number;
}) {
  const { t } = useTranslation();

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = previous;
    };
  }, [onClose]);

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div
        className={`modal ${className}`}
        style={width ? { width: `min(${width}px, 100%)` } : undefined}
        onClick={(event) => event.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label={title}
      >
        <header className="modal-head">
          <h2>{title}</h2>
          <button type="button" className="btn small" onClick={onClose}>
            {t("common.close")}
          </button>
        </header>

        <div className="modal-body">{children}</div>

        {footer && <footer className="modal-foot">{footer}</footer>}
      </div>
    </div>
  );
}
