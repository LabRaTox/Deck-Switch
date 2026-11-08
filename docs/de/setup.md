# Installation und Einrichtung

*[English version](../en/setup.md)* · Zurück zur [Übersicht](../../README.de.md).

## Mit einem Befehl (alle Distributionen)

```sh
curl -fsSL https://raw.githubusercontent.com/LabRaTox/Deck-Switch/main/scripts/get.sh | bash
```

Das holt `uv`, falls es fehlt, entpackt das neueste Release nach
`~/.local/share/deckswitch/app` und startet den Installer. Node, Rust oder ein
Compiler sind nicht nötig, Fenster und Oberfläche kommen fertig mit dem Release.
Das Passwort wird einmal abgefragt, für alles, was root braucht: fehlende
Systempakete, die udev-Regel und die Gruppe `input`. Danach läuft das Backend,
jetzt und bei jeder Anmeldung, und DECK//SWITCH steht im Anwendungsmenü. Zum
Aktualisieren denselben Befehl noch einmal ausführen, die Einstellungen bleiben.

Das Menü *Hilfe* im Fenster führt zum Repository, zur Discord-Community und zur
Seite *Über* mit der Version.

Zum Entfernen:

```sh
~/.local/share/deckswitch/app/scripts/delete.sh
```

Deine Einstellungen bleiben in `~/.config/deckswitch/`, deine Bilder und Plugins
in `~/.local/share/deckswitch/`. Mit `--all` verschwinden sie auch, nach einer
Rückfrage.

Das läuft durch auf Arch, Debian 12 und 13, Ubuntu 22.04, 24.04 und 25.04,
Fedora 42 und 43, openSUSE Tumbleweed und Leap 15.6. Auf
einem Fedora mit Image wie Bazzite nennt der Installer stattdessen den
`rpm-ostree`-Befehl, weil ein Paket dort erst mit dem nächsten Start ankommt.
Ohne `layer-shell`, etwa unter GNOME oder Ubuntu, läuft das virtuelle Deck über
XWayland, ebenfalls ohne Eintrag in der Fensterleiste und ohne den
Tastaturfokus zu nehmen.

Auf Arch und CachyOS ist das Paket weiter unten der bessere Weg, weil pacman es
dann verwaltet.

## Arch und CachyOS

Im AUR steht DECK//SWITCH noch nicht, das Paket liegt am GitHub-Release. Es legt
die udev-Regel und die systemd-Unit gleich dorthin, wo sie hingehören.

Zuerst kommt die Bibliothek für das Deck, denn die gibt es nur im AUR. Mit `paru`
oder `yay` reicht `paru -S python-elgato-streamdeck`, sonst:

```sh
git clone https://aur.archlinux.org/python-elgato-streamdeck.git
cd python-elgato-streamdeck
makepkg -si
cd ..
```

Dann das Paket laden und installieren. Mit der Adresse direkt in `pacman -U`
geht es nicht, pacman sucht dort eine Signatur:

```sh
curl -fLO https://github.com/LabRaTox/Deck-Switch/releases/download/v1.4.2/deckswitch-1.4.2-1-x86_64.pkg.tar.zst
sudo pacman -U ./deckswitch-1.4.2-1-x86_64.pkg.tar.zst
systemctl --user enable --now deckswitch.service
```

Danach einmal in die Gruppe `input` eintragen und neu anmelden. Die brauchst
du für die Aktionen *Tastenkombination* und *Text tippen*:

```sh
sudo usermod -aG input "$USER"
```

Für ein Update lädst du die neue Paketdatei und installierst sie genauso. Selbst
bauen geht auch, die Bibliothek muss dafür ebenfalls schon da sein:

```sh
git clone https://github.com/LabRaTox/Deck-Switch.git
cd Deck-Switch/packaging/aur
makepkg -si
```

## Aus dem Repo

Zum Mitentwickeln:

```sh
git clone https://github.com/LabRaTox/Deck-Switch.git
cd Deck-Switch
./scripts/install.sh
```

`install.sh` macht dasselbe wie der Einzeiler, mit einem Unterschied. Es holt
`uv` nicht. Fehlt `uv`, hält es an und nennt den Befehl, mit dem du es
installierst. Im Git-Checkout baut es das Fenster selbst, wenn `npm` und
`cargo` da sind. Mehrfach ausführen ist sicher.

| Option | |
| --- | --- |
| `--no-root` | nichts ändern, was root braucht, stattdessen ausgeben, was bleibt |
| `--no-download` | nichts vom Release nehmen, alles hier bauen |
| `--no-start` | alles installieren, den Dienst aber nicht starten |
| `--no-autostart` | jetzt starten, aber nicht bei der nächsten Anmeldung |

Die Oberfläche läuft dann unter <http://127.0.0.1:8770>, oder als eigenes
Fenster:

```sh
./scripts/start-gui.sh
```

## Gerätezugriff (udev)

Ohne udev-Regel gehört der HID-Knoten root. Das Gerät wäre dann nur als root
ansprechbar. `install.sh` richtet sie ein, von Hand geht es so:

```sh
sudo install -m 644 packaging/70-streamdeck.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules
sudo udevadm trigger --subsystem-match=usb --subsystem-match=hidraw --subsystem-match=misc
```

Danach den Stream Deck einmal ab- und wieder anstecken.

