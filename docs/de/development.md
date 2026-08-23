# Aufbau, Entwicklung und Grenzen

*[English version](../en/development.md)* · Zurück zur [Übersicht](../../README.de.md).

## Aufbau

```
backend/
  deckswitch/            Kern: Geräte, Runtime, Rendering, HTTP/WebSocket
    config.py            Datenmodell (Decks → Profile → Seiten → Belegungen)
    runtime.py           Geteiltes: Config, Plugins, Dienste, Gerätesuche
    deck.py              Ein Deck: Seite, Tastenlogik, Zeichnen, Schoner
    device.py            HID-Anbindung, Wiederverbinden
    server.py            REST + WebSocket für die GUI (nur 127.0.0.1)
    netserver.py         Netz-Decks: zweite, winzige Anwendung fürs Netz
    netauth.py           Passwörter, Sitzungen, Bremse gegen Raten
    virtualdeck.py       Deck ohne Hardware, Bilder gehen in den Speicher
    plugins/base.py      Plugin-API (die einzige Datei für Plugin-Autoren)
    services/            Audio (PipeWire), Icons, Rendering, Hintergründe,
                         Autostart, App-Symbol, Eingabe (uinput),
                         Medien (MPRIS), Desktop (KDE), Soundboard, Overlay,
                         globale Kurzbefehle, Sitzungserkennung, Portal,
                         Plugin-Store
    web/netdeck.html     die Seite, die ein Netz-Gast im Browser bekommt
  plugins/               Mitgelieferte Plugins, technisch ganz normale
    audio/ system/ streamdeck/ multi/ sound/ iconset-tabler/
  tests/                 Prüfsuiten (siehe unten)
gui/                     Tauri + Vite/React
packaging/               udev-Regeln, systemd-Unit, URL-Handler
  overlay/               das virtuelle Deck als QML-Overlay
plugin-sources/          Quellen der nachinstallierbaren Plugins
scripts/                 Setup und Start (POSIX sh)
docs/                    diese Dokumentation
```

`runtime.py` und `deck.py` teilen sich die Arbeit nach einer einfachen Regel.
Was sich mehrere Geräte teilen (Config, Plugins, Dienste), gehört der
Runtime. Was einem einzelnen Gerät gehört (aktuelle Seite, gedrückte Tasten,
Bildschirmschoner, Dial-Stack, laufende Ketten), gehört dem Deck. Zwei
angeschlossene Decks sind damit zwei Sitzungen auf denselben Plugins.

## Daten des Nutzers

| Pfad | Inhalt |
| --- | --- |
| `~/.config/deckswitch/config.json` | Decks, Profile, Belegungen, Einstellungen |
| `~/.config/deckswitch/discord-token.json` | Discord-Zugriffstoken (0600) |
| `~/.config/deckswitch/store-token` | Anmeldung beim Plugin-Store (0600) |
| `~/.local/share/deckswitch/backups/` | frühere Stände der Konfiguration |
| `~/.local/share/deckswitch/uploads/` | eigene Icons und Kachelhintergründe |
| `~/.local/share/deckswitch/wallpapers/` | Touchstrip-Hintergründe (800 × 100) |
| `~/.local/share/deckswitch/plugins/` | nachinstallierte Plugins |

Die beiden Bildablagen sind getrennt, weil ein 800 × 100 breiter Streifen als
Icon nichts taugt und in der Icon-Auswahl nur im Weg stünde.

Die Plugin-Ordner heißen nach einer laufenden Nummer (`0001`, `0002`, …).
Damit bestimmt kein Archiv, wie ein Ordner auf deiner Platte heißt. Welches
Plugin darin liegt, steht in dessen `manifest.json`. Ältere Installationen
haben noch Ordner mit dem Namen der Kennung, beide Formen funktionieren.

Vor jedem Schreiben wandert der bisherige Stand der Konfiguration in den
Backup-Ordner, einer je Stunde, die letzten 30 bleiben liegen. Eine Belegung
ist Handarbeit von Stunden und steht in genau einer Datei.

## Entwicklung

```sh
./scripts/dev.sh     # Backend + Vite mit Hot-Reload (GUI auf :5173)
```

