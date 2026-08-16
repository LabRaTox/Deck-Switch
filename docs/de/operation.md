# Bedienung

*[English version](../en/operation.md)* · Zurück zur [Übersicht](../../README.de.md).

## Editor

Links die Aktionen aller Plugins, in der Mitte das Deck in Gerätegeometrie,
rechts die Eigenschaften der ausgewählten Position.

* Aktion aus der linken Spalte auf eine Taste oder einen Dial ziehen.
* Belegungen lassen sich untereinander per Drag & Drop tauschen.
* ▶ auf einer Kachel löst die Aktion aus, ohne das Gerät anzufassen.
* Die Kachelvorschau wird vom Backend gerendert — sie zeigt exakt das, was
  auf dem Gerät steht.

## Seiten und Ordner

Beides ist dasselbe: eine Seite mit oder ohne Elternteil. Der Seitenbaum
links neben dem Deck zeigt die Zugehörigkeit: Unterseiten stehen eingerahmt
unter ihrer Seite, der Zweig der geöffneten Seite ist farbig markiert, und ↳
legt direkt eine Unterseite an. Umbenennen per Doppelklick oder F2, Zweige
mit ▾ zuklappen. Zum Springen gibt es die Aktionen des Plugins *Streamdeck*
(Ordner, Home, Zurück, Seitenanzeige, Gehe zu Seite, Nächste/Vorherige
Seite).

**Reihenfolge** — im Baum ziehen: über oder unter eine Zeile gezogen
sortiert um, mitten auf eine Zeile gezogen macht zur Unterseite. Ohne Maus
geht dasselbe mit `Alt` + `↑↓` (verschieben) und `Alt` + `←→` (aus- und
einrücken). Die Reihenfolge gilt auch am Gerät — Wischen und
Nächste/Vorherige Seite folgen ihr.

**Wischen auf dem Touchstrip** blättert zwischen den Seiten derselben Ebene:
nach links vorwärts, nach rechts zurück. Tippen bleibt dabei bei der Aktion,
die auf dem Segment liegt — nur Wischgesten gehen ans Gerät. Schwelle,
Umbruch und Abschalten stehen in den Einstellungen unter *Touchstrip*.

## Tastenlogik: Drücken, Doppeldruck, Halten

Jede Taste kann drei Aktionen tragen. Im Eigenschaften-Panel schaltet man
mit den drei Reitern dazwischen um; ein Punkt am Reiter zeigt, welcher Zweig
belegt ist.

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
neuen Seite an derselben Stelle liegt.

## Multi-Aktionen

Die Aktion *Multi-Aktion* führt mehrere Schritte nacheinander aus: Programm
starten, kurz warten, Tastenkombination schicken, Text tippen. Die Schritte
stehen als Liste in den Eigenschaften. Gefüllt wird sie wie das Deck selbst:
**Aktionen aus der linken Spalte direkt in die Liste ziehen** — abgelegt
wird vor dem Schritt, über dem der Zeiger steht, und am Ende, wer unter den
letzten zielt. Wer lieber klickt, nimmt *+ Aktion*. Sortiert wird ebenfalls
durch Ziehen oder mit `Alt` + `↑↓`.

Eine **Pause** ist ein eigener Schritt und keine Eigenschaft der Aktion
davor — so lässt sie sich verschieben, mehrfach einsetzen und einzeln
abschalten. Jeder Schritt hat einen Haken: abgeschaltete Schritte bleiben
stehen, laufen aber nicht mit. Das ist beim Suchen, welcher Schritt hakt,
mehr wert als ein Löschen.

*Wiederholen* lässt die Kette in Schleife laufen, bis erneut gedrückt wird.
Der **Umschalter** (*Multi-Aktion (Umschalter)*) hat zwei Ketten: Der erste
Druck läuft die eine ab, der nächste die andere — mit eigenem Symbol je
Richtung. Ketten in Ketten sind nicht möglich; das wäre eine Schleife, die
niemand mehr anhält.

## Dials

