# DECK//SWITCH

Eigenständige Steuerungssoftware für den Elgato Stream Deck+ — ohne Elgatos
offizielle Software, mit eigenem Plugin-System.

> Der Name wird **DECK//SWITCH** geschrieben, die Schrägstriche in der
> Akzentfarbe. Technisch heißt alles `deckswitch` (Paket, Dienst,
> Konfigurationsordner) — siehe „Zum Namen“ weiter unten.

* **Backend:** Python 3, [`streamdeck`](https://github.com/abcminiuser/python-elgato-streamdeck), FastAPI
* **GUI:** Tauri + Vite/React (System-WebView statt gebündeltem Chromium)
* **Audio:** PipeWire über `wpctl`/`pactl`, Soundboard über `pw-play`
* **Eingaben:** virtuelle Tastatur über `/dev/uinput`, Belegung über libxkbcommon
* **Desktop:** MPRIS und KDEs globale Kurzbefehle über D-Bus
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
aus einer einzigen Geometrie in `backend/deckswitch/services/brand.py`:
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
    nodejs npm noto-fonts wireplumber libpulse libxkbcommon pipewire-audio \
    qt6-declarative layer-shell-qt
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

Dieselbe Regel richtet den Zugriff auf `/dev/uinput` ein — die virtuelle
Tastatur, über die **Tastenkombination** und **Text tippen** laufen. Dafür
muss der Benutzer in der Gruppe `input` sein:

```sh
groups | grep -q input || sudo usermod -aG input "$USER"
```

Die Gruppenmitgliedschaft greift erst nach dem nächsten Anmelden. Ob es
klappt, sagt die Oberfläche: In den Einstellungen einer Hotkey-Aktion steht
sonst im Klartext, was fehlt.

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
  deckswitch/            Kern: Geräte, Runtime, Rendering, HTTP/WebSocket
    config.py            Datenmodell (Decks → Profile → Seiten → Belegungen)
    runtime.py           Geteiltes: Config, Plugins, Dienste, Gerätesuche
    deck.py              Ein Deck: Seite, Tastenlogik, Zeichnen, Schoner
    device.py            HID-Anbindung, Wiederverbinden
    server.py            REST + WebSocket für die GUI
    plugins/base.py      Plugin-API (die einzige Datei, die Plugin-Autoren brauchen)
    services/            Audio (PipeWire), Icons, Rendering, Hintergründe,
                         Autostart, App-Symbol (brand.py), Eingabe (uinput),
                         Medien (MPRIS), Desktop (KDE), Soundboard
    virtualdeck.py       Deck ohne Hardware — Bilder in den Speicher statt auf USB
  plugins/               Mitgelieferte Plugins — technisch normale Plugins
    audio/ obs/ discord/ system/ streamdeck/ multi/ sound/ iconset-tabler/
gui/                     Tauri + Vite/React
packaging/               udev-Regeln, systemd-Unit, URL-Handler
  overlay/               das virtuelle Deck als QML-Overlay
plugin-sources/          Quellen der nachinstallierbaren Plugins
scripts/                 Setup und Start (POSIX sh)
docs/                    Plugin-Entwicklung, Discord-Einrichtung
```

`runtime.py` und `deck.py` teilen sich die Arbeit nach einer einfachen
Regel: Was sich mehrere Geräte teilen (Config, Plugins, Dienste), gehört der
Runtime; was einem einzelnen Gerät gehört (aktuelle Seite, gedrückte Tasten,
Bildschirmschoner, Dial-Stack, laufende Ketten), gehört dem Deck. Zwei
angeschlossene Decks sind damit zwei Sitzungen auf denselben Plugins.

Daten des Nutzers:

| Pfad | Inhalt |
| --- | --- |
| `~/.config/deckswitch/config.json` | Decks, Profile, Belegungen, Einstellungen |
| `~/.config/deckswitch/discord-token.json` | Discord-Zugriffstoken (0600) |
| `~/.local/share/deckswitch/uploads/` | eigene Icons und Kachelhintergründe |
| `~/.local/share/deckswitch/wallpapers/` | Touchstrip-Hintergründe (800 × 100) |
| `~/.local/share/deckswitch/plugins/` | nachinstallierte Plugins |

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

**Tastenlogik** — jede Taste kann drei Aktionen tragen: **Drücken**,
**Doppeldruck** und **Halten**. Im Eigenschaften-Panel schaltet man mit den
drei Reitern dazwischen um; ein Punkt am Reiter zeigt, welcher Zweig belegt
ist.

Der Grundsatz dabei: **Wer nichts Zweites hinterlegt, wartet auf nichts.**
Eine Taste mit nur einer Aktion löst weiterhin im Moment des Drückens aus.
Erst ein belegter Doppeldruck kauft sich die Wartezeit ein, die nötig ist,
um zu erkennen, ob ein zweiter Druck folgt (voreingestellt 280 ms); ein
belegtes Halten verschiebt die Hauptaktion auf das Loslassen. Anders geht es
nicht — ob ein zweiter Druck kommt, weiß man erst hinterher —, und bei
Elgato ist es dieselbe Abwägung.

Praktische Folge: Push-to-Talk-Aktionen, die echtes Drücken *und* Loslassen
brauchen, gehören auf eine Taste ohne Doppeldruck und ohne Halten.

Ein Tastendruck bleibt immer bei der Belegung, auf der er begonnen hat: Wer
einen Ordner öffnet, löst nicht nachträglich die Taste aus, die auf der
neuen Seite an derselben Stelle liegt. Dasselbe gilt für jeden Zweig — jeder
hat seinen eigenen Zwischenspeicher und kommt sich mit den anderen nicht ins
Gehege.

**Multi-Aktionen** — die Aktion *Multi-Aktion* führt mehrere Schritte
nacheinander aus: Programm starten, kurz warten, Tastenkombination
schicken, Text tippen. Die Schritte stehen als Liste in den Eigenschaften.
Gefüllt wird sie wie das Deck selbst: **Aktionen aus der linken Spalte
direkt in die Liste ziehen** — abgelegt wird vor dem Schritt, über dem der
Zeiger steht, und am Ende, wer unter den letzten zielt. Wer lieber klickt,
nimmt *+ Aktion*. Sortiert wird ebenfalls durch Ziehen oder mit Alt + ↑↓. Eine **Pause** ist ein eigener
Schritt und keine Eigenschaft der Aktion davor — so lässt sie sich
verschieben, mehrfach einsetzen und einzeln abschalten. Jeder Schritt hat
einen Haken: abgeschaltete Schritte bleiben stehen, laufen aber nicht mit.
Das ist beim Suchen, welcher Schritt hakt, mehr wert als ein Löschen.

*Wiederholen* lässt die Kette in Schleife laufen, bis erneut gedrückt wird.
Der **Umschalter** (*Multi-Aktion (Umschalter)*) hat zwei Ketten: Der erste
Druck läuft die eine ab, der nächste die andere — mit eigenem Symbol je
Richtung. Ketten in Ketten sind nicht möglich; das wäre eine Schleife, die
niemand mehr anhält.

**Drehrichtungen belegen** — normalerweise bekommt die Aktion eines Dials
das Drehen als Delta und regelt damit stufenlos: Lautstärke, Helligkeit,
Position. Man kann aber auch **je Drehrichtung eine eigene Aktion**
hinterlegen; dann wirkt jede Drehung wie ein kurzer Druck darauf — links
„vorheriger Titel", rechts „nächster Titel". Die Reiter dafür stehen unter
*Dial-Belegung*, gleich neben *Drücken*.

Zwei Dinge dazu:

* **Ausgelöst wird nach je _n_ Rasten** (voreingestellt 2). Ein zügiger Dreh
  erzeugt schnell ein Dutzend Rasten, und „nächster Titel" darf nicht ein
  Dutzend Mal feuern. Gezählt statt nach Zeit gedrosselt: So führt dieselbe
  Handbewegung immer zum selben Ergebnis, egal wie schnell sie war. Ein
  Richtungswechsel setzt den Zähler zurück.
* **Die Richtungen sind unabhängig.** Ist nur eine belegt, geht die andere
  weiterhin an die Grundaktion. Wer gar nichts auf dem Druck haben will,
  legt die Aktion *Leer* aus dem Streamdeck-Plugin auf den Grundplatz.

**Dial-Stack** — auf einem Dial können mehrere Belegungen übereinander
liegen. Am Gerät schaltet **langes Drücken** zum nächsten Eintrag weiter,
kurzes Drücken löst weiterhin die Aktion aus. Jeder Eintrag ist eine
vollwertige Belegung mit eigenem Symbol, eigener Beschriftung und eigenen
Einstellungen; im Editor wählt man oben aus, welcher davon bearbeitet wird.
Ein Dial ohne Stack verhält sich unverändert — dort löst der Druck sofort
aus.

## Aussehen einer Taste

Symbol, Beschriftung und Hintergrund stehen im Eigenschaften-Panel unter
*Aussehen*.

**Beschriftung** — neben Text, Größe, Farbe und Position gibt es die
**Schriftart** (alles, was fontconfig kennt), **fett**, *kursiv*,
unterstrichen und die Ausrichtung links/mittig/rechts. Gerendert wird im
Backend, die Vorschau in der GUI zeigt also exakt das, was auf dem Gerät
steht.

**Hintergrundbild pro Taste** — unter *Hintergrund* gibt es neben Farbe,
Verlauf, Textur und Akzent auch **Bild**: hochladen oder aus den eigenen
Bildern wählen, dazu Einpassung (füllend, ganz zeigen, verzerren) und
Deckkraft. Unter voller Deckkraft wird das Bild auf den Grundton gelegt und
nicht einfach durchsichtig gemacht — auf einer Taste liegt nichts dahinter,
es käme sonst nur dunkler an.

**Animierte Tastenbilder** — GIFs (und animierte WebP/PNG) laufen auf der
Taste ab, als Symbol wie als Hintergrund. Abgespielt wird nur, was sich
wirklich bewegt: Jede Kachel geht einzeln über USB zum Deck, und die
Bandbreite ist das knappste Gut dieses Geräts. Bildrate und Ein/Aus stehen
in den Einstellungen (Voreinstellung 10 Bilder/Sekunde). Die Anzeigedauer
kommt aus der Datei, nicht aus einer festen Rate — ein GIF mit langem
Standbild und kurzer Bewegung läuft dadurch richtig ab.

**Tastenbild gestalten** — der Knopf öffnet eine kleine Werkstatt: Bild
wählen, zoomen, verschieben, drehen, Hintergrund als Farbe oder Verlauf,
Text mit Schriftart, Größe, Farbe, Position und Rand. Das Ergebnis ist ein
fertiges PNG (288 × 288), das entweder als **Tastenbild** (Hintergrund,
Symbol und Beschriftung aus) oder als **Symbol** übernommen wird. Bewusst
eine Datei und kein weiterer Zeichenschritt im Backend: Was hier entsteht,
lässt sich weitergeben und woanders einsetzen.

## Mehrere Decks

Es können mehrere Stream Decks gleichzeitig angeschlossen sein. Jedes Gerät
ist eigenständig: eigenes Profil mit eigenem Seitenbaum, eigene Helligkeit,
eigener Bildschirmschoner, eigene Zeiten für Halten und Doppeldruck.

Zugeordnet wird über die **Seriennummer**. Ein Deck darf also an einem
anderen USB-Anschluss stecken oder in anderer Reihenfolge erkannt werden und
findet trotzdem seine Belegung wieder. Kommt ein bisher unbekanntes Gerät
dazu, legt die App ein leeres Profil dafür an.

In der Kopfzeile stehen die Decks als Umschalter, sobald es mehr als eines
gibt — der Editor bearbeitet immer genau eines. Unter *Einstellungen →
Decks* lassen sich Geräte umbenennen; ein Deck, das nicht mehr da ist, kann
man dort entfernen (sein Profil bleibt erhalten).

Wer nur ein Deck hat, merkt von alldem nichts: Die bestehende Konfiguration
wird beim ersten Start übernommen, das erste angeschlossene Gerät erbt sie
samt Belegung und Einstellungen.

## Virtuelles Deck

Ein Deck muss nicht am USB-Anschluss hängen. Unter *Einstellungen → Decks →
**Virtuelles Deck anlegen*** entsteht ein zweites Deck mit frei wählbarem
Raster (Spalten, Reihen, Dials, Kachelgröße), das als **Overlay** über dem
Bildschirm liegt.

Für alles darüber ist es ein Deck wie jedes andere: eigenes Profil mit
eigenem Seitenbaum, Tastenlogik mit Doppeldruck und Halten, Multi-Aktionen,
Dial-Stacks, Bildschirmschoner. Die Kacheln zeigen exakt dieselben Bilder,
die auch auf die Hardware gingen — sie kommen aus derselben Zeichenkette.

**Es ist bewusst kein Fenster.** Über `zwlr_layer_shell_v1` liegt die Fläche
auf der Overlay-Ebene: kein Eintrag in der Fensterleiste, kein Alt-Tab, kein
Rahmen — und vor allem **kein Fokus**. Das ist der Punkt, an dem so etwas
sonst scheitert: Würde ein Klick auf die Taste den Fokus stehlen, tippte die
Aktion *Text tippen* anschließend ins Deck statt in die Anwendung, aus der
du kamst. Am 2026-08-16 unter KWin gemessen — der Klick kommt an, der Fokus
bleibt beim Vordergrundfenster.

**Herbeirufen** geht auf zwei Wegen:

* über *Einstellungen → Decks → Overlay zeigen*
* über die Aktion **Virtuelles Deck** (Plugin *Streamdeck*) auf einer Taste
  des echten Decks — wahlweise umschaltend, und auf Wunsch **am Mauszeiger**

Die Zeigerposition verrät unter Wayland kein Client-Protokoll; das ist
Absicht. KWin weiß sie aber und darf D-Bus rufen, also fragen wir über ein
winziges KWin-Skript zurück an uns selbst. Ohne KDE erscheint das Overlay
an einer festen Stelle — kein Fehler, nur weniger bequem.

Im Editor stehen Raster und Overlay-Schalter rechts in den
Seiten-Eigenschaften — dort, wo auch das Hintergrundbild des Touchstrips
steht. Die Kachelgröße ist stufenlos; dazu gibt es zwei Schalter:

* **Hintergrund transparent** — ohne Platte darunter schweben nur die
  Kacheln über dem Bildschirm.
* **Leere Kacheln ausblenden** — unbelegte Plätze bleiben unsichtbar und
  nehmen auch keine Klicks an. Ihr Platz bleibt aber frei, damit die
  übrigen Kacheln nicht bei jeder Belegung springen.

Die Kacheln bekommen dabei **runde Ecken mit echter Transparenz** — gerundet
wird beim Rendern und nicht im Overlay, weil Qt nur rechteckig zuschneiden
kann und die Ecken sonst als Quadrate stehen blieben.

Die **Helligkeit** gibt es hier nicht: Ein Overlay hat keine
Hintergrundbeleuchtung, die sich drosseln ließe. Beide denkbaren
Übertragungen sind schlechter als gar keine — als Deckkraft wird die Kachel
durchscheinend und auf hellem Grund unlesbar, als Abdunkeln stimmen die
Farben nicht mehr mit der Vorschau überein. Der Regler ist deshalb bei
virtuellen Decks abgeschaltet, und die Kacheln sehen aus, wie sie gestaltet
wurden.

Beim Überfahren wächst die Kachel leicht, hellt auf und bekommt einen
farbigen Schein — auf einem Bildschirm fehlt die Rückmeldung, die eine
echte Taste beim Einsinken gibt.

Voraussetzungen: `qt6-declarative` (bringt `qml6` mit) und `layer-shell-qt`.
Fehlt eines davon, sagt es die Oberfläche im Klartext, statt den Knopf
wirkungslos anzubieten.

Ein globaler **Tastenkürzel** zum Herbeirufen fehlt noch. Der saubere Weg
dafür wäre das Portal `org.freedesktop.portal.GlobalShortcuts`; KDEs
`kglobalaccel` nimmt die Anmeldung zwar an, liefert das Signal aber nicht
aus (gemessen).

## Eingebaute Plugins

| Plugin | Aktionen |
| --- | --- |
| **Audio** | Lautstärke (Dial mit Balken), Mikrofon stumm (auch Push-to-Talk), Ausgabegerät wechseln, App-Lautstärke |
| **Multi-Aktion** | Multi-Aktion, Multi-Aktion (Umschalter) |
| **Soundboard** | Klang abspielen (mit eigenem Ausgabegerät), alles anhalten |
| **OBS** | Aufnahme (inkl. Pause und Kapitelmarken), Stream, Wiedergabepuffer und Replay speichern, Szenensammlung, Szene, Quelle, Ton stumm, Medienwiedergabe, Studio-Modus, Vorschau live schalten, Filter, Screenshot, Übergang, virtuelle Kamera |
| **Discord** | Mute (auch Push-to-Talk und Push-to-Mute), Deafen, Sprachkanal wechseln, Kanal verlassen, Textkanal öffnen, Mikrofonpegel |
| **System** | Programm starten und beenden, Ordner/Datei/Link öffnen, Shell-Befehl, Tastenkombination (auch als Umschalter und als Push-to-Talk), Text tippen, Multimedia, Fenster & Arbeitsfläche, Bildschirmfoto, Sitzung (sperren, abmelden, ruhen, neu starten, ausschalten), Systemwerte (CPU, RAM, GPU, Temperaturen, Netz), Monitorhelligkeit über DDC/CI |
| **Streamdeck** | Ordner, Home, Zurück, Seitenanzeige, Gehe zu Seite, Blättern, Helligkeit, Leer (Platzhalter), Virtuelles Deck |

Sie sind fachlich Pflicht, technisch aber gewöhnliche Plugins — sie liegen
nur in `backend/plugins/` statt in `~/.local/share/deckswitch/plugins/`
und tauchen in der GUI ganz normal in der Plugin-Liste auf.

**Tastenkombination und Text tippen** gehen über eine virtuelle Tastatur am
Kernel vorbei am Compositor (`/dev/uinput`). Unter Wayland ist das der
einzige Weg: Die Protokolle zum Einschleusen von Tasten bietet KWin nicht
an, und `xdotool` erreicht nur XWayland-Fenster.

Wichtig dabei: Der Kernel kennt keine Zeichen, nur Tastenpositionen. Welches
Zeichen daraus wird, entscheidet die eingestellte Belegung. Deshalb wird die
Zuordnung Zeichen → Taste aus der *tatsächlich aktiven* Belegung berechnet
(libxkbcommon, gelesen aus KDE bzw. `localectl`) — sonst tippte „Strg+Z" auf
einer deutschen Tastatur ein „Strg+Y". Zeichen, die nur über Tottasten
erreichbar sind, werden übersprungen und ins Log geschrieben; lieber ein
fehlendes Zeichen als eine Kombination, die etwas ganz anderes auslöst.

Aufgenommen wird eine Kombination über den Knopf *Aufnehmen* am Feld. Was
der Browser selbst abfängt (Strg+W schließt den Tab), lässt sich von Hand
eintragen.

**Fenster & Arbeitsfläche** löst KDEs eigene globalen Kurzbefehle aus —
maximieren, kacheln, auf Bildschirm 2 schieben, Arbeitsfläche wechseln, und
was sonst noch angemeldet ist (bei einer Standardinstallation rund 170
Einträge allein für KWin). Das ist unter Wayland der saubere Weg: Fenster
von außen zu verschieben gibt es dort nicht, und diese Kurzbefehle muss man
nicht einmal selbst belegt haben.

**Sitzung** kennt sperren, abmelden, Bereitschaft, Ruhezustand, neu starten
und ausschalten — jeweils mit oder ohne Rückfrage von Plasma. Voreingestellt
ist zusätzlich **zweimal drücken**: Der erste Druck macht die Taste nur
scharf und zeigt „Sicher?", erst der zweite führt aus. Ein versehentlich
getroffenes Herunterfahren wäre der teuerste Fehlgriff, den dieses Gerät
anbieten kann.

**Multimedia** steuert den Player, der *gerade spielt* (MPRIS) — also den
Browser, wenn dort ein Video läuft, und den Musikspieler, wenn dort Musik
läuft. Ein bestimmter Player lässt sich fest einstellen. Findet sich gar
keiner, wird die Multimedia-Taste einer Tastatur geschickt; damit verteilt
der Desktop sie selbst.

**Das Soundboard** spielt über `pw-play` ab und darf je Belegung ein eigenes
**Ausgabegerät** wählen. Genau dafür ist ein Soundboard beim Streamen da:
Der Jingle soll in die Sendung, nicht zwingend in die eigenen Kopfhörer.
Wahlweise in Schleife, und ein zweiter Druck startet neu oder hält an.

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

Installiert wird nach `~/.local/share/deckswitch/plugins/`. Eingebaute
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
ein Ordner unter `~/.local/share/deckswitch/plugins/` mit
`manifest.json` und einer Python-Datei, die von `ActionPlugin` erbt.
Iconsets brauchen nur ein Manifest und einen Ordner voller SVGs.

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

Backend-Log: `~/.local/share/deckswitch/deckswitch.log`
(bzw. `journalctl --user -u deckswitch -f` beim systemd-Dienst).

## Zur Sicherheit

Der Server bindet nur an `127.0.0.1`. Das schützt vor dem Netz, aber nicht
vor dem Browser: Jede Webseite, die du offen hast, läuft auf demselben
Rechner. Deshalb drei Riegel:

* **CORS** auf eine feste Liste von Herkünften statt `*`.
* Ein **Origin-Riegel** vor jeder verändernden Anfrage — CORS allein hilft
  dort nicht, weil eine „einfache" Anfrage ohne Vorabprüfung rausgeht und
  der Browser erst *danach* das Lesen der Antwort blockt.
* Eine **Herkunftsprüfung beim WebSocket**. Die ist gesondert nötig:
  WebSockets unterliegen nicht der Same-Origin-Policy, und die
  CORS-Schicht sieht den Handshake nie. Ohne sie könnte jede offene
  Webseite den Ereignisstrom mitlesen.

Ohne `Origin` — Kommandozeile, eigene Skripte — bleibt alles frei. Der
Riegel richtet sich gegen den Browser, nicht gegen dich.

Was er **nicht** leistet: Ein Plugin ist Programmcode mit deinen Rechten,
und eine importierte Konfiguration kann `Shell-Befehl`-Belegungen
mitbringen. Beides fragt vor der Übernahme nach, aber geprüft wird nur die
Herkunft der Anfrage, nicht der Inhalt.

## Bekannte Grenzen

* Profile gibt es je Deck automatisch, aber **kein freies Umschalten**
  mehrerer Profile auf demselben Gerät und keinen automatischen Wechsel je
  Vordergrund-Anwendung („Smart Profiles“).
* **Push-to-Talk verträgt sich nicht mit Doppeldruck oder Halten** auf
  derselben Taste: Wer beides belegt, verschiebt das Auslösen zwangsläufig
  auf das Loslassen. Das ist kein Fehler, sondern die Folge davon, dass ein
  zweiter Druck erst abgewartet werden muss.
* **Text tippen** schafft nur Zeichen, die auf der aktiven Belegung direkt
  erreichbar sind — was dort über Tottasten entsteht, wird übersprungen.
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

Technisch heißt das Projekt `deckswitch`:

| | |
| --- | --- |
| systemd-Dienst | `deckswitch.service` |
| Konfiguration | `~/.config/deckswitch/` |
| Daten | `~/.local/share/deckswitch/` |
| Python-Paket | `backend/deckswitch/` |

Das ist die übliche Trennung — „VLC media player" heißt im Terminal `vlc`.

## Lizenzen

Tabler Icons stehen unter der MIT-Lizenz
(`backend/plugins/iconset-tabler/LICENSE`).
