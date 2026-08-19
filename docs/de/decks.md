# Decks: Hardware, Overlay und Netz

*[English version](../en/decks.md)* · Zurück zur [Übersicht](../../README.de.md).

Ein „Deck" ist in DECK//SWITCH nicht zwingend ein Gerät am USB-Anschluss.
Es gibt drei Bauarten, und für alles oberhalb der Bedienung sind sie
gleichwertig: eigenes Profil mit eigenem Seitenbaum, Tastenlogik mit
Doppeldruck und Halten, Multi-Aktionen, Dial-Stacks, Bildschirmschoner. Die
Kacheln entstehen bei allen dreien in derselben Zeichenkette.

| Bauart | Bedient über | Wozu |
| --- | --- | --- |
| **Hardware** | Elgato Stream Deck am USB | der Normalfall |
| **Virtuelles Deck** | Overlay auf dem eigenen Bildschirm | wenn das Gerät gerade nicht in Reichweite ist |
| **Netz-Deck** | Browser eines anderen Rechners | wenn jemand anderes mitsteuern soll |

## Mehrere Decks gleichzeitig

Es können mehrere Stream Decks gleichzeitig angeschlossen sein. Jedes Gerät
ist eigenständig: eigenes Profil, eigene Helligkeit, eigener
Bildschirmschoner, eigene Zeiten für Halten und Doppeldruck.

Zugeordnet wird über die **Seriennummer**. Ein Deck darf also an einem
anderen USB-Anschluss stecken oder in anderer Reihenfolge erkannt werden und
findet trotzdem seine Belegung wieder. Kommt ein bisher unbekanntes Gerät
dazu, legt die App ein leeres Profil dafür an.

In der Kopfzeile stehen die Decks als Umschalter, sobald es mehr als eines
gibt — der Editor bearbeitet immer genau eines. Unter *Einstellungen →
Decks* lassen sich Geräte umbenennen; ein Deck, das nicht mehr da ist, kann
man dort entfernen (sein Profil bleibt erhalten).

Wer nur ein Deck hat, merkt von alldem nichts.

## Welches Stream Deck?

Die Oberfläche richtet sich nach dem angeschlossenen Gerät: Tastenzahl,
Rasteranordnung und das Vorhandensein von Dials kommen aus der
Gerätemeldung, nicht aus einer festen Annahme. Ein Stream Deck XL zeigt
8 × 4 Tasten, ein Mini 3 × 2, und ohne Dials entfällt der Touchstrip-Bereich
ganz. Entwickelt und am Gerät geprüft ist der **Stream Deck +**; die übrigen
Modelle sind gegen vorgetäuschte Gerätemeldungen getestet, aber nie an
echter Hardware.

---

## Virtuelles Deck (Overlay)

Unter *Einstellungen → Decks → **+ Virtuelles Deck*** entsteht ein Deck mit
frei wählbarem Raster (Spalten, Reihen, Dials, Kachelgröße), das als
**Overlay** über dem Bildschirm liegt.

**Es ist bewusst kein Fenster.** Über `zwlr_layer_shell_v1` liegt die Fläche
auf der Overlay-Ebene: kein Eintrag in der Fensterleiste, kein Alt-Tab, kein
Rahmen — und vor allem **kein Fokus**. Das ist der Punkt, an dem so etwas
sonst scheitert: Würde ein Klick auf die Taste den Fokus stehlen, tippte die
Aktion *Text tippen* anschließend ins Deck statt in die Anwendung, aus der
du kamst. Unter KWin gemessen — der Klick kommt an, der Fokus bleibt beim
Vordergrundfenster.

**Herbeirufen** geht auf drei Wegen:

* über einen **globalen Kurzbefehl** — siehe unten
* über *Einstellungen → Decks → Overlay zeigen*
* über die Aktion **Virtuelles Deck** (Plugin *Streamdeck*) auf einer Taste
  des echten Decks — wahlweise umschaltend, und auf Wunsch **am Mauszeiger**

