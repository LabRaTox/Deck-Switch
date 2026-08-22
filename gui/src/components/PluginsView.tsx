import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { api } from "../api/client";
import { localized } from "../i18n";
import { useStore } from "../store";
import type { PluginInfo } from "../types";
import { Modal } from "./Modal";
import { PfadText } from "./PfadText";
import { PluginInstaller } from "./PluginInstaller";
import { SettingsForm } from "./SettingsForm";

/**
 * Plugin-Übersicht. Die eingebauten Plugins stehen hier ganz normal in der
 * Liste — sie sind technisch keine Sonderfälle, nur von Anfang an dabei.
 */
const ORDER_MIME = "application/x-streamdeck-plugin";

export function PluginsView() {
  const { t, i18n } = useTranslation();
  const plugins = useStore((s) => s.plugins);
  const reloadPlugins = useStore((s) => s.reloadPlugins);
  const setPluginOrder = useStore((s) => s.setPluginOrder);
  const [dragOver, setDragOver] = useState<string | null>(null);
  const [installOpen, setInstallOpen] = useState(false);

  const actions = plugins.filter((p) => p.manifest.type === "action");
  const screensavers = plugins.filter((p) => p.manifest.type === "screensaver");
  const wallpapers = plugins.filter((p) => p.manifest.type === "wallpaper");
  const iconsets = plugins.filter((p) => p.manifest.type === "iconset");

  /** Verschiebt das gezogene Plugin an die Position des Ziels. */
  const reorder = (draggedId: string, targetId: string) => {
    if (draggedId === targetId) return;
    const ids = actions.map((p) => p.id);
    const from = ids.indexOf(draggedId);
    const to = ids.indexOf(targetId);
    if (from < 0 || to < 0) return;
    ids.splice(to, 0, ...ids.splice(from, 1));
    // Alles Übrige hinten anhängen, damit keine ID aus der Reihenfolge
    // fällt — was fehlt, sortiert das Backend sonst ans Ende.
    const rest = plugins
      .filter((p) => p.manifest.type !== "action")
      .map((p) => p.id);
    void setPluginOrder([...ids, ...rest]);
  };

  return (
    <div className="page-view">
      <div className="page-head">
        <h2>{t("plugins.title")}</h2>
        <div className="row">
          <button type="button" className="btn" onClick={() => void reloadPlugins()}>
            {t("plugins.reload")}
          </button>
          <button
            type="button"
            className="btn primary"
            onClick={() => setInstallOpen(true)}
          >
            {t("plugins.install")}
          </button>
        </div>
      </div>

      <p className="hint">{t("plugins.reorderHint")}</p>

      <div className="plugin-list">
        {actions.map((plugin) => (
          <div
            key={plugin.id}
            className={dragOver === plugin.id ? "plugin-slot drop" : "plugin-slot"}
            onDragOver={(event) => {
              if (!event.dataTransfer.types.includes(ORDER_MIME)) return;
              event.preventDefault();
              event.dataTransfer.dropEffect = "move";
              setDragOver(plugin.id);
            }}
            onDragLeave={() => setDragOver((id) => (id === plugin.id ? null : id))}
            onDrop={(event) => {
              event.preventDefault();
              setDragOver(null);
              const dragged = event.dataTransfer.getData(ORDER_MIME);
              if (dragged) reorder(dragged, plugin.id);
            }}
          >
            <PluginCard plugin={plugin} />
          </div>
        ))}
      </div>

      {/* Schoner und Hintergründe belegen keine Taste und stehen deshalb in
          eigenen Abschnitten — eingestellt werden sie unter Einstellungen. */}
      <PluginSection
        title={t("plugins.screensavers")}
        hint={t("plugins.screensaversHint")}
        plugins={screensavers}
      />

      <PluginSection
        title={t("plugins.wallpapers")}
        hint={t("plugins.wallpapersHint")}
        plugins={wallpapers}
      />

      {installOpen && (
        <Modal
          title={t("plugins.install")}
          width={560}
          onClose={() => setInstallOpen(false)}
        >
          <PluginInstaller onInstalled={() => setInstallOpen(false)} />
        </Modal>
      )}

      <h3 className="section-title">{t("plugins.iconsets")}</h3>
      <div className="plugin-list">
        {iconsets.map((plugin) => (
          <div
            key={plugin.id}
            className="plugin-card"
            style={{ borderLeftColor: plugin.manifest.accent }}
          >
            <div className="plugin-head">
              <PluginIcon plugin={plugin} />
              <div className="plugin-title">
                <strong>{localized(plugin.manifest.name, i18n.language)}</strong>
                <small>
                  v{plugin.manifest.version}
                  {plugin.manifest.license ? ` · ${plugin.manifest.license}` : ""}
                </small>
              </div>
              {plugin.builtin && <span className="badge">{t("plugins.builtin")}</span>}
            </div>
            <p className="plugin-description">
              {localized(plugin.manifest.description, i18n.language)}
            </p>
            {plugin.error && <p className="error-text">{plugin.error}</p>}
          </div>
        ))}
      </div>
    </div>
  );
}

