# Plugins

*[English version](../en/plugins.md)* · Zurück zur [Übersicht](../../README.de.md).

Die eingebauten Plugins gehören zum Lieferumfang. Alles andere kommt aus dem
Store, im Netz unter <https://streamdeckstore.labratox.de> und in der App
unter *Plugins*. Manche Store-Plugins brauchen eine einmalige Einrichtung,
siehe [Store-Plugins einrichten](store-plugin-setup.md).

## Eingebaute Plugins

| Plugin | Aktionen |
| --- | --- |
| **Audio** | Lautstärke (Dial mit Balken und Pegelanzeige), Lautstärke auf Festwert setzen, Mikrofon stumm (auch Push-to-Talk), Ausgabegerät wechseln, App-Lautstärke |
| **Multi-Aktion** | Multi-Aktion, Multi-Aktion (Umschalter) |
| **Soundboard** | Klang abspielen (mit eigenem Ausgabegerät), alles anhalten |
| **System** | Programm starten und beenden, Ordner/Datei/Link öffnen, Shell-Befehl, Tastenkombination (auch als Umschalter und als Push-to-Talk), Text tippen, Multimedia, Fenster & Arbeitsfläche, Bildschirmfoto, Sitzung (sperren, Bildschirme aus und ein, Bereitschaft, Ruhezustand, abmelden, neu starten, ausschalten), Systemwerte (CPU, RAM, Auslagerung, GPU, Grafikspeicher, CPU-/GPU-/SSD-Temperatur, Speicherplatz, Netz), Monitorhelligkeit über DDC/CI |
| **Streamdeck** | Ordner, Home, Zurück, Seitenanzeige, Gehe zu Seite, Blättern, Profil wechseln, Helligkeit, Leer (Platzhalter), Virtuelles Deck |
| **Tabler-Icons** | kein Aktions-Plugin, sondern der mitgelieferte Symbolsatz |

Fachlich sind sie Pflicht, technisch aber ganz gewöhnliche Plugins. Im
Quellbaum liegen sie in `backend/plugins/`, in einer installierten App in
`/usr/share/deckswitch/plugins/`. Nie in `~/.local/share/deckswitch/plugins/`,
und in der GUI tauchen sie ganz normal in der Plugin-Liste auf.

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

Unter Plasma löst das KDEs eigene globale Kurzbefehle aus: maximieren,
kacheln, auf Bildschirm 2 schieben, Arbeitsfläche wechseln, und was sonst noch
angemeldet ist. Bei einer Standardinstallation sind das rund 170 Einträge
allein für KWin. Unter Wayland ist das der saubere Weg, denn Fenster von außen
zu verschieben gibt es dort nicht. Und diese Kurzbefehle musst du nicht einmal
selbst belegt haben.

Unter Hyprland und Sway spricht die Aktion direkt mit dem Compositor. Beide
kennen keine Liste benannter Aktionen, deshalb bringt die App eine feste
Auswahl an Befehlen mit. Beide bekommen Vollbild, Fenster schließen, schwebend
umschalten, das Fenster in vier Richtungen schieben, zur Arbeitsfläche 1 bis
10 wechseln und das Fenster dorthin schieben. Hyprland hat zusätzlich
Maximieren, Anheften und Mittig setzen (beides nur für schwebende Fenster)
und die Arbeitsfläche auf den nächsten Bildschirm. Sway hat zusätzlich auf
allen Arbeitsflächen anheften, Aufteilung umschalten und das Fenster auf den
nächsten Bildschirm. Auf anderen Desktops steht die Aktion nicht zur
Verfügung.

### Sitzung

Kennt sperren, Bildschirme aus und ein, Bereitschaft, Ruhezustand, neu
starten, ausschalten und abmelden. Abmelden, neu starten und ausschalten gibt
es zusätzlich *mit Rückfrage*, dann erscheint die Bestätigung von Plasma. Die
Varianten mit Rückfrage und das Abmelden ohne brauchen die Sitzungsverwaltung
von Plasma. Bildschirme aus und ein geht unter Plasma (über
`kscreen-doctor`), Hyprland und Sway.

Voreingestellt ist zusätzlich **zweimal drücken**. Der erste Druck macht die
Taste nur scharf und zeigt „Sicher?", erst der zweite führt aus. Ein
versehentlich getroffenes Herunterfahren wäre der teuerste Fehlgriff, den
dieses Gerät anbieten kann.

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

**Pegelanzeige.** *Lautstärke* und *Lautstärke setzen* zeigen unter dem Text,
was gerade aus dem Gerät kommt: von -60 bis 0 dBFS, gelb ab -12, rot ab -3,
dazu eine weiße Marke für die letzte Spitze. Der Wert folgt dem
Lautstärkeregler. Gemessen wird nur, solange die Anzeige zu sehen ist, und der
Ausgang darf dabei weiter in den Ruhezustand gehen. Abschalten lässt sie sich
je Belegung über den Schalter *Pegelanzeige*. Stumm bleibt sie leer.