Die Zeigerposition verrät unter Wayland kein Client-Protokoll; das ist
Absicht. KWin weiß sie aber und darf D-Bus rufen, also fragen wir über ein
winziges KWin-Skript zurück an uns selbst. Ohne KDE erscheint das Overlay an
seiner gemerkten Stelle — kein Fehler, nur weniger bequem.

### Verschieben und ablegen

Ist *Am Mauszeiger erscheinen* **aus**, lässt sich das Overlay dorthin
legen, wo es hingehört — die Stelle wird gespeichert und gilt bei jedem
weiteren Aufruf:

* **linke Maustaste** auf dem Rand rings um die Kacheln
* **rechte Maustaste** überall, auch auf den Kacheln — nötig, wenn bei
  durchsichtigem Grund und ausgeblendeten leeren Kacheln kaum freie Fläche
  übrig ist

Während des Ziehens tritt das Overlay zurück und springt beim Loslassen an
die neue Stelle. Es gleitet nicht mit: Eine Layer-Shell-Fläche lässt sich im
Betrieb nicht verschieben — `Window::setMargins` aus layer-shell-qt merkt
sich den Wert und meldet ihn als Signal, erreicht die laufende
Wayland-Fläche damit aber nicht. Deshalb wird sie an der neuen Stelle neu
aufgebaut.

### Einstellungen

Im Editor stehen Raster und Overlay-Schalter rechts in den
Seiten-Eigenschaften. Die Kachelgröße ist stufenlos; dazu gibt es zwei
Schalter:

* **Hintergrund transparent** — ohne Platte darunter schweben nur die
  Kacheln über dem Bildschirm.
* **Leere Kacheln ausblenden** — unbelegte Plätze bleiben unsichtbar und
  nehmen auch keine Klicks an. Ihr Platz bleibt aber frei, damit die
  übrigen Kacheln nicht bei jeder Belegung springen.

### Kurzbefehl

Darunter steht der **Kurzbefehl**, der genau dieses Overlay holt und wieder
wegschickt — von überall, ohne die Oberfläche zu öffnen. Wer nur ein
virtuelles Deck hat, braucht ihn: Ein Deck ohne Gehäuse hat sonst keinen
Griff. *Aufnehmen* drücken und die Kombination tippen; das Feld lässt sich
auch von Hand beschreiben (`ctrl+alt+d`), weil der Browser manche
Kombinationen abfängt, bevor die Seite sie sieht.

Angemeldet wird der Kurzbefehl bei Plasma (`kglobalaccel`). Das hat drei
Folgen, die man kennen sollte:

* Er steht danach auch in den **KDE-Systemeinstellungen** unter *Kurzbefehle
  → DECK//SWITCH* und lässt sich dort ändern.
