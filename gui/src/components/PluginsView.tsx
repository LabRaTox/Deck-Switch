import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { api } from "../api/client";
import { localized } from "../i18n";
import { useStore } from "../store";
import type { PluginCategory, PluginInfo } from "../types";
import { Modal } from "./Modal";
import { PfadText } from "./PfadText";
import { PluginDetail } from "./PluginDetail";
import { PluginInstaller } from "./PluginInstaller";
import { SettingsForm } from "./SettingsForm";
import { StoreView } from "./StoreView";

/**
 * Plugin-Übersicht. Die eingebauten Plugins stehen hier ganz normal in der
 * Liste — sie sind technisch keine Sonderfälle, nur von Anfang an dabei.
 */
/**
 * Die Reiter oben — nach Art des Plugins, nicht nach Thema.
 *
 * Das ist die grobe Trennung: Ein Iconset liefert Symbole, ein Schoner malt
 * über das ganze Deck, ein Action-Plugin belegt Tasten. Die feine Sortierung
 * nach Thema macht das Menü links.
 */
const TYPEN = ["action", "iconset", "screensaver", "wallpaper"] as const;
type PluginTyp = (typeof TYPEN)[number];

/**
 * Die Themen, in der Reihenfolge des Menüs.
 *
 * ``system`` steht vorn und nicht alphabetisch zwischen „Streaming" und
 * „Video": Dort stecken Seiten, Helligkeit und Tastendrücke — die Bedienung
 * des Decks selbst, nicht die Zutaten für den nächsten Stream. ``other``
 * bleibt hinten, wo Nachzügler ohne Angabe landen.
 */