**Drehrichtungen belegen** — normalerweise bekommt die Aktion eines Dials
das Drehen als Delta und regelt damit stufenlos: Lautstärke, Helligkeit,
Position. Man kann aber auch **je Drehrichtung eine eigene Aktion**
hinterlegen; dann wirkt jede Drehung wie ein kurzer Druck darauf — links
„vorheriger Titel", rechts „nächster Titel". Die Reiter dafür stehen unter
*Dial-Belegung*, gleich neben *Drücken*.

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
kommt aus der Datei, nicht aus einer festen Rate.

**Tastenbild gestalten** — der Knopf öffnet eine kleine Werkstatt: Bild
wählen, zoomen, verschieben, drehen, Hintergrund als Farbe oder Verlauf,
Text mit Schriftart, Größe, Farbe, Position und Rand. Das Ergebnis ist ein
fertiges PNG (288 × 288), das entweder als **Tastenbild** (Hintergrund,
Symbol und Beschriftung aus) oder als **Symbol** übernommen wird.

## Bildschirmschoner und Hintergrundbild

Beides steht in den **Einstellungen**, nicht unter den Aktionen — es gehört
dem ganzen Gerät und keiner einzelnen Taste.

Der **Bildschirmschoner** legt nach einer einstellbaren Ruhezeit *ein* Bild
über alle Tasten und den Touchstrip. Das Motiv wird dafür auf eine Fläche in
Geräteproportionen gerechnet und erst dann zerschnitten, damit es über die
Stege hinweg durchläuft; die Vorschau zeigt genau das, samt der schwarzen
Fugen. Animierte GIFs laufen ab, jede Eingabe beendet den Schoner.

Das **Hintergrundbild des Touchstrips** gehört dagegen zur *Seite* — jede
Seite kann ein eigenes haben. Eingestellt wird es im Editor: keine Taste
auswählen, dann zeigen die Eigenschaften rechts die Seite statt einer
Belegung.

Es ersetzt den Grund der Segmente überall dort, wo für das Segment kein
eigener Hintergrund gewählt wurde. Wer einem Dial bewusst eine Farbe oder
einen Verlauf gibt, behält diese. Über die Deckkraft tritt das Bild zurück,
damit Symbole und Beschriftungen lesbar bleiben.

Ein paar fertige Motive gibt es auf Zuruf:

```sh
./scripts/make-wallpapers.py     # acht Streifen, direkt in die Auswahl
```

Maße: Eine Taste hat 120 × 120 Pixel, der Touchstrip 800 × 100 (ein Segment
davon 200 × 100 — die Zahl, die auch Elgatos SDK nennt).

Beide nehmen entweder ein hochgeladenes Bild oder ein Plugin. Plugins dafür
tragen `"type": "screensaver"` bzw. `"type": "wallpaper"` im Manifest, erben
von `CanvasPlugin` und bekommen nur eine Leinwand — wie das Ergebnis auf
Tasten und Segmente verteilt wird, ist Sache der App. `plugin-sources/
clock-saver/` ist ein vollständiges Beispiel.

## Symbol in der Leiste

Läuft das Backend, erscheint ein Symbol im Systemabschnitt der Leiste. Es
zeigt den Gerätezustand — farbig wenn verbunden, grau wenn nicht — und
bietet:

* **Linksklick** öffnet die Oberfläche
* **Rechtsklick** öffnet ein Menü (Oberfläche öffnen, Gerät neu verbinden,
  Beenden)
* **Scrollen** über dem Symbol regelt die Helligkeit des Decks

Technisch ist das ein StatusNotifierItem über D-Bus — der Standard, den KDE
Plasma, Waybar und GNOME (mit Erweiterung) verstehen. Damit braucht das
Backend weder GTK noch Qt. Gibt es keine passende Leiste oder gar keine
Sitzung (Server, TTY), entfällt das Symbol stillschweigend; die
Gerätesteuerung läuft unverändert weiter. Abschalten lässt es sich mit
`--no-tray`.

> **Achtung bei anderer Deck-Software:** Der Zugriff auf das Gerät ist
> exklusiv. Läuft parallel etwa StreamController oder Elgatos eigene
> Software, bekommt nur eine von beiden das Deck — die andere meldet „kein
> Gerät verbunden". Wer beide installiert hat, sollte nur eine automatisch
> starten lassen.
