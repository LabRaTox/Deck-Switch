# Aufbau, Entwicklung und Grenzen

*[English version](../en/development.md)* · Zurück zur [Übersicht](../../README.de.md).

## Aufbau

```
backend/
  pyproject.toml         Python-Paket und seine Abhängigkeiten
  deckswitch/            Kern: Geräte, Runtime, Rendering, HTTP/WebSocket
    __main__.py          Einstieg, startet Runtime und lokalen Server gemeinsam
    config.py            Datenmodell (Decks → Profile → Seiten → Belegungen)
    runtime.py           Geteiltes: Config, Plugins, Dienste, Gerätesuche
    deck.py              Ein Deck: Seite, Tastenlogik, Zeichnen, Schoner
    device.py            HID-Anbindung, Wiederverbinden
    events.py            Ereignis-Bus zwischen Runtime, Plugins und GUI
    paths.py             wo Konfiguration, Daten und Mitgeliefertes liegen
    texte.py             Texte für die Oberfläche in der eingestellten Sprache
    locales/             die Sprachdateien (de.json, en.json)
    server.py            REST + WebSocket für die GUI (nur 127.0.0.1)
    netserver.py         Netz-Decks: zweite, winzige Anwendung fürs Netz
    netauth.py           Passwörter, Sitzungen, Bremse gegen Raten
    virtualdeck.py       Deck ohne Hardware, Bilder gehen in den Speicher
    tray.py              Symbol in der Leiste (StatusNotifierItem)
    plugins/base.py      Plugin-API (die einzige Datei für Plugin-Autoren)
    plugins/loader.py    findet, lädt und registriert Plugins
    plugins/installer.py installiert und entfernt Plugins
    plugins/abhaengigkeiten.py  Was Plugins mitbringen: Python- und Systempakete
    services/            Audio (PipeWire), Pegelanzeige, Icons, Rendering,
                         Hintergründe, Touchstrip-Hintergrund,
                         Bildschirmschoner, Autostart, App-Symbol,
                         Eingabe (uinput), Medien (MPRIS), Desktop (KDE),
                         Soundboard, Overlay, globale Kurzbefehle,
                         automatischer Profilwechsel, Programmliste,
                         Sitzungserkennung, Portal, Sicherung, Plugin-Store
    web/netdeck.html     die Seite, die ein Netz-Gast im Browser bekommt
  plugins/               Mitgelieferte Plugins, technisch ganz normale
    audio/ system/ streamdeck/ multi/ sound/ iconset-tabler/
  tests/                 Prüfsuiten (siehe unten)
gui/                     Tauri + Vite/React
packaging/               udev-Regeln, systemd-Units (Checkout und Paket),
                         Menüeintrag, Fensterstarter (deckswitch-gui.sh),
                         URL-Handler
  aur/                   PKGBUILD für das Arch-Paket
  overlay/               das virtuelle Deck als QML-Overlay
scripts/                 Installation, Start, Entfernen, Release-Dateien (Shell),
                         Helfer für Bilder und Plugin-Archive (Python)
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
| `~/.local/share/deckswitch/app/` | die Anwendung selbst nach der Installation mit einem Befehl |
| `~/.local/share/deckswitch/deckswitch.log` | Log des Backends |
| `~/.cache/deckswitch/fensterstart` | wie das Fenster auf diesem System startet ([setup.md](setup.md#wenn-das-fenster-nicht-aufgeht)) |
| `~/.config/systemd/user/deckswitch.service` | Dienst für den Start beim Anmelden, nur im Checkout oder nach der Installation mit einem Befehl (das Paket bringt einen eigenen mit) |

Die beiden Bildablagen sind getrennt, weil ein 800 × 100 breiter Streifen als
Icon nichts taugt und in der Icon-Auswahl nur im Weg stünde.

Die Plugin-Ordner heißen nach einer laufenden Nummer (`0001`, `0002`, …).
Damit bestimmt kein Archiv, wie ein Ordner auf deiner Platte heißt. Welches
Plugin darin liegt, steht in dessen `manifest.json`. Ältere Installationen
haben noch Ordner mit dem Namen der Kennung, beide Formen funktionieren.

Vor jedem Schreiben wandert der bisherige Stand der Konfiguration in den
Backup-Ordner, höchstens einer je Stunde. Jeder Stand bleibt 24 Stunden
liegen. Danach bleibt von jedem Tag nur der letzte, und nach 7 Tagen wird er
gelöscht. Insgesamt bleiben höchstens 30 Stände. Eine Belegung ist
Handarbeit von Stunden und steht in genau einer Datei.

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
echte Konfiguration nicht an. `XDG_DATA_HOME` hält Sicherungen, Uploads und
das Log aus deinem echten Datenordner heraus.

Suiten für Store-Plugins laden das Plugin aus `plugin-sources/` neben
`backend/`. Dieser Ordner gehört nicht zum Repository. In einem frischen
Klon überspringen sich diese Suiten selbst.

`hotkey_test.py` redet mit dem `kglobalaccel` der laufenden Sitzung. Sonst
wäre nichts davon geprüft, sondern nur nachgespielt. Die Suite meldet ihre
Kurzbefehle am Ende wieder ab und überspringt sich selbst, wenn kein Plasma
läuft.

`store_test.py` startet einen echten Plugin-Store-Server und fährt die ganze
Kette durch: hochladen, Katalog, Download mit Prüfsumme. Dafür muss die
Quelle des Stores neben diesem Repository liegen. Fehlt sie, überspringt
sich die Suite.

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
`gui/package.json`, dann `version_test.py` laufen lassen. Für ein Release
ändern sich außerdem `pkgver` in `packaging/aur/PKGBUILD` und die Adresse mit
Versionsnummer im Arch-Abschnitt von [setup.md](setup.md#arch-und-cachyos).
Die `sha256sums` im PKGBUILD lassen sich erst eintragen, wenn der Tarball zum
Tag existiert.

Davon getrennt sind **`CONFIG_VERSION`** in `config.py` (der Schemastand der
Konfiguration, zählt nur bei Migrationen hoch) und die **Versionen der
Plugins** in deren Manifesten. Die gehören dem jeweiligen Plugin und nicht
der Anwendung.

### Zu den Skripten

Die Installationsskripte (`get.sh`, `install.sh`, `fetch-release.sh`,
`build-release-files.sh`) brauchen `bash`. Die übrigen Shell-Skripte
(`dev.sh`, `start-backend.sh`, `start-gui.sh`, `delete.sh`,
`install-service.sh`, `install-desktop-entry.sh`, `install-url-handler.sh`)
sind POSIX-`sh`. Keines davon braucht fish. Ihre Ausgaben sind auf Englisch,
nur `install-desktop-entry.sh` meldet sich auf Deutsch. Ein Teil der
Kommentare ist deutsch.

Daneben liegen Helfer in Python. `make-icon.py`, `make-plugin-icons.py`,
`make-wallpapers.py` und `make-plugin-screenshots.py` erzeugen das
App-Symbol, die Plugin-Icons, Touchstrip-Hintergründe und die Bilder für die
Plugin-Ansicht. `package_plugins.py` packt Plugin-Quellen zu ZIP-Archiven.

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

* **Der automatische Profilwechsel geht nur unter KDE Plasma.** Eine Taste
  mit der Aktion *Profil wechseln* funktioniert auf jedem Desktop. Der
  Vordergrund-Anwendung zu folgen braucht ein KWin-Skript
  (`services/smartprofile.py`), weil Wayland einer gewöhnlichen Anwendung
  nicht verrät, welches Fenster den Fokus hat.
* **Push-to-Talk verträgt sich nicht mit Doppeldruck oder Halten** auf
  derselben Taste. Wer beides belegt, verschiebt das Auslösen zwangsläufig
  auf das Loslassen.
* **Text tippen** schafft nur Zeichen, die auf der aktiven Belegung direkt
  erreichbar sind. Was dort über Tottasten entsteht, wird übersprungen.
* **Globale Kurzbefehle übernehmen deine Kombination nur unter Plasma
  unverändert.** Dort laufen sie über `kglobalaccel`
  (`services/shortcuts.py`). Anderswo laufen sie über
  `org.freedesktop.portal.GlobalShortcuts` (`services/portal.py`), sofern der
  Desktop es anbietet. Der Desktop zeigt dann einen Dialog, nimmt deine
  Kombination als Vorschlag und vergibt womöglich eine andere. Die App zeigt
  die Kombination an, die tatsächlich gilt. Ändert sich die Liste der
  Overlay-Decks, kommt der Dialog erneut.
* **Nach neuen Plugins sehen** lädt nur Plugins, die neu sind, entfernt
  wurden oder eine neue Versionsnummer im Manifest tragen. Nach einer
  Änderung am Code eines Plugins ohne neue Nummer startest du das Backend
  neu.
* **systemd und PipeWire setzt die App voraus.** `install.sh` kennt Arch,
  Debian, Ubuntu, Fedora und openSUSE. Auf einem Fedora mit Image wie Bazzite
  installiert es keine Pakete und nennt stattdessen den `rpm-ostree`-Befehl.
  Entwickelt und am Gerät getestet wird nur auf
  CachyOS, die anderen Distributionen laufen im Container.
* **DDC/CI hängt am Monitor.** Die Helligkeitssteuerung braucht ein Gerät,
  das DDC/CI zulässt, und viele muss man dafür erst im Bildschirmmenü
  freischalten. Außerdem ist `ddcutil` von Natur aus langsam. Deshalb führt
  die App den Wert lokal und schreibt ihn nur entprellt.
* **GPU-Werte nur mit NVIDIA.** Sie kommen aus `nvidia-smi`. Für AMD-Karten
  wäre `/sys/class/drm/…/device/hwmon` der Weg, das ist aber nicht gebaut.

## Aufgebaut auf

| | |
| --- | --- |
| **Backend** | Python 3, [`streamdeck`](https://github.com/abcminiuser/python-elgato-streamdeck), FastAPI mit uvicorn |
| **Rendering** | Pillow für die Tastenbilder, cairosvg für SVG-Icons |
| **GUI** | Tauri + Vite/React, mit dem WebView des Systems |
| **Audio** | PipeWire über `wpctl`/`pactl`, Pegelanzeige über `parec`, Soundboard über `pw-play` |
| **Eingaben** | virtuelle Tastatur über `/dev/uinput` mit `evdev`, Belegung über libxkbcommon (`xkbcommon`) |
| **Desktop** | D-Bus über `dbus-next` für MPRIS, Tray und KWin. Globale Kurzbefehle und Bildschirmfotos über KDE, sonst über `xdg-desktop-portal` |
| **Overlay** | `zwlr_layer_shell_v1` über layer-shell-qt, unter X11 und XWayland über Fenster-Hinweise |
| **Installation** | [`uv`](https://github.com/astral-sh/uv) für die Python-Umgebung und die Pakete von Plugins |
| **Icons** | [Tabler Icons](https://tabler.io/icons) (MIT), eingebunden als ganz normales Iconset-Plugin |

Ohne [`python-elgato-streamdeck`](https://github.com/abcminiuser/python-elgato-streamdeck)
von Dean Camera gäbe es dieses Projekt nicht. Die ganze Geräteanbindung baut
darauf auf.

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
