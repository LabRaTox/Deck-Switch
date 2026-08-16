# Plugins

Zurück zur [Übersicht](../README.de.md).

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
nur in `backend/plugins/` statt in `~/.local/share/deckswitch/plugins/` und
tauchen in der GUI ganz normal in der Plugin-Liste auf.

### Tastenkombination und Text tippen

Beides geht über eine virtuelle Tastatur am Compositor vorbei direkt an den
Kernel (`/dev/uinput`). Unter Wayland ist das der einzige Weg: Die
Protokolle zum Einschleusen von Tasten bietet KWin nicht an, und `xdotool`
erreicht nur XWayland-Fenster.

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

### Fenster & Arbeitsfläche

Löst KDEs eigene globale Kurzbefehle aus — maximieren, kacheln, auf
Bildschirm 2 schieben, Arbeitsfläche wechseln, und was sonst noch angemeldet
ist (bei einer Standardinstallation rund 170 Einträge allein für KWin). Das
ist unter Wayland der saubere Weg: Fenster von außen zu verschieben gibt es
dort nicht, und diese Kurzbefehle muss man nicht einmal selbst belegt haben.

### Sitzung

Kennt sperren, abmelden, Bereitschaft, Ruhezustand, neu starten und
ausschalten — jeweils mit oder ohne Rückfrage von Plasma. Voreingestellt ist
zusätzlich **zweimal drücken**: Der erste Druck macht die Taste nur scharf
und zeigt „Sicher?", erst der zweite führt aus. Ein versehentlich
getroffenes Herunterfahren wäre der teuerste Fehlgriff, den dieses Gerät
anbieten kann.

### Multimedia

Steuert den Player, der *gerade spielt* (MPRIS) — also den Browser, wenn
dort ein Video läuft, und den Musikspieler, wenn dort Musik läuft. Ein
bestimmter Player lässt sich fest einstellen. Findet sich gar keiner, wird
die Multimedia-Taste einer Tastatur geschickt; damit verteilt der Desktop
sie selbst.

### Soundboard

Spielt über `pw-play` ab und darf je Belegung ein eigenes **Ausgabegerät**
wählen. Genau dafür ist ein Soundboard beim Streamen da: Der Jingle soll in
die Sendung, nicht zwingend in die eigenen Kopfhörer. Wahlweise in Schleife,
und ein zweiter Druck startet neu oder hält an.

### Audio

**Ausgabegerät wechseln** setzt nicht nur den Standard-Sink, sondern zieht
auch alle laufenden Streams mit — sonst bliebe die schon laufende Musik auf
dem alten Gerät.

**Zustände von außen**: Ändert jemand die Lautstärke in den
Systemeinstellungen, wechselt OBS die Szene oder mutet Discord sich selbst,
zeichnet die betroffene Taste sofort neu. Dafür laufen `pactl subscribe`
sowie die Event-Kanäle von obs-websocket und Discord-RPC mit; der
Sekundentakt ist nur das Sicherheitsnetz.

### OBS

