# Marketplace — Planung

Stand: 2026-08-03. **Noch nichts davon ist gebaut.** Das Dokument hält fest,
was entschieden ist, wie das Datenmodell aussehen soll und was noch offen
ist. Es ist bewusst ausführlich beim Datenmodell: Alles andere lässt sich
später umbauen, ein Schema mit echten Daten darin nicht mehr billig.

## Festlegungen

* Eigene Webseite, **auf Englisch**, geschrieben mit **Next.js**.
* Die Plugin-Dateien liegen **bei uns**.
* **SQLite** als Datenbank.
* **Keine bezahlten Plugins.**
* Plugins werden **von Moderatoren manuell geprüft**, bevor sie erscheinen.
* Autoren können als **vertrauenswürdig** markiert werden und
  veröffentlichen dann ohne diese Prüfung.
* **Benutzer- und Gruppenverwaltung** mit Rechten.
* Download **direkt** (HTTP) und über das **Schema**
  (`streamdeck://install?url=…`) — beide werden gezählt.
* **Bewertungen mit Herzchen, positiv wie negativ**, für Plugins und für
  Autoren.
* Die App zeigt einen Ausschnitt: die populärsten Plugins.

## Technik

| Teil | Wahl | Anmerkung |
| --- | --- | --- |
| Web | Next.js (App Router) | Server Actions für Formulare, Route Handler für die API |
| Datenbank | SQLite | über **Drizzle** oder **better-sqlite3** — synchron, kein Verbindungspool nötig |
| Anmeldung | Auth.js (NextAuth) | GitHub als Anbieter, Rollen liegen bei uns |
| Dateien | Dateisystem neben der Datenbank | `data/plugins/<id>/<version>.zip` |
| Suche | SQLite FTS5 | reicht weit über das hinaus, was hier je nötig wird |

### Ein Fallstrick, der vorab geklärt sein muss

**SQLite und Vercel vertragen sich nicht.** Die übliche Next.js-Umgebung
läuft serverlos und hat kein beständiges Dateisystem — eine SQLite-Datei
wäre nach jedem Aufruf wieder weg, und die hochgeladenen ZIPs ebenso.

Wer SQLite will, braucht einen Ort mit echter Platte:

* ein eigener kleiner Server (VPS) mit Node und einem Reverse Proxy,
* oder eine Plattform mit beständigem Volume (Fly.io, Railway, Coolify auf
  eigener Hardware).

Das ist kein Argument gegen SQLite — für diese Größenordnung ist es die
richtige Wahl und spart einen Datenbankserver. Es legt nur fest, wo die
Seite laufen kann.

## Datenmodell

