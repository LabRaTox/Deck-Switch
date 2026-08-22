# Discord einrichten

*[English version](../en/discord-setup.md)* · Zurück zur [Übersicht](../../README.de.md).

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

Das Secret brauchst du nur ein einziges Mal, nämlich um den
Autorisierungs-Code gegen ein dauerhaftes Zugriffstoken zu tauschen.

## 3. In der GUI eintragen

*Plugins → Discord → Plugin-Einstellungen*

| Feld | Wert |
| --- | --- |
| Application-ID | die Client ID |
| Client-Secret | das Client Secret |
| Redirect-URI | `http://localhost` (identisch zum Developer Portal) |

**Speichern** klicken, dann **Mit Discord verbinden**.

## 4. Zugriff bestätigen

Im laufenden Discord-Client erscheint ein Dialog, der um Erlaubnis für die
Anwendung bittet. Nach dem Bestätigen ist die Verbindung fertig. Das
Zugriffstoken landet in `~/.config/deckswitch/discord-token.json` mit den
Rechten 0600 und wird von da an automatisch verwendet.

Das Token liegt mit Absicht nicht in der `config.json`. Die lässt sich
exportieren und weitergeben, und das Token soll dabei nicht mitwandern.

## Fehlersuche

**„Kein Discord-IPC-Socket gefunden"**
Der Discord-Client läuft nicht. Bei Flatpak- oder Snap-Installationen sucht
das Plugin zusätzlich in den jeweiligen Runtime-Ordnern. Findet es dort
nichts, hilft die native Installation.

**„Anmeldung fehlgeschlagen"**
Meist stimmt die Redirect-URI im Developer Portal nicht genau mit der in den
Plugin-Einstellungen überein, oder das Secret wurde inzwischen zurückgesetzt.
Wirf mit **Autorisierung löschen** das gespeicherte Token weg und verbinde
erneut.

**Tasten zeigen „nicht verbunden" (abgedunkelt)**
Das ist der normale Zustand, solange Discord nicht läuft. Das Plugin
versucht alle paar Sekunden erneut zu verbinden und zeichnet die Tasten neu,
sobald es klappt.
