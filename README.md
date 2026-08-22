# DECK//SWITCH

**Control software for the Elgato Stream Deck on Linux.** No official Elgato
software needed, with its own plugin system.

*[Deutsche Fassung](README.de.md)*

Built and tested on a **Stream Deck +** running **CachyOS / Arch Linux** with
KDE Plasma on Wayland.

Other desktops work too. On startup the app checks what the running session
can do and only shows actions that will work there. If something is missing
on your system, the settings tell you what and why.

| | Virtual deck | Window control |
| --- | --- | --- |
| KDE Plasma (Wayland and X11) | yes | yes |
| Hyprland, Sway | yes | yes |
| XFCE, Cinnamon, MATE, i3 … (X11) | yes | no |
| GNOME | no | no |

The virtual deck needs `zwlr_layer_shell_v1` on Wayland and the classic
window hints on X11. Either way, a click never takes the keyboard focus.
GNOME's compositor cannot do the protocol. Window control needs an interface
in the compositor: Plasma, Hyprland and Sway have one, GNOME does not.

> The name is written **DECK//SWITCH**, with the slashes in the accent
> colour. Technically everything is called `deckswitch`: package, service,
> config directory.

![The editor](docs/screenshots/editor.png)

---

## Features

**Keys and dials**
Three actions per key: press, double press, hold. Dials either adjust
continuously or fire a separate action per rotation direction. Several
assignments can share one dial (dial stack). Swiping the touch strip pages
through your layout.

**Pages and folders**
A page tree as deep as you like, sortable by drag and drop. Folders are
simply sub-pages.

**Multi-actions**
Several steps one after another. Pauses count as their own step, every step
can be switched off individually, and the whole chain runs in a loop if you
want. There is also a toggle with two chains and its own icon per direction.

**Appearance**
Icon, label (font, weight, size, colour, alignment) and background (colour,
gradient, texture, image) for every key. Animated GIFs play on the key. For
ready-made key images there is a built-in workshop. Everything is drawn in
the backend, so the preview shows exactly what ends up on the device.

**Multiple decks**
As many devices at once as you have. Each gets its own profile, its own
brightness and its own timings, matched by serial number.

**Virtual deck**
A deck as an overlay on screen, with a grid of your choosing. No window
frame, no entry in Alt-Tab, and the keyboard focus stays where it is. You can
put it anywhere and the app remembers the spot. A **global shortcut** brings
it up from anywhere.

**Network deck**
A deck that someone else on the same network operates in a browser — your
moderator during a stream, for example. Password protected, nothing to
install, and guests cannot change anything.

<p align="center">
  <img src="docs/screenshots/netzdeck-login.png" alt="Network deck login" width="300">
  <img src="docs/screenshots/netzdeck.png" alt="Network deck in the browser" width="300">
</p>

**Screensavers and wallpapers**
One image across all keys and the touch strip, animated or still. Every page
can have its own touch strip wallpaper.

**Plugins**
Eight plugins are built in: audio, OBS, Discord, system, soundboard,
multi-action, navigation and the Tabler icon set. Three more can be installed
afterwards: Spotify, weather and a clock screensaver. For your own there is
an open API. Icon sets are plugins too.

There are four ways to install one: through the **store** inside the app,
from a ZIP file, from a URL, or through a `streamdeck://` link in the
browser.

**Plugin overview and settings**

<p align="center">
  <img src="docs/screenshots/plugins.png" alt="Plugin overview" width="49%">
  <img src="docs/screenshots/einstellungen.png" alt="Settings" width="49%">
</p>

More on all of this: [Operation](docs/en/operation.md) ·
[Decks](docs/en/decks.md) · [Plugins](docs/en/plugins.md)

---

## Installation

This is meant for **CachyOS and Arch Linux**, so `setup.sh` needs `pacman`.
On other distributions it stops and shows you the list of packages to install
yourself.

### From the AUR

The convenient way. It puts the udev rule and the systemd unit where they
belong, which is exactly the step people forget when doing it by hand.

