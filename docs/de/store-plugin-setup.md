# Store-Plugins einrichten

*[English version](../en/store-plugin-setup.md)* · Zurück zur
[Übersicht](../../README.de.md) oder zu den [Plugins](plugins.md).

Die meisten Plugins aus dem Store funktionieren gleich nach der Installation.
Die auf dieser Seite sprechen mit einem Programm, einem Gerät oder einem
Konto, oder sie wollen vorher eine Auswahl von dir. Ihre Einstellungen liegen
auf der Karte des Plugins unter *Plugins → Plugin-Einstellungen*. Der Knopf
erscheint, solange das Plugin eingeschaltet ist. Discord, Twitch und YouTube
haben dort außerdem einen Knopf zum Verbinden.

## Discord

Braucht eine eigene Anwendung im Discord Developer Portal. Die Schritte
stehen auf einer eigenen Seite: [Discord einrichten](discord-setup.md).

Kanaltasten zeigen das Logo des Servers, zu dem der Kanal gehört. Je Taste
schaltest du das mit *Serverlogo als Icon* ab, und ein selbst gewähltes Icon
hat immer Vorrang. Die Logos liegen unter
`~/.local/share/deckswitch/cache/discord-guilds/`.

## OBS

Braucht obs-websocket, das in OBS 28 und neuer eingebaut ist. Aktivieren
kannst du es in OBS unter *Werkzeuge → WebSocket-Servereinstellungen*, dort
steht auch das Passwort.

| Feld | Wert |
| --- | --- |
| Host | `127.0.0.1` (Vorgabe) für OBS auf diesem Rechner |
| Port | `4455` (Vorgabe) |
| Passwort | das aus den WebSocket-Servereinstellungen |
| Ordner für Screenshots | wohin die Aktion *Screenshot* speichert. Wird bei Bedarf angelegt |
| Automatisch verbinden | an (Vorgabe): verbindet sich beim Start des Backends |

Kapitelmarken brauchen OBS 30.2 oder neuer und Hybrid-MP4 als
Aufnahmeformat. Sonst meldet die Taste, dass die Marke abgelehnt wurde.

## Twitch

Einzutragen gibt es nichts. Twitch will zu jedem Aufruf eine Client-ID sehen.
Die gehört zu einer registrierten App und wird mitgeliefert. Ein Geheimnis
kommt nicht vor, denn was auf fremden Rechnern liegt, wäre keins mehr.
Stattdessen der Gerätecode-Weg:

1. *Plugins → Twitch → Plugin-Einstellungen*, **Mit Twitch verbinden**
   drücken
