# Plugins

*[Deutsche Fassung](../de/plugins.md)* · Back to the [overview](../../README.md).

## Built-in plugins

| Plugin | Actions |
| --- | --- |
| **Audio** | volume (dial with bar), set volume to a fixed percentage, microphone mute (push-to-talk too), switch output device, per-app volume |
| **Multi action** | multi action, multi action (toggle) |
| **Soundboard** | play sound (with its own output device), stop everything |
| **System** | start and stop programs, open folder/file/link, shell command, hotkey (as a toggle and as push-to-talk too), type text, multimedia, windows and desktops, screenshot, session (lock, log out, suspend, restart, shut down), system values (CPU, RAM, GPU, temperatures, network), monitor brightness over DDC/CI |
| **Streamdeck** | folder, home, back, page indicator, go to page, page through, brightness, empty (placeholder), virtual deck |
| **Tabler icons** | not an action plugin, but the icon set that ships with the app |

They are required in practice but ordinary plugins technically. They live in
`backend/plugins/` rather than `~/.local/share/deckswitch/plugins/`, and in
the GUI they show up in the plugin list like any other.

### Hotkey and type text

Both go through a virtual keyboard, past the compositor and straight to the
kernel (`/dev/uinput`). On Wayland that is the only way: KWin does not offer
the protocols for injecting keys, and `xdotool` only reaches XWayland
windows.

One thing matters here. The kernel knows no characters, only key positions.
Which character comes out is decided by the active layout. So the app works
out the character → key mapping from the *actually active* layout, read
through libxkbcommon from KDE or `localectl`. Otherwise "Ctrl+Z" would type
"Ctrl+Y" on a German keyboard. Characters only reachable through dead keys
are skipped and written to the log. A missing character beats a combination
that triggers something entirely different.

You record a combination with the *record* button on the field. What the
browser catches itself (Ctrl+W closes the tab) you type in by hand.

### Windows and desktops

This triggers KDE's own global shortcuts: maximise, tile, move to screen 2,
switch desktop, and whatever else is registered. On a default installation
that is around 170 entries for KWin alone. On Wayland it is the clean way,
because moving windows from outside does not exist there. And you do not even
need to have assigned those shortcuts yourself.

### Session

Knows lock, log out, standby, hibernate, restart and shut down, each with or
without Plasma's confirmation. On top of that **press twice** is the default:
the first press only arms the key and shows "sure?", the second one runs it.
An accidental shutdown would be the most expensive misfire this device can
offer.

### Multimedia

Controls the player that is *currently playing* (MPRIS). So the browser when
a video runs there, and the music player when music runs there. You can pin a
specific player. If none is found, the multimedia key of a keyboard goes out
and the desktop distributes it itself.

### Soundboard

Plays through `pw-play` and may pick its own **output device** per
assignment. That is exactly what a soundboard is for while streaming: the
jingle should go into the broadcast, not necessarily into your own
headphones. Looping optional, and a second press restarts or stops.

### Audio

**Switch output device** does not only set the default sink, it pulls all
running streams along. Otherwise the music already playing would stay on the
old device.

**Set volume** jumps to a fixed percentage with one press — one key for
20%, one for 50%, one for 100%. A muted device is unmuted by default;
otherwise the bar would show the value while nothing could be heard. While
that value is the current one, the key gets a border. On a dial both apply:
rotating steps through the volume as usual, pressing jumps to the fixed
value.

**State from outside.** If somebody changes the volume in the system
settings, OBS switches the scene or Discord mutes itself, the affected key
redraws immediately. For that, `pactl subscribe` and the event channels of
obs-websocket and Discord RPC are running. The one-second tick is only the
safety net.

## Plugins to install afterwards

These five do not ship with the app. Their sources are in
[plugin-sources/](../../plugin-sources/) though.

| Plugin | Actions |
| --- | --- |
| **Discord** | mute (push-to-talk and push-to-mute too), deafen, switch voice channel, leave channel, open text channel, microphone level |
| **OBS** | recording (incl. pause and chapter markers), stream, replay buffer and save replay, scene collection, scene, source, mute, media playback, studio mode, push preview live, filter, screenshot, transition, virtual camera |
| **Spotify** | playback, next/previous track, start playlist, shuffle, repeat, volume, multimedia dial |
| **Weather** | current weather, multi-day forecast, air quality |
| **Clock screensaver** | screen saver: the time as one digit per key |

### Discord

Needs a one-time setup, see [discord-setup.md](discord-setup.md).

**Channel keys** show the logo of the server the channel belongs to by
themselves. You can switch that off per key, and an icon you chose yourself
always wins. The logos live in
`~/.local/share/deckswitch/cache/discord-guilds/`.

### OBS

Needs obs-websocket, built into OBS 28+. You enable it under *tools →
WebSocket server settings*. Host, port, password and the screenshot folder
are in the GUI under *plugins → OBS → plugin settings*.

The feature set matches the official Elgato OBS plugin. A few specifics:

* **Source** and **filter** have dependent dropdowns. Pick the scene or
  source first, then the second list fills accordingly.
