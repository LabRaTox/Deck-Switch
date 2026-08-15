# Spezifikation: Eigene Stream Deck+ Software für CachyOS

## Ziel
Eigenständige Steuerungssoftware für den Elgato Stream Deck+ auf CachyOS,
komplett ohne Elgatos offizielle Software. Backend in Python, GUI in
Tauri + Vite/React. Erweiterbar über ein eigenes Plugin-System.
Zielgruppe/Use-Case: Streamer.

## Tech-Stack (festgelegt)
- **Backend:** Python 3, Bibliothek `streamdeck` (python-elgato-streamdeck,
  pip: `pip install streamdeck`) für die Geräte-Kommunikation
- **GUI:** Tauri + Vite/React (nicht Electron/Next.js — CachyOS ist das
  einzige Zielsystem, kein Cross-Plattform-Zwang, der für Electron
  sprechen würde; Tauri nutzt das System-WebView (WebKitGTK unter Linux)
  statt Chromium zu bundeln → deutlich kleinere Binary, weniger
  RAM-Verbrauch im Idle, relevant weil die App dauerhaft im Hintergrund
  läuft. Rust-Anteil bleibt minimal — nur die Fenster-Shell, alle
  Fachlogik bleibt im Python-Backend bzw. im React-Frontend)
- **Backend↔GUI-Kommunikation:** lokaler HTTP/WebSocket-Server im Backend
  (Vorschlag: FastAPI + uvicorn auf `127.0.0.1`, fester Port), GUI spricht
  ihn per `fetch`/WebSocket an
- **Icon-Rendering:** Pillow (PNG-Erzeugung fürs Gerät); SVG→Raster via
  CairoSVG oder vergleichbare Bibliothek
- **Audio-Steuerung:** PipeWire über die CLI-Tools `wpctl` und `pactl`
  (kein direktes PipeWire-Binding — CLI-Tools sind stabiler/einfacher zu
  debuggen und auf CachyOS Standard)
- **Build-Voraussetzung zusätzlich zu Node/Python:** Rust-Toolchain
  (für Tauri) sowie `webkit2gtk` als Systempaket

## Zielsystem-Spezifika (labratox-pc)
- CachyOS, KDE Plasma/Wayland
- Shell ist **fish**, nicht bash — Setup-Skripte/Doku entsprechend anpassen
  (kein `<< EOF` Heredoc, `source .venv/bin/activate.fish` statt `activate`)
- Audio-Backend: PipeWire (nicht PulseAudio, nicht reines ALSA)
- Zugriff auf das USB-HID-Gerät erfordert eine udev-Regel (sonst nur mit
  root nutzbar) — Vendor-ID des Stream Deck+ ist `0fd9` (Elgato)
- Für Tauri zusätzlich per pacman: `webkit2gtk-4.1`, `rustup`/`rust`,
  `base-devel`

## Gerätelayout Stream Deck+
- 8 physische Tasten, jede mit eigenem kleinen LCD
- 4 Dreh-Encoder ("Dials"), jeder drückbar
- Ein durchgehender Touchstrip über den 4 Dials (kein 4 getrenntes Display,
  ein LCD-Streifen — Touch-Events liefern x/y-Koordinaten darauf)
- Bibliothek `streamdeck` stellt bereit: `set_key_callback`,
  `set_dial_callback` (liefert Dreh-Delta bzw. Push als Event),
  `set_touchscreen_callback` (liefert x/y bei Touch), `set_key_image`,
  `set_touchscreen_image(image, x, y, w, h)`, `key_image_format()`,
  `touchscreen_image_format()`, `set_brightness()`

## Plugin-System

Zwei Plugin-Typen:

### 1. Action-Plugins
Steuern Tasten/Dials/Touchstrip-Segmente. Jedes Plugin:
- `manifest.json` (id, name, version, entry-Datei, Python-Klassenname,
  Liste der angebotenen "actions" mit id/name/unterstützten Input-Typen
  key/dial/default_icon)