/**
 * Abschnitt für Plugins, die keine Taste belegen.
 *
 * Bleibt sichtbar, auch wenn noch keines installiert ist — sonst wäre nicht
 * erkennbar, dass es die Sorte überhaupt gibt.
 */
function PluginSection({
  title,
  hint,
  plugins,
}: {
  title: string;
  hint: string;
  plugins: PluginInfo[];
}) {
  const { t } = useTranslation();
  return (
    <>
      <h3 className="section-title">{title}</h3>
      <p className="hint">
        <PfadText text={hint} />
      </p>
      {plugins.length === 0 ? (
        <p className="empty-note">{t("plugins.noneInstalled")}</p>
      ) : (
        <div className="plugin-list">
          {plugins.map((plugin) => (
            <PluginCard key={plugin.id} plugin={plugin} sortable={false} />
          ))}
        </div>
      )}
    </>
  );
}

/**
 * Symbol eines Plugins. Ohne eigenes Bild bleibt ein farbiges Feld mit dem
 * Anfangsbuchstaben — besser als eine Lücke, und die Akzentfarbe ist ohnehin
 * das, woran man die Plugins in der Liste auseinanderhält.
 */
function PluginIcon({ plugin }: { plugin: PluginInfo }) {
  const { i18n } = useTranslation();
  const name = localized(plugin.manifest.name, i18n.language);

  if (plugin.has_icon) {
    return <img className="plugin-icon" src={api.pluginIconUrl(plugin.id)} alt="" />;
  }
  return (
    <span
      className="plugin-icon placeholder"
      style={{ background: plugin.manifest.accent }}
      aria-hidden="true"
    >
      {name.slice(0, 1).toUpperCase()}
    </span>
  );
}

/**
 * Verbindungsanzeige eines Plugins: grün wenn verbunden, grau wenn nicht.
 *
 * Plugins ohne externe Verbindung (Audio, System, Streamdeck) liefern keinen
 * Status — dort bleibt der Platz leer, statt eine Bedeutung vorzutäuschen.
 * Die Farbe des Plugins steckt stattdessen im Streifen an der Kartenkante.
 */
function ConnectionDot({ status }: { status: PluginInfo["status"] }) {
  const { t } = useTranslation();
  if (!status) return <span className="dot-placeholder" />;

  return (
    <span
      className={status.connected ? "status-dot online" : "status-dot offline"}
      title={`${status.connected ? t("plugins.connected") : t("plugins.disconnected")}${
        status.detail ? ` — ${status.detail}` : ""
      }`}
    />
  );
}

