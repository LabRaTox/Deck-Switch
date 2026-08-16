import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { api } from "../api/client";
import { useStore } from "../store";

/**
 * Plugins nachinstallieren: aus einer Adresse, aus einer Datei — oder auf
 * Anfrage über einen `streamdeck://`-Link im Browser.
 *
 * Steckt in einem Modal. Die Erfolgsmeldung bleibt deshalb kurz stehen,
 * bevor ``onInstalled`` schließt — sonst verschwände sie mit dem Dialog,
 * und man wüsste nicht, ob es geklappt hat.
 */
export function PluginInstaller({ onInstalled }: { onInstalled?: () => void } = {}) {
  const { t } = useTranslation();
  const load = useStore((s) => s.load);

  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ kind: "ok" | "error"; text: string } | null>(
    null,
  );
  const [dragging, setDragging] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);

  const run = async (task: () => Promise<{ installed: string }>) => {
    setBusy(true);
    setMessage(null);
    try {
      const result = await task();
      await load();
      setMessage({ kind: "ok", text: t("plugins.installed", { name: result.installed }) });
      setUrl("");
      if (onInstalled) window.setTimeout(onInstalled, 1200);
    } catch (error) {
      setMessage({
        kind: "error",
        text: error instanceof Error ? error.message : String(error),
      });
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="installer">
      <div className="field">
        <label htmlFor="plugin-url">{t("plugins.fromUrl")}</label>
        <div className="row">
          <input
            id="plugin-url"
            type="url"
            value={url}
            placeholder="https://…/plugin.zip"
            onChange={(event) => setUrl(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && url.trim()) {
                void run(() => api.installFromUrl(url.trim()));
              }
            }}
          />
          <button
            type="button"
            className="btn primary"
            disabled={busy || !url.trim()}
            onClick={() => void run(() => api.installFromUrl(url.trim()))}
          >
            {busy ? t("plugins.installing") : t("plugins.installAction")}
          </button>
        </div>
      </div>

      <div
        className={dragging ? "dropzone dragging" : "dropzone"}
        onClick={() => fileInput.current?.click()}
        onDragOver={(event) => {
          event.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(event) => {
          event.preventDefault();
          setDragging(false);
          const file = event.dataTransfer.files?.[0];
          if (file) void run(() => api.installPlugin(file));
        }}
      >
        {busy ? t("plugins.installing") : t("plugins.dropArchive")}
        <input
          ref={fileInput}
          type="file"
          accept=".zip,.sdplugin,application/zip"
          hidden
          onChange={(event) => {
            const file = event.target.files?.[0];
            if (file) void run(() => api.installPlugin(file));
            event.target.value = "";
          }}
        />
      </div>

      {message && (
        <p className={message.kind === "ok" ? "saved-hint" : "error-text"}>
          {message.text}
        </p>
      )}

      <p className="help">{t("plugins.trustWarning")}</p>
    </section>
  );
}

/**
 * Bestätigungsleiste für Installationen, die über einen `streamdeck://`-Link
 * angefragt wurden.
 *
 * Bewusst als Nachfrage und nicht als automatische Installation: Ein Klick
 * auf einen Link im Browser darf niemals ungefragt Code auf den Rechner
 * bringen. Deshalb steht die Herkunft groß dabei.
 */
export function InstallRequestBanner() {
  const { t } = useTranslation();
  const requests = useStore((s) => s.installRequests);
  const confirm = useStore((s) => s.confirmInstallRequest);
  const dismiss = useStore((s) => s.dismissInstallRequest);
  const [busy, setBusy] = useState<string | null>(null);

  useEffect(() => {
    void useStore.getState().loadInstallRequests();
  }, []);

  if (requests.length === 0) return null;
  const request = requests[requests.length - 1];
  const host = safeHost(request.url);

  return (
    <div className="install-request">
      <div className="install-request-text">
        <strong>{t("plugins.requestTitle")}</strong>
        <span className="install-origin">{host}</span>
        <code>{request.url}</code>
        <small>{t("plugins.trustWarning")}</small>
      </div>

      <div className="row">
        <button
          type="button"
          className="btn small"
          onClick={() => void dismiss(request.id)}
        >
          {t("plugins.requestReject")}
        </button>
        <button
          type="button"
          className="btn small primary"
          disabled={busy === request.id}
          onClick={async () => {
            setBusy(request.id);
            try {
              await confirm(request.id);
            } finally {
              setBusy(null);
            }
          }}
        >
          {busy === request.id ? t("plugins.installing") : t("plugins.requestAccept")}
        </button>
      </div>
    </div>
  );
}

function safeHost(url: string): string {
  try {
    return new URL(url).host;
  } catch {
    return url.slice(0, 40);
  }
}
