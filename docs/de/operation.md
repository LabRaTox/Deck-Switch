# Bedienung

*[English version](../en/operation.md)* · Zurück zur [Übersicht](../../README.de.md).

## Editor

Links stehen die Aktionen aller Plugins, in der Mitte das Deck in der
Geometrie deines Geräts, rechts die Eigenschaften der ausgewählten Position.

* Zieh eine Aktion aus der linken Spalte auf eine Taste oder einen Dial.
* Belegungen lassen sich untereinander per Drag & Drop tauschen.
* Mit ▶ auf einer Kachel löst du die Aktion aus, ohne das Gerät anzufassen.
  ✕ entfernt die Belegung.
* Ein Rechtsklick auf eine Kachel öffnet ein Menü mit *Kopieren*,
  *Ausschneiden*, *Einfügen* und *Löschen*. Einfügen geht nur, wenn die
  kopierte Aktion zum Platz passt, also auf eine Taste oder einen Dial.
* Die Kachelvorschau kommt aus dem Backend. Sie zeigt genau das, was auf dem
  Gerät steht.

Das Feld *Aktion suchen …* über der Liste filtert nach Name und Beschreibung
der Aktion und nach dem Plugin. Aktionen, die nur auf einer Eingabeart
funktionieren, tragen den Hinweis *Nur Tasten* oder *Nur Dials*. Ein Klick
auf den Kopf eines Plugins klappt seine Gruppe zu. Die Reihenfolge der
Plugins änderst du, indem du am Griff ⠿ im Kopf ziehst. Während einer Suche
ist der Griff ausgeblendet.

## Seiten und Ordner

Beides ist dasselbe: eine Seite mit oder ohne Elternteil. Der Seitenbaum
links neben dem Deck zeigt, was wohin gehört. Unterseiten stehen eingerahmt
unter ihrer Seite, der Zweig der geöffneten Seite ist farbig markiert, und
mit ↳ legst du direkt eine Unterseite an. Umbenennen geht per Doppelklick
oder F2, Zweige klappst du mit ▾ zu. Mit + oben legst du eine Seite an, das
Papierkorb-Symbol löscht eine Seite samt Unterseiten nach einer Rückfrage.
Die Startseite lässt sich nicht löschen. Der Knopf neben dem Titel klappt
den ganzen Baum zu einem schmalen Streifen ein. Zum Springen gibt es die
Aktionen des Plugins *Streamdeck*: Ordner, Home, Zurück, Seitenanzeige,
Gehe zu Seite, Nächste und Vorherige Seite.

**Reihenfolge** änderst du im Baum durch Ziehen. Über oder unter eine Zeile
gezogen sortiert um, mitten auf eine Zeile gezogen macht eine Unterseite
daraus. Ohne Maus geht dasselbe mit `Alt` + `↑↓` zum Verschieben und `Alt` +
`←→` zum Aus- und Einrücken. Die Reihenfolge gilt auch am Gerät: Wischen und
Nächste/Vorherige Seite folgen ihr.

**Wischen auf dem Touchstrip** blättert zwischen den Seiten derselben Ebene.
Nach links geht vorwärts, nach rechts zurück. Tippen bleibt dabei bei der
Aktion, die auf dem Segment liegt, denn nur Wischgesten gehen ans Gerät.
Schwelle, Umbruch und Abschalten findest du in den Einstellungen unter
*Touchstrip*.

## Tastenlogik: Drücken, Doppeldruck, Halten

Jede Taste kann drei Aktionen tragen. Im Eigenschaften-Panel schaltest du mit
den drei Reitern dazwischen um. Ein Punkt am Reiter zeigt, welcher Zweig
belegt ist.