```sql
-- ─────────────────────────────────────────────── Benutzer und Rechte

CREATE TABLE users (
  id            INTEGER PRIMARY KEY,
  handle        TEXT    NOT NULL UNIQUE,      -- Anzeigename, in URLs
  email         TEXT    UNIQUE,               -- nur für Benachrichtigungen
  avatar_url    TEXT,
  bio           TEXT,
  website       TEXT,
  -- Wer hier steht, darf ohne manuelle Prüfung veröffentlichen. Bewusst
  -- ein Feld am Benutzer und kein Recht in einer Gruppe: Es wird einzeln
  -- vergeben, mit Begründung, und man will sehen, von wem und wann.
  trusted_at    TEXT,
  trusted_by    INTEGER REFERENCES users(id),
  trusted_note  TEXT,
  banned_at     TEXT,
  banned_reason TEXT,
  created_at    TEXT    NOT NULL DEFAULT (datetime('now')),
  last_seen_at  TEXT
);

CREATE TABLE accounts (               -- Anmeldung über externe Anbieter
  id           INTEGER PRIMARY KEY,
  user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  provider     TEXT    NOT NULL,      -- 'github', …
  provider_id  TEXT    NOT NULL,
  UNIQUE (provider, provider_id)
);

CREATE TABLE groups (
  id          INTEGER PRIMARY KEY,
  name        TEXT    NOT NULL UNIQUE,   -- 'member', 'moderator', 'admin'
  label       TEXT    NOT NULL,
  -- Rang entscheidet, wer wen verwalten darf: niemand vergibt eine Gruppe
  -- oberhalb der eigenen.
  rank        INTEGER NOT NULL DEFAULT 0,
  is_default  INTEGER NOT NULL DEFAULT 0  -- neue Konten bekommen diese
);

CREATE TABLE permissions (
  id     INTEGER PRIMARY KEY,
  name   TEXT NOT NULL UNIQUE   -- 'plugin.review', 'user.trust', 'user.ban', …
);

CREATE TABLE group_permissions (
  group_id      INTEGER NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
  permission_id INTEGER NOT NULL REFERENCES permissions(id) ON DELETE CASCADE,
  PRIMARY KEY (group_id, permission_id)
);

CREATE TABLE user_groups (
  user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  group_id   INTEGER NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
  granted_by INTEGER REFERENCES users(id),
  granted_at TEXT    NOT NULL DEFAULT (datetime('now')),
  PRIMARY KEY (user_id, group_id)
);

-- ─────────────────────────────────────────────────────────── Plugins

CREATE TABLE plugins (
  id          INTEGER PRIMARY KEY,
  slug        TEXT    NOT NULL UNIQUE,   -- die Plugin-ID aus dem Manifest
  owner_id    INTEGER NOT NULL REFERENCES users(id),
  name        TEXT    NOT NULL,
  summary     TEXT    NOT NULL,          -- eine Zeile für die Kachel
  description TEXT,                      -- Markdown für die Detailseite
  kind        TEXT    NOT NULL,          -- action | iconset | screensaver | wallpaper
  license     TEXT,
  source_url  TEXT,
  icon_path   TEXT,
  created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
  -- Sichtbarkeit steuert die Liste, nicht der Prüfstatus einer Version:
  -- ein Plugin bleibt sichtbar, auch wenn die neueste Version noch wartet.
  visibility  TEXT    NOT NULL DEFAULT 'draft',  -- draft | listed | hidden
  removed_at  TEXT,
  removed_reason TEXT
);

CREATE TABLE plugin_versions (
  id           INTEGER PRIMARY KEY,
  plugin_id    INTEGER NOT NULL REFERENCES plugins(id) ON DELETE CASCADE,
  version      TEXT    NOT NULL,
  file_path    TEXT    NOT NULL,
  file_size    INTEGER NOT NULL,
  sha256       TEXT    NOT NULL,
  -- Das Manifest, wie es im Archiv steht. Als Rohtext aufbewahrt, damit
  -- sich später nachvollziehen lässt, was tatsächlich ausgeliefert wurde.
  manifest_json TEXT   NOT NULL,
  min_app_version TEXT,
  changelog    TEXT,
  status       TEXT    NOT NULL DEFAULT 'pending',  -- pending|approved|rejected|withdrawn
  submitted_at TEXT    NOT NULL DEFAULT (datetime('now')),
  reviewed_at  TEXT,
  reviewed_by  INTEGER REFERENCES users(id),
  review_note  TEXT,
  -- Denormalisiert, damit Listen ohne Aggregat auskommen.
  download_count INTEGER NOT NULL DEFAULT 0,
  UNIQUE (plugin_id, version)
);

CREATE INDEX idx_versions_status ON plugin_versions(status, submitted_at);

-- ────────────────────────────────────────────────────── Bewertungen

-- Ein Herz oder ein gebrochenes: +1 oder -1. Eine Tabelle für Plugins und
-- Autoren, damit die Auswertung nicht zweimal geschrieben werden muss.
CREATE TABLE ratings (
  id          INTEGER PRIMARY KEY,
  user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  target_type TEXT    NOT NULL CHECK (target_type IN ('plugin', 'user')),
  target_id   INTEGER NOT NULL,
  value       INTEGER NOT NULL CHECK (value IN (-1, 1)),
  comment     TEXT,
  created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
  updated_at  TEXT,
  -- Jeder bewertet jedes Ziel genau einmal; Meinungsänderung ändert die
  -- Zeile, statt eine zweite anzulegen.
  UNIQUE (user_id, target_type, target_id)
);

CREATE INDEX idx_ratings_target ON ratings(target_type, target_id);

-- ─────────────────────────────────────────────────────── Downloads

CREATE TABLE download_events (
  id          INTEGER PRIMARY KEY,
  version_id  INTEGER NOT NULL REFERENCES plugin_versions(id) ON DELETE CASCADE,
  -- 'direct'  = Klick auf der Webseite
  -- 'scheme'  = über streamdeck://install
  -- 'app'     = aus dem Reiter „Entdecken" der App
  method      TEXT    NOT NULL CHECK (method IN ('direct', 'scheme', 'app')),
  -- Gekürzter Hash der Adresse, nur um Mehrfachzählung zu erkennen. Keine
  -- IP im Klartext, und nach der Aufbewahrungsfrist fällt die Zeile weg.
  visitor_key TEXT,
  created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_downloads_time ON download_events(created_at);
CREATE INDEX idx_downloads_version ON download_events(version_id, created_at);

-- ─────────────────────────────────────────────── Moderation und Meldungen

CREATE TABLE reports (
  id          INTEGER PRIMARY KEY,
  reporter_id INTEGER REFERENCES users(id),
  target_type TEXT    NOT NULL CHECK (target_type IN ('plugin', 'user', 'rating')),
  target_id   INTEGER NOT NULL,
  reason      TEXT    NOT NULL,
  detail      TEXT,
  status      TEXT    NOT NULL DEFAULT 'open',   -- open | resolved | dismissed
  handled_by  INTEGER REFERENCES users(id),
  handled_at  TEXT,
  created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- Jede Handlung eines Moderators wird festgehalten — auch die eigene.
CREATE TABLE audit_log (
  id          INTEGER PRIMARY KEY,
  actor_id    INTEGER REFERENCES users(id),
  action      TEXT    NOT NULL,   -- 'version.approve', 'user.trust', …
  target_type TEXT,
  target_id   INTEGER,
  detail      TEXT,
  created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);
```

