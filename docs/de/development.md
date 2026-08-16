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
    virtualdeck.py       Deck ohne Hardware — Bilder in den Speicher statt auf USB
    plugins/base.py      Plugin-API (die einzige Datei, die Plugin-Autoren brauchen)
    services/            Audio (PipeWire), Icons, Rendering, Hintergründe,
                         Autostart, App-Symbol, Eingabe (uinput),
                         Medien (MPRIS), Desktop (KDE), Soundboard, Overlay
    web/netdeck.html     die Seite, die ein Netz-Gast im Browser bekommt
  plugins/               Mitgelieferte Plugins — technisch normale Plugins
    audio/ obs/ discord/ system/ streamdeck/ multi/ sound/ iconset-tabler/
  tests/                 Prüfsuiten (siehe unten)
gui/                     Tauri + Vite/React
packaging/               udev-Regeln, systemd-Unit, URL-Handler
  overlay/               das virtuelle Deck als QML-Overlay
plugin-sources/          Quellen der nachinstallierbaren Plugins
scripts/                 Setup und Start (POSIX sh)
docs/                    diese Dokumentation
```

`runtime.py` und `deck.py` teilen sich die Arbeit nach einer einfachen
Regel: Was sich mehrere Geräte teilen (Config, Plugins, Dienste), gehört der
Runtime; was einem einzelnen Gerät gehört (aktuelle Seite, gedrückte Tasten,
Bildschirmschoner, Dial-Stack, laufende Ketten), gehört dem Deck. Zwei
angeschlossene Decks sind damit zwei Sitzungen auf denselben Plugins.

## Daten des Nutzers

| Pfad | Inhalt |
| --- | --- |
| `~/.config/deckswitch/config.json` | Decks, Profile, Belegungen, Einstellungen |
| `~/.config/deckswitch/discord-token.json` | Discord-Zugriffstoken (0600) |
| `~/.local/share/deckswitch/backups/` | frühere Stände der Konfiguration |
| `~/.local/share/deckswitch/uploads/` | eigene Icons und Kachelhintergründe |
| `~/.local/share/deckswitch/wallpapers/` | Touchstrip-Hintergründe (800 × 100) |
| `~/.local/share/deckswitch/plugins/` | nachinstallierte Plugins |

Die beiden Bildablagen sind getrennt, weil ein 800 × 100 breiter Streifen
als Icon nichts taugt und in der Icon-Auswahl nur im Weg stünde.

Vor jedem Schreiben wandert der bisherige Stand der Konfiguration in den
Backup-Ordner (einer je Stunde, die letzten 30 bleiben liegen). Eine
Belegung ist Handarbeit von Stunden und steht in genau einer Datei.

## Entwicklung

```sh
./scripts/dev.sh     # Backend + Vite mit Hot-Reload (GUI auf :5173)
```

Das Skript startet das Backend mit `--dev`. Nur dann gilt der Vite-Server
als erlaubte Herkunft — im normalen Betrieb wäre er ein offenes Scheunentor:
Wer auf Port 5173 irgendetwas laufen lässt, dürfte sonst die ganze
Schnittstelle lesen, samt der Zugangsdaten in den Plugin-Einstellungen.

Die HTTP-Schnittstelle ist unter <http://127.0.0.1:8770/api/docs>
dokumentiert.

Backend-Log: `~/.local/share/deckswitch/deckswitch.log` (bzw.
`journalctl --user -u deckswitch -f` beim systemd-Dienst).

### Tests

Die Suiten unter `backend/tests/` legen echte Decks, Profile und Seiten an.
Sie brauchen deshalb ein eigenes Konfigurationsverzeichnis — je Suite ein
frisches, sonst sieht die nächste die Seiten der vorigen:

```sh
cd backend
for f in tests/*_test.py; do
    d=$(mktemp -d)
    env XDG_CONFIG_HOME=$d XDG_DATA_HOME=$d ../.venv/bin/python "$f"
done
```

Ohne gesetztes `XDG_CONFIG_HOME` brechen sie von selbst ab, statt die echte
Konfiguration zu überschreiben.

### GUI

Die Typprüfung läuft **nur** über `npm run build` (`tsc -b`). Ein `tsc
--noEmit` geht in diesem Projekt wirkungslos durch, weil `tsconfig.json` nur
ein Container mit Projektreferenzen ist.

### Zu den Skripten

Die Skripte unter `scripts/` sind POSIX-`sh` und **auf Englisch** — Ausgaben
wie Kommentare. Sie laufen damit aus jeder Shell heraus, ohne dass fish
installiert sein muss; geprüft mit `sh`, `dash`, `bash`, `zsh` und `fish`.

Das venv wird dabei nie „aktiviert": die Skripte rufen `.venv/bin/python`
direkt auf, was von der Shell unabhängig ist. Von Hand aktivieren geht
natürlich trotzdem:

| Shell | Befehl |
| --- | --- |
| bash, zsh, sh | `source .venv/bin/activate` |
| fish | `source .venv/bin/activate.fish` |

## Zur Sicherheit

Der Server für die Oberfläche bindet nur an `127.0.0.1`. Das schützt vor dem
Netz, aber nicht vor dem Browser: Jede Webseite, die du offen hast, läuft auf
demselben Rechner. Deshalb drei Riegel:

* **CORS** auf eine feste Liste von Herkünften statt `*`.
* Ein **Origin-Riegel** vor jeder verändernden Anfrage — CORS allein hilft
  dort nicht, weil eine „einfache" Anfrage ohne Vorabprüfung rausgeht und
  der Browser erst *danach* das Lesen der Antwort blockt.
* Eine **Herkunftsprüfung beim WebSocket**. Die ist gesondert nötig:
  WebSockets unterliegen nicht der Same-Origin-Policy, und die CORS-Schicht
  sieht den Handshake nie.

Ohne `Origin` — Kommandozeile, eigene Skripte — bleibt alles frei. Der
Riegel richtet sich gegen den Browser, nicht gegen dich.

Netz-Decks laufen bewusst in einer **eigenen Anwendung auf eigenem Port**,
die nichts ändern kann; Einzelheiten in [decks.md](decks.md#netz-deck).

Was das **nicht** leistet: Ein Plugin ist Programmcode mit deinen Rechten,
und eine importierte Konfiguration kann `Shell-Befehl`-Belegungen
mitbringen. Beides fragt vor der Übernahme nach, aber geprüft wird nur die
Herkunft der Anfrage, nicht der Inhalt.

## Bekannte Grenzen

* Profile gibt es je Deck automatisch, aber **kein freies Umschalten**
  mehrerer Profile auf demselben Gerät und keinen automatischen Wechsel je
  Vordergrund-Anwendung („Smart Profiles").
* **Push-to-Talk verträgt sich nicht mit Doppeldruck oder Halten** auf
  derselben Taste: Wer beides belegt, verschiebt das Auslösen zwangsläufig
  auf das Loslassen.
* **Text tippen** schafft nur Zeichen, die auf der aktiven Belegung direkt
  erreichbar sind — was dort über Tottasten entsteht, wird übersprungen.
* **Kein globales Tastenkürzel** zum Herbeirufen des Overlays. Der saubere
  Weg wäre `org.freedesktop.portal.GlobalShortcuts`; KDEs `kglobalaccel`
  nimmt die Anmeldung an, liefert das Signal aber nicht aus (gemessen).
* Plugin-Hot-Reload lädt Manifeste und Klassen neu, aber Python cached
  bereits importierte Module — nach Änderungen an einem Plugin ist ein
  Neustart des Backends der verlässlichere Weg.
* **Nur CachyOS und Arch.** Das ist eine bewusste Festlegung, keine Lücke:
  `setup.sh` setzt `pacman` voraus, systemd und PipeWire werden als gegeben
  angenommen.
* **DDC/CI hängt am Monitor.** Die Helligkeitssteuerung braucht ein Gerät,
  das DDC/CI zulässt; viele muss man dafür erst im Bildschirmmenü
  freischalten. Zudem ist `ddcutil` von Natur aus langsam — deshalb wird der
  Wert lokal geführt und nur entprellt geschrieben.
* **GPU-Werte nur mit NVIDIA.** Sie kommen aus `nvidia-smi`. Für AMD-Karten
  wäre `/sys/class/drm/…/device/hwmon` der Weg, das ist aber nicht gebaut.

## Zum Namen

**DECK//SWITCH** ist der Anzeigename: Fenstertitel, Kopfzeile, Tray. Die
beiden Schrägstriche stehen in der Akzentfarbe und sind Teil der Wortmarke.

Technisch heißt das Projekt `deckswitch`:

| | |
| --- | --- |
| systemd-Dienst | `deckswitch.service` |
| Konfiguration | `~/.config/deckswitch/` |
| Daten | `~/.local/share/deckswitch/` |
| Python-Paket | `backend/deckswitch/` |

Das ist die übliche Trennung — „VLC media player" heißt im Terminal `vlc`.