Der Grundsatz: **Wer nichts Zweites hinterlegt, wartet auf nichts.** Eine
Taste mit nur einer Aktion löst weiterhin im Moment des Drückens aus. Erst
ein belegter Doppeldruck kauft sich die Wartezeit ein, die nötig ist, um zu
erkennen, ob ein zweiter Druck folgt (voreingestellt 280 ms). Ein belegtes
Halten verschiebt die Hauptaktion auf das Loslassen. Anders geht es nicht,
denn ob ein zweiter Druck kommt, weiß man erst hinterher. Bei Elgato ist es
dieselbe Abwägung.

Als Halten zählt ein Druck voreingestellt ab 500 ms. Beide Zeiten stellst du
je Deck in den Einstellungen unter *Schwelle für langen Druck* und
*Doppeldruck-Fenster* ein.

Daraus folgt etwas Praktisches: Push-to-Talk braucht echtes Drücken *und*
Loslassen. Solche Aktionen gehören auf eine Taste ohne Doppeldruck und ohne
Halten.

Ein Tastendruck bleibt immer bei der Belegung, auf der er begonnen hat. Wer
einen Ordner öffnet, löst nicht nachträglich die Taste aus, die auf der neuen
Seite an derselben Stelle liegt.

## Multi-Aktionen

Die Aktion *Multi-Aktion* führt mehrere Schritte nacheinander aus: Programm
starten, kurz warten, Tastenkombination schicken, Text tippen. Die Schritte
stehen als Liste in den Eigenschaften. Gefüllt wird sie wie das Deck selbst,
nämlich indem du **Aktionen aus der linken Spalte direkt in die Liste
ziehst**. Abgelegt wird vor dem Schritt, über dem der Zeiger steht, und am
Ende, wenn du unter den letzten zielst. Wer lieber klickt, nimmt *+ Aktion*.
*+ Pause* hängt eine Pause an. Sortieren geht ebenfalls durch Ziehen oder mit
`Alt` + `↑↓`.

Eine **Pause** ist ein eigener Schritt und keine Eigenschaft der Aktion
davor. So kannst du sie verschieben, mehrfach einsetzen und einzeln
abschalten. Jeder Schritt hat einen Haken: Abgeschaltete Schritte bleiben
stehen, laufen aber nicht mit. Beim Suchen, welcher Schritt hakt, ist das
mehr wert als ein Löschen.

*Wiederholen* lässt die Kette in Schleife laufen, bis du erneut drückst. Der
**Umschalter** (*Multi-Aktion (Umschalter)*) hat zwei Ketten: Der erste Druck
läuft die eine ab, der nächste die andere, jede mit eigenem Symbol. Ketten in
Ketten gibt es nicht. Das wäre eine Schleife, die niemand mehr anhält.

## Dials

**Drehrichtungen belegen.** Normalerweise bekommt die Aktion eines Dials das
Drehen als Delta und regelt damit stufenlos: Lautstärke, Helligkeit,
Position. Du kannst aber auch **je Drehrichtung eine eigene Aktion**
hinterlegen. Dann wirkt jede Drehung wie ein kurzer Druck darauf, links
„vorheriger Titel", rechts „nächster Titel". Die Reiter dafür stehen unter
*Dial-Belegung*, gleich neben *Drücken*.

* **Ausgelöst wird nach je _n_ Rasten** (voreingestellt 2). Einstellen
  kannst du das unter *Auslösen alle … Rasten*, von 1 bis 10. Ein zügiger
  Dreh erzeugt schnell ein Dutzend Rasten, und „nächster Titel" darf nicht
  ein Dutzend Mal feuern. Gezählt wird, nicht nach Zeit gedrosselt: So führt
  dieselbe Handbewegung immer zum selben Ergebnis, egal wie schnell sie war.
  Ein Richtungswechsel setzt den Zähler zurück.
* **Die Richtungen sind unabhängig.** Ist nur eine belegt, geht die andere
  weiterhin an die Grundaktion. Wer auf dem Druck gar nichts haben will, legt
  die Aktion *Leer* aus dem Streamdeck-Plugin auf den Grundplatz.