### Warum einiges so und nicht anders

* **`trusted_at` am Benutzer statt als Gruppenrecht.** „Darf ohne Prüfung
  veröffentlichen" wird einzeln vergeben, mit Begründung, und man will
  später sehen, wer das wann getan hat. Als Recht in einer Gruppe wäre es
  ein Schalter ohne Geschichte.
* **Status an der Version, Sichtbarkeit am Plugin.** Sonst verschwindet ein
  etabliertes Plugin aus der Liste, sobald der Autor eine neue Fassung
  einreicht, die noch auf Prüfung wartet.
* **`manifest_json` als Rohtext.** Wenn später jemand fragt, was in einer
  bestimmten Fassung stand, ist das die einzige verlässliche Antwort.
* **`download_events` einzeln, dazu ein Zähler an der Version.** Der Zähler
  trägt die Listen, die Ereignisse tragen „populär in den letzten 30
  Tagen". Ohne Einzelzeilen gäbe es nur eine Gesamtsumme, in der ein altes
  Plugin dauerhaft vorn stünde.
* **Bewertungen in einer Tabelle mit `target_type`.** Plugins und Autoren
  werden gleich bewertet; zwei getrennte Tabellen hießen jede Auswertung
  zweimal.
* **`audit_log` von Anfang an.** Nachträglich einzuführen bedeutet, dass
  für alles davor nichts dokumentiert ist.

## Rollen und Rechte

| Gruppe | Rechte |
| --- | --- |
| `member` | Plugins einreichen, bewerten, melden |
| `moderator` | `plugin.review`, `plugin.hide`, `report.handle`, `user.trust` |
| `admin` | zusätzlich `user.ban`, `group.manage`, `permission.manage` |