Das Skript startet das Backend mit `--dev`. Nur dann gilt der Vite-Server als
erlaubte Herkunft. Im normalen Betrieb wäre er ein offenes Scheunentor: Wer
auf Port 5173 irgendetwas laufen lässt, dürfte sonst die ganze Schnittstelle
lesen, samt der Zugangsdaten in den Plugin-Einstellungen.

Die HTTP-Schnittstelle ist unter <http://127.0.0.1:8770/api/docs>
dokumentiert.

Backend-Log: `~/.local/share/deckswitch/deckswitch.log`, beim systemd-Dienst
`journalctl --user -u deckswitch -f`.

### Tests

Die Suiten unter `backend/tests/` legen echte Decks, Profile und Seiten an.
Sie brauchen deshalb ein eigenes Konfigurationsverzeichnis, und zwar je Suite
ein frisches. Sonst sieht die nächste die Seiten der vorigen:

```sh
cd backend
for f in tests/*_test.py; do
    d=$(mktemp -d)
    env XDG_CONFIG_HOME=$d XDG_DATA_HOME=$d ../.venv/bin/python "$f"
done
```

Ohne gesetztes `XDG_CONFIG_HOME` brechen sie von selbst ab und rühren die
echte Konfiguration nicht an.

`hotkey_test.py` redet mit dem `kglobalaccel` der laufenden Sitzung. Sonst
wäre nichts davon geprüft, sondern nur nachgespielt. Die Suite meldet ihre
Kurzbefehle am Ende wieder ab und überspringt sich selbst, wenn kein Plasma
läuft.

`store_test.py` startet den Plugin-Store aus dem Nachbarprojekt `PlugInStore`
und fährt die ganze Kette durch: hochladen, Katalog, Download mit Prüfsumme.
Liegt der Store nicht daneben, überspringt sich die Suite.

### GUI

Die Typprüfung läuft **nur** über `npm run build` (`tsc -b`). Ein
`tsc --noEmit` geht in diesem Projekt wirkungslos durch, weil
`tsconfig.json` nur ein Container mit Projektreferenzen ist.

### Version

Die Version der Anwendung steht in **`backend/deckswitch/__init__.py`** und
sonst nirgends von Hand:

* `pyproject.toml` liest sie über `[tool.setuptools.dynamic]` von dort.
* Der Server schickt sie als `version` in `/api/state`, und die Oberfläche
  zeigt die Zahl unten in den Einstellungen. Das ist die Version des
  **Backends**: Bei einem Netz-Deck läuft die Oberfläche womöglich auf einem
  anderen Rechner.
* `gui/src-tauri/tauri.conf.json` hat **kein** `version`-Feld. Tauri nimmt
  dann die Zahl aus `Cargo.toml`.
* Rust und npm können die Python-Datei nicht lesen. Dort steht die Zahl
  deshalb noch einmal, und `backend/tests/version_test.py` erzwingt, dass
  sie übereinstimmt.

Zum Anheben also: `__init__.py`, `gui/src-tauri/Cargo.toml`,
`gui/package.json`, dann `version_test.py` laufen lassen.

Davon getrennt sind **`CONFIG_VERSION`** in `config.py` (der Schemastand der
Konfiguration, zählt nur bei Migrationen hoch) und die **Versionen der
Plugins** in deren Manifesten. Die gehören dem jeweiligen Plugin und nicht
der Anwendung.

### Zu den Skripten

Die Skripte unter `scripts/` sind POSIX-`sh` und **auf Englisch**, Ausgaben
wie Kommentare. Sie laufen damit aus jeder Shell heraus, ohne dass fish
installiert sein muss. Geprüft mit `sh`, `dash`, `bash`, `zsh` und `fish`.

Das venv wird dabei nie „aktiviert". Die Skripte rufen `.venv/bin/python`
direkt auf, und das ist von der Shell unabhängig. Von Hand aktivieren geht
natürlich trotzdem:

| Shell | Befehl |
| --- | --- |
| bash, zsh, sh | `source .venv/bin/activate` |
| fish | `source .venv/bin/activate.fish` |

## Zur Sicherheit

Der Server für die Oberfläche bindet nur an `127.0.0.1`. Das schützt vor dem
Netz, aber nicht vor dem Browser, denn jede Webseite, die du offen hast,
läuft auf demselben Rechner. Deshalb drei Riegel:

