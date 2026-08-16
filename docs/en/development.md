# Layout, development and limits

*[Deutsche Fassung](../de/development.md)* · Back to the
[overview](../../README.md).

## Project layout

```
backend/
  deckswitch/            core: devices, runtime, rendering, HTTP/WebSocket
    config.py            data model (decks → profiles → pages → assignments)
    runtime.py           shared: config, plugins, services, device discovery
    deck.py              one deck: page, key logic, drawing, screen saver
    device.py            HID binding, reconnecting
    server.py            REST + WebSocket for the GUI (127.0.0.1 only)
    netserver.py         network decks: second, tiny application for the network
    netauth.py           passwords, sessions, brake against guessing
    virtualdeck.py       deck without hardware — images into memory, not onto USB
    plugins/base.py      plugin API (the only file plugin authors need)
    services/            audio (PipeWire), icons, rendering, backgrounds,
                         autostart, app icon, input (uinput),
                         media (MPRIS), desktop (KDE), soundboard, overlay
    web/netdeck.html     the page a network guest gets in the browser
  plugins/               bundled plugins — technically ordinary plugins
    audio/ obs/ discord/ system/ streamdeck/ multi/ sound/ iconset-tabler/
  tests/                 test suites (see below)
gui/                     Tauri + Vite/React
packaging/               udev rules, systemd unit, URL handler
  overlay/               the virtual deck as a QML overlay
plugin-sources/          sources of the installable plugins
scripts/                 setup and start (POSIX sh)
docs/                    this documentation
```

`runtime.py` and `deck.py` divide the work by a simple rule: whatever
several devices share (config, plugins, services) belongs to the runtime;
whatever belongs to a single device (current page, pressed keys, screen
saver, dial stack, running chains) belongs to the deck. Two connected decks
are therefore two sessions on the same plugins.

## User data

| Path | Content |
| --- | --- |
| `~/.config/deckswitch/config.json` | decks, profiles, assignments, settings |
| `~/.config/deckswitch/discord-token.json` | Discord access token (0600) |
| `~/.local/share/deckswitch/backups/` | earlier states of the configuration |
| `~/.local/share/deckswitch/uploads/` | your own icons and tile backgrounds |
| `~/.local/share/deckswitch/wallpapers/` | touch strip wallpapers (800 × 100) |
| `~/.local/share/deckswitch/plugins/` | installed plugins |

The two image stores are separate because an 800 × 100 strip is useless as
an icon and would only get in the way in the icon picker.

Before every write, the previous state of the configuration moves into the
backup directory (one per hour, the last 30 are kept). A layout is hours of
manual work and lives in exactly one file.

## Development

```sh
./scripts/dev.sh     # backend + Vite with hot reload (GUI on :5173)
```

The script starts the backend with `--dev`. Only then does the Vite server
count as an allowed origin — in normal operation it would be a wide open
barn door: anyone running anything on port 5173 could otherwise read the
whole interface, including the credentials in the plugin settings.

The HTTP interface is documented at <http://127.0.0.1:8770/api/docs>.

Backend log: `~/.local/share/deckswitch/deckswitch.log` (or
`journalctl --user -u deckswitch -f` with the systemd service).

### Tests

The suites under `backend/tests/` create real decks, profiles and pages.
They therefore need a configuration directory of their own — a fresh one per
suite, otherwise the next one sees the pages of the previous:

```sh
cd backend
for f in tests/*_test.py; do
    d=$(mktemp -d)
    env XDG_CONFIG_HOME=$d XDG_DATA_HOME=$d ../.venv/bin/python "$f"
done
```

Without `XDG_CONFIG_HOME` set they abort by themselves rather than
overwriting the real configuration.

### GUI

Type checking runs **only** through `npm run build` (`tsc -b`). A `tsc
--noEmit` passes without doing anything in this project, because
`tsconfig.json` is nothing but a container of project references.

### About the scripts

The scripts under `scripts/` are POSIX `sh` and **in English** — output as
well as comments. They therefore run from any shell without fish having to
be installed; tested with `sh`, `dash`, `bash`, `zsh` and `fish`.

The venv is never "activated": the scripts call `.venv/bin/python` directly,
which is independent of the shell. Activating it by hand works all the same:

| Shell | Command |
| --- | --- |
| bash, zsh, sh | `source .venv/bin/activate` |
| fish | `source .venv/bin/activate.fish` |

## On security

The server for the interface binds to `127.0.0.1` only. That protects
against the network, but not against the browser: every web page you have
open runs on the same machine. Hence three bolts:

* **CORS** restricted to a fixed list of origins instead of `*`.
* An **origin guard** in front of every modifying request — CORS alone does
  not help there, because a "simple" request goes out without a preflight
  and the browser only blocks reading the response *afterwards*.
* An **origin check on the WebSocket**. That one is needed separately:
  WebSockets are not subject to the same-origin policy, and the CORS layer
  never sees the handshake.

Without an `Origin` — command line, your own scripts — everything stays
open. The bolt is aimed at the browser, not at you.

Network decks deliberately run in a **separate application on a separate
port** that cannot change anything; details in
[decks.md](decks.md#network-deck).

What this does **not** provide: a plugin is program code with your
privileges, and an imported configuration can bring `shell command`
assignments with it. Both ask before being taken over, but what is checked
is the origin of the request, not the content.

## Known limits

* Profiles exist per deck automatically, but there is **no free switching**
  between several profiles on the same device and no automatic switch per
  foreground application ("smart profiles").
* **Push-to-talk does not mix with double press or hold** on the same key:
  assigning both inevitably moves the trigger to the release.
* **Type text** only manages characters directly reachable on the active
  layout — anything produced by dead keys is skipped.
* **No global keyboard shortcut** for summoning the overlay. The clean route
  would be `org.freedesktop.portal.GlobalShortcuts`; KDE's `kglobalaccel`
  accepts the registration but never delivers the signal (measured).
* Plugin hot reload reloads manifests and classes, but Python caches modules
  it has already imported — after changing a plugin, restarting the backend
  is the more reliable route.
* **CachyOS and Arch only.** That is a deliberate decision, not a gap:
  `setup.sh` requires `pacman`, systemd and PipeWire are taken as given.
* **DDC/CI depends on the monitor.** Brightness control needs a device that
  permits DDC/CI; many have to be unlocked in the on-screen menu first. On
  top of that `ddcutil` is slow by nature — so the value is kept locally and
  only written debounced.
* **GPU readings with NVIDIA only.** They come from `nvidia-smi`. For AMD
  cards `/sys/class/drm/…/device/hwmon` would be the way, but that is not
  built.

## About the name

**DECK//SWITCH** is the display name: window title, header, tray. The two
slashes are in the accent colour and part of the wordmark.

Technically the project is called `deckswitch`:

| | |
| --- | --- |
| systemd service | `deckswitch.service` |
| configuration | `~/.config/deckswitch/` |
| data | `~/.local/share/deckswitch/` |
| Python package | `backend/deckswitch/` |

That is the usual split — "VLC media player" is `vlc` in the terminal.