**Dial-Stack.** Auf einem Dial können mehrere Belegungen übereinander liegen.
Am Gerät schaltet **langes Drücken** zum nächsten Eintrag weiter, kurzes
Drücken löst weiterhin die Aktion aus. Mit Stack löst der kurze Druck beim
Loslassen aus, denn erst dann steht fest, dass es kein langer Druck war.
Jeder Eintrag ist eine vollwertige Belegung mit eigenem Symbol, eigener
Beschriftung und eigenen Einstellungen. Im Editor wählst du oben aus, welchen
davon du gerade bearbeitest. *+ Eintrag* fügt einen hinzu, ✕ neben einem
Eintrag entfernt ihn (der erste bleibt). *Weiterschalten* springt zum
nächsten Eintrag, genau wie langes Drücken am Gerät. Ein Dial ohne Stack
verhält sich wie vorher, dort löst der Druck sofort aus.

## Aussehen einer Taste

Symbol, Beschriftung und Hintergrund stehen im Eigenschaften-Panel unter
*Aussehen*.

**Beschriftung.** Neben Text, Größe, Farbe und Position gibt es die
**Schriftart** (alles, was fontconfig kennt), **fett**, *kursiv*,
unterstrichen und die Ausrichtung links, mittig oder rechts. Gezeichnet wird
im Backend, deshalb zeigt die Vorschau in der GUI genau das, was auf dem
Gerät landet.

**Hintergrundbild pro Taste.** Unter *Hintergrund* gibt es neben Farbe,
Verlauf, Textur und Akzent auch **Bild**: hochladen oder aus deinen eigenen
Bildern wählen, dazu Einpassung (füllend, ganz zeigen, verzerren) und
Deckkraft. Unter voller Deckkraft legt die App das Bild auf den Grundton und
macht es nicht einfach durchsichtig. Auf einer Taste liegt ja nichts
dahinter, es käme sonst nur dunkler an.

Als Hintergrund gibt es außerdem **Transparent**. Auf einem Dial-Segment
scheint damit das Touchstrip-Hintergrundbild der Seite durch. Auf einer
Taste bleibt es schwarz.

**Animierte Tastenbilder.** GIFs und animierte WebP/PNG laufen auf der Taste
ab, als Symbol wie als Hintergrund. Abgespielt wird nur, was sich wirklich
bewegt. Jede Kachel geht einzeln über USB zum Deck, und die Bandbreite ist
das knappste Gut dieses Geräts. Bildrate und Ein/Aus stehen in den
Einstellungen, voreingestellt sind 10 Bilder pro Sekunde. Die Anzeigedauer
kommt aus der Datei und nicht aus einer festen Rate.

**Tastenbild gestalten.** Der Knopf öffnet eine kleine Werkstatt: Bild
wählen, zoomen, verschieben, drehen, Hintergrund als Farbe, Verlauf oder
transparent, Text mit Schriftart, Größe, Farbe, Position, fett, kursiv und
Rand. Heraus kommt ein fertiges PNG mit 288 × 288 Pixeln, das du entweder
als **Tastenbild** übernimmst oder als **Symbol**. Als Tastenbild wird es
zum Hintergrund der Taste, Symbol und Beschriftung sind dann aus.

**Pegelanzeige.** *Lautstärke* und *Lautstärke setzen* aus dem Plugin
*Audio* können einen Pegel dessen zeigen, was gerade aus dem Gerät kommt.
Die Anzeige ist voreingestellt an und lässt sich in den Einstellungen der
Aktion abschalten. Gemessen wird nur, solange sie zu sehen ist.

## Bildschirmschoner und Hintergrundbild

Der **Bildschirmschoner** steht in den **Einstellungen**. Er gehört zum
ganzen Gerät. Nach einer einstellbaren Ruhezeit legt er *ein* Bild über alle
Tasten und den Touchstrip. Das Motiv rechnet die App dafür auf eine Fläche
in Geräteproportionen und zerschneidet es erst dann, damit es über die Stege
hinweg durchläuft. Die Vorschau zeigt genau das, samt der schwarzen Fugen.
Animierte GIFs laufen ab, und jede Eingabe beendet den Schoner.