```sh
paru -S deckswitch        # or yay, or makepkg from packaging/aur/
systemctl --user enable --now deckswitch.service
```

Then add yourself to the `input` group once and log in again. You need it for
the *hotkey* and *type text* actions:

```sh
sudo usermod -aG input "$USER"
```

### From the repository

For hacking on it, or if you want something newer than the last release:

```sh
git clone https://github.com/LabRaTox/Deck-Switch.git
cd Deck-Switch
./scripts/setup.sh          # packages, venv, GUI build, udev rule
./scripts/start-backend.sh  # start the backend
```

The interface then runs at <http://127.0.0.1:8770>, or as its own window:

```sh
./scripts/start-gui.sh
```

### Packages by hand

`setup.sh` checks for them and offers to install what is missing:

```sh
sudo pacman -S --needed python webkit2gtk-4.1 base-devel rust hidapi libusb \
    nodejs npm noto-fonts wireplumber libpulse libxkbcommon pipewire-audio \
    qt6-declarative layer-shell-qt cairo
```

### Device access (udev)

Without the udev rule the HID node belongs to root, so only root could talk
to the device. `setup.sh` offers to install it; by hand it goes like this:

```sh
sudo install -m 644 packaging/70-streamdeck.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules
sudo udevadm trigger --subsystem-match=usb --subsystem-match=hidraw
```

Then unplug the Stream Deck once and plug it back in.

The same rule also sets up access to `/dev/uinput`. That is the virtual
keyboard behind **hotkey** and **type text**. Your user needs to be in the
`input` group for it:

```sh
groups | grep -q input || sudo usermod -aG input "$USER"
```

Group membership only takes effect after your next login. You can see whether
it worked in the interface: the settings of a hotkey action spell out what is
missing.

### Start at login

The easiest way is the **Start at login** switch in the settings. It creates
the systemd service and turns it on or off. The same from the command line:

```sh
./scripts/install-service.sh            # set up
./scripts/install-service.sh --remove   # remove again
```

---

## Built on

| | |
| --- | --- |
| **Backend** | Python 3, [`streamdeck`](https://github.com/abcminiuser/python-elgato-streamdeck), FastAPI |
| **GUI** | Tauri + Vite/React, using the system WebView |
| **Audio** | PipeWire via `wpctl`/`pactl`, soundboard via `pw-play` |
| **Input** | virtual keyboard via `/dev/uinput`, layout via libxkbcommon |
| **Desktop** | MPRIS over D-Bus. Global shortcuts and screenshots via KDE, otherwise via `xdg-desktop-portal` |
| **Overlay** | `zwlr_layer_shell_v1` via layer-shell-qt, window hints on X11 |
| **Icons** | [Tabler Icons](https://tabler.io/icons) (MIT), wired in as an ordinary icon set plugin |

Without [`python-elgato-streamdeck`](https://github.com/abcminiuser/python-elgato-streamdeck)
by Dean Camera this project would not exist. All of the device handling
builds on it.

## Documentation

Everything in both languages, under [`docs/de/`](docs/de/) and
[`docs/en/`](docs/en/).

| | |
| --- | --- |
| [Operation](docs/en/operation.md) | editor, key logic, multi-actions, dials, appearance |
| [Decks](docs/en/decks.md) | multiple devices, virtual deck, network deck |
| [Plugins](docs/en/plugins.md) | built in and installable, how to install |
| [Writing plugins](docs/en/plugin-development.md) | the plugin API |
| [Discord setup](docs/en/discord-setup.md) | one-time setup |
| [Architecture and development](docs/en/development.md) | project layout, tests, security, limits |

## Licence

[MIT](LICENSE) — Heiko Stuhrmann.

The Tabler Icons are MIT licensed as well
(`backend/plugins/iconset-tabler/LICENSE`).

This project has nothing to do with Elgato or Corsair. "Stream Deck" is a
trademark of Corsair Memory, Inc.