**Ausgabegerät wechseln** setzt nicht nur den Standard-Sink, sondern zieht
auch alle laufenden Streams mit. Sonst bliebe die schon laufende Musik auf
dem alten Gerät. Soll nur neue Wiedergabe auf dem neuen Gerät landen,
schaltest du in der Belegung *Laufende Streams mitziehen* ab.

**Lautstärke setzen** springt mit einem Druck auf einen festen Prozentwert.
Eine Taste für 20 %, eine für 50 %, eine für 100 %. Ein stummes Gerät wird
dabei standardmäßig wieder freigeschaltet (*Stummschaltung aufheben*), sonst
zeigte der Balken den Wert und zu hören wäre nichts. Liegt der Wert gerade
an, bekommt die Taste einen Rahmen. Auf einem Dial gilt beides: Drehen ändert
wie gewohnt schrittweise, Druck springt auf den Festwert.

**Zustände von außen.** Ändert jemand die Lautstärke in den
Systemeinstellungen, wechselt OBS die Szene oder mutet Discord sich selbst,
zeichnet die betroffene Taste sofort neu. Dafür laufen `pactl subscribe` und
die Event-Kanäle von obs-websocket und Discord-RPC mit. Der Sekundentakt ist
nur das Sicherheitsnetz.

## Was deine Sitzung nicht kann

Eine Aktion oder eine Auswahl kann von etwas abhängen, das der Desktop
liefern muss, etwa Fenstersteuerung oder die Sitzungsverwaltung. Ein Plugin
nennt das in seinem Manifest (`requires`). Fehlt es deiner Sitzung, taucht die
Aktion in der Aktionsbibliothek nicht auf. Auf einer Taste, die sie schon
trägt, steht im Inspector „Wirkungslos in dieser Sitzung" mit dem Grund.
Auswahllisten verhalten sich genauso: Die Einträge verschwinden, nur der schon
gewählte bleibt stehen und ist mit „(in dieser Sitzung wirkungslos)"
markiert.

## Die Plugin-Liste

Unter *Plugins* stehen die installierten Plugins und die Kacheln aus dem
Store in einer Liste. Oben wählst du die Art (*Plugins*, *Icons*,
*Bildschirmschoner*, *Hintergrundbilder*), links eine Kategorie, *Alle* oder
*Installiert*. Die Zahlen daneben zählen, was das Suchfeld (*Plugins
durchsuchen*) übrig lässt. So siehst du, wo die Treffer liegen, auch unter
einem anderen Reiter. *Sortieren* ordnet die Liste *A bis Z*, *Z bis A*,
*Neueste zuerst* oder nach *Beste Bewertung*.

Ein Klick auf den Namen eines Plugins öffnet seine Detailseite. Dort ist der
Name des Autors ein Link. Ein Klick darauf zeigt in der Liste nur noch dessen
Plugins, und ein Chip *Nur von …* über der Liste holt alles zurück.
Eingebaute Plugins haben diesen Link nicht.

Jedes installierte Plugin hat einen Schalter, der es ein- und ausschaltet.
*Plugin-Einstellungen* erscheint, solange es eingeschaltet ist und
Einstellungen hat. Eingebaute Plugins tragen das Abzeichen *Eingebaut*. Die
übrigen haben einen Knopf *Entfernen*. Vor dem Entfernen kommt eine Rückfrage,
denn die Belegungen dieses Plugins werden mit gelöscht.

*Nach neuen Plugins sehen* liest ein, was auf der Platte dazugekommen ist, und
frischt den Store-Katalog auf. Laufende Plugins bleiben unangetastet.

### Updates

Hat der Store eine neuere Fassung eines installierten Plugins, bekommt dessen
Karte einen Knopf mit der neuen Versionsnummer. Sind es mehrere, bietet ein
Balken über der Liste *Alle aktualisieren* an. Eine Fassung, die eine neuere
App braucht, lässt sich nicht installieren: Der Knopf bleibt gesperrt und
sagt „Braucht DECK//SWITCH … oder neuer". Der Installer lehnt so ein Plugin
auch aus jeder anderen Quelle ab.

## Nachinstallieren

Kacheln aus dem **Store** haben einen gestrichelten Rand und den Knopf
*Installieren*. Bevor du klickst, siehst du, was die Durchsicht des Stores im
Quelltext gefunden hat, auf der Kachel und auf der Detailseite.

Der Store prüft jeden Download. Der Katalog nennt zu jeder Fassung eine
SHA-256-Prüfsumme, und ausgepackt wird nur, wenn sie stimmt. Nennt der
Katalog keine, wird nichts installiert. Außerdem muss die Plugin-ID im Archiv
zu dem Plugin passen, nach dem du gefragt hast.

Zum Store gehört eine Anmeldung über GitHub (*Im Store anmelden*). Brauchen
tust du sie zum **Einreichen** eigener Plugins und zum **Bewerten**; stöbern
und installieren geht ohne.

Daneben gibt es unter *Plugins installieren* zwei weitere Wege, dazu Links
aus dem Browser:

1. **Von einer Adresse installieren**: ein ZIP von einer http(s)-Adresse
2. **Plugin-Archiv (.zip) hierher ziehen oder klicken**: ein ZIP per Drag &
   Drop oder Dateiauswahl
