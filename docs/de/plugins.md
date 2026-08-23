# Plugins

*[English version](../en/plugins.md)* · Zurück zur [Übersicht](../../README.de.md).

## Eingebaute Plugins

| Plugin | Aktionen |
| --- | --- |
| **Audio** | Lautstärke (Dial mit Balken), Lautstärke auf Festwert setzen, Mikrofon stumm (auch Push-to-Talk), Ausgabegerät wechseln, App-Lautstärke |
| **Multi-Aktion** | Multi-Aktion, Multi-Aktion (Umschalter) |
| **Soundboard** | Klang abspielen (mit eigenem Ausgabegerät), alles anhalten |
| **System** | Programm starten und beenden, Ordner/Datei/Link öffnen, Shell-Befehl, Tastenkombination (auch als Umschalter und als Push-to-Talk), Text tippen, Multimedia, Fenster & Arbeitsfläche, Bildschirmfoto, Sitzung (sperren, abmelden, ruhen, neu starten, ausschalten), Systemwerte (CPU, RAM, GPU, Temperaturen, Netz), Monitorhelligkeit über DDC/CI |
| **Streamdeck** | Ordner, Home, Zurück, Seitenanzeige, Gehe zu Seite, Blättern, Helligkeit, Leer (Platzhalter), Virtuelles Deck |
| **Tabler-Icons** | kein Aktions-Plugin, sondern der mitgelieferte Symbolsatz |

Fachlich sind sie Pflicht, technisch aber ganz gewöhnliche Plugins. Sie
liegen in `backend/plugins/` und nicht in
`~/.local/share/deckswitch/plugins/`, und in der GUI tauchen sie ganz normal
in der Plugin-Liste auf.

### Tastenkombination und Text tippen

Beides läuft über eine virtuelle Tastatur am Compositor vorbei direkt an den
Kernel (`/dev/uinput`). Unter Wayland ist das der einzige Weg: Die Protokolle
zum Einschleusen von Tasten bietet KWin nicht an, und `xdotool` erreicht nur
XWayland-Fenster.

Dabei ist etwas wichtig: Der Kernel kennt keine Zeichen, nur Tastenpositionen.
Welches Zeichen daraus wird, entscheidet die eingestellte Belegung. Die
Zuordnung Zeichen → Taste berechnet die App deshalb aus der *tatsächlich
aktiven* Belegung, gelesen über libxkbcommon aus KDE oder `localectl`. Sonst
tippte „Strg+Z" auf einer deutschen Tastatur ein „Strg+Y". Zeichen, die nur
über Tottasten erreichbar sind, überspringt sie und schreibt es ins Log. Ein
fehlendes Zeichen ist besser als eine Kombination, die etwas ganz anderes
auslöst.

Eine Kombination nimmst du über den Knopf *Aufnehmen* am Feld auf. Was der
Browser selbst abfängt (Strg+W schließt den Tab), trägst du von Hand ein.

### Fenster & Arbeitsfläche

Das löst KDEs eigene globale Kurzbefehle aus: maximieren, kacheln, auf
Bildschirm 2 schieben, Arbeitsfläche wechseln, und was sonst noch angemeldet
ist. Bei einer Standardinstallation sind das rund 170 Einträge allein für
KWin. Unter Wayland ist das der saubere Weg, denn Fenster von außen zu
verschieben gibt es dort nicht. Und diese Kurzbefehle musst du nicht einmal
selbst belegt haben.

### Sitzung

Kennt sperren, abmelden, Bereitschaft, Ruhezustand, neu starten und
ausschalten, jeweils mit oder ohne Rückfrage von Plasma. Voreingestellt ist
zusätzlich **zweimal drücken**: Der erste Druck macht die Taste nur scharf
und zeigt „Sicher?", erst der zweite führt aus. Ein versehentlich getroffenes
Herunterfahren wäre der teuerste Fehlgriff, den dieses Gerät anbieten kann.

### Multimedia

