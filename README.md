# DECK//SWITCH

Eigenständige Steuerungssoftware für den Elgato Stream Deck+ — ohne Elgatos
offizielle Software, mit eigenem Plugin-System.

> Der Name wird **DECK//SWITCH** geschrieben, die Schrägstriche in der
> Akzentfarbe. Technisch heißt alles weiterhin `streamdeck-app`
> (Paket, Dienst, Konfigurationsordner) — siehe „Zum Namen“ weiter unten.

* **Backend:** Python 3, [`streamdeck`](https://github.com/abcminiuser/python-elgato-streamdeck), FastAPI
* **GUI:** Tauri + Vite/React (System-WebView statt gebündeltem Chromium)
* **Audio:** PipeWire über `wpctl`/`pactl`
* **Icons:** Tabler Icons (MIT), eingebunden als ganz normales Iconset-Plugin

---

## Schnellstart

```sh
./scripts/setup.sh          # Pakete, venv, GUI-Build, udev-Regel
./scripts/start-backend.sh  # Backend starten
```

Die Oberfläche liegt dann unter <http://127.0.0.1:8770> — oder als eigenes
Fenster:

```sh
./scripts/start-gui.sh
```

Backend beim Login automatisch starten — am einfachsten über den Schalter
**Beim Anmelden starten** in den Einstellungen. Er legt den systemd-Dienst
an und schaltet ihn ein bzw. aus; die Änderung wirkt beim nächsten Anmelden,
der gerade laufende Dienst wird nicht angefasst.

Dasselbe von der Kommandozeile aus:

```sh
./scripts/install-service.sh            # einrichten
./scripts/install-service.sh --remove   # wieder entfernen
```

### Bildschirmschoner und Hintergrundbild

Beides steht in den **Einstellungen**, nicht unter den Aktionen — es gehört
dem ganzen Gerät und keiner einzelnen Taste.

Der **Bildschirmschoner** legt nach einer einstellbaren Ruhezeit *ein* Bild
über alle acht Tasten und den Touchstrip. Das Motiv wird dafür auf eine
Fläche in Geräteproportionen gerechnet und erst dann zerschnitten, damit es
über die Stege hinweg durchläuft; die Vorschau in den Einstellungen zeigt
genau das, samt der schwarzen Fugen, in denen ein Teil des Bildes
verschwindet. Animierte GIFs laufen ab, jede Eingabe beendet den Schoner.

Das **Hintergrundbild des Touchstrips** gehört dagegen zur *Seite* — jede
Seite kann ein eigenes haben. Eingestellt wird es im Editor: keine Taste
auswählen, dann zeigen die Eigenschaften rechts die Seite statt einer
Belegung.

Es ersetzt den Grund der vier Segmente überall dort, wo für das Segment
kein eigener Hintergrund gewählt wurde. Wer einem Dial bewusst eine Farbe
oder einen Verlauf gibt, behält diese — sonst ließe sich ein Segment nicht
mehr absetzen. Über die Deckkraft tritt das Bild zurück, damit Symbole und
Beschriftungen lesbar bleiben.

Ein paar fertige Motive gibt es auf Zuruf:

```sh
./scripts/make-wallpapers.py     # acht Streifen, direkt in die Auswahl
```

Maße: Eine Taste hat 120 × 120 Pixel, der Touchstrip 800 × 100 (ein Segment
davon 200 × 100 — die Zahl, die auch Elgatos SDK nennt).

Beide nehmen entweder ein hochgeladenes Bild oder ein Plugin. Plugins dafür
tragen `"type": "screensaver"` bzw. `"type": "wallpaper"` im Manifest,
erben von `CanvasPlugin` und bekommen nur eine Leinwand — wie das Ergebnis
auf Tasten und Segmente verteilt wird, ist Sache der App. `plugin-sources/
clock-saver/` ist ein vollständiges Beispiel.

### Symbol in der Leiste

Läuft das Backend, erscheint ein Symbol im Systemabschnitt der Leiste. Es
zeigt den Gerätezustand — farbig wenn verbunden, grau wenn nicht — und
bietet:

* **Linksklick** öffnet die Oberfläche
* **Rechtsklick** öffnet ein Menü (Oberfläche öffnen, Gerät neu verbinden,
  Beenden)
* **Scrollen** über dem Symbol regelt die Helligkeit des Decks

Das Symbol ist dasselbe wie Favicon und Logo in der Kopfzeile. Es entsteht
aus einer einzigen Geometrie in `backend/streamdeck_app/services/brand.py`:
Das Tray zeichnet sie zur Laufzeit in der angefragten Größe, für GUI und
Fenster-Symbole erzeugt `./scripts/make-icon.py` die Dateien. Nach einer
Änderung am Symbol also das Skript aufrufen und die GUI neu bauen.

Technisch ist das ein StatusNotifierItem über D-Bus — der Standard, den KDE
Plasma, Waybar und GNOME (mit Erweiterung) verstehen. Damit braucht das
Backend weder GTK noch Qt. Gibt es keine passende Leiste oder gar keine
Sitzung (Server, TTY), entfällt das Symbol stillschweigend; die
Gerätesteuerung läuft unverändert weiter. Abschalten lässt es sich mit
`--no-tray`.

> **Achtung bei anderer Deck-Software:** Der Zugriff auf das Gerät ist
> exklusiv. Läuft parallel etwa StreamController oder Elgatos eigene
> Software, bekommt nur eine von beiden das Deck — die andere meldet „kein
> Gerät verbunden“. Wer beide installiert hat, sollte nur eine automatisch
> starten lassen.

### Zu den Skripten

Die Skripte unter `scripts/` sind POSIX-`sh` und **auf Englisch** — Ausgaben
wie Kommentare. Sie laufen damit aus jeder Shell heraus, ohne dass fish
installiert sein muss; geprüft mit `sh`, `dash`, `bash`, `zsh` und `fish`.

Zielplattform sind **CachyOS und Arch Linux**. `setup.sh` setzt deshalb
`pacman` voraus und bricht auf anderen Distributionen mit einer Liste der
nötigen Pakete ab, statt eine Erkennung vorzutäuschen, die niemand testet.

Das venv wird dabei nie „aktiviert“: die Skripte rufen `.venv/bin/python`
direkt auf, was von der Shell unabhängig ist. Von Hand aktivieren geht
natürlich trotzdem:

| Shell | Befehl |
| --- | --- |
| bash, zsh, sh | `source .venv/bin/activate` |
| fish | `source .venv/bin/activate.fish` |

## Voraussetzungen

`setup.sh` prüft die Pakete selbst und bietet an, fehlende zu installieren.
Von Hand:

```sh
sudo pacman -S --needed python webkit2gtk-4.1 base-devel rust hidapi libusb \
    nodejs npm noto-fonts wireplumber libpulse
```

Zielplattform sind **CachyOS und Arch Linux** — anderes wird weder getestet
noch unterstützt.

Ohne udev-Regel gehört der HID-Knoten root, das Gerät wäre also nur mit
root ansprechbar. `setup.sh` bietet die Installation an; von Hand:

```sh
sudo install -m 644 packaging/70-streamdeck.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules
sudo udevadm trigger --subsystem-match=usb --subsystem-match=hidraw
```

Danach den Stream Deck einmal ab- und wieder anstecken.

### Plugin-Symbole

Ein Plugin darf ein eigenes Bild mitbringen — `"icon": "icon.png"` im
Manifest, 256 × 256 Pixel. Es erscheint **nur in der Plugin-Übersicht**,
nicht in der Aktionsbibliothek: Dort stünde neben jeder Aktion desselben
Plugins dasselbe Bild, was beim Suchen nicht hilft. Ohne Symbol zeigt die
Übersicht ein farbiges Feld mit dem Anfangsbuchstaben.

Die Symbole der mitgelieferten Plugins entstehen aus Akzentfarbe und
Aktions-Symbol:

```sh
./scripts/make-plugin-icons.py          # alle
./scripts/make-plugin-icons.py audio    # nur eines
```

### Welches Stream Deck?

Die Oberfläche richtet sich nach dem angeschlossenen Gerät: Tastenzahl,
Rasteranordnung und das Vorhandensein von Dials kommen aus der
Gerätemeldung, nicht aus einer festen Annahme. Ein Stream Deck XL zeigt
8 × 4 Tasten, ein Mini 3 × 2, und ohne Dials entfällt der Touchstrip-Bereich
ganz. Entwickelt und am Gerät geprüft ist der **Stream Deck +**; die übrigen
Modelle sind gegen vorgetäuschte Gerätemeldungen getestet, aber nie an
echter Hardware.

## Aufbau

```
backend/
  streamdeck_app/        Kern: Gerät, Runtime, Rendering, HTTP/WebSocket
    config.py            Datenmodell (Profile → Seiten/Ordner → Belegungen)
    runtime.py           Verdrahtung Gerät ↔ Belegung ↔ Plugins
    device.py            HID-Anbindung, Wiederverbinden
    server.py            REST + WebSocket für die GUI
    plugins/base.py      Plugin-API (die einzige Datei, die Plugin-Autoren brauchen)
    services/            Audio (PipeWire), Icons, Rendering, Hintergründe,
                         Autostart, App-Symbol (brand.py)
  plugins/               Mitgelieferte Plugins — technisch normale Plugins
    audio/ obs/ discord/ system/ streamdeck/ iconset-tabler/
gui/                     Tauri + Vite/React
packaging/               udev-Regel, systemd-Unit, URL-Handler
plugin-sources/          Quellen der nachinstallierbaren Plugins
scripts/                 Setup und Start (POSIX sh)
docs/                    Plugin-Entwicklung, Discord-Einrichtung
```

Daten des Nutzers:

| Pfad | Inhalt |
| --- | --- |
| `~/.config/streamdeck-app/config.json` | Belegungen, Profile, Einstellungen |
| `~/.config/streamdeck-app/discord-token.json` | Discord-Zugriffstoken (0600) |
| `~/.local/share/streamdeck-app/uploads/` | eigene Icons und Kachelhintergründe |
| `~/.local/share/streamdeck-app/wallpapers/` | Touchstrip-Hintergründe (800 × 100) |
| `~/.local/share/streamdeck-app/plugins/` | nachinstallierte Plugins |

Die beiden Bildablagen sind getrennt, weil ein 800 × 100 breiter Streifen
als Icon nichts taugt und in der Icon-Auswahl nur im Weg stünde. Wo eine
Datei liegt, entscheidet sich beim Hochladen — gefunden wird sie danach in
beiden, eine einmal eingestellte Quelle bleibt also gültig.

## Bedienung

**Editor** — links die Aktionen aller Plugins, Mitte das Deck in
Gerätegeometrie (8 Tasten, 4 Dials mit Touchstrip), rechts die
Eigenschaften der ausgewählten Position.

* Aktion aus der linken Spalte auf eine Taste oder einen Dial ziehen.
* Belegungen lassen sich untereinander per Drag&Drop tauschen.
* ▶ auf einer Kachel löst die Aktion aus, ohne das Gerät anzufassen.
* Die Kachelvorschau wird vom Backend gerendert — sie zeigt exakt das,
  was auf dem Gerät steht.

**Seiten und Ordner** — beides ist dasselbe: eine Seite mit oder ohne
Elternteil. Der Seitenbaum links neben dem Deck zeigt die Zugehörigkeit:
Unterseiten stehen eingerahmt unter ihrer Seite, der Zweig der geöffneten
Seite ist farbig markiert, und ↳ legt direkt eine Unterseite an. Umbenennen
per Doppelklick oder F2, Zweige mit ▾ zuklappen. Zum Springen gibt es die
Aktionen des Plugins „Streamdeck“ (Ordner, Home, Zurück, Seitenanzeige,
Gehe zu Seite, Nächste/Vorherige Seite).

**Reihenfolge der Seiten** — im Baum ziehen: über oder unter eine Zeile
gezogen sortiert um, mitten auf eine Zeile gezogen macht zur Unterseite.
Ohne Maus geht dasselbe mit Alt + ↑↓ (verschieben) und Alt + ←→ (aus- und
einrücken). Die Reihenfolge gilt auch am Gerät — Wischen und
Nächste/Vorherige Seite folgen ihr.

**Wischen auf dem Touchstrip** blättert zwischen den Seiten derselben
Ebene: nach links vorwärts, nach rechts zurück. Tippen bleibt dabei bei
der Aktion, die auf dem Segment liegt — nur Wischgesten gehen ans Gerät.
Schwelle, Umbruch und Abschalten stehen in den Einstellungen unter
*Touchstrip*.

**Lang drücken** — jede Taste kann eine zweite Aktion bekommen, die ab
500 ms (einstellbar) greift. Ohne Zweitbelegung löst eine Taste weiterhin
sofort beim Drücken aus, ohne künstliche Verzögerung.

Ein Tastendruck bleibt dabei immer bei der Belegung, auf der er begonnen
hat: Wer einen Ordner öffnet, löst nicht nachträglich die Taste aus, die
auf der neuen Seite an derselben Stelle liegt.

## Eingebaute Plugins

| Plugin | Aktionen |
| --- | --- |
| **Audio** | Lautstärke (Dial mit Balken), Mikrofon stumm (auch Push-to-Talk), Ausgabegerät wechseln, App-Lautstärke |
| **OBS** | Aufnahme (inkl. Pause und Kapitelmarken), Stream, Wiedergabepuffer und Replay speichern, Szenensammlung, Szene, Quelle, Ton stumm, Medienwiedergabe, Studio-Modus, Vorschau live schalten, Filter, Screenshot, Übergang, virtuelle Kamera |
| **Discord** | Mute (auch Push-to-Talk und Push-to-Mute), Deafen, Sprachkanal wechseln, Kanal verlassen, Textkanal öffnen, Mikrofonpegel |
| **System** | Programm starten, Ordner/Datei/Link öffnen, Shell-Befehl, Systemwerte (CPU, RAM, GPU, Temperaturen, Netz), Monitorhelligkeit über DDC/CI |
| **Streamdeck** | Ordner, Home, Zurück, Seitenanzeige, Gehe zu Seite, Blättern, Helligkeit |

Sie sind fachlich Pflicht, technisch aber gewöhnliche Plugins — sie liegen
nur in `backend/plugins/` statt in `~/.local/share/streamdeck-app/plugins/`
und tauchen in der GUI ganz normal in der Plugin-Liste auf.

**Discord-Kanaltasten** zeigen von sich aus das Logo des Servers, zu dem
der Kanal gehört — abschaltbar je Taste, ein selbst gewähltes Icon hat
immer Vorrang. Die Logos liegen unter
`~/.local/share/deckswitch/cache/discord-guilds/`.

**Ausgabegerät wechseln** setzt nicht nur den Standard-Sink, sondern zieht
auch alle laufenden Streams mit — sonst bliebe die schon laufende Musik auf
dem alten Gerät.

**Zustände von außen** — ändert jemand die Lautstärke in den
Systemeinstellungen, wechselt OBS die Szene oder mutet Discord sich selbst,
zeichnet die betroffene Taste sofort neu. Dafür laufen `pactl subscribe`
sowie die Event-Kanäle von obs-websocket und Discord-RPC mit; der
Sekundentakt ist nur das Sicherheitsnetz.

**OBS** braucht obs-websocket (in OBS 28+ eingebaut, unter *Werkzeuge →
WebSocket-Servereinstellungen* aktivieren). Host, Port, Passwort und der
Screenshot-Ordner stehen in der GUI unter *Plugins → OBS →
Plugin-Einstellungen*.

Der Funktionsumfang entspricht dem offiziellen Elgato-OBS-Plugin. Ein paar
Besonderheiten:

* **Quelle** und **Filter** haben abhängige Auswahllisten — erst die Szene
  bzw. Quelle wählen, dann füllt sich die zweite Liste passend.
* **Ton stumm** kann statt Umschalten auch als Push-to-Talk oder
  Push-to-Mute arbeiten.
* **Auf einem Dial** blättern *Szene*, *Übergang* und *Szenensammlung* per
  Drehen durch die jeweilige Liste.
* **Stream** und **Aufnahme** lassen sich gegen versehentliches Stoppen
  absichern („zweimal drücken“) — beim Stream ist das voreingestellt.
* **Kapitelmarken** verlangen OBS 30.2 oder neuer und Hybrid-MP4 als
  Aufnahmeformat; andernfalls erscheint ein entsprechender Hinweis.

**Discord** braucht eine einmalige Einrichtung, siehe
[docs/discord-setup.md](docs/discord-setup.md).

### Nachinstallierbare Plugins

Diese beiden gehören **nicht** zum Lieferumfang, ihre Quellen liegen aber in
[plugin-sources/](plugin-sources/) — siehe „Plugins nachinstallieren“.

| Plugin | Aktionen |
| --- | --- |
| **Spotify** | Wiedergabe, nächster/vorheriger Titel, Playlist starten, Shuffle, Wiederholung, Lautstärke, Multimedia-Dial |
| **Wetter** | Aktuelles Wetter, Mehrtagesvorhersage, Luftqualität |

**Spotify** braucht gar keine Einrichtung: Die Steuerung läuft über MPRIS,
den D-Bus-Standard für Medienspieler unter Linux — kein Konto, keine
Zugangsdaten, kein OAuth. Titel, Künstler, Wiedergabe-, Shuffle- und
Wiederholungszustand aktualisieren sich in Echtzeit, das Albumbild kann als
Hintergrund des Dial-Segments dienen.

Zwei Punkte dazu:

* Gesteuert wird der **lokal laufende Player**. Die offizielle
  Elgato-Version greift über Spotifys Web-API auch auf Handy oder
  Lautsprecher zu — das kann MPRIS nicht.
* Das Plugin funktioniert mit **jedem MPRIS-fähigen Player**, nicht nur
  Spotify (einstellbar unter *Plugins → Spotify*). Die Lautstärke läuft
  standardmäßig über den PipeWire-Stream des Players, weil Spotify seine
  eigene Lautstärke über MPRIS nicht verlässlich anbietet.

**Playlist starten** braucht den Link zur Playlist: in Spotify Rechtsklick
→ *Teilen* → *Link kopieren*, dann in die Taste einfügen. Album-, Titel- und
Künstler-Links gehen genauso. Eine Auswahlliste der eigenen Playlists gibt
es bewusst nicht: MPRIS kennt keine — der Spotify-Client bietet weder das
`Playlists`-Interface noch eine Titelliste an, das ginge nur über Spotifys
Web-API mit eigener App-Registrierung und OAuth.

**Wetter** kommt von [Open-Meteo](https://open-meteo.com) — ohne Konto, ohne
API-Schlüssel. Unter *Plugins → Wetter* einen Ort suchen und aus der
Trefferliste wählen (Stadt oder Postleitzahl); die Daten werden alle zehn
Minuten aufgefrischt.

* **Wetter** zeigt Temperatur und Wetterlage. Kurzer Druck blendet Höchst-
  und Tiefstwert ein. Am Dial wird gedreht, um in Dreistundenschritten durch
  den Tag zu blättern, und gedrückt, um zwischen Stundenverlauf,
  Temperaturdiagramm und Detailansicht (gefühlt, Regenrisiko, Wind, UV) zu
  wechseln.
* **Vorhersage** zeigt einen bestimmten Tag; am Dial stehen fünf Tage
  nebeneinander, durch die man dreht.
* **Luftqualität** zeigt den AQI mit Einstufung, wahlweise europäische oder
  US-Skala, und färbt sich nach Schweregrad.

Jede Belegung kann über *Abweichender Ort* eine eigene Stadt bekommen — so
liegen Heimatort und Urlaubsziel nebeneinander auf dem Deck.

## Plugins nachinstallieren

Unter *Plugins → Installieren* gibt es drei Wege:

1. **Adresse eintragen** — ein ZIP von einer http(s)-Adresse
2. **Datei ablegen** — ZIP per Drag & Drop oder Dateiauswahl
3. **`streamdeck://`-Link** im Browser (siehe unten)

Installiert wird nach `~/.local/share/streamdeck-app/plugins/`. Eingebaute
Plugins lassen sich weder überschreiben noch entfernen; nachinstallierte
haben in der Liste einen „Entfernen“-Knopf.

**Wetter und Spotify** sind nicht Teil der Auslieferung. Ihre Quellen liegen
in [plugin-sources/](plugin-sources/); verteilbare Archive baut

```sh
./scripts/package_plugins.py          # → dist/plugins/*.zip
```

### streamdeck://-Links

Damit lassen sich Plugins direkt aus dem Browser installieren:

```sh
./scripts/install-url-handler.sh     # einmalig registrieren
```

Danach führt ein Link der Form

```
streamdeck://install?url=https://example.com/mein-plugin.zip
```

zu einer **Anfrage**, die in der Oberfläche bestätigt werden muss — mit
Angabe der Herkunft. Ein Klick auf einen Link installiert also nichts von
selbst. Das ist Absicht: Ein Plugin ist Programmcode, der mit deinen Rechten
läuft, und eine beliebige Webseite darf das nicht ohne Rückfrage auslösen.
Unbestätigte Anfragen verfallen nach zehn Minuten.

Läuft das Backend nicht, meldet der Handler das per Desktop-Benachrichtigung,
statt still zu scheitern.

## Plugins anordnen

Unter *Plugins* lassen sich die Karten am Griff (⠿) in die gewünschte
Reihenfolge ziehen. Sie gilt auch für die Aktionsliste im Editor und wird in
der Config gespeichert. Neu installierte Plugins landen hinten, damit sich
eine eingespielte Anordnung nicht von selbst verschiebt.

## Eigene Plugins

Siehe [docs/plugin-entwicklung.md](docs/plugin-entwicklung.md). Kurz:
ein Ordner unter `~/.local/share/streamdeck-app/plugins/` mit
`manifest.json` und einer Python-Datei, die von `ActionPlugin` erbt.
Iconsets brauchen nur ein Manifest und einen Ordner voller SVGs.

## Entwicklung

```sh
./scripts/dev.sh     # Backend + Vite mit Hot-Reload (GUI auf :5173)
```

Die HTTP-Schnittstelle ist unter <http://127.0.0.1:8770/api/docs>
dokumentiert.

Backend-Log: `~/.local/share/streamdeck-app/streamdeck-app.log`
(bzw. `journalctl --user -u streamdeck-app -f` beim systemd-Dienst).

## Bekannte Grenzen

* Profile (mehrere unabhängige Belegungs-Sets) sind im Datenmodell und in
  der Config vollständig angelegt, haben aber noch keine Umschaltfläche in
  der GUI — es gibt vorerst nur das Profil „Standard“.
* Hintergrund-**Bilder** pro Kachel kann das Backend rendern; im
  Hintergrund-Editor stehen bislang nur die Farb-, Verlaufs-, Textur- und
  Akzent-Varianten zur Auswahl.
* Plugin-Hot-Reload lädt Manifeste und Klassen neu, aber Python cached
  bereits importierte Module — nach Änderungen an einem Plugin ist ein
  Neustart des Backends der verlässlichere Weg.
* **Nur CachyOS und Arch.** Das ist eine bewusste Festlegung, keine Lücke:
  `setup.sh` setzt `pacman` voraus, systemd und PipeWire werden als gegeben
  angenommen. Auf anderen Distributionen mag vieles laufen — geprüft wird
  es nicht.
* **DDC/CI hängt am Monitor.** Die Helligkeitssteuerung braucht ein Gerät,
  das DDC/CI zulässt; viele muss man dafür erst im Bildschirmmenü
  freischalten, und über manche DisplayPort-Hubs geht es gar nicht. Zudem
  ist `ddcutil` von Natur aus langsam (hier knapp zwei Sekunden pro
  Zugriff) — deshalb wird der Wert lokal geführt und nur entprellt
  geschrieben.
* **GPU-Werte nur mit NVIDIA.** Sie kommen aus `nvidia-smi`. Für AMD-Karten
  wäre `/sys/class/drm/…/device/hwmon` der Weg, das ist aber nicht gebaut.

## Zum Namen

**DECK//SWITCH** ist der Anzeigename: Fenstertitel, Kopfzeile, Tray, später
Webseite und Marktplatz. Die beiden Schrägstriche stehen in der
Akzentfarbe und sind Teil der Wortmarke.

Technisch heißt das Projekt weiterhin `streamdeck-app`:

| | |
| --- | --- |
| systemd-Dienst | `streamdeck-app.service` |
| Konfiguration | `~/.config/streamdeck-app/` |
| Daten | `~/.local/share/streamdeck-app/` |
| Python-Paket | `backend/streamdeck_app/` |

Das ist Absicht und die übliche Trennung — „VLC media player" heißt im
Terminal `vlc`. Ein Umbenennen auf `deckswitch` wäre möglich, würde aber
die Konfiguration mitnehmen müssen: Ohne Umzug der bestehenden Ordner
stünde die App nach dem Wechsel ohne Belegungen da.

## Lizenzen

Tabler Icons stehen unter der MIT-Lizenz
(`backend/plugins/iconset-tabler/LICENSE`).