function PluginCard({
  plugin,
  sortable = true,
}: {
  plugin: PluginInfo;
  /** Nur Aktions-Plugins haben eine Reihenfolge, die etwas bedeutet. */
  sortable?: boolean;
}) {
  const { t, i18n } = useTranslation();
  const setPluginConfig = useStore((s) => s.setPluginConfig);
  const setPluginEnabled = useStore((s) => s.setPluginEnabled);
  const uninstall = useStore((s) => s.uninstallPlugin);

  const [draft, setDraft] = useState<Record<string, unknown>>(plugin.config);
  const [saved, setSaved] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [open, setOpen] = useState(false);

  // Vorgabewerte aus dem Schema mit übernehmen: im Formular stehen sie
  // ohnehin sichtbar drin, also sollen sie auch so gespeichert werden — sonst
  // hängt das Verhalten an Fallbacks tief im Plugin.
  useEffect(() => {
    const withDefaults: Record<string, unknown> = {};
    for (const field of plugin.manifest.config_schema) {
      if (field.default !== null && field.default !== undefined) {
        withDefaults[field.key] = field.default;
      }
    }
    setDraft({ ...withDefaults, ...plugin.config });
    setDirty(false);
  }, [plugin.config, plugin.manifest.config_schema]);

  const hasConfig = plugin.manifest.config_schema.length > 0;

  return (
    <div
      className={plugin.enabled ? "plugin-card" : "plugin-card disabled"}
      style={{ borderLeftColor: plugin.manifest.accent }}
    >
      <div className="plugin-head">
        {/* Nur der Griff ist ziehbar — sonst könnte man beim Bedienen der
            Schalter versehentlich die Reihenfolge verändern. */}
        {sortable && (
          <span
            className="drag-handle"
            draggable
            title={t("plugins.reorder")}
            onDragStart={(event) => {
              event.dataTransfer.setData(ORDER_MIME, plugin.id);
              event.dataTransfer.effectAllowed = "move";
            }}
          >
            ⠿
          </span>
        )}
        <PluginIcon plugin={plugin} />
        <ConnectionDot status={plugin.status} />
        <div className="plugin-title">
          <strong>{localized(plugin.manifest.name, i18n.language)}</strong>
          <small>
            v{plugin.manifest.version}
            {/* Die Aktionszahl nur dort, wo sie etwas aussagt — bei einem
                Schoner stünde dauerhaft "0 Aktionen". */}
            {plugin.manifest.type === "action" &&
              ` · ${t("plugins.actions", { count: plugin.manifest.actions.length })}`}
            {plugin.status && ` · ${plugin.status.detail}`}
          </small>
        </div>

        {plugin.builtin ? (
          <span className="badge">{t("plugins.builtin")}</span>
        ) : (
          <button
            type="button"
            className="btn small danger"
            title={t("plugins.uninstall")}
            onClick={() => {
              const name = localized(plugin.manifest.name, i18n.language);
              if (window.confirm(t("plugins.uninstallConfirm", { name }))) {
                void uninstall(plugin.id);
              }
            }}
          >
            {t("plugins.uninstall")}
          </button>
        )}

        <label className="switch" title={t("plugins.enabled")}>
          <input
            type="checkbox"
            checked={plugin.enabled}
            onChange={(event) => void setPluginEnabled(plugin.id, event.target.checked)}
          />
          <span />
        </label>
      </div>

      <p className="plugin-description">
        {localized(plugin.manifest.description, i18n.language)}
      </p>

      {plugin.error && <p className="error-text">{plugin.error}</p>}

      {plugin.enabled && hasConfig && (
        <button type="button" className="btn small" onClick={() => setOpen(true)}>
          {t("plugins.config")}
        </button>
      )}

      {open && (
        <Modal
          title={`${localized(plugin.manifest.name, i18n.language)} — ${t("plugins.config")}`}
          width={560}
          onClose={() => {
            // Ungespeichertes verwerfen wäre unhöflich — lieber nachfragen.
            if (dirty && !window.confirm(t("plugins.discardChanges"))) return;
            setDraft(plugin.config);
            setDirty(false);
            setOpen(false);
          }}
          footer={
            <>
              {saved && <span className="saved-hint">{t("plugins.saved")}</span>}
              <button
                type="button"
                className="btn primary"
                disabled={!dirty}
                onClick={async () => {
                  await setPluginConfig(plugin.id, draft);
                  setDirty(false);
                  setSaved(true);
                }}
              >
                {t("plugins.save")}
              </button>
            </>
          }
        >
          <SettingsForm
            pluginId={plugin.id}
            schema={plugin.manifest.config_schema}
            values={draft}
            onChange={(key, value) => {
              setDraft((current) => ({ ...current, [key]: value }));
              setDirty(true);
              setSaved(false);
            }}
          />

          {plugin.id === "discord" && <DiscordConnect />}
        </Modal>
      )}
    </div>
  );
}

/**
 * Discord braucht einen Schritt, der in kein Eingabefeld passt: Der
 * Discord-Client fragt beim ersten Verbinden per Dialog um Erlaubnis.
 */
function DiscordConnect() {
  const { t } = useTranslation();
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<{ connected?: boolean; user?: unknown; error?: string }>(
    {},
  );

  useEffect(() => {
    api
      .pluginCommand("discord", "status")
      .then((result) => setStatus(result as typeof status))
      .catch(() => undefined);
  }, []);

  const userName = (status.user as { username?: string } | undefined)?.username;

  return (
    <div className="discord-connect">
      <button
        type="button"
        className="btn primary"
        disabled={busy}
        onClick={async () => {
          setBusy(true);
          setStatus({});
          try {
            const result = await api.pluginCommand("discord", "connect");
            setStatus(result as typeof status);
          } catch (error) {
            setStatus({
              error: error instanceof Error ? error.message : String(error),
            });
          } finally {
            setBusy(false);
          }
        }}
      >
        {busy ? t("plugins.discordConnecting") : t("plugins.discordConnect")}
      </button>

      {status.connected && (
        <span className="saved-hint">
          {t("plugins.discordConnected", { user: userName ?? "?" })}
        </span>
      )}
      {status.error && <span className="error-text">{status.error}</span>}

      <button
        type="button"
        className="btn small"
        onClick={() => void api.pluginCommand("discord", "forget").then(() => setStatus({}))}
      >
        {t("plugins.discordForget")}
      </button>
    </div>
  );
}