const KATEGORIEN: PluginCategory[] = [
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

export function PluginsView() {
  const { t, i18n } = useTranslation();
  const plugins = useStore((s) => s.plugins);
  const reloadPlugins = useStore((s) => s.reloadPlugins);
  const [installOpen, setInstallOpen] = useState(false);
  /**
   * Installiert oder Store. Zwei Zustände statt eines eigenen Reiters oben:
   * Wer nach einem Plugin sucht, sucht es hier — ob es schon auf dem Rechner
   * liegt oder erst geholt werden muss, ist die zweite Frage, nicht die erste.
   */
  const [quelle, setQuelle] = useState<"installiert" | "store">("installiert");
  const [typ, setTyp] = useState<PluginTyp>("action");
  /** Welches Plugin gerade im Ganzen zu sehen ist — ``null`` = die Liste. */
  const [detail, setDetail] = useState<string | null>(null);
  /** ``null`` heißt „alle Kategorien". */
  const [kategorie, setKategorie] = useState<PluginCategory | null>(null);

  /** Alles vom gewählten Typ — die Grundlage für Menü und Liste. */
  const vomTyp = plugins.filter((p) => p.manifest.type === typ);

  /** Wie viele Plugins je Kategorie, damit das Menü Zahlen zeigen kann. */
  const anzahl = new Map<PluginCategory, number>();
  for (const plugin of vomTyp) {
    const k = plugin.manifest.category ?? "other";
    anzahl.set(k, (anzahl.get(k) ?? 0) + 1);
  }

  const sichtbar = kategorie
    ? vomTyp.filter((p) => (p.manifest.category ?? "other") === kategorie)
    : vomTyp;

  if (quelle === "store") {
    return (
      <>
        <QuelleWaehlen quelle={quelle} setQuelle={setQuelle} />
        <StoreView />
      </>
    );
  }

  const gezeigt = detail ? plugins.find((p) => p.id === detail) : null;
  if (gezeigt) {
    return (
      <div className="page-view">
        <PluginDetail plugin={gezeigt} onBack={() => setDetail(null)} />
      </div>
    );
  }

  return (
    <div className="page-view">
      <QuelleWaehlen quelle={quelle} setQuelle={setQuelle} />
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

      {/* Oben die Art, links das Thema — wie im Elgato-Marketplace, nur
          ohne Aufklappmenü: Bei zwei Dutzend Kategorien sieht man so auf
          einen Blick, was es überhaupt gibt. */}
      <div className="plugin-tabs" role="tablist">
        {TYPEN.map((eintrag) => {
          const zahl = plugins.filter((p) => p.manifest.type === eintrag).length;
          return (
            <button
              key={eintrag}
              type="button"
              role="tab"
              aria-selected={typ === eintrag}
              className={typ === eintrag ? "plugin-tab aktiv" : "plugin-tab"}
              onClick={() => {
                setTyp(eintrag);
                // Beim Wechsel der Art alle Themen zeigen: Die vorher
                // gewählte Kategorie ist hier womöglich gar nicht belegt,
                // und eine leere Liste ohne erkennbaren Grund verwirrt.
                setKategorie(null);
              }}
            >
              {t(`plugins.types.${eintrag}`)}
              <span className="plugin-tab-zahl">{zahl}</span>
            </button>
          );
        })}
      </div>

      <div className="plugin-layout">
        <nav className="plugin-kategorien" aria-label={t("plugins.title")}>
          <button
            type="button"
            className={kategorie === null ? "kategorie aktiv" : "kategorie"}
            onClick={() => setKategorie(null)}
          >
            {t("plugins.categories.all")}
            <span className="kategorie-zahl">{vomTyp.length}</span>
          </button>
          {/* Bewusst *alle* Kategorien, auch die leeren: Die Liste ist
              dieselbe wie im Elgato-Marketplace, und wer dort sucht, soll
              hier dieselben Schubladen finden. Leere sind gedämpft und
              nicht anklickbar — sie zeigen, was es geben *kann*, führen
              aber nicht auf eine leere Seite. */}
          {KATEGORIEN.map((k) => {
            const zahl = anzahl.get(k) ?? 0;
            return (
              <button
                key={k}
                type="button"
                disabled={zahl === 0}
                className={
                  kategorie === k
                    ? "kategorie aktiv"
                    : zahl === 0
                      ? "kategorie leer"
                      : "kategorie"
                }
                onClick={() => setKategorie(k)}
              >
                {t(`plugins.categories.${k}`)}
                <span className="kategorie-zahl">{zahl}</span>
              </button>
            );
          })}
        </nav>

        <div className="plugin-inhalt">
          {/* Ohne die Existenzprüfung stünde bei einem neuen Typ der rohe
              Schlüssel in der Oberfläche — genau das ist beim Einbau der
              Reiter passiert („plugins.iconsetsHint"). */}
          {typ !== "action" && i18n.exists(`plugins.${typ}sHint`) && (
            <p className="hint">
              <PfadText text={t(`plugins.${typ}sHint`)} />
            </p>
          )}

          {sichtbar.length === 0 ? (
            <p className="empty-note">{t("plugins.emptyCategory")}</p>
          ) : (
            <div className="plugin-list">
              {sichtbar.map((plugin) => (
                <PluginCard
                  key={plugin.id}
                  plugin={plugin}
                  onOeffnen={() => setDetail(plugin.id)}
                />
              ))}
            </div>
          )}
        </div>
      </div>

      {installOpen && (
        <Modal
          title={t("plugins.install")}
          width={560}
          onClose={() => setInstallOpen(false)}
        >
          <PluginInstaller onInstalled={() => setInstallOpen(false)} />
        </Modal>
      )}
    </div>
  );
}

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
  onOeffnen,
}: {
  plugin: PluginInfo;
  onOeffnen: () => void;
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
        <PluginIcon plugin={plugin} />
        <ConnectionDot status={plugin.status} />
        <div className="plugin-title">
          {/* Nur der Name öffnet die Detailansicht, nicht die ganze Karte:
              Darin stecken Schalter, Knöpfe und ein Formular — ein Klick
              darauf soll nicht die Ansicht wechseln. */}
          <button type="button" className="plugin-name" onClick={onOeffnen}>
            {localized(plugin.manifest.name, i18n.language)}
          </button>
          <small>
            v{plugin.manifest.version}
            {/* Die Aktionszahl nur dort, wo sie etwas aussagt — bei einem
                Schoner stünde dauerhaft "0 Aktionen". */}
            {plugin.manifest.type === "action" &&
              ` · ${t("plugins.actions", { count: plugin.manifest.actions.length })}`}
            {/* Iconsets haben keine Aktionen, dafür eine Lizenz — die stand
                bisher nur im eigenen Abschnitt und ginge sonst verloren. */}
            {plugin.manifest.license ? ` · ${plugin.manifest.license}` : ""}
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

/**
 * Der Umschalter zwischen dem, was da ist, und dem, was es gibt.
 *
 * Die Zahl am Store-Knopf zeigt, was auf Prüfung wartet — sie steht nur bei
 * denen, die prüfen dürfen.
 */
function QuelleWaehlen({
  quelle,
  setQuelle,
}: {
  quelle: "installiert" | "store";
  setQuelle: (q: "installiert" | "store") => void;
}) {
  const { t } = useTranslation();
  const storePending = useStore((s) => s.storePending);
  const offen = storePending ? storePending.submissions + storePending.reports : 0;

  return (
    <div className="plugin-quelle" role="tablist">
      {(["installiert", "store"] as const).map((eintrag) => (
        <button
          key={eintrag}
          type="button"
          role="tab"
          aria-selected={quelle === eintrag}
          className={quelle === eintrag ? "plugin-tab aktiv" : "plugin-tab"}
          onClick={() => setQuelle(eintrag)}
        >
          {t(`plugins.source.${eintrag}`)}
          {eintrag === "store" && offen > 0 && <span className="plugin-tab-zahl">{offen}</span>}
        </button>
      ))}
    </div>
  );
}