- Python-Datei mit einer Klasse, die von einer gemeinsamen Basisklasse
  erbt und optional folgende Hooks überschreibt:
  - `on_key_down(action_id, settings)`
  - `on_key_up(action_id, settings)`
  - `on_dial_rotate(action_id, settings, delta)`
  - `on_dial_push(action_id, settings)`
  - `on_touch(action_id, settings, x, y)`
  - `render(action_id, settings, ctx) -> PIL.Image` — zeichnet die
    Tasten-/Dial-Anzeige
  - `on_tick(action_id, settings)` — periodischer Aufruf (Default 1x/Sek.)
    für Status, der sich von außen ändern kann
- Ein Plugin kann **mehrere Actions** anbieten (z. B. das Audio-Plugin:
  Lautstärke-Dial, Mute-Taste, Ausgabegerät-Taste) — Actions sind die
  einzeln belegbaren Einheiten, das Plugin ist die fachliche Klammer
  darum
- Plugins bekommen einen Services-Container injiziert, u.a. einen
  Audio-Service und einen Icon-Service, sowie eine Methode um ein
  sofortiges Neuzeichnen einer bestimmten Taste/eines Dials anzustoßen
  (wichtig für Live-Status, siehe unten)

### 2. Iconset-Plugins
Liefern nur eine Sammlung von Icons (SVG-Ordner + Manifest), die im
Icon-Picker der GUI zusätzlich zur Auswahl stehen.

### Icon-Auflösung (Priorität)
1. Vom User pro Tastenbelegung hochgeladenes eigenes Icon
2. Icon aus dem aktuell aktiven Iconset (Standard: Tabler Icons,
   MIT-lizenziert, SVG — Basis-Iconset ist als Iconset-Plugin umzusetzen,
   nicht hart ins Backend zu kodieren)
3. Generischer Platzhalter

## Eingebaute Plugins (v1, nicht optional)

Fachlich Pflicht, technisch aber genau wie normale (Drittanbieter-)Plugins
umzusetzen — kein Sonderweg im Backend. In der GUI ganz normal als Plugin
gelistet, nur eben von Anfang an mitgeliefert statt nachinstallierbar.

### Audio
Ein Plugin, mehrere Actions:
- **Lautstärke (Dial):** Drehen ändert die Master-Lautstärke
  (`wpctl set-volume`), Push = Mute-Toggle (`wpctl set-mute ... toggle`),
  Live-Balkenanzeige auf dem Touchstrip-Segment über dem Dial
- **Mic-Mute (Taste):** Mikrofon stummschalten/entstummen
- **Ausgabegerät wechseln (Taste, eine pro Gerät):** Gerät wird
  System-Default (`pactl set-default-sink`) **und** alle gerade laufenden
  Audio-Streams werden explizit dorthin verschoben
  (`pactl list sink-inputs` + `pactl move-sink-input <id> <sink>` für
  jeden aktiven Stream) — reines Setzen des Default-Sinks würde nur neue
  Wiedergabe betreffen, laufende Streams (Spotify, Browser, Spiel)
  blieben sonst auf dem alten Gerät. Aktives Gerät muss auf der
  zugehörigen Taste visuell erkennbar sein (z. B. farbiger Rahmen/Badge),
  auch wenn der Wechsel von außen passiert ist
- Muss auch reagieren, wenn sich etwas **von außen** ändert (System-
  Einstellungen, andere App) — dafür im Hintergrund `pactl subscribe`
  laufen lassen und bei relevanten Events ein Neuzeichnen anstoßen

### OBS
Steuerung via `obs-websocket`: Szene wechseln, Stream/Recording
start/stop, Quelle ein-/ausblenden.

### Discord
Eigenständiges Plugin (heißt nur **„Discord“**, nicht „Discord-Mute“) —
Scope bewusst breiter als nur Mute:
- Mute/Unmute
- Channel wechseln
- Weitere Discord-Aktionen sind im selben Plugin naheliegend (z. B.
  Deafen-Toggle) — Anbindung vermutlich über eine lokale Discord-RPC/IPC-
  Verbindung oder ein Bot-Token, technische Detailentscheidung folgt bei
  der Umsetzung

### System
Für grundlegende Desktop-Interaktion:
- Programm starten (Befehl/Pfad in den Settings der Tastenbelegung)
- Ordner im Dateimanager öffnen (Pfad in den Settings)
- Weitere System-Actions (z. B. Datei öffnen, URL öffnen) sind
  naheliegende spätere Ergänzungen im selben Plugin

