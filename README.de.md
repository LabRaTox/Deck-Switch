# DECK//SWITCH

*[English version](README.md)*

[![Discord](https://img.shields.io/badge/Discord-Community-5865F2?logo=discord&logoColor=white)](https://discord.gg/2ckNnCZ4wq)

![Der Editor von DECK//SWITCH](docs/screenshots/editor.png)

Steuerungssoftware für das **Elgato Stream Deck** unter Linux. Ohne Elgatos
offizielle Software, mit eigenem Plugin-System und einem Store direkt in der
App.

## Wo läuft es?

**Unterstützt:** CachyOS, Arch Linux, Debian 12 und 13, Ubuntu 22.04, 24.04
und 25.04, Fedora 42 und 43, openSUSE Tumbleweed und Leap 15.6 sowie Bazzite,
jeweils x86_64.

- **Linux** mit systemd. Entwickelt und getestet mit einem **Stream Deck +**
  auf [CachyOS](https://cachyos.org/) mit KDE Plasma unter Wayland. Auf den
  anderen Distributionen ist die Installation selbst in frischen
  Docker-Images geprüft.
- **Wayland oder X11.** Die App schaut beim Start nach, was die Sitzung kann,
  und zeigt nur Aktionen an, die dort funktionieren. Was fehlt und warum,
  steht in den Einstellungen.
- **Desktops:**

| Sitzung | Virtuelles Deck | Fenster steuern |
|---|---|---|
| KDE Plasma (Wayland und X11) | ja | ja |
| Hyprland, Sway | ja | ja |
| XFCE, Cinnamon, MATE, i3 … (X11) | ja | nein |
| GNOME | ja, über XWayland | nein |

Das virtuelle Deck nimmt nie den Tastaturfokus. Fenster zu steuern braucht
eine Schnittstelle im Compositor: Plasma, Hyprland und Sway haben eine, GNOME
hat keine.

## Was kann es?

- **Tasten und Dials**: Drücken, Doppeldruck und Halten je Taste. Dials
  regeln stufenlos oder lösen je Richtung eine Aktion aus, mehrere können
  sich einen Dial teilen. Wischen über den Touchstrip blättert durch die
  Seiten.
- **Seiten und Ordner** in einem beliebig tiefen Baum, per Drag & Drop
  sortiert.
- **Multi-Aktionen** mit Pausen, einzeln abschaltbaren Schritten, Schleifen
  und einem Umschalter mit zwei Ketten.
- **Aussehen**: Symbol, Beschriftung, Verlauf, Textur oder Bild je Taste,
  auch animierte GIFs. Die Vorschau zeigt genau das, was auf dem Gerät steht.
- **Mehrere Decks** gleichzeitig, jedes mit eigenem Profil und eigener
  Helligkeit.
- **Virtuelles Deck**: ein Deck als Overlay auf dem Bildschirm, ohne Rahmen
  und ohne Eintrag in Alt-Tab, per globalem Kurzbefehl geholt.
- **Netz-Deck**: Jemand anderes im selben Netz bedient ein Deck im Browser,
  zum Beispiel der Moderator während des Streams. Passwortgeschützt, ändern
  kann der Gast nichts.
- **Bildschirmschoner und Hintergrundbilder** über alle Tasten und den
  Touchstrip.
- **Deutsch und Englisch.**

<p align="center">
  <img src="docs/screenshots/netzdeck-login.png" alt="Anmeldung am Netz-Deck" width="300">
  <img src="docs/screenshots/netzdeck.png" alt="Netz-Deck im Browser" width="300">
</p>

## Plugins

<p align="center">
  <img src="docs/screenshots/plugins.png" alt="Plugin-Übersicht mit Store-Karten" width="49%">
  <img src="docs/screenshots/store.png" alt="Ein Plugin aus dem Store" width="49%">
</p>

Audio, System, Soundboard, Multi-Aktion, Navigation und der Tabler-Iconset
sind eingebaut. Weitere kommen aus dem
[Plugin-Store](https://streamdeckstore.labratox.de), mit einem Klick unter
**Plugins**. Manche brauchen eine einmalige Einrichtung, siehe
[Store-Plugins einrichten](docs/de/store-plugin-setup.md).

- Ein Plugin bringt die Python- und Systempakete mit, die es braucht.
- Updates melden sich von selbst, **Alle aktualisieren** holt sie.
- Downloads aus dem Store werden vor der Installation gegen ihre
  SHA-256-Prüfsumme geprüft.
- Außer über den Store installiert sich ein Plugin aus einer ZIP-Datei, von
  einer Adresse oder über einen `streamdeck://`-Link im Browser. Eigene lassen
  sich im selben Fenster beim Store einreichen.

Wie man eins baut: [Eigene Plugins schreiben](docs/de/plugin-development.md).

## Wie wird es installiert?

**Jede Distribution**, mit einem Befehl. Er holt `uv`, falls es fehlt,
installiert das neueste Release und fragt einmal nach dem Passwort, für
Systempakete, die udev-Regel und die Gruppe `input`. Noch einmal ausgeführt
aktualisiert er, die Einstellungen bleiben.

```sh
curl -fsSL https://raw.githubusercontent.com/LabRaTox/Deck-Switch/main/scripts/get.sh | bash
```

**Arch und CachyOS**: die `.pkg.tar.zst` aus dem
[neuesten Release](https://github.com/LabRaTox/Deck-Switch/releases/latest)
laden, dann kommen Updates über pacman. Vorher braucht es `python-elgato-streamdeck`
aus dem AUR.

```sh
paru -S python-elgato-streamdeck
sudo pacman -U ./deckswitch-*-x86_64.pkg.tar.zst
systemctl --user enable --now deckswitch.service
sudo usermod -aG input "$USER"
```

**Aus dem Repository**, für die Entwicklung:

```sh
git clone https://github.com/LabRaTox/Deck-Switch.git
cd Deck-Switch
./scripts/install.sh
```

Danach läuft das Backend bei jeder Anmeldung und DECK//SWITCH steht im
Anwendungsmenü. Logs: `journalctl --user -u deckswitch -f`.

## Mehr

- [Installation und Einrichtung](docs/de/setup.md): der Installer im
  Einzelnen, Entfernen, udev, wenn das Fenster nicht aufgeht, Sichern und
  Wiederherstellen
- [Bedienung](docs/de/operation.md): Editor, Tastenlogik, Multi-Aktionen,
  Dials, Aussehen
- [Decks](docs/de/decks.md): mehrere Geräte, virtuelles Deck, Netz-Deck
- [Plugins](docs/de/plugins.md) und [Eigene Plugins schreiben](docs/de/plugin-development.md)
- [Store-Plugins einrichten](docs/de/store-plugin-setup.md) und
  [Discord einrichten](docs/de/discord-setup.md)
- [Aufbau und Entwicklung](docs/de/development.md): Projektstruktur, Tests,
  Sicherheit, Grenzen

Fragen, Ideen und eigene Layouts gehören auf den
[Discord-Server](https://discord.gg/2ckNnCZ4wq), Fehler und Wünsche in die
[GitHub-Issues](https://github.com/LabRaTox/Deck-Switch/issues).

Die ganze Geräteanbindung baut auf
[`python-elgato-streamdeck`](https://github.com/abcminiuser/python-elgato-streamdeck)
von Dean Camera auf.

MIT, siehe [LICENSE](LICENSE). Dieses Projekt hat nichts mit Elgato oder
Corsair zu tun. „Stream Deck" ist eine Marke der Corsair Memory, Inc.