Dieselbe Regel richtet auch den Zugriff auf `/dev/uinput` ein. Darüber läuft
die virtuelle Tastatur für **Tastenkombination** und **Text tippen**. Dafür
muss dein Benutzer in der Gruppe `input` sein. `install.sh` trägt dich
ein, von Hand geht es so:

```sh
groups | grep -q input || sudo usermod -aG input "$USER"
```

Die Gruppenmitgliedschaft greift erst nach dem nächsten Anmelden. Ob es
geklappt hat, siehst du in der Oberfläche: In den Einstellungen einer
Hotkey-Aktion steht sonst im Klartext, was fehlt.

## Wenn das Fenster nicht aufgeht

Auf manchen Treibern verträgt sich WebKitGTK nicht mit Wayland, das
Fenster schließt sich nach einer halben Sekunde und im Terminal steht
`Gdk-Message: Error 71 (Protokollfehler) dispatching to Wayland display`.
Mit NVIDIA unter KDE tritt das zuverlässig auf.

Das wird abgefangen: Geht der erste Versuch sofort schief, startet das
Fenster gleich noch einmal mit abgeschaltetem DMABUF-Renderer. Zuständig
ist `packaging/deckswitch-gui.sh`, dasselbe Skript, das im Paket als
`deckswitch-gui` landet und das `scripts/start-gui.sh` im Checkout
aufruft. Aus dem Paket installiert gilt also genau dasselbe.

Passieren tut das aber nur einmal. Was dabei herauskam, notiert das Skript
zusammen mit einer Signatur des Systems in

```
~/.cache/deckswitch/fensterstart
```

Die Signatur besteht aus der Sitzungsart, der Version des NVIDIA-Kernelmoduls
(oder „ohne NVIDIA") und der WebKit-Version. Solange diese drei gleich
bleiben, startet das Fenster künftig sofort richtig, ohne den kurzen
Fehlversuch. Ändert sich eines davon, etwa nach einem Update des
NVIDIA-Treibers, wird die Notiz verworfen und neu gemessen. Ein Update von
Mesa oder vom AMD- oder Intel-Treiber ändert die Signatur nicht und fällt
nicht auf. Geschrieben wird die Notiz erst, wenn das Fenster mindestens
5 Sekunden lief. Die Datei zu löschen ist jederzeit harmlos.

Wer den Umweg von vornherein überspringen will, setzt den Schalter selbst:

```sh
export WEBKIT_DISABLE_DMABUF_RENDERER=1
```

## Im Anwendungsmenü

`install.sh` legt den Starter gleich mit an. Von Hand:

```sh
./scripts/install-desktop-entry.sh            # eintragen
./scripts/install-desktop-entry.sh --remove   # wieder entfernen
```

Eintrag und Symbol landen unter `~/.local/share`, dafür braucht es kein
sudo. Der Starter ruft `scripts/start-gui.sh` auf, das das Backend mitbringt,
falls es noch nicht läuft. Zuerst versucht es
`systemctl --user start deckswitch.service`. Nur wenn das scheitert, startet
es das Backend selbst, aus dem `.venv` des Checkouts oder als
`/usr/bin/deckswitch`. So gestartet läuft es nach dem Schließen des Fensters
weiter, bis zur Abmeldung. Der Dienst weiter unten startet es
außerdem beim Anmelden, noch bevor ein Fenster aufgeht, und nach einem
Absturz neu. Aus dem Arch-Paket kommt der Eintrag ohnehin mit.

## Beim Anmelden starten

Am einfachsten über den Schalter **Beim Anmelden starten** in den
Einstellungen. Er legt den systemd-Dienst an und schaltet ihn ein oder aus.
Dasselbe von der Kommandozeile:

```sh
./scripts/install-service.sh               # einrichten, jetzt und beim Anmelden starten
./scripts/install-service.sh --no-enable   # einrichten und starten, aber nicht beim Anmelden
./scripts/install-service.sh --remove      # wieder entfernen
```

## Sichern, wiederherstellen, weitergeben

In den Einstellungen unter **Sichern & Wiederherstellen**:

| | |
| --- | --- |
| **Belegung exportieren** | Die Konfiguration als JSON, klein und lesbar, aber ohne deine hochgeladenen Bilder |
| **Sicherungspaket** | Konfiguration *und* alle eigenen Bilder in einer ZIP-Datei. Das ist der Weg für einen Umzug oder ein echtes Backup |
| **Frühere Stände** | Vor jedem Überschreiben legt DECK//SWITCH eine Kopie der Konfiguration ab, höchstens eine je Stunde. Jede Kopie bleibt 24 Stunden liegen, danach nur noch die letzte jedes Tages, und nach 7 Tagen wird sie gelöscht. Insgesamt bleiben höchstens dreißig. Hier führt der Weg zurück |

Ein einzelnes Profil gibst du über die Profilverwaltung weiter: **Exportieren**
neben dem Profil packt es samt der Bilder, die darin vorkommen. **Profil
importieren** legt es beim Empfänger *zusätzlich* an, überschrieben wird
dabei nichts, und bei gleichem Namen bekommt es eine Nummer.

Nicht enthalten sind die Klänge des Soundboards: Die bindest du über beliebige
Pfade ein, sie liegen also irgendwo bei dir und nicht im Datenverzeichnis der
Anwendung. Die Verweise darauf überstehen eine Sicherung, die Dateien selbst
sicherst du wie deine anderen eigenen Dateien. Nachinstallierte Plugins sind
ebenfalls nicht dabei, die holst du nach dem Zurückspielen über den Store.
