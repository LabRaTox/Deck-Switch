# Discord einrichten

*[English version](../en/discord-setup.md)* · Zurück zur
[Übersicht](../../README.de.md) oder zu
[Store-Plugins einrichten](store-plugin-setup.md).

Das Discord-Plugin steuert den **laufenden Discord-Client** über dessen
lokale RPC-Schnittstelle. Also genau das, was man von einem Stream Deck
erwartet: das eigene Mikrofon muten, sich selbst taub schalten, den Sprach-
oder Textkanal wechseln.

Was **nicht** geht: Kamera und „Go Live" ein- und ausschalten. Discords
RPC-Schnittstelle kennt dafür keine Kommandos. Das ist keine Lücke dieses
Plugins, sondern eine der Schnittstelle.

Discord verlangt eine eigene Anwendung im Developer Portal. Das ist einmalige
Klickarbeit von wenigen Minuten. Weil du selbst Besitzer dieser Anwendung
bist, darfst du sie auch ohne Freigabe durch Discord für die RPC-Zugriffe
autorisieren.

## 1. Anwendung anlegen

1. <https://discord.com/developers/applications> öffnen
2. **New Application** → Namen vergeben (zum Beispiel „Stream Deck") →
   **Create**
3. Unter **OAuth2** die Redirect-URI `http://localhost` eintragen und
   speichern

## 2. Zugangsdaten kopieren

Auf der Seite **OAuth2**:

* **Client ID** ist die *Application-ID*
* **Client Secret** bekommst du über **Reset Secret**, dann den Wert
  kopieren

Das Plugin braucht das Secret zweimal. Einmal, um den Autorisierungs-Code
gegen ein Zugriffstoken zu tauschen, und dann bei jeder Erneuerung dieses
Tokens. Lass es deshalb in den Einstellungen stehen.

## 3. In der GUI eintragen

*Plugins → Discord → Plugin-Einstellungen*

| Feld | Wert |
| --- | --- |
| Application-ID | die Client ID |
| Client-Secret | das Client Secret |
| Redirect-URI | `http://localhost` (identisch zum Developer Portal) |
| Automatisch verbinden | an (Vorgabe): Das Plugin verbindet sich beim Start des Backends und versucht es erneut, solange Discord nicht läuft. Aus: nur über den Knopf |

**Speichern** klicken, dann **Mit Discord verbinden**.

## 4. Zugriff bestätigen

Im laufenden Discord-Client erscheint ein Dialog, der um Erlaubnis für die
Anwendung bittet. Nach dem Bestätigen ist die Verbindung fertig. Das
Zugriffstoken landet in `~/.config/deckswitch/discord-token.json` mit den
Rechten 0600 und wird von da an automatisch verwendet.

Discord stellt das Token für 7 Tage aus. Einen Tag vor Ablauf holt das
Plugin selbst ein neues, ohne dass der Dialog noch einmal erscheint. Für diese
Erneuerung braucht es das Client-Secret. Ist das Feld leer, lässt das Plugin
sie aus, und nach 7 Tagen musst du neu verbinden.

Das Token liegt mit Absicht nicht in der `config.json`. Die lässt sich
exportieren und weitergeben, und das Token soll dabei nicht mitwandern.

## Fehlersuche

**„Kein Discord-IPC-Socket gefunden"**
Der Discord-Client läuft nicht. Bei Flatpak- oder Snap-Installationen sucht
das Plugin zusätzlich in den jeweiligen Runtime-Ordnern. Findet es dort
nichts, hilft die native Installation.

**„Anmeldung fehlgeschlagen: …"**
Hinter dem Doppelpunkt folgt der Grund, den Discord nennt.

* „Client-Secret stimmt nicht mit der Application-ID überein." Das Secret
  ist falsch kopiert oder wurde im Developer Portal inzwischen zurückgesetzt.
  Kopiere das aktuelle.
* „Der Autorisierungs-Code wurde abgelehnt. Meist weicht die Redirect-URI von
  der im Developer Portal ab." Beide müssen genau übereinstimmen.
* „Die angefragten RPC-Berechtigungen wurden abgelehnt." Discord hat die
  Berechtigungen, die das Plugin anfragt, nicht erteilt.

Danach wirfst du mit **Autorisierung löschen** das gespeicherte Token weg und
verbindest erneut.

**„Discord hat die Erneuerung der Anmeldung abgelehnt. Bitte in den
Plugin-Einstellungen neu verbinden."**
Das steht im Log des Backends. Discord hat das gespeicherte Token nicht zur
Erneuerung angenommen, oder das Secret wurde inzwischen zurückgesetzt. Trag
das aktuelle Secret ein, speichere und drück **Mit Discord verbinden**.

**Tasten zeigen „nicht verbunden" (abgedunkelt)**
Das ist der normale Zustand, solange Discord nicht läuft. Ist *Automatisch
verbinden* eingeschaltet, versucht das Plugin alle paar Sekunden erneut zu
verbinden und zeichnet die Tasten neu, sobald es klappt.
