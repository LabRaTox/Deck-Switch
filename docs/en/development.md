# Layout, development and limits

*[Deutsche Fassung](../de/development.md)* · Back to the
[overview](../../README.md).

## Project layout

```
backend/
  pyproject.toml         Python package and its dependencies
  deckswitch/            core: devices, runtime, rendering, HTTP/WebSocket
    __main__.py          entry point, starts runtime and local server together
    config.py            data model (decks → profiles → pages → assignments)
    runtime.py           shared things: config, plugins, services, discovery
    deck.py              one deck: page, key logic, drawing, screen saver
    device.py            HID handling, reconnecting
    events.py            event bus between runtime, plugins and GUI
    paths.py             where configuration, data and bundled files live
    texte.py             texts for the interface in the chosen language
    locales/             the language files (de.json, en.json)
    server.py            REST + WebSocket for the GUI (127.0.0.1 only)
    netserver.py         network decks: second, tiny application for the LAN
    netauth.py           passwords, sessions, brake against guessing
    virtualdeck.py       deck without hardware, images go to memory
    tray.py              tray icon (StatusNotifierItem)
    plugins/base.py      plugin API (the only file plugin authors need)
    plugins/loader.py    finds, loads and registers plugins
    plugins/installer.py installs and removes plugins
    plugins/abhaengigkeiten.py  what plugins bring along: Python and system packages
    services/            audio (PipeWire), level meter, icons, rendering,
                         backgrounds, touch strip wallpaper, screen saver,
                         autostart, app icon, input (uinput), media (MPRIS),
                         desktop (KDE), soundboard, overlay, global
                         shortcuts, automatic profile switching, program
                         list, session detection, portal, backup, plugin store
    web/netdeck.html     the page a network guest gets in the browser
  plugins/               bundled plugins, ordinary ones technically
    audio/ system/ streamdeck/ multi/ sound/ iconset-tabler/
  tests/                 test suites (see below)
gui/                     Tauri + Vite/React
packaging/               udev rules, systemd units (checkout and package),
                         menu entry, window launcher (deckswitch-gui.sh),
                         URL handler
  aur/                   PKGBUILD for the Arch package
  overlay/               the virtual deck as a QML overlay
scripts/                 installation, start, removal, release files (shell),
                         helpers for images and plugin archives (Python)
docs/                    this documentation
```

`runtime.py` and `deck.py` split the work by a simple rule. What several
devices share (config, plugins, services) belongs to the runtime. What
belongs to one device (current page, pressed keys, screen saver, dial stack,
running chains) belongs to the deck. Two connected decks are therefore two
sessions on the same plugins.

## User data

