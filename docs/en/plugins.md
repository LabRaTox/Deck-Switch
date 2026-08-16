# Plugins

*[Deutsche Fassung](../de/plugins.md)* · Back to the
[overview](../../README.md).

## Built-in plugins

| Plugin | Actions |
| --- | --- |
| **Audio** | Volume (dial with bar), microphone mute (also push-to-talk), switch output device, per-app volume |
| **Multi action** | Multi action, multi action (toggle) |
| **Soundboard** | Play sound (with its own output device), stop everything |
| **OBS** | Recording (incl. pause and chapter markers), stream, replay buffer and save replay, scene collection, scene, source, mute, media playback, studio mode, push preview live, filter, screenshot, transition, virtual camera |
| **Discord** | Mute (also push-to-talk and push-to-mute), deafen, switch voice channel, leave channel, open text channel, microphone level |
| **System** | Launch and close programs, open folder/file/link, shell command, hotkey (also as toggle and as push-to-talk), type text, media keys, windows & desktops, screenshot, session (lock, log out, suspend, restart, shut down), system readings (CPU, RAM, GPU, temperatures, network), monitor brightness over DDC/CI |
| **Streamdeck** | Folder, home, back, page indicator, go to page, paging, brightness, empty (placeholder), virtual deck |

They are mandatory in substance but ordinary plugins in technique — they
merely live in `backend/plugins/` instead of
`~/.local/share/deckswitch/plugins/` and show up in the plugin list like any
other.

### Hotkey and type text

Both go through a virtual keyboard, past the compositor, straight to the
kernel (`/dev/uinput`). Under Wayland that is the only way: KWin does not
offer the protocols for injecting keys, and `xdotool` only reaches XWayland
windows.

The important part: the kernel knows no characters, only key positions.
Which character comes out is decided by the configured layout. The mapping
from character to key is therefore computed from the *actually active*
layout (libxkbcommon, read from KDE or `localectl`) — otherwise "Ctrl+Z"
would type "Ctrl+Y" on a German keyboard. Characters only reachable through
dead keys are skipped and logged; better a missing character than a
combination that triggers something else entirely.

A combination is captured with the *Record* button on the field. Whatever
the browser swallows itself (Ctrl+W closes the tab) can be typed in by hand.

### Windows & desktops

Triggers KDE's own global shortcuts — maximise, tile, move to screen 2,
switch desktop, and whatever else is registered (around 170 entries for KWin
alone in a default installation). Under Wayland that is the clean route:
moving windows from outside does not exist there, and you do not even have
to have assigned those shortcuts yourself.

### Session

Knows lock, log out, standby, hibernate, restart and shut down — each with
or without Plasma's confirmation. On top of that, **press twice** is on by
default: the first press only arms the key and shows "Sure?", the second
carries it out. An accidental shutdown would be the most expensive misfire
this device can offer.

### Media keys

Controls the player that is *currently playing* (MPRIS) — the browser when a
video runs there, the music player when music runs there. A specific player
can be pinned. If none is found, a keyboard's media key is sent instead;
then the desktop distributes it itself.

### Soundboard

Plays through `pw-play` and may pick its own **output device** per
assignment. That is exactly what a soundboard is for while streaming: the
jingle should go into the broadcast, not necessarily into your own
headphones. Optionally looping, and a second press restarts or stops.

### Audio

**Switch output device** does not just set the default sink but drags all
running streams along — otherwise music already playing would stay on the
old device.

**State from outside**: if someone changes the volume in the system
settings, OBS switches the scene or Discord mutes itself, the affected key
is redrawn immediately. `pactl subscribe` and the event channels of
obs-websocket and Discord RPC run along for that; the one-second tick is
only the safety net.

### OBS

Needs obs-websocket (built into OBS 28+, enable it under *Tools → WebSocket
Server Settings*). Host, port, password and the screenshot folder live in
the interface under *Plugins → OBS → Plugin settings*.

The feature set matches the official Elgato OBS plugin. A few specifics:

* **Source** and **filter** have dependent drop-downs — pick the scene or
  source first, then the second list fills accordingly.
* **Mute** can work as push-to-talk or push-to-mute instead of toggling.
* **On a dial**, *scene*, *transition* and *scene collection* page through
  their respective lists by turning.
* **Stream** and **recording** can be guarded against accidental stopping
  ("press twice") — for the stream that is the default.