2. Den angezeigten Code auf
   [twitch.tv/activate](https://www.twitch.tv/activate) eintippen
   (**twitch.tv/activate öffnen** öffnet die Seite)
3. Bei Twitch bestätigen. Danach steht in den Einstellungen „Verbunden als …"

Das Token liegt in `~/.config/deckswitch/twitch-token.json` und ist nur für
dich lesbar. Das Plugin erneuert es selbst. **Abmelden** entfernt es.

Gezählt wird alle 20 Sekunden nach. Twitch begrenzt die Zahl der Anfragen,
und acht Kacheln sollen nicht acht Abfragen auslösen. Ohne Verbindung steht
auf den Tasten „nicht verbunden" und keine Zahl.

Einen Stream starten kann Twitch nicht. Die Helix-API hat dafür keinen
Aufruf, denn Twitch empfängt nur, losgeschickt wird der Stream von deiner
Software. Live gehst du mit der Aktion *Stream* aus dem OBS-Plugin. Für beides
auf einer Taste legst du eine Multi-Aktion an: erster Schritt *Twitch → Titel
setzen*, zweiter Schritt *OBS → Stream*.

## YouTube

Einrichten braucht ein eigenes Google-Projekt. YouTubes Kontingent gilt je
Projekt und nicht je Benutzer: zehntausend Einheiten am Tag, geteilt von
allen, die dieselbe Kennung benutzen. Eine mitgelieferte Client-ID wäre nach
ein paar Dutzend Installationen erschöpft, und dann funktionierte das Plugin
für niemanden mehr.

So kommst du an die Zugangsdaten:

1. In der [Google Cloud Console](https://console.cloud.google.com) ein
   Projekt anlegen
2. Unter *APIs & Dienste* die **YouTube Data API v3** aktivieren
3. Unter *Anmeldedaten* einen **OAuth-Client** anlegen, Typ *Fernseher und
   Geräte mit begrenzter Eingabe*
4. Unter *OAuth-Zustimmungsbildschirm → Zielgruppe* dich selbst als
   **Testnutzer** eintragen
5. Client-ID und Client-Secret in die Plugin-Einstellungen eintragen und
   speichern
6. **Mit YouTube verbinden** drücken und den Code auf
   [google.com/device](https://www.google.com/device) eintippen

Schritt 4 wird gern übersehen. Solange die App die Überprüfung durch Google
nicht durchlaufen hat, lässt Google nur eingetragene Testnutzer hinein, auch
dich selbst nicht, obwohl du sie angelegt hast. Die Anmeldung endet dann mit
„Zugriff blockiert" und `Fehler 403: access_denied`.

Im Testmodus laufen die Anmeldungen nach sieben Tagen ab. Danach einmal neu
verbinden. Wer das nicht will, schickt die App durch Googles Überprüfung, und
für den Eigengebrauch ist das mehr Aufwand als Nutzen.

Das Secret liegt danach auf deinem Rechner. Google nennt es bei installierten
Anwendungen ausdrücklich nicht geheim. Es benennt die Anwendung und erlaubt
nichts. Das Token liegt in `~/.config/deckswitch/youtube-token.json` und ist
nur für dich lesbar. **Abmelden** entfernt es.

**Zuschauerzahl auffrischen (Sekunden).** Lesen kostet eine Einheit,
Schreiben fünfzig. Bei der Vorgabe von 30 Sekunden braucht die Zuschauerzahl
knapp 3 000 Einheiten am Tag und lässt Luft für Chat und Werbung. Auf 5
Sekunden gestellt wären es 17 000, und danach ginge bis Mitternacht nichts
mehr, auch kein Beenden des Streams. Das Feld lässt sich deshalb nicht unter
10 Sekunden stellen. Die Kacheln selbst fragen nie, sie zeichnen aus den
zuletzt geholten Werten.

Eine Sendung muss in YouTube Studio angelegt sein, bevor sie sich von hier
starten lässt. „YouTube lehnt ab (403)" heißt meist, dass das Kontingent des
Projekts für heute aufgebraucht ist oder der Kanal nicht für Livestreams
freigeschaltet ist.

## Govee

Govee gibt jedem seinen eigenen API-Schlüssel. In der Govee-Home-App unter
*Profil → Einstellungen → Apply for API Key* anfordern, er kommt per Mail.
Dann unter *Plugins → Govee → Plugin-Einstellungen* als *API-Schlüssel*
eintragen.

**Schnittstelle.** Govee betreibt zwei APIs nebeneinander, und welche bei
welchem Gerät funktioniert, lässt sich von außen nicht vorhersagen. Bei
manchen Geräten meldet die neue Werte, die sie danach selbst abweist, hält das
Gerät für offline, während die alte es schaltet, oder quittiert Befehle, ohne
dass sich etwas ändert. Deshalb wählst du selbst:

* **Alte (developer-api)**, die Vorgabe. Erprobt, kennt aber keine Szenen.
* **Neue (openapi)**. Kennt Szenen.
* **Beide, neue zuerst**. Jeder Befehl geht über beide Wege, für Geräte, bei
  denen die neue quittiert, ohne zu handeln.

Danach füllen sich die Auswahllisten von selbst. Welche Geräte da sind und
was sie können, sagt Govee.

Govee erlaubt dreißig Zustandsabfragen je Minute und Gerät. Deshalb bündelt
das Plugin sie alle 25 Sekunden, und nur für Geräte auf einer sichtbaren
Taste. Was du selbst schaltest, steht sofort auf der Kachel. Bremst Govee doch
einmal, steht das im Klartext da statt „unbekannter Fehler".

## Home Assistant

| Feld | Wert |
| --- | --- |
| Adresse | die Adresse der Weboberfläche, mit Port |
| Langlebiges Zugriffstoken | in Home Assistant unter *Profil → Sicherheit → Langlebige Zugriffstoken* anlegen |
| HTTPS-Zertifikat prüfen | an (Vorgabe). Nur bei einem selbst signierten Zertifikat abschalten |

Das Plugin braucht das Python-Paket `websockets`, das mit installiert wird.
Es verbindet sich nur mit der Adresse, die du einträgst.

## OpenRGB

OpenRGB muss selbst laufen, mit eingeschaltetem SDK-Server. Das Plugin
startet es nicht. In OpenRGB drückst du im Reiter *SDK Server* auf *Start
Server*, oder du startest es mit `openrgb --server`.

| Feld | Wert |
| --- | --- |
| Adresse | der Rechner, auf dem OpenRGB läuft, als Vorgabe `127.0.0.1` |
| Port | `6742` (Vorgabe) |

## Netzwerk

Wake on LAN und Meine IP brauchen keine Einrichtung. Die Pi-hole-Tasten
bleiben leer, bis diese Felder ausgefüllt sind:

| Feld | Wert |
| --- | --- |
| Pi-hole-Adresse | die Adresse der Weboberfläche, etwa `http://192.168.1.2` oder `https://pi.hole` |
| Passwort oder App-Passwort | Pi-hole 6: das Passwort der Weboberfläche oder ein App-Passwort aus *Einstellungen → Web-Oberfläche/API*. Pi-hole 5: das Passwort oder der API-Token aus *Einstellungen → API* |
| Pi-hole-Version | *Selbst erkennen* (Vorgabe), oder fest 5 oder 6 |
| HTTPS-Zertifikat prüfen | Pi-hole 6 bringt ein selbst signiertes Zertifikat mit. Wer es nicht ersetzt hat und `https://` nutzt, schaltet die Prüfung ab |

## Akku

Die Werte kommen aus UPower, das braucht keine Einrichtung. Headsets, die
UPower nicht kennt, kommen dazu, wenn `headsetcontrol` installiert ist.
Corsair-Geräte am Funkempfänger liefert OpenLinkHub. *Adresse von
OpenLinkHub* bleibt leer, wenn es wie üblich auf diesem Rechner unter Port
27003 läuft. Läuft es nicht, fällt diese Quelle weg.

## KI-Nutzung

Die Daten kommen von CodexBar, einem eigenen Programm, das als Dienst auf
deinem Rechner läuft (<https://github.com/steipete/CodexBar>).

| Feld | Wert |
| --- | --- |
| CodexBar-Adresse | wo `codexbar serve` läuft, als Vorgabe `http://127.0.0.1:8790` |
| Token-Datei | die Datei mit der Zeile `CODEXBAR_DASHBOARD_TOKEN=…`, dieselbe, die der CodexBar-Dienst liest. Vorgabe `~/.config/codexbar/dashboard.env`. Der Token selbst wird nirgends gespeichert |
| Aktualisierung (Sekunden) | als Vorgabe 60 |
| Warnung ab % / Kritisch ab % | als Vorgabe 70 und 90 |

Ohne CodexBar zeigt das Plugin nur Claude. *Claude direkt, wenn CodexBar
fehlt* liest den Login aus `~/.claude/.credentials.json`. Er wird nur gelesen
und nie erneuert.

## Instant Replay

Braucht das Systempaket `gpu-screen-recorder`, nach dem die Installation
fragt. Es liegt derzeit nur in den offiziellen Arch-Paketquellen. Unter
Debian, Ubuntu und Fedora bricht die Installation dieses Plugins deshalb ab.

Unter Wayland fragt das Desktop-Portal beim ersten Start einmal um Erlaubnis.
*Quelle* auf automatisch nimmt unter Wayland das Portal, sonst den ersten
Monitor. Ein Monitor unter Wayland kann beim Start nach dem Passwort fragen,
das Portal nicht.

Der Puffer liegt im Arbeitsspeicher. *Puffer in Sekunden* (Vorgabe 60) ist,
wie viel sich rückwirkend speichern lässt, und *Qualität* bestimmt, wie viel
Speicher das belegt: 60 Sekunden bei 40 MBit/s sind etwa 300 MB. Änderungen
am Puffer gelten beim nächsten Start des Replays. Clips landen im
*Zielordner*, ohne Angabe in `~/Videos`. *Beim Start der App mitstarten* ist
als Vorgabe aus, der Rekorder läuft also erst nach einem Tastendruck.

## Speed Test

Die eingebaute Messung braucht nichts weiter. Wählst du unter *Messwerkzeug*
librespeed-cli oder Ookla speedtest, müssen sie installiert sein. Ookla fragt
beim ersten Start nach seiner Lizenz, starte es dafür einmal im Terminal.

*Von selbst messen alle … Stunden* steht als Vorgabe auf 0 (aus). Eine
Messung überträgt rund 8 Sekunden lang, was die Leitung hergibt, bei 1 Gbit/s
also etwa 1 GB. Gemessen wird nur, solange eine Kachel zu sehen ist.

## Spotify

Braucht kein Konto. Die Steuerung läuft über MPRIS, den D-Bus-Standard für
Medienspieler unter Linux, und erreicht damit den Player, der auf diesem
Rechner läuft. Unter *Player* kannst du statt Spotify jeden anderen
MPRIS-fähigen Player wählen. *Lautstärke über PipeWire regeln* ist als
Vorgabe an und zuverlässiger als die spielereigene Lautstärke.

**Playlist starten** braucht den Link zur Playlist: in Spotify Rechtsklick →
*Teilen* → *Link kopieren*, dann in die Taste einfügen. Eine Auswahlliste
deiner eigenen Playlists gibt es nicht, denn MPRIS kennt keine.

## Wetter

Die Daten kommen von [Open-Meteo](https://open-meteo.com), ohne Konto und
ohne API-Schlüssel. Tipp unter *Ort suchen* eine Stadt oder Postleitzahl ein
und wähl darunter bei *Ort* den Treffer. *Einheiten* stellt zwischen °C, km/h
und °F, mph um. *Aktualisierung (Minuten)* steht als Vorgabe auf 10 und geht
von 5 bis 120.

Jede Belegung kann über *Abweichender Ort* eine eigene Stadt bekommen.

## Timer

Jede Belegung führt ihre eigene Uhr. Die Dauer des Countdowns trägst du als
`5:00` oder `1:30:00` ein. `90`, `5m` und `1h30m` versteht er auch. Zum
Zurücksetzen legst du dieselbe Aktion mit *Ein Druck → setzt zurück* auf den
Doppeldruck derselben Taste.

Der Klang ist die *Mitgelieferte Klingel*. Du kannst stattdessen eine eigene
Datei wählen (WAV, FLAC, OGG, Opus oder MP3) oder *Kein Ton*. *Ton
wiederholen* ist beim Wecker an und beim Countdown aus.

Laufende Uhren und die am Dial gedrehten Zeiten überleben einen Neustart des
Backends nicht. Danach gilt wieder, was im Formular steht.