### Streamdeck (Seiten-/Ordner-Navigation)
Heißt in der GUI bewusst **„Streamdeck“**, da es das Kernkonzept
„Seiten/Ordner“ des Geräts selbst abbildet — ein einzelnes Plugin mit
mehreren Actions:
- Ordner anlegen (eine Taste kann in einen Unter-„Ordner“ mit eigener
  Belegung springen — technisch eine weitere Seite im Belegungsmodell)
- **Home** (zur Wurzel-Seite)
- **Zurück** (eine Ebene hoch)
- **Seitenanzeige** (zeigt die aktuelle Seitennummer als numerischen Wert
  auf der Taste an)
- **Gehe zu Seite** (springt direkt zu einer in den Settings hinterlegten
  Seiten-Nummer/ID)
- **Konsequenz fürs Datenmodell:** Das Belegungs-/Profil-Schema in
  `config.py` muss dafür von Anfang an eine Seiten-/Ordner-Hierarchie
  abbilden (nicht nur ein flaches `keys`/`dials`-Objekt pro Profil,
  sondern verschachtelte Seiten, zwischen denen dieses Plugin navigiert).
  Das ist damit Teil von v1 — die Navigation selbst ist ein Kern-Plugin,
  das Datenmodell dahinter muss also in v1 stehen.

## Eingebaute Plugins — Übersicht
v1 liefert fünf fest eingebaute, aber ganz normal als Plugin dargestellte
Erweiterungen: **Audio** (Lautstärke, Mic-Mute, Ausgabegerät wechseln),
**OBS**, **Discord**, **System**, **Streamdeck** (Seiten-/Ordner-
Navigation).

## Statusanzeige (allgemein)
Jedes Plugin, dessen Zustand sich außerhalb einer Nutzerinteraktion ändern
kann, muss die Möglichkeit haben, ein Neuzeichnen anzustoßen — nicht nur
über den periodischen Tick, sondern sofort bei einem Event. Diese
Fähigkeit gehört ins Plugin-API-Design, nicht nur ins Audio-Plugin.

## Icon-System — konkrete Anforderungen
- Basis-Iconset: **Tabler Icons** (als Iconset-Plugin)
- User muss pro Tastenbelegung ein eigenes Icon hochladen können
  (überschreibt das Plugin-Icon nur für diese eine Belegung)
- Weitere Iconsets sollen als eigene Plugins nachrüstbar sein (gleicher
  Mechanismus wie Tabler, nur anderes SVG-Set)

## Tasten-Aussehen (konfigurierbar)
- **Icon pro State:** eine Action kann mehrere visuelle Zustände haben
  (z. B. Audio-Mute: „aktiv“/„stumm“, Ausgabegerät: „aktiv“/„inaktiv“) —
  für jeden State muss ein eigenes Icon hinterlegbar sein, nicht nur ein
  statisches
- **Icon-Größe:** pro Belegung einstellbar, nicht fest im Plugin verdrahtet
- **Text auf der Taste:** pro Belegung konfigurierbarer Label-Text
  (Inhalt), inkl. Textgröße
- Das bedeutet: das bereits geplante Settings-Schema pro Belegung
  (`icon_by_state`, `icon_size`, `label_text`, `label_size` o. ä.) muss
  generisch im Plugin-API verankert sein, nicht pluginspezifisch
  nachgebaut werden — jedes Action-Plugin liefert seinen State (z. B.
  „muted: true/false“), das generische Rendering von Icon+Text
  übernimmt eine gemeinsame Basis-Funktion, die einzelne Plugins bei
  Bedarf überschreiben können

## Design-Ziel: Elgato-ähnliches Look & Feel
Wichtige Vorgabe: Die App soll sich optisch stark an der offiziellen
Elgato Stream Deck Software orientieren — **sowohl auf dem Gerät selbst**
als auch in der Konfigurations-GUI:
- **Auf dem Gerät:** vertrautes Layout pro Taste (Icon zentriert im
  oberen/mittleren Bereich, Label-Text darunter in ähnlicher Größe/
  Position wie bei der Elgato-Software), damit sich das Deck für jemanden,
  der die offizielle Software kennt, sofort vertraut anfühlt
- **In der GUI:** Grid-Ansicht der Tasten/Dials wie im Elgato-Editor,
  Eigenschaften-Panel für die ausgewählte Taste (Icon, Text, Größe,
  Plugin-Settings), ähnliche Icon-Auswahl-Erfahrung
