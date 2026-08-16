# DECK//SWITCH

**Independent control software for the Elgato Stream Deck on Linux** — no
official Elgato software required, with its own plugin system.

*[Deutsche Fassung](README.de.md)*

Built and tested against a **Stream Deck +** on **CachyOS / Arch Linux**
with KDE Plasma on Wayland.

> The name is written **DECK//SWITCH**, the slashes in the accent colour.
> Technically everything is called `deckswitch` — package, service, config
> directory.

![The editor](docs/screenshots/editor.png)

---

## Features

**Keys and dials**
Three actions per key: press, double press, hold. Dials either adjust
continuously or fire a separate action per rotation direction; several
assignments can share one dial (dial stack). Swiping the touch strip pages
through your layout.

**Pages and folders**
An arbitrarily deep page tree, sortable by drag & drop. Folders are not a
separate concept — they are simply sub-pages.

**Multi actions**
Several steps in sequence, with pauses as steps in their own right,
individually switchable, optionally looping. Plus a toggle variant with two
chains and its own icon per direction.

**Appearance**
Icon, label (font family, weight, size, colour, alignment) and background
(colour, gradient, texture, image) per key. Animated GIFs play on the key
itself. A built-in editor composes finished key images. Everything is
rendered in the backend, so the preview shows exactly what the device shows.

**Multiple decks**
Any number of devices at once, each with its own profile, brightness and
timings. Matched by serial number, so a deck keeps its layout regardless of
which USB port it lands on.

**Virtual deck**
A deck as an overlay on your screen with a freely chosen grid — no window
frame, no Alt-Tab entry, and it never steals keyboard focus. Freely
placeable; the position is remembered.

**Network deck**
A deck operated by someone else on the same network, in a browser — your
moderator during a stream, for instance. Password protected, nothing to
install, and the guest cannot change anything.

<p align="center">
  <img src="docs/screenshots/netzdeck-login.png" alt="Network deck login" width="300">
  <img src="docs/screenshots/netzdeck.png" alt="Network deck in a browser" width="300">
</p>

**Screen saver and wallpapers**
One image spanning all keys and the touch strip, animated or still; a
separate touch strip wallpaper per page.

**Plugins**
Seven built-in plugins (audio, OBS, Discord, system, soundboard, multi
action, navigation), two installable ones (Spotify, weather) and an open API
for your own. Icon sets are plugins too. Installation happens from a ZIP,
a URL or a `streamdeck://` link in the browser — a **marketplace** for
finding and installing plugins straight from the app is planned.

**Plugin overview and settings**

<p align="center">
  <img src="docs/screenshots/plugins.png" alt="Plugin overview" width="49%">
  <img src="docs/screenshots/einstellungen.png" alt="Settings" width="49%">
</p>

Details: [Operation](docs/en/operation.md) ·
[Decks](docs/en/decks.md) · [Plugins](docs/en/plugins.md)

---

## Installation

The target platform is **CachyOS and Arch Linux**. `setup.sh` therefore
requires `pacman` and stops on other distributions with a list of the needed
packages, rather than faking a detection nobody tests.

```sh
git clone https://github.com/LabRaTox/Deck-Switch.git
cd Deck-Switch
./scripts/setup.sh          # packages, venv, GUI build, udev rule
./scripts/start-backend.sh  # start the backend
```

The interface is then at <http://127.0.0.1:8770> — or as its own window:

```sh
./scripts/start-gui.sh
```

### Packages by hand

`setup.sh` checks them itself and offers to install what is missing:

```sh
sudo pacman -S --needed python webkit2gtk-4.1 base-devel rust hidapi libusb \
    nodejs npm noto-fonts wireplumber libpulse libxkbcommon pipewire-audio \
    qt6-declarative layer-shell-qt cairo
```

### Device access (udev)

Without the udev rule the HID node belongs to root, so the device would only
be reachable as root. `setup.sh` offers to install it; by hand:

```sh
sudo install -m 644 packaging/70-streamdeck.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules
sudo udevadm trigger --subsystem-match=usb --subsystem-match=hidraw
```

Then unplug and replug the Stream Deck once.

The same rule sets up access to `/dev/uinput` — the virtual keyboard behind
the **hotkey** and **type text** actions. For that your user needs to be in
the `input` group:

```sh
groups | grep -q input || sudo usermod -aG input "$USER"
```

Group membership only takes effect after the next login. Whether it works is
shown in the interface: the settings of a hotkey action spell out what is
missing.

### Start at login

Easiest via the **Start at login** switch in the settings. It writes the
systemd user unit and enables or disables it. The same from the command
line:

```sh
./scripts/install-service.sh            # install
./scripts/install-service.sh --remove   # remove again
```

---

## Built on

| | |
| --- | --- |
| **Backend** | Python 3, [`streamdeck`](https://github.com/abcminiuser/python-elgato-streamdeck), FastAPI |
| **GUI** | Tauri + Vite/React (system WebView instead of a bundled Chromium) |
| **Audio** | PipeWire via `wpctl`/`pactl`, soundboard via `pw-play` |
| **Input** | virtual keyboard via `/dev/uinput`, layout via libxkbcommon |
| **Desktop** | MPRIS and KDE's global shortcuts over D-Bus |
| **Overlay** | `zwlr_layer_shell_v1` via layer-shell-qt |
| **Icons** | [Tabler Icons](https://tabler.io/icons) (MIT), wired in as an ordinary icon set plugin |

Without [`python-elgato-streamdeck`](https://github.com/abcminiuser/python-elgato-streamdeck)
by Dean Camera this project would not exist — the entire device layer rests
on it.

## Documentation

Available in both languages — [`docs/en/`](docs/en/) and
[`docs/de/`](docs/de/).

| | |
| --- | --- |
| [Operation](docs/en/operation.md) | editor, key logic, multi actions, dials, appearance |
| [Decks](docs/en/decks.md) | multiple devices, virtual deck, network deck |
| [Plugins](docs/en/plugins.md) | built-in and installable ones, installation |
| [Writing plugins](docs/en/plugin-development.md) | the plugin API |
| [Setting up Discord](docs/en/discord-setup.md) | one-time setup |
| [Layout and development](docs/en/development.md) | project layout, tests, security, limits |

## License

[MIT](LICENSE) — Heiko Stuhrmann.

Tabler Icons are MIT licensed as well
(`backend/plugins/iconset-tabler/LICENSE`).

This project is not affiliated with Elgato or Corsair. "Stream Deck" is a
trademark of Corsair Memory, Inc.