Die Rechte selbst stehen in der Datenbank, nicht im Quelltext — eine neue
Gruppe „Prüfer, aber ohne Sperrrecht" ist dann ein Datensatz und kein
Programmierauftrag. Der `rank` verhindert, dass jemand eine Gruppe über der
eigenen vergibt.

## Ablauf einer Einreichung

```
Autor lädt ZIP hoch
        │
        ├─ Serverprüfung: Archiv lesbar? manifest.json gültig? ID frei
        │  bzw. gehört dem Autor? Version noch nicht vergeben? SHA-256
        │  berechnen, Größe, Icon extrahieren
        │
        ├─ Autor ist trusted? ──ja──▶ status = approved, sofort sichtbar
        │                              (audit_log hält fest, dass die
        │                               Prüfung übersprungen wurde)
        └──nein──▶ status = pending, erscheint in der Moderationsliste
                          │
                          ├─ freigegeben ▶ approved, Autor bekommt Nachricht
                          └─ abgelehnt   ▶ rejected mit Begründung
```

Ein automatischer Virenscanner ist bewusst nicht vorgesehen: Bei
Python-Quelltext findet er praktisch nichts und erzeugt ein falsches
Sicherheitsgefühl. Die manuelle Sichtung ist der wirksame Schritt.

## Downloads zählen

Beide Wege führen über denselben Endpunkt, damit keiner an der Zählung
vorbeiläuft:

```
GET /api/download/<plugin>/<version>?via=direct|scheme|app
  → Zeile in download_events, Zähler +1, dann Weiterleitung auf die Datei
```

Der Installieren-Knopf auf der Seite erzeugt
`streamdeck://install?url=https://…/api/download/weather/1.0.0?via=scheme`.
Die App lädt dann von genau dieser Adresse — die Zählung passiert also auch
beim Schema-Weg, ohne dass die App etwas dazu tun müsste.

Gegen Mehrfachzählung: derselbe `visitor_key` auf dieselbe Version innerhalb
von 24 Stunden zählt einmal.

## Öffentliche API für die App

```
GET /api/catalog                      alles, für die Suche in der App
GET /api/catalog/popular?days=30      die Bestenliste
GET /api/catalog/<slug>               ein Plugin mit allen Versionen
```

Antwort je Plugin: Slug, Name, Zusammenfassung, Art, Autor, Version,
Download-Adresse, **SHA-256**, Größe, Downloadzahl, Bewertung.

Der SHA-256 ist nicht schmückendes Beiwerk: Er ist das, was die App prüfen
kann, bevor sie fremden Code auspackt. **Der Installer der App prüft ihn
heute noch nicht — das ist die eine Änderung an der App, die zuerst
kommen sollte.**

## Was noch zu entscheiden ist

1. **Anmeldung.** GitHub allein, oder zusätzlich E-Mail und Passwort?
   GitHub ist für Plugin-Autoren naheliegend und erspart uns Passwörter,
   Zurücksetzen und die zugehörigen Sorgen.
2. **Wo läuft es?** Siehe den Fallstrick oben — SQLite braucht eine echte
   Platte. Gibt es bereits einen Server oder eine Domain?
3. **Bewertung von Autoren.** Eigenständig, oder als Mittel aus den
   Bewertungen ihrer Plugins? Ein Autor ohne Plugin bewerten zu können ist
   schwer zu begründen und eine offene Flanke für Missbrauch.
4. **Negative Bewertungen ohne Kommentar** zulassen? Ein Pflichtkommentar
   ab −1 macht Meckern teurer und die Rückmeldung nützlicher.
5. **Wer ist am Anfang Moderator?** Vermutlich du allein. Das sollte auf
   der Seite stehen, damit „geprüft" nicht mehr verspricht, als dahinter
   steckt.
6. **Namensraum der Plugin-IDs.** `weather` global, oder `heiko/weather`?
   Global ist bequemer, führt aber irgendwann zum Streit um kurze Namen.