Braucht obs-websocket (in OBS 28+ eingebaut, unter *Werkzeuge →
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
  absichern („zweimal drücken") — beim Stream ist das voreingestellt.
* **Kapitelmarken** verlangen OBS 30.2 oder neuer und Hybrid-MP4 als
  Aufnahmeformat; andernfalls erscheint ein entsprechender Hinweis.

### Discord

Braucht eine einmalige Einrichtung, siehe
[discord-setup.md](discord-setup.md).

**Kanaltasten** zeigen von sich aus das Logo des Servers, zu dem der Kanal
gehört — abschaltbar je Taste, ein selbst gewähltes Icon hat immer Vorrang.
Die Logos liegen unter `~/.local/share/deckswitch/cache/discord-guilds/`.

## Nachinstallierbare Plugins

Diese beiden gehören **nicht** zum Lieferumfang, ihre Quellen liegen aber in
[plugin-sources/](../plugin-sources/).

| Plugin | Aktionen |
| --- | --- |
| **Spotify** | Wiedergabe, nächster/vorheriger Titel, Playlist starten, Shuffle, Wiederholung, Lautstärke, Multimedia-Dial |
| **Wetter** | Aktuelles Wetter, Mehrtagesvorhersage, Luftqualität |

**Spotify** braucht gar keine Einrichtung: Die Steuerung läuft über MPRIS,
den D-Bus-Standard für Medienspieler unter Linux — kein Konto, keine
Zugangsdaten, kein OAuth. Titel, Künstler, Wiedergabe-, Shuffle- und
Wiederholungszustand aktualisieren sich in Echtzeit, das Albumbild kann als
Hintergrund des Dial-Segments dienen.

* Gesteuert wird der **lokal laufende Player**. Die offizielle
  Elgato-Version greift über Spotifys Web-API auch auf Handy oder
  Lautsprecher zu — das kann MPRIS nicht.
* Das Plugin funktioniert mit **jedem MPRIS-fähigen Player**, nicht nur
  Spotify (einstellbar unter *Plugins → Spotify*).

**Playlist starten** braucht den Link zur Playlist: in Spotify Rechtsklick →
*Teilen* → *Link kopieren*, dann in die Taste einfügen. Eine Auswahlliste
der eigenen Playlists gibt es bewusst nicht: MPRIS kennt keine.

**Wetter** kommt von [Open-Meteo](https://open-meteo.com) — ohne Konto, ohne
API-Schlüssel. Unter *Plugins → Wetter* einen Ort suchen und aus der
Trefferliste wählen; die Daten werden alle zehn Minuten aufgefrischt.

* **Wetter** zeigt Temperatur und Wetterlage. Kurzer Druck blendet Höchst-
  und Tiefstwert ein. Am Dial wird gedreht, um in Dreistundenschritten durch
  den Tag zu blättern, und gedrückt, um zwischen Stundenverlauf,
  Temperaturdiagramm und Detailansicht zu wechseln.
* **Vorhersage** zeigt einen bestimmten Tag; am Dial stehen fünf Tage
  nebeneinander.
* **Luftqualität** zeigt den AQI mit Einstufung, wahlweise europäische oder
  US-Skala, und färbt sich nach Schweregrad.

Jede Belegung kann über *Abweichender Ort* eine eigene Stadt bekommen — so
liegen Heimatort und Urlaubsziel nebeneinander auf dem Deck.

## Nachinstallieren

Unter *Plugins → Installieren* gibt es drei Wege:

1. **Adresse eintragen** — ein ZIP von einer http(s)-Adresse
2. **Datei ablegen** — ZIP per Drag & Drop oder Dateiauswahl
3. **`streamdeck://`-Link** im Browser (siehe unten)

Installiert wird nach `~/.local/share/deckswitch/plugins/`. Eingebaute
Plugins lassen sich weder überschreiben noch entfernen; nachinstallierte
haben in der Liste einen „Entfernen"-Knopf.

Verteilbare Archive der mitgelieferten Quellen baut:

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

Läuft das Backend nicht, meldet der Handler das per
Desktop-Benachrichtigung, statt still zu scheitern.

## Anordnen

Unter *Plugins* lassen sich die Karten am Griff (⠿) in die gewünschte
Reihenfolge ziehen. Sie gilt auch für die Aktionsliste im Editor und wird in
der Config gespeichert. Neu installierte Plugins landen hinten, damit sich
eine eingespielte Anordnung nicht von selbst verschiebt.

## Plugin-Symbole

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

## Eigene Plugins schreiben

Siehe [plugin-entwicklung.md](plugin-entwicklung.md). Kurz: ein Ordner unter
`~/.local/share/deckswitch/plugins/` mit `manifest.json` und einer
Python-Datei, die von `ActionPlugin` erbt. Iconsets brauchen nur ein
Manifest und einen Ordner voller SVGs.