* **CORS** auf eine feste Liste von Herkünften und nicht auf `*`.
* Ein **Origin-Riegel** vor jeder verändernden Anfrage. CORS allein hilft
  dort nicht, weil eine „einfache" Anfrage ohne Vorabprüfung rausgeht und der
  Browser erst *danach* das Lesen der Antwort blockt.
* Eine **Herkunftsprüfung beim WebSocket**. Die braucht es gesondert:
  WebSockets unterliegen nicht der Same-Origin-Policy, und die CORS-Schicht
  sieht den Handshake nie.

Ohne `Origin`, also von der Kommandozeile oder aus eigenen Skripten, bleibt
alles frei. Der Riegel richtet sich gegen den Browser und nicht gegen dich.

Netz-Decks laufen mit Absicht in einer **eigenen Anwendung auf eigenem
Port**, die nichts ändern kann. Einzelheiten in
[decks.md](decks.md#netz-deck).

Ein Plugin aus dem **Store** wird beim Herunterladen gegen die Prüfsumme aus
dem Katalog gehalten. Stimmt sie nicht, packt die App gar nicht erst aus.

Was das **nicht** leistet: Ein Plugin ist Programmcode mit deinen Rechten,
und eine importierte Konfiguration kann `Shell-Befehl`-Belegungen
mitbringen. Beides fragt vor der Übernahme nach, aber geprüft wird die
Herkunft der Anfrage und nicht der Inhalt.

## Bekannte Grenzen

* Profile gibt es je Deck automatisch, aber **kein freies Umschalten**
  mehrerer Profile auf demselben Gerät und keinen automatischen Wechsel je
  Vordergrund-Anwendung („Smart Profiles").
* **Push-to-Talk verträgt sich nicht mit Doppeldruck oder Halten** auf
  derselben Taste. Wer beides belegt, verschiebt das Auslösen zwangsläufig
  auf das Loslassen.
* **Text tippen** schafft nur Zeichen, die auf der aktiven Belegung direkt
  erreichbar sind. Was dort über Tottasten entsteht, wird übersprungen.
* **Globale Kurzbefehle gehen nur unter Plasma** (`kglobalaccel`, siehe
  `services/shortcuts.py`). Der portable Weg wäre
  `org.freedesktop.portal.GlobalShortcuts`, der verlangt aber ein
  Elternfenster und einen Bestätigungsdialog je Sitzung.

  Hier stand früher, `kglobalaccel` liefere das Signal nicht aus. Das war ein
  Messfehler: Ohne passende `AddMatch`-Regel schickt der Bus einem Client
  keine Broadcasts. Am 2026-08-19 mit Regel nachgemessen, da kommt das Signal
  an, vom echten Tastendruck über den Compositor bis in den Dienst
  (`tests/hotkey_test.py`).
* Plugin-Hot-Reload lädt Manifeste und Klassen neu, aber Python cached
  bereits importierte Module. Nach Änderungen an einem Plugin ist ein
  Neustart des Backends der verlässlichere Weg.
* **Nur CachyOS und Arch.** Das ist eine bewusste Festlegung und keine Lücke.
  `setup.sh` braucht `pacman`, systemd und PipeWire setzt die App voraus.
* **DDC/CI hängt am Monitor.** Die Helligkeitssteuerung braucht ein Gerät,
  das DDC/CI zulässt, und viele muss man dafür erst im Bildschirmmenü
  freischalten. Außerdem ist `ddcutil` von Natur aus langsam. Deshalb führt
  die App den Wert lokal und schreibt ihn nur entprellt.
* **GPU-Werte nur mit NVIDIA.** Sie kommen aus `nvidia-smi`. Für AMD-Karten
  wäre `/sys/class/drm/…/device/hwmon` der Weg, das ist aber nicht gebaut.

## Zum Namen

**DECK//SWITCH** ist der Anzeigename: Fenstertitel, Kopfzeile, Tray. Die
beiden Schrägstriche stehen in der Akzentfarbe und gehören zur Wortmarke.

Technisch heißt das Projekt `deckswitch`:

| | |
| --- | --- |
| systemd-Dienst | `deckswitch.service` |
| Konfiguration | `~/.config/deckswitch/` |
| Daten | `~/.local/share/deckswitch/` |
| Python-Paket | `backend/deckswitch/` |

Das ist die übliche Trennung. „VLC media player" heißt im Terminal auch nur
`vlc`.