* **Mute** can work as push-to-talk or push-to-mute instead of toggling.
* **On a dial**, *scene*, *transition* and *scene collection* page through
  their list as you turn.
* **Stream** and **recording** can be protected against accidental stopping
  ("press twice"). For the stream that is the default.
* **Chapter markers** need OBS 30.2 or newer and hybrid MP4 as the recording
  format. Otherwise you get a note.

**Spotify** needs no setup at all. Control runs over MPRIS, the D-Bus
standard for media players on Linux: no account, no credentials, no OAuth.
Title, artist, playback, shuffle and repeat state update in real time, and
the album art can serve as the background of the dial segment.

* It controls the **locally running player**. The official Elgato version
  reaches phones and speakers through Spotify's web API, which MPRIS cannot
  do.
* The plugin works with **any MPRIS-capable player**, not just Spotify. You
  set that under *plugins → Spotify*.

**Start playlist** needs the link to the playlist: in Spotify right-click →
*share* → *copy link*, then paste it into the key. There is deliberately no
dropdown of your own playlists, because MPRIS does not know any.

**Weather** comes from [Open-Meteo](https://open-meteo.com), without an
account and without an API key. Search for a place under *plugins → weather*
and pick it from the results. The plugin refreshes the data every ten
minutes.

* **Weather** shows temperature and conditions. A short press reveals today's
  high and low. On a dial you turn through the day in three-hour steps and
  press to switch between hourly view, temperature chart and details.
* **Forecast** shows a particular day, and on a dial five days sit next to
  each other.
* **Air quality** shows the AQI with a rating, European or US scale as you
  prefer, and colours itself by severity.

Every assignment can get its own city through *different location*. That way
home and holiday destination sit next to each other on the deck.

## Installing plugins

Under *plugins* the tiles from the **store** sit right next to your own. What
you do not have yet you can spot by the dashed border and the *install*
button. Before you click, you see what the store's scan found in the source.

The store comes with a GitHub sign-in. You only need it to **submit** your
own plugins; browsing and installing work without.

Next to that, *plugins → install* offers three more ways:

1. **Enter a URL** — a ZIP from an http(s) address
2. **Drop a file** — ZIP by drag and drop or file picker
3. **`streamdeck://` link** in the browser (see below)

Plugins are installed into `~/.local/share/deckswitch/plugins/`. The folders
there are named after a running number (`0001`, `0002`, …) and not after the
plugin's id. That way no archive decides what a folder on your disk is
called. Which plugin sits in which folder is in its `manifest.json`.

Built-in plugins can neither be overwritten nor removed. The ones you
installed have a *remove* button in the list.

You build distributable archives of the bundled sources like this:

```sh
./scripts/package_plugins.py          # → dist/plugins/*.zip
```

### Submitting your own plugins

*Plugins → submit plugin* opens a field you drop an archive into. ZIP, TAR
and tar.gz all work: the store accepts what it can open for review. What
ships later is always a ZIP, because that is what the installer can unpack.

The same window lists your previous submissions with their state (waiting,
approved, rejected) and the moderator's note. Every row has a button to get
rid of it again, and what that does depends on the state:

* **Waiting or rejected:** the version is deleted, its archive with it, and
  the version number is free again. Handy when you uploaded too early.
* **Approved:** it only leaves the catalogue. Anyone who already installed it
  can still download it — otherwise a fresh install would suddenly face an
  address that no longer exists.
* **Blocked:** stays where it is. A moderator decided that, and no button of
  yours changes it.

### streamdeck:// links

These let you install plugins straight from the browser:

```sh
./scripts/install-url-handler.sh     # register once
```

After that a link of this form

```
streamdeck://install?url=https://example.com/my-plugin.zip
```

creates a **request** that you confirm in the interface, including where it
came from. So clicking a link installs nothing by itself. That is deliberate:
a plugin is program code running with your rights, and no random web page may
trigger that without asking. Unconfirmed requests expire after ten minutes.

If the backend is not running, the handler says so with a desktop
notification.

## Arranging them

Under *plugins* you drag the cards by the handle (⠿) into the order you want.
It applies to the action list in the editor as well and is stored in the
config. Newly installed plugins land at the end, so an order you settled on
does not shift by itself.

## Plugin icons

A plugin may bring its own image: `"icon": "icon.png"` in the manifest,
256 × 256 pixels. It only appears in the **plugin overview** and not in the
action library. There, the same image would sit next to every action of the
same plugin, which does not help you find anything. Without an icon the
overview shows a coloured field with the first letter.

On top of that come up to three **images for the detail view** through
`"screenshots": [...]` in the manifest.

Icons and images for the bundled plugins are built from the accent colour,
the action icons and what the manifest says:

```sh
./scripts/make-plugin-icons.py          # icons, all of them
./scripts/make-plugin-icons.py audio    # just one
./scripts/make-plugin-screenshots.py    # images for the detail view
```

## Writing your own plugins

See [plugin-development.md](plugin-development.md). In short: a folder under
`~/.local/share/deckswitch/plugins/` with a `manifest.json` and a Python file
that inherits from `ActionPlugin`. Icon sets need nothing but a manifest and
a folder full of SVGs.
