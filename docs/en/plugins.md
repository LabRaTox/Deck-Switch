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

These nine do not ship with the app. Their sources are in
[plugin-sources/](../../plugin-sources/) though.

| Plugin | Actions |
| --- | --- |
| **Discord** | mute (push-to-talk and push-to-mute too), deafen, switch voice channel, leave channel, open text channel, microphone level |
| **OBS** | recording (incl. pause and chapter markers), stream, replay buffer and save replay, scene collection, scene, source, mute, media playback, studio mode, push preview live, filter, screenshot, transition, virtual camera |
| **Spotify** | playback, next/previous track, start playlist, shuffle, repeat, volume, multimedia dial |
| **Weather** | current weather, multi-day forecast, air quality |
| **Clock screensaver** | screen saver: the time as one digit per key |
| **Timer** | countdown, stopwatch, alarm clock |
| **Twitch** | title, category, commercial, marker, clip, raid, chat, chat mode, clear chat, shoutout, poll, prediction, stream status, followers |
| **Govee** | on/off, brightness, colour, colour temperature, scene, every device at once |
| **YouTube** | viewers, chat message, ad, open dashboard, start and stop the stream |

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

### Timer

Three actions, and every assignment runs its own clock — two countdowns side
by side do not interfere.

**Countdown** counts down from a set time. Type the duration as `5:00` or
`1:30:00`; `90`, `5m` and `1h30m` work too. A press starts and pauses it; on
a dial, turning sets the time, even while it runs — like adding a minute on a
microwave. When the time is up it rings and the key blinks red until you
press it.

To reset, put the same action with *A press → resets* on the double press of
the same key.

**Stopwatch** counts up until you stop it. A green frame means it is
running, an amber one that it stands still — a progress bar is not possible
here, as there is nothing to count towards. Turning the dial resets it while
it stands still.

**Alarm clock** rings at a fixed time of day: every day, Monday to Friday, at
the weekend, or once. A press arms or disarms it; on a dial the time moves in
five-minute steps.

Below the time is how long until it rings, days included: looking at a
Monday-to-Friday alarm on a Saturday evening reads “in 1 day 11 h”, not “in
11 h”. A one-off alarm that has rung is over — nothing is shown there any
more, rather than promising a next day. A press arms it again.

It keeps ringing until you press the key — an alarm that beeps once and then
goes quiet wakes nobody. *Repeat the sound* turns that off. The countdown is
the other way round: it rings once, but can be set to keep going.

The sound ships with the plugin; you can pick your own file instead (WAV,
FLAC, OGG, Opus or MP3) or turn it off.

What a backend restart does not survive: running clocks and times turned on a
dial. After that, whatever is in the form applies again.

### Twitch

Fourteen actions for the things you do while streaming, without switching
away from the game.