Einstellen kannst du das Einpassen (*Füllen (Ränder abschneiden)* oder
*Ganz zeigen (schwarze Ränder)*), die *Helligkeit*, solange er läuft
(voreingestellt 40 %), und *Starten nach* (voreingestellt 600 Sekunden,
gezählt ab der letzten Eingabe am Deck). *Jetzt zeigen* startet ihn sofort,
damit du ihn am Gerät prüfen kannst.

Das **Hintergrundbild des Touchstrips** gehört dagegen zur *Seite*, jede kann
ein eigenes haben. Eingestellt wird es im Editor: Wähle keine Taste aus, dann
zeigen die Eigenschaften rechts die Seite. Den Abschnitt gibt es nur bei
Hardware-Decks.

Es ersetzt den Grund der Segmente überall dort, wo für das Segment kein
eigener Hintergrund gewählt ist. Gibst du einem Dial bewusst eine Farbe oder
einen Verlauf, bleibt die erhalten. Beim Einpassen gibt es dieselben zwei
Möglichkeiten wie beim Schoner. Über die Deckkraft tritt das Bild zurück,
damit Symbole und Beschriftungen lesbar bleiben.

Ein paar fertige Motive gibt es auf Zuruf:

```sh
./scripts/make-wallpapers.py     # acht Streifen, direkt in die Auswahl
```

Die Maße beim Stream Deck +: Eine Taste hat 120 × 120 Pixel, der Touchstrip
800 × 100. Ein Segment davon ist 200 × 100, dieselbe Zahl nennt auch Elgatos
SDK. Andere Modelle melden ihre eigene Tastengröße.

Beide nehmen entweder ein hochgeladenes Bild oder ein Plugin. Plugins dafür
tragen `"type": "screensaver"` oder `"type": "wallpaper"` im Manifest, erben
von `CanvasPlugin` und bekommen nur eine Leinwand. Wie das Ergebnis auf
Tasten und Segmente verteilt wird, macht die App.

## Symbol in der Leiste

Läuft das Backend, erscheint ein Symbol im Systemabschnitt der Leiste. Es
zeigt den Zustand des ersten verbundenen Hardware-Decks: farbig, wenn es
verbunden ist, blasser, wenn es abgedunkelt ist, und grau, wenn kein Gerät
verbunden ist. Es bietet:

* **Linksklick** und **Mittelklick** öffnen das Fenster der App. Ist das
  Fenster nicht installiert, öffnet sich die Oberfläche stattdessen im
  Browser.
* **Rechtsklick** öffnet ein Menü (Oberfläche öffnen, Gerät neu verbinden,
  Beenden). Neu verbunden wird ebenfalls das erste Hardware-Deck.
* **Scrollen** über dem Symbol ändert die Helligkeit dieses Decks in
  Fünferschritten zwischen 5 und 100.

Dahinter steckt ein StatusNotifierItem über D-Bus, der Standard, den KDE
Plasma, Waybar und GNOME (mit Erweiterung) verstehen. Damit braucht das
Backend weder GTK noch Qt. Gibt es keine passende Leiste oder gar keine
Sitzung, etwa auf einem Server oder im TTY, fällt das Symbol einfach weg. Die
Gerätesteuerung läuft weiter. Abschalten kannst du es mit `--no-tray`.

> **Achtung bei anderer Deck-Software.** Der Zugriff auf das Gerät ist
> exklusiv. Läuft parallel etwa StreamController oder Elgatos eigene
> Software, bekommt nur eine von beiden das Deck. Die andere meldet „kein
> Gerät verbunden". Wenn du beide installiert hast, lass nur eine automatisch
> starten.