* **Chapter markers** require OBS 30.2 or newer and hybrid MP4 as the
  recording format; otherwise a corresponding note appears.

### Discord

Needs a one-time setup, see [discord-setup.md](discord-setup.md).

**Channel keys** show the logo of the server the channel belongs to by
themselves — switchable per key, a self-chosen icon always wins. The logos
live in `~/.local/share/deckswitch/cache/discord-guilds/`.

## Installable plugins

These two are not part of the delivery, but their sources are in
[plugin-sources/](../../plugin-sources/).

| Plugin | Actions |
| --- | --- |
| **Spotify** | Playback, next/previous track, start playlist, shuffle, repeat, volume, media dial |
| **Weather** | Current weather, multi-day forecast, air quality |

**Spotify** needs no setup at all: control runs over MPRIS, the D-Bus
standard for media players on Linux — no account, no credentials, no OAuth.
Title, artist, playback, shuffle and repeat state update in real time, and
the album art can serve as the background of the dial segment.

* It controls the **locally running player**. The official Elgato version
  reaches phones or speakers through Spotify's web API — MPRIS cannot do
  that.
* The plugin works with **any MPRIS-capable player**, not just Spotify
  (configurable under *Plugins → Spotify*).

**Start playlist** needs the link to the playlist: in Spotify right-click →
*Share* → *Copy link*, then paste it into the key. There is deliberately no
drop-down of your own playlists: MPRIS knows none.

**Weather** comes from [Open-Meteo](https://open-meteo.com) — no account, no
API key. Under *Plugins → Weather*, search for a place and pick it from the
results; the data is refreshed every ten minutes.

* **Weather** shows temperature and conditions. A short press reveals the
  high and low. On a dial you turn to page through the day in three-hour
  steps, and press to switch between hourly course, temperature chart and
  detail view.
* **Forecast** shows a specific day; on a dial five days sit next to each
  other.
* **Air quality** shows the AQI with a rating, either the European or the US
  scale, and colours itself by severity.

Every assignment can get its own city through *Different location* — so home
and holiday destination sit next to each other on the deck.

## Installing plugins

> A **marketplace** for browsing and installing plugins straight from the
> app is planned. Until then the three routes below apply — and the
> `streamdeck://` link is already the interface a marketplace will hook
> into later.

Under *Plugins → Install* there are three routes:

1. **Enter an address** — a ZIP from an http(s) address
2. **Drop a file** — ZIP by drag & drop or file picker
3. **`streamdeck://` link** in the browser (see below)

Installation goes to `~/.local/share/deckswitch/plugins/`. Built-in plugins
can neither be overwritten nor removed; installed ones have a "Remove"
button in the list.

Distributable archives of the bundled sources are built by:

```sh
./scripts/package_plugins.py          # → dist/plugins/*.zip
```

### streamdeck:// links

These allow installing plugins straight from the browser:

```sh
./scripts/install-url-handler.sh     # register once
```

After that a link of the form

```
streamdeck://install?url=https://example.com/my-plugin.zip
```

leads to a **request** that has to be confirmed in the interface — including
where it came from. Clicking a link therefore installs nothing by itself.
That is deliberate: a plugin is program code running with your privileges,
and an arbitrary web page must not be able to trigger that unasked.
Unconfirmed requests expire after ten minutes.

If the backend is not running, the handler reports that via a desktop
notification instead of failing silently.

## Arranging plugins

Under *Plugins* the cards can be dragged into the desired order by their
handle (⠿). It applies to the action list in the editor as well and is saved
in the config. Newly installed plugins land at the end, so an established
arrangement does not shift by itself.

## Plugin icons

A plugin may bring its own image — `"icon": "icon.png"` in the manifest,
256 × 256 pixels. It appears **only in the plugin overview**, not in the
action library: there the same image would stand next to every action of the
same plugin, which does not help when searching. Without an icon the
overview shows a coloured field with the initial letter.

The icons of the bundled plugins are generated from accent colour and action
symbol:

```sh
./scripts/make-plugin-icons.py          # all of them
./scripts/make-plugin-icons.py audio    # just one
```

## Writing your own plugins

See [plugin-development.md](plugin-development.md). In short: a directory
under `~/.local/share/deckswitch/plugins/` with a `manifest.json` and a
Python file inheriting from `ActionPlugin`. Icon sets need nothing but a
manifest and a directory full of SVGs.