3. **`streamdeck://`-Link** im Browser (siehe unten)

Installiert wird nach `~/.local/share/deckswitch/plugins/`. Die Ordner dort
heißen nach einer laufenden Nummer (`0001`, `0002`, …) und nicht nach der
Kennung des Plugins. So bestimmt kein Archiv mehr, wie ein Ordner auf deiner
Platte heißt. Welches Plugin in welchem Ordner liegt, steht in dessen
`manifest.json`.

Bringt ein Plugin Abhängigkeiten mit, stehen sie auf seiner Detailseite und
werden mit installiert. Python-Pakete kommen über `uv` von PyPI, nur als
fertige Wheels, und landen je Plugin in einem eigenen Ordner unter
`~/.local/share/deckswitch/plugins/.deps/`. Sie gehen mit dem Plugin.
Systempakete werden je Distributionsfamilie benannt (Arch, Debian und Ubuntu,
Fedora, openSUSE), und das System fragt nach deinem Passwort. Auf einem Fedora mit Image
wie Bazzite kommt ein Paket erst mit dem nächsten Start an, dort ist es immer
Handarbeit. Lässt sich etwas nicht installieren, bleibt das Plugin draußen,
und die Meldung nennt den Befehl.

Eingebaute Plugins lassen sich weder überschreiben noch entfernen.

### Die Detailseite im Store

Neben Beschreibung und *Was ist neu* listet die Detailseite die *Fassungen*,
sobald es mehr als eine gibt, mit Datum, Downloads, dem Stand, wenn sie nicht
freigegeben ist, und dem Text der Moderation. Unter *Bewertung* empfiehlst du
ein Plugin oder nicht und kannst einen Text mit höchstens 500 Zeichen
dazuschreiben. Ein Daumen nach unten braucht eine kurze Begründung. Eigene
Plugins kannst du nicht bewerten. Auch die Detailseite eines installierten
Plugins aus dem Store zeigt die Bewertung.

### Eigene Plugins einreichen

*Plugin einreichen* öffnet ein Feld, in das du ein Archiv ziehst. ZIP, TAR,
tar.gz und tgz gehen alle: Der Store nimmt an, was er zum Prüfen öffnen kann.
Ausgeliefert wird später immer ein ZIP, weil nur das der Installer auspacken
kann.

Im selben Fenster stehen deine bisherigen Einreichungen mit ihrem Stand
(*wartet auf Prüfung*, *freigegeben*, *abgelehnt*, *zurückgezogen*,
*gesperrt*) und dem Text der Moderation. Fassungen, die auf Prüfung warten,
abgelehnt oder freigegeben sind, haben einen Knopf. Was er tut, hängt vom
Stand ab:

* **Wartet auf Prüfung oder abgelehnt:** *Löschen*. Die Fassung wird
  gelöscht, das Archiv mit ihr, und die Versionsnummer ist wieder frei.
  Praktisch, wenn du zu früh hochgeladen hast.
* **Freigegeben:** *Zurückziehen*. Sie fällt nur aus dem Katalog. Wer sie
  schon installiert hat, kann sie weiter herunterladen. Sonst stünde eine
  Neuinstallation plötzlich vor einer Adresse, die es nicht mehr gibt.

Zurückgezogene und gesperrte Fassungen haben keinen Knopf. Eine Sperre hat
ein Moderator entschieden, und daran ändert kein Klick etwas.

### streamdeck://-Links

Damit lassen sich Plugins direkt aus dem Browser installieren. Den Handler
melden der Installer und das AUR-Paket an. Nur in einem bloßen Checkout der
Quellen registrierst du ihn selbst:

```sh
./scripts/install-url-handler.sh     # einmalig registrieren
```

Danach führt ein Link der Form

```
streamdeck://install?url=https://example.com/mein-plugin.zip
```

zu einer **Anfrage**, die du in der Oberfläche bestätigen musst, mit Angabe
der Adresse, von der sie kommt. Ein Klick auf einen Link installiert also
nichts von selbst. Das ist Absicht: Ein Plugin ist Programmcode, der mit
deinen Rechten läuft, und eine beliebige Webseite darf das nicht ohne
Rückfrage auslösen. Unbestätigte Anfragen verfallen nach zehn Minuten.

Ein Link kann die erwartete Prüfsumme als `&sha256=…` mitbringen. Die Anfrage
zeigt dann „Angekündigte Prüfsumme: …", und ausgepackt wird nur, wenn sie
stimmt. Ohne sie steht dort „Ohne Prüfsumme: Es wird installiert, was gerade
unter der Adresse liegt."

Läuft das Backend nicht, meldet der Handler das per
Desktop-Benachrichtigung.

## Anordnen

In der Aktionsbibliothek des Editors ziehst du die Plugins am Griff (⠿) in
die gewünschte Reihenfolge. Während einer Suche ist der Griff ausgeblendet.
Die Reihenfolge wird in der Config gespeichert. Neu installierte Plugins
landen hinten, damit sich eine eingespielte Anordnung nicht von selbst
verschiebt.

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