| Path | Contents |
| --- | --- |
| `~/.config/deckswitch/config.json` | decks, profiles, assignments, settings |
| `~/.config/deckswitch/discord-token.json` | Discord access token (0600) |
| `~/.config/deckswitch/store-token` | sign-in for the plugin store (0600) |
| `~/.local/share/deckswitch/backups/` | earlier states of the configuration |
| `~/.local/share/deckswitch/uploads/` | your own icons and key backgrounds |
| `~/.local/share/deckswitch/wallpapers/` | touch strip wallpapers (800 × 100) |
| `~/.local/share/deckswitch/plugins/` | plugins installed afterwards |
| `~/.local/share/deckswitch/app/` | the application itself after the one-command install |
| `~/.local/share/deckswitch/deckswitch.log` | backend log |
| `~/.cache/deckswitch/fensterstart` | how the window starts on this system ([setup.md](setup.md#when-the-window-does-not-open)) |
| `~/.config/systemd/user/deckswitch.service` | service for start at login, only in a checkout or one-command install (the package brings its own) |

The two image stores are separate because an 800 × 100 strip is useless as an
icon and would only get in the way in the icon picker.

The plugin folders are named after a running number (`0001`, `0002`, …). That
way no archive decides what a folder on your disk is called. Which plugin is
inside is in its `manifest.json`. Older installations still have folders
named after the plugin id, and both forms work.

Before every write the previous state of the configuration goes into the
backup folder, at most one per hour. Every state stays for 24 hours. After
that only the last one of each day is kept, and after 7 days it is deleted.
No more than 30 states stay in total. An assignment is hours of manual work
and lives in exactly one file.

## Development

```sh
./scripts/dev.sh     # backend + Vite with hot reload (GUI on :5173)
```

The script starts the backend with `--dev`. Only then does the Vite server
count as an allowed origin. In normal operation it would be a wide open door:
anyone running something on port 5173 could otherwise read the whole
interface, credentials in the plugin settings included.

The HTTP interface is documented at <http://127.0.0.1:8770/api/docs>.

Backend log: `~/.local/share/deckswitch/deckswitch.log`, or
`journalctl --user -u deckswitch -f` with the systemd service.

### Tests

The suites under `backend/tests/` create real decks, profiles and pages. They
need a config directory of their own, and a fresh one per suite. Otherwise
the next suite sees the pages of the previous one:

```sh
cd backend
for f in tests/*_test.py; do
    d=$(mktemp -d)
    env XDG_CONFIG_HOME=$d XDG_DATA_HOME=$d ../.venv/bin/python "$f"
done
```

Without `XDG_CONFIG_HOME` set they abort by themselves and leave the real
configuration alone. `XDG_DATA_HOME` keeps backups, uploads and the log out
of your real data folder.

Suites for store plugins load the plugin from `plugin-sources/` next to
`backend/`. That folder is not part of the repository. In a fresh clone
these suites skip themselves.

`hotkey_test.py` talks to the `kglobalaccel` of the running session.
Otherwise none of it would be tested, only imitated. The suite unregisters
its shortcuts at the end and skips itself when Plasma is not running.

`store_test.py` starts a real plugin store server and runs the whole chain:
upload, catalogue, download with checksum. It needs the store's source next
to this repository. If it is missing, the suite skips itself.

### GUI

Type checking runs **only** through `npm run build` (`tsc -b`). A
`tsc --noEmit` passes without doing anything in this project, because
`tsconfig.json` is nothing but a container of project references.

### Version

The application version lives in **`backend/deckswitch/__init__.py`** and
nowhere else by hand:

* `pyproject.toml` reads it from there via `[tool.setuptools.dynamic]`.
* The server sends it as `version` in `/api/state`, and the interface shows
  the number at the bottom of the settings. That is the version of the
  **backend**: with a network deck the interface may well run on a different
  machine.
* `gui/src-tauri/tauri.conf.json` has **no** `version` field. Tauri then
  takes the number from `Cargo.toml`.
* Rust and npm cannot read the Python file. The number is repeated there, and
  `backend/tests/version_test.py` enforces that it matches.

To raise it: `__init__.py`, `gui/src-tauri/Cargo.toml`, `gui/package.json`,
then run `version_test.py`. For a release `pkgver` in `packaging/aur/PKGBUILD`
changes as well, and so does the versioned download address in the Arch
section of [setup.md](setup.md#arch-and-cachyos). The `sha256sums` in the
PKGBUILD can only be filled in once the tarball for the tag exists.

Separate from all of this are **`CONFIG_VERSION`** in `config.py` (the schema
level of the configuration, bumped only for migrations) and the **plugin
versions** in their manifests. Those belong to the respective plugin and not
to the application.

### About the scripts

The installation scripts (`get.sh`, `install.sh`, `fetch-release.sh`,
`build-release-files.sh`) need `bash`. The other shell scripts (`dev.sh`,
`start-backend.sh`, `start-gui.sh`, `delete.sh`, `install-service.sh`,
`install-desktop-entry.sh`, `install-url-handler.sh`) are POSIX `sh`. None of
them needs fish. Their output is in English, except `install-desktop-entry.sh`,
which reports in German. Some comments are in German.

Next to them are Python helpers. `make-icon.py`, `make-plugin-icons.py`,
`make-wallpapers.py` and `make-plugin-screenshots.py` generate the app icon,
plugin icons, touch strip wallpapers and plugin screenshots.
`package_plugins.py` packs plugin sources into ZIP archives.

The venv is never "activated". The scripts call `.venv/bin/python` directly,
and that is independent of the shell. Activating it by hand works all the
same:

| Shell | Command |
| --- | --- |
| bash, zsh, sh | `source .venv/bin/activate` |
| fish | `source .venv/bin/activate.fish` |

## On security

The server for the interface binds to `127.0.0.1` only. That protects against
the network but not against the browser, because every web page you have open
runs on the same machine. Hence three bolts:

* **CORS** restricted to a fixed list of origins rather than `*`.
* An **origin guard** in front of every modifying request. CORS alone does
  not help there, because a "simple" request goes out without a preflight and
  the browser only blocks reading the response *afterwards*.
* An **origin check on the WebSocket**. That one is needed separately:
  WebSockets are not subject to the same-origin policy, and the CORS layer
  never sees the handshake.

Without an `Origin`, so from the command line or your own scripts, everything
stays open. The bolt is aimed at the browser and not at you.

Network decks deliberately run in a **separate application on a separate
port** that cannot change anything. Details in
[decks.md](decks.md#network-deck).

A plugin from the **store** is checked against the checksum from the
catalogue while downloading. If it does not match, the app does not unpack it
at all.

What this does **not** provide: a plugin is program code with your
privileges, and an imported configuration can bring `shell command`
assignments with it. Both ask before being taken over, but what is checked is
the origin of the request and not the content.

## Known limits

* **Automatic profile switching only works under KDE Plasma.** A key with
  the *Switch profile* action works on every desktop. Following the
  foreground application needs a KWin script (`services/smartprofile.py`),
  because Wayland does not tell an ordinary application which window has the
  focus.
* **Push-to-talk does not mix with double press or hold** on the same key.
  Assigning both inevitably moves the trigger to the release.
* **Type text** only manages characters directly reachable on the active
  layout. Anything produced by dead keys is skipped.
* **Global shortcuts take your combination as given only under Plasma.**
  There they go through `kglobalaccel` (`services/shortcuts.py`). Elsewhere
  they go through `org.freedesktop.portal.GlobalShortcuts`
  (`services/portal.py`), if the desktop offers it. The desktop then shows a
  dialog, treats your combination as a suggestion and may assign a
  different one. The app shows the combination that really applies. When
  the list of overlay decks changes, the dialog comes again.
* **Check for new plugins** only loads plugins that are new, were removed or
  carry a new version number in the manifest. After changing a plugin's code
  without a new number, restart the backend.
* **systemd and PipeWire are taken as given.** `install.sh` knows Arch, Debian,
  Ubuntu, Fedora and openSUSE. On an image-based Fedora such as Bazzite it installs no
  packages and names the `rpm-ostree` command instead. Developed and tested on
  the device on CachyOS only, the other distributions are checked in
  containers.
* **DDC/CI depends on the monitor.** Brightness control needs a device that
  permits DDC/CI, and many have to be unlocked in the on-screen menu first.
  On top of that `ddcutil` is slow by nature, so the app keeps the value
  locally and only writes it debounced.
* **GPU readings with NVIDIA only.** They come from `nvidia-smi`. For AMD
  cards `/sys/class/drm/…/device/hwmon` would be the way, but that is not
  built.

## Built on

| | |
| --- | --- |
| **Backend** | Python 3, [`streamdeck`](https://github.com/abcminiuser/python-elgato-streamdeck), FastAPI with uvicorn |
| **Rendering** | Pillow for key images, cairosvg for SVG icons |
| **GUI** | Tauri + Vite/React, using the system WebView |
| **Audio** | PipeWire via `wpctl`/`pactl`, level meter via `parec`, soundboard via `pw-play` |
| **Input** | virtual keyboard via `/dev/uinput` with `evdev`, layout via libxkbcommon (`xkbcommon`) |
| **Desktop** | D-Bus via `dbus-next` for MPRIS, tray and KWin. Global shortcuts and screenshots via KDE, otherwise via `xdg-desktop-portal` |
| **Overlay** | `zwlr_layer_shell_v1` via layer-shell-qt, window hints on X11 and XWayland |
| **Installation** | [`uv`](https://github.com/astral-sh/uv) for the Python environment and the packages of plugins |
| **Icons** | [Tabler Icons](https://tabler.io/icons) (MIT), wired in as an ordinary icon set plugin |

Without [`python-elgato-streamdeck`](https://github.com/abcminiuser/python-elgato-streamdeck)
by Dean Camera this project would not exist. All of the device handling
builds on it.

## About the name

**DECK//SWITCH** is the display name: window title, header, tray. The two
slashes are in the accent colour and belong to the wordmark.

Technically the project is called `deckswitch`:

| | |
| --- | --- |
| systemd service | `deckswitch.service` |
| configuration | `~/.config/deckswitch/` |
| data | `~/.local/share/deckswitch/` |
| Python package | `backend/deckswitch/` |

That is the usual split. "VLC media player" is just `vlc` in the terminal.