Steuert den Player, der *gerade spielt* (MPRIS). Also den Browser, wenn dort
ein Video läuft, und den Musikspieler, wenn dort Musik läuft. Einen
bestimmten Player kannst du fest einstellen. Findet sich gar keiner, geht die
Multimedia-Taste einer Tastatur raus, und der Desktop verteilt sie selbst.

### Soundboard

Spielt über `pw-play` ab und darf je Belegung ein eigenes **Ausgabegerät**
wählen. Genau dafür ist ein Soundboard beim Streamen da: Der Jingle soll in
die Sendung und nicht zwingend in die eigenen Kopfhörer. Wahlweise in
Schleife, und ein zweiter Druck startet neu oder hält an.

### Audio

**Ausgabegerät wechseln** setzt nicht nur den Standard-Sink, sondern zieht
auch alle laufenden Streams mit. Sonst bliebe die schon laufende Musik auf
dem alten Gerät.

**Lautstärke setzen** springt mit einem Druck auf einen festen Prozentwert
— eine Taste für 20 %, eine für 50 %, eine für 100 %. Ein stummes Gerät wird
dabei standardmäßig wieder freigeschaltet, sonst zeigte der Balken den Wert
und zu hören wäre nichts. Liegt der Wert gerade an, bekommt die Taste einen
Rahmen. Auf einem Dial gilt beides: Drehen ändert wie gewohnt schrittweise,
Druck springt auf den Festwert.

**Zustände von außen.** Ändert jemand die Lautstärke in den
Systemeinstellungen, wechselt OBS die Szene oder mutet Discord sich selbst,
zeichnet die betroffene Taste sofort neu. Dafür laufen `pactl subscribe` und
die Event-Kanäle von obs-websocket und Discord-RPC mit. Der Sekundentakt ist
nur das Sicherheitsnetz.

## Nachinstallierbare Plugins

Diese fünf gehören nicht zum Lieferumfang. Ihre Quellen liegen aber in
[plugin-sources/](../../plugin-sources/).

| Plugin | Aktionen |
| --- | --- |
| **Discord** | Mute (auch Push-to-Talk und Push-to-Mute), Deafen, Sprachkanal wechseln, Kanal verlassen, Textkanal öffnen, Mikrofonpegel |
| **OBS** | Aufnahme (inkl. Pause und Kapitelmarken), Stream, Wiedergabepuffer und Replay speichern, Szenensammlung, Szene, Quelle, Ton stumm, Medienwiedergabe, Studio-Modus, Vorschau live schalten, Filter, Screenshot, Übergang, virtuelle Kamera |
| **Spotify** | Wiedergabe, nächster/vorheriger Titel, Playlist starten, Shuffle, Wiederholung, Lautstärke, Multimedia-Dial |
| **Wetter** | Aktuelles Wetter, Mehrtagesvorhersage, Luftqualität |
| **Uhr-Schoner** | Bildschirmschoner: Uhrzeit als je eine Ziffer pro Taste |

### Discord

Braucht eine einmalige Einrichtung, siehe
[discord-setup.md](discord-setup.md).

**Kanaltasten** zeigen von sich aus das Logo des Servers, zu dem der Kanal
gehört. Das kannst du je Taste abschalten, und ein selbst gewähltes Icon hat
immer Vorrang. Die Logos liegen unter
`~/.local/share/deckswitch/cache/discord-guilds/`.

### OBS

Braucht obs-websocket, das in OBS 28+ eingebaut ist. Aktivieren kannst du es
unter *Werkzeuge → WebSocket-Servereinstellungen*. Host, Port, Passwort und
der Screenshot-Ordner stehen in der GUI unter *Plugins → OBS →
Plugin-Einstellungen*.

Der Funktionsumfang entspricht dem offiziellen Elgato-OBS-Plugin. Ein paar
Besonderheiten:

* **Quelle** und **Filter** haben abhängige Auswahllisten. Erst die Szene
  oder Quelle wählen, dann füllt sich die zweite Liste passend.