* Eine **schon vergebene Kombination wird abgelehnt**, nicht weggenommen —
  unter dem Feld steht dann, wem sie gehört (etwa „KWin — Blick auf die
  Arbeitsfläche"). Wer sie trotzdem will, nimmt sie erst dort weg.
* Beendet sich das Backend, ist der Kurzbefehl wieder frei. Es bleibt nichts
  stehen, hinter dem kein Programm mehr steckt.

`AltGr` geht nicht — das ist bei Qt keine Modifier-Stufe, die ein globaler
Kurzbefehl abbilden kann. Ein leeres Feld heißt: kein Kurzbefehl.

Die Kacheln bekommen **runde Ecken mit echter Transparenz** — gerundet wird
beim Rendern und nicht im Overlay, weil Qt nur rechteckig zuschneiden kann
und die Ecken sonst als Quadrate stehen blieben.

Die **Helligkeit** gibt es hier nicht: Ein Overlay hat keine
Hintergrundbeleuchtung, die sich drosseln ließe. Beide denkbaren
Übertragungen sind schlechter als gar keine — als Deckkraft wird die Kachel
durchscheinend und auf hellem Grund unlesbar, als Abdunkeln stimmen die
Farben nicht mehr mit der Vorschau überein. Der Regler ist deshalb
abgeschaltet.

**Voraussetzungen:** `qt6-declarative` (bringt `qml6` mit) und
`layer-shell-qt`. Fehlt eines davon, sagt es die Oberfläche im Klartext,
statt den Knopf wirkungslos anzubieten.

Ein globales **Tastenkürzel** zum Herbeirufen fehlt noch. Der saubere Weg
dafür wäre das Portal `org.freedesktop.portal.GlobalShortcuts`; KDEs
`kglobalaccel` nimmt die Anmeldung zwar an, liefert das Signal aber nicht
aus (gemessen).

---

## Netz-Deck

Ein Netz-Deck wird von **einem anderen Rechner im selben Netz** im Browser
bedient — gedacht für den Moderator, der während des Streams mitsteuern
soll, ohne an deinen Rechner zu müssen. Er sieht genau dieses eine Deck und
kann nichts daran ändern.

Anlegen unter *Einstellungen → Decks → **+ Netz-Deck***. Belegt wird es wie
jedes andere Deck; im Editor stehen rechts Raster, Passwort und Adresse.

### Einrichten

1. Deck anlegen und die Tasten belegen.
2. Im Editor unter *Zugang* ein **Passwort** setzen (mindestens 4 Zeichen).
3. Die angezeigte **Adresse** an den Gast weitergeben, etwa
   `http://192.168.178.37:8771/deck/net-a1b2c3d4`.

Der Gast öffnet die Adresse, gibt das Passwort ein und hat das Deck vor
sich. Nichts zu installieren — die Seite ist eine einzelne Datei ohne
Bibliotheken und läuft auf Handy, Tablet und fremdem Laptop.

Drücken und Loslassen gehen einzeln an das Backend, damit Halten,
Doppeldruck und Push-to-Talk genau wie am Gerät greifen. Dials haben − und +
mit Wiederholung beim Halten.

Falls eine Firewall läuft, muss der Port frei sein — besser nur fürs eigene
Subnetz als pauschal:

```sh
sudo ufw allow from 192.168.178.0/24 to any port 8771 proto tcp
```

### Wie es abgesichert ist

Der reguläre Server, der die Oberfläche bedient, bindet **ausschließlich an
`127.0.0.1`** und bleibt es auch. Er darf alles: Belegungen ändern, Plugins
installieren, die Konfiguration exportieren — samt der Zugangsdaten in den
Plugin-Einstellungen. So etwas gehört nicht ins Netz.

Ins Netz geht stattdessen eine **zweite, absichtlich winzige Anwendung** auf
einem eigenen Port (voreingestellt 8771). Sie kann drei Dinge: anmelden,
Kacheln zeigen, Tasten drücken. Es existiert schlicht kein Endpunkt, mit dem
sich etwas ändern ließe — der Schutz liegt in dem, was fehlt, und nicht in
einer Regel, die jemand später aufweicht.

Dazu:

* Das **Passwort** wird nur abgeleitet gespeichert (PBKDF2-HMAC-SHA256,
  210 000 Runden, eigenes Salz) — in der Konfigurationsdatei steht kein
  Klartext.
* Nach dem Anmelden gilt ein **Token**, zwölf Stunden, an genau ein Deck
  gebunden.
* Ein **Passwortwechsel trennt alle**, die gerade verbunden sind.
* Nach fünf Fehlversuchen ist die Adresse fünf Minuten **gesperrt**; jeder
  Fehlversuch kostet zusätzlich eine halbe Sekunde.
* **Ohne Passwort wird ein Deck gar nicht angeboten.** Ist kein Netz-Deck
  mehr aktiv, hört der Server ganz auf zu lauschen — ein offener Port ohne
  Zweck ist eine Angriffsfläche ohne Gegenwert.

Was das **nicht** leistet: Die Verbindung ist unverschlüsselt. Im eigenen
Netz ist das vertretbar — über fremde Netze oder gar das Internet gehört ein
Netz-Deck nicht.