**Signing in.** There is nothing to set up. Twitch wants a client ID with
every call; it belongs to a registered app and ships with the plugin. No
secret is involved — anything that sits on other people's machines would not
be one. Instead the device code flow: under *plugins → Twitch → plugin
settings* press *connect to Twitch*, type the code shown at
[twitch.tv/activate](https://www.twitch.tv/activate), done. The token then
lives in `~/.config/deckswitch/twitch-token.json`, readable only by you.

**Running the stream.** *Set title* puts a prepared title on a key,
optionally with a category — several keys, several titles. *Set category*
comes with a search list. Plus *commercial* (30 seconds to 3 minutes), *set
marker* for a spot you can find again in the recording, *create clip*
(optionally opening the editor afterwards) and *raid*, where a second press
cancels the countdown.

**Chat and moderation.** A prepared *chat message*, and *chat mode* for slow,
subscribers-only, followers-only, emotes-only and unique messages — the key
shows what is on and a press toggles it. Plus *clear chat* and *shoutout*.

**Polls and predictions.** Question and answers live in the assignment,
separated by a vertical bar. If a poll is already running, a press ends it.
For a prediction the first press locks betting, the next resolves it to the
outcome you set.

**Displays.** *Stream status* shows viewers, uptime or followers — you choose
what is large; a coloured strip at the bottom says live or not. *Followers*
shows just the number. Both work on a dial as well.

**What Twitch cannot do: start the stream.** The Helix API simply has no
call for it — its stream endpoints are limited to fetching the stream key,
looking up streams, setting markers and managing the schedule. That follows
from how it works: Twitch only *receives*; the stream is sent by your own
software. So you go live with the *stream* action from the OBS plugin. If
you want both on one key — set the title and go live — build a multi action:
first step *Twitch → set title*, second step *OBS → stream*.

What cannot be shown is not claimed: without a connection it says “not
connected” and no number. Figures are refreshed every 20 seconds — Twitch
limits how often you may ask, and eight keys should not cause eight
requests.

### Govee

**Setting up.** Govee gives everyone their own key: request it in the Govee
Home app under *profile → settings → Apply for API Key*, it arrives by
email. Then enter it under *plugins → Govee → plugin settings*.

**Two interfaces, one switch.** Govee runs two APIs side by side, and which
one works with which device cannot be told from the outside. On an H615C the
new one reported brightness as 154 and rejected that very value when setting
it as “out of range”; it considered the device offline while the old one
switched it fine; and it acknowledged colour commands with “success” without
anything changing. So this is a choice rather than a guess:

* **Old** (default) — `developer-api.govee.com`. Proven, but no scenes.
* **New** — `openapi.api.govee.com`. Knows scenes.
* **Both** — every command goes down both paths. For devices where the new
  one acknowledges without acting. After that
the dropdowns fill themselves — which devices exist and what they can do
comes from Govee, nothing is guessed here.

**On/off** toggles a device, or only switches on or only off if a key should
always do the same thing. The key carries a coloured border: yellow when on,
grey when off, red when the device does not answer. If a colour is lit, the
border has it.

**Brightness** sets a fixed value; on a dial you turn it in steps you choose.
**Colour** and **colour temperature** work the same way — the key shows the
colour before you press, and for white roughly the light's tint from warm to
daylight.

**Scene** calls up whatever scenes the device itself offers. The list comes
from the device; a model without scenes shows an empty one.

**All devices** is the key for the way out. Toggling means: if any light is
on, everything goes off. Toggling each device separately would leave a
half-lit room, and after that nobody knows what the next press will do.

**Govee counts requests.** Thirty state queries per minute and device — eight
keys checking every second would be blocked at once. So queries are bundled,
every 25 seconds, and only for devices currently on a visible key. What you
switch yourself shows on the key immediately, without waiting for the next
query. If Govee does throttle, it says so plainly instead of “unknown
error”.

### YouTube

Five actions for a running livestream: **viewers** shows how many are
watching. **Chat message** posts a prepared text to the live chat. **Ad**
inserts a break. **Open dashboard** jumps into YouTube Studio, straight to
the running broadcast's page if there is one. **Start/stop stream** switches
the broadcast's state — the key shows which applies.

**Setting up needs your own Google project**, and that is arithmetic rather
than red tape: YouTube's quota is per project, not per user — ten thousand
units a day, shared by everyone using the same credentials. A bundled client
ID would be exhausted after a few dozen installs, and then the plugin works
for nobody. Twitch counts per user, so one app serves everyone there; not
here.

How to get the credentials:

1. Create a project in the [Google Cloud Console](https://console.cloud.google.com)
2. Under *APIs & Services*, enable the **YouTube Data API v3**
3. Under *Credentials*, create an **OAuth client** of type *TV and limited
   input device*
4. Under *OAuth consent screen → Audience*, add yourself as a **test user**
5. Enter client ID and client secret in the plugin settings
6. Press *connect to YouTube* and type the code at
   [google.com/device](https://www.google.com/device)

Step 4 is easily missed and is where things first go wrong: until the app has
passed Google's verification, only registered test users may sign in — not
even you, although you created it. Signing in then ends with “Access blocked”
and `Error 403: access_denied`.

In testing mode sign-ins expire after seven days; just connect again after
that. Avoiding it means putting the app through Google's verification, which
for personal use is more effort than it is worth.

The secret then sits on your machine. Google explicitly does not treat it as
secret for installed applications — it names the application, it grants
nothing. The token lives in `~/.config/deckswitch/youtube-token.json`,
readable only by you.

**The quota is budgeted for.** A read costs one unit, a write fifty. The
viewer count refreshes every 30 seconds by default — about 3,000 units a day,
leaving room for chat and ads. Set to 5 seconds it would be 17,000, and
after that nothing would work until midnight, not even stopping the stream.
That is why the field will not go below 10 seconds. Drawing uses mirrored
values only; the keys themselves never query.

**What YouTube does not promise:** that every viewer sees the ad. It is
served to those currently eligible; the rest keep watching. And a broadcast
has to exist in YouTube Studio before it can be started from here.

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