* **Ton stumm** kann statt Umschalten auch als Push-to-Talk oder
  Push-to-Mute arbeiten.
* **Auf einem Dial** blättern *Szene*, *Übergang* und *Szenensammlung* per
  Drehen durch die jeweilige Liste.
* **Stream** und **Aufnahme** lassen sich gegen versehentliches Stoppen
  absichern („zweimal drücken"). Beim Stream ist das voreingestellt.
* **Kapitelmarken** brauchen OBS 30.2 oder neuer und Hybrid-MP4 als
  Aufnahmeformat. Sonst erscheint ein Hinweis.

**Spotify** braucht gar keine Einrichtung. Die Steuerung läuft über MPRIS,
den D-Bus-Standard für Medienspieler unter Linux: kein Konto, keine
Zugangsdaten, kein OAuth. Titel, Künstler, Wiedergabe-, Shuffle- und
Wiederholungszustand aktualisieren sich in Echtzeit, und das Albumbild kann
als Hintergrund des Dial-Segments dienen.

* Gesteuert wird der **lokal laufende Player**. Die offizielle
  Elgato-Version greift über Spotifys Web-API auch auf Handy oder
  Lautsprecher zu, das kann MPRIS nicht.
* Das Plugin funktioniert mit **jedem MPRIS-fähigen Player**, nicht nur
  Spotify. Einstellbar unter *Plugins → Spotify*.

**Playlist starten** braucht den Link zur Playlist: in Spotify Rechtsklick →
*Teilen* → *Link kopieren*, dann in die Taste einfügen. Eine Auswahlliste
deiner eigenen Playlists gibt es mit Absicht nicht, denn MPRIS kennt keine.

**Wetter** kommt von [Open-Meteo](https://open-meteo.com), ohne Konto und
ohne API-Schlüssel. Such unter *Plugins → Wetter* einen Ort und wähl ihn aus
der Trefferliste. Die Daten frischt das Plugin alle zehn Minuten auf.

* **Wetter** zeigt Temperatur und Wetterlage. Kurzer Druck blendet Höchst-
  und Tiefstwert ein. Am Dial drehst du in Dreistundenschritten durch den Tag
  und drückst, um zwischen Stundenverlauf, Temperaturdiagramm und
  Detailansicht zu wechseln.
* **Vorhersage** zeigt einen bestimmten Tag, am Dial stehen fünf Tage
  nebeneinander.
* **Luftqualität** zeigt den AQI mit Einstufung, wahlweise europäische oder
  US-Skala, und färbt sich nach Schweregrad.

Jede Belegung kann über *Abweichender Ort* eine eigene Stadt bekommen. So
liegen Heimatort und Urlaubsziel nebeneinander auf dem Deck.

## Nachinstallieren

Unter *Plugins* stehen die Kacheln aus dem **Store** gleich neben deinen
eigenen. Was du noch nicht hast, erkennst du am gestrichelten Rand und am
Knopf *Installieren*. Bevor du klickst, siehst du, was die Durchsicht des
Stores im Quelltext gefunden hat.

Zum Store gehört eine Anmeldung über GitHub. Brauchen tust du sie nur zum
**Einreichen** eigener Plugins; stöbern und installieren geht ohne.

Daneben gibt es unter *Plugins → Installieren* drei weitere Wege:

1. **Adresse eintragen** — ein ZIP von einer http(s)-Adresse
2. **Datei ablegen** — ZIP per Drag & Drop oder Dateiauswahl
3. **`streamdeck://`-Link** im Browser (siehe unten)

Installiert wird nach `~/.local/share/deckswitch/plugins/`. Die Ordner dort
heißen nach einer laufenden Nummer (`0001`, `0002`, …) und nicht nach der
Kennung des Plugins. So bestimmt kein Archiv mehr, wie ein Ordner auf deiner
Platte heißt. Welches Plugin in welchem Ordner liegt, steht in dessen
`manifest.json`.

Eingebaute Plugins lassen sich weder überschreiben noch entfernen.
Nachinstallierte haben in der Liste einen *Entfernen*-Knopf.

Verteilbare Archive der mitgelieferten Quellen baust du so:

```sh
./scripts/package_plugins.py          # → dist/plugins/*.zip
```

### Eigene Plugins einreichen

*Plugins → Plugin einreichen* öffnet ein Feld, in das du ein Archiv ziehst.
ZIP, TAR und tar.gz gehen alle: Der Store nimmt an, was er zum Prüfen öffnen
kann. Ausgeliefert wird später immer ein ZIP, weil nur das der Installer
auspacken kann.

Im selben Fenster stehen deine bisherigen Einreichungen mit ihrem Stand
(wartet, freigegeben, abgelehnt) und dem Text der Moderation. Jede Zeile hat
einen Knopf, um sie wieder loszuwerden — was dabei passiert, hängt vom Stand
ab:

* **Wartet oder abgelehnt:** Die Fassung wird gelöscht, das Archiv mit ihr,
  und die Versionsnummer ist wieder frei. Praktisch, wenn du zu früh
  hochgeladen hast.
* **Freigegeben:** Sie fällt nur aus dem Katalog. Wer sie schon installiert
  hat, kann sie weiter herunterladen — sonst stünde eine Neuinstallation
  plötzlich vor einer Adresse, die es nicht mehr gibt.
* **Gesperrt:** bleibt liegen. Das hat ein Moderator entschieden, und daran
  ändert kein Knopf etwas.

### streamdeck://-Links

Damit lassen sich Plugins direkt aus dem Browser installieren:

```sh
./scripts/install-url-handler.sh     # einmalig registrieren
```

Danach führt ein Link der Form

```
streamdeck://install?url=https://example.com/mein-plugin.zip
```

zu einer **Anfrage**, die du in der Oberfläche bestätigen musst, mit Angabe
der Herkunft. Ein Klick auf einen Link installiert also nichts von selbst.
Das ist Absicht: Ein Plugin ist Programmcode, der mit deinen Rechten läuft,
und eine beliebige Webseite darf das nicht ohne Rückfrage auslösen.
Unbestätigte Anfragen verfallen nach zehn Minuten.

Läuft das Backend nicht, meldet der Handler das per
Desktop-Benachrichtigung.

## Anordnen

Unter *Plugins* ziehst du die Karten am Griff (⠿) in die gewünschte
Reihenfolge. Sie gilt auch für die Aktionsliste im Editor und wird in der
Config gespeichert. Neu installierte Plugins landen hinten, damit sich eine
eingespielte Anordnung nicht von selbst verschiebt.

## Plugin-Symbole

Ein Plugin darf ein eigenes Bild mitbringen: `"icon": "icon.png"` im
Manifest, 256 × 256 Pixel. Es erscheint **nur in der Plugin-Übersicht** und
nicht in der Aktionsbibliothek. Dort stünde neben jeder Aktion desselben
Plugins dasselbe Bild, das hilft beim Suchen nicht. Ohne Symbol zeigt die
Übersicht ein farbiges Feld mit dem Anfangsbuchstaben.

Dazu kommen bis zu drei **Bilder für die Detailansicht** über
`"screenshots": [...]` im Manifest.

Symbole und Bilder der mitgelieferten Plugins entstehen aus Akzentfarbe,
Aktions-Symbolen und dem, was im Manifest steht:

```sh
./scripts/make-plugin-icons.py          # Symbole, alle
./scripts/make-plugin-icons.py audio    # nur eines
./scripts/make-plugin-screenshots.py    # Bilder für die Detailansicht
```

## Eigene Plugins schreiben

Siehe [plugin-development.md](plugin-development.md). Kurz gesagt: ein Ordner
unter `~/.local/share/deckswitch/plugins/` mit `manifest.json` und einer
Python-Datei, die von `ActionPlugin` erbt. Iconsets brauchen nur ein Manifest
und einen Ordner voller SVGs.