- Kein 1:1-Nachbau nötig, aber die Grundanmutung (Layout, Proportionen,
  Bedienlogik) soll erkennbar an das Original angelehnt sein


Jedes Dial-Segment auf dem Touchstrip soll einen konfigurierbaren
Hintergrund haben, vor dem Icon/Balken/Text der jeweiligen Action liegt
(nicht nur schwarz wie im Grundgerüst). Vorschlag für den Umfang:
- Hintergrund ist ein eigenes Settings-Feld pro Belegung (Farbe, Verlauf,
  oder Bild), Rendering-Reihenfolge: Hintergrund zeichnen → Icon/Content
  der Action darüberlegen
- Kollege soll direkt ein paar Startvarianten mitbauen, z. B.:
  - einfarbig dunkel (Standard/Fallback)
  - dezenter vertikaler Verlauf (z. B. dunkelgrau → schwarz)
  - dezente Textur/Noise für mehr Tiefe ohne vom Icon abzulenken
  - eine "Akzent"-Variante, die eine pro Plugin/Action definierbare
    Akzentfarbe als schwachen Farbverlauf nutzt (z. B. Audio-Segment
    leicht bläulich, Discord-Segment leicht lila) — rein optisch zur
    Wiedererkennung, nicht zwingend v1-kritisch
- Eigene Bild-Uploads (analog zu den Icon-Uploads) als Hintergrund sind
  eine naheliegende spätere Erweiterung, aber nicht zwingend für den
  ersten Wurf der Hintergründe
- Technisch einfach als weitere kleine Funktion/Modul im Icon-/Render-
  Service, kein eigenes Plugin nötig


- **Mehrsprachigkeit der GUI** — Architektur muss das von Anfang an
  vorsehen (z. B. Text-Strings nicht hart im Code, sondern über ein
  i18n-Framework wie `react-i18next`), damit es nicht später aufwendig
  nachgerüstet werden muss
- **Profile (mehrere unabhängige Belegungs-Sets, z. B. „Streaming“ vs.
  „Arbeit“)** — zu unterscheiden von den Seiten/Ordnern innerhalb eines
  Profils (die sind über das „Streamdeck“-Plugin Teil von v1, siehe oben).
  Das Umschalten zwischen ganzen Profilen ist weiterhin nur mitzuplanen,
  nicht zwingend in v1 fertig — Config-Schema
  (`profiles: { <name>: { ... } }`) unterstützt es bereits strukturell.

## Weitere Vorschläge (zur Diskussion, noch nicht entschieden)
- **Idle-Dimming/Screensaver:** Helligkeit nach X Minuten Inaktivität
  runterfahren bzw. Anzeige abdunkeln — schont die LCDs (Burn-in-Risiko
  bei statischen Icons über lange Zeit) und spart Strom
- **Kurz- vs. Lang-Drücken unterscheiden:** z. B. kurzer Druck = Action A,
  langer Druck (>500ms) = Action B oder Kontextmenü — praktisch für
  Streamdeck-Ordner ("lang drücken = Belegung direkt bearbeiten")
- **Config-Export/Import:** Belegung als JSON exportierbar — nützlich für
  Backup und falls später ein zweites System dazukommt
- **Plugin-Hot-Reload:** Plugins ohne Backend-Neustart neu laden, spart
  Zeit während der Entwicklung eigener Plugins
- **Fehlerzustände sichtbar machen:** GUI zeigt an, wenn das Gerät nicht
  verbunden ist oder ein Plugin beim Laden/Rendern einen Fehler wirft,
  statt nur im Terminal-Log zu verschwinden


- Verpackung als AUR-Paket / Autostart-Service

## Entschieden (vormals offene Punkte)
1. Streamer-Funktionen (OBS, Audio inkl. Mic-Mute, Discord) sind Teil von
   v1, als fest eingebaute, aber als Plugin dargestellte Erweiterungen.
2. Die GUI pusht Belegungsänderungen **direkt** an das laufende Backend
   (kein "speichern → Backend neu starten"-Workflow).
3. Persistenz der Belegungen als JSON unter `~/.config/streamdeck-app/`
   ist bestätigt.
