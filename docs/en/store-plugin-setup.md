# Setting up store plugins

*[Deutsche Fassung](../de/store-plugin-setup.md)* · Back to the
[overview](../../README.md) or to the [plugins](plugins.md).

Most plugins from the store work right after installing. The ones on this
page talk to a program, a device or an account, or want a choice from you
first. Their settings sit on the plugin's card under *Plugins → Plugin
settings*. The button appears while the plugin is switched on. Discord, Twitch
and YouTube also have a button there to connect.

## Discord

Needs an application of your own in the Discord developer portal. The steps
are on a page of their own: [Setting up Discord](discord-setup.md).

Channel keys show the logo of the server the channel belongs to. You switch
that off per key with *Server logo as icon*, and an icon you chose yourself
always wins. The logos live in
`~/.local/share/deckswitch/cache/discord-guilds/`.

## OBS

Needs obs-websocket, built into OBS 28 and newer. You enable it in OBS under
*Tools → WebSocket Server Settings*, where you also find the password.

| Field | Value |
| --- | --- |
| Host | `127.0.0.1` (default) for OBS on this computer |
| Port | `4455` (default) |
| Password | the one from the WebSocket server settings |
| Screenshot folder | where the *Screenshot* action saves. Created if missing |
| Connect automatically | on (default): connects when the backend starts |

Chapter markers need OBS 30.2 or newer and Hybrid MP4 as the recording
format. Otherwise the key reports that the marker was rejected.

## Twitch

There is nothing to enter. Twitch wants a client ID with every call. It
belongs to a registered app and ships with the plugin. No secret is involved,
because anything that sits on other people's machines would not be one.
Instead the device code flow:

1. *Plugins → Twitch → Plugin settings*, press **Connect to Twitch**
2. Type the code shown at [twitch.tv/activate](https://www.twitch.tv/activate)
   (**Open twitch.tv/activate** opens the page)
3. Confirm at Twitch. The settings then say "Connected as …"

The token lives in `~/.config/deckswitch/twitch-token.json`, readable only by
you. The plugin renews it by itself. **Sign out** removes it.

Figures are refreshed every 20 seconds. Twitch limits how often you may ask,
and eight keys should not cause eight requests. Without a connection the keys
say "not connected" and show no number.

Twitch cannot start a stream. The Helix API has no call for it, because
Twitch only receives and the stream is sent by your own software. You go live
with the *Stream* action of the OBS plugin. For both on one key, build a
multi action: first step *Twitch → Set title*, second step *OBS → Stream*.

## YouTube

Setting up needs your own Google project. YouTube's quota is per project, not
per user: ten thousand units a day, shared by everyone using the same
credentials. A bundled client ID would be exhausted after a few dozen
installs, and then the plugin would work for nobody.

How to get the credentials:

1. Create a project in the [Google Cloud Console](https://console.cloud.google.com)
2. Under *APIs & Services*, enable the **YouTube Data API v3**
3. Under *Credentials*, create an **OAuth client** of type *TV and limited
   input device*
4. Under *OAuth consent screen → Audience*, add yourself as a **test user**
5. Enter client ID and client secret in the plugin settings and save
6. Press **Connect to YouTube** and type the code at
   [google.com/device](https://www.google.com/device)

Step 4 is easily missed. Until the app has passed Google's verification, only
registered test users may sign in, you included, although you created it.
Signing in then ends with "Access blocked" and `Error 403: access_denied`.

In testing mode sign-ins expire after seven days. Connect again after that.
Avoiding it means putting the app through Google's verification, which for
personal use is more effort than it is worth.

The secret then sits on your machine. Google explicitly does not treat it as
secret for installed applications. It names the application and grants
nothing. The token lives in `~/.config/deckswitch/youtube-token.json`,
readable only by you. **Sign out** removes it.

**Refresh viewers (seconds).** A read costs one unit, a write fifty. At the
default of 30 seconds the viewer count uses about 3,000 units a day, leaving
room for chat and ads. At 5 seconds it would be 17,000, and after that
nothing would work until midnight, not even stopping the stream. That is why
the field will not go below 10 seconds. The keys never query themselves, they
draw from the last fetched values.

A broadcast has to exist in YouTube Studio before it can be started from
here. "YouTube refuses (403)" usually means the project's quota is used up for
the day or the channel is not enabled for live streaming.

## Govee

Govee gives everyone their own API key. Request it in the Govee Home app under
*profile → settings → Apply for API Key*. It arrives by email. Enter it under
*Plugins → Govee → Plugin settings* as *API key*.

**Interface.** Govee runs two APIs side by side, and which one works with
which device cannot be told from the outside. On some devices the new one
reports values it then rejects, considers the device offline while the old
one switches it, or acknowledges commands without anything changing. So you
choose:

* **Old (developer-api)**, the default. Proven, but no scenes.
* **New (openapi)**. Knows scenes.
* **Both, new one first**. Every command goes down both paths, for devices
  where the new one acknowledges without acting.

After that the dropdowns fill themselves. Which devices exist and what they
can do comes from Govee.

Govee allows thirty state queries per minute and device. So the plugin
bundles them every 25 seconds, and only for devices on a visible key. What
you switch yourself shows on the key immediately. If Govee does throttle, the
key says so instead of "unknown error".

## Home Assistant

| Field | Value |
| --- | --- |
| Address | the address of the web interface, with port |
| Long-lived access token | created in Home Assistant under *Profile → Security → Long-lived access tokens* |
| Verify HTTPS certificate | on (default). Only switch it off for a self-signed certificate |

The plugin needs the Python package `websockets`, which installs along with
it. It only connects to the address you enter.

## OpenRGB

OpenRGB has to run on its own with its SDK server switched on. The plugin
does not start it. In OpenRGB, press *Start Server* on the *SDK Server* tab,
or start it with `openrgb --server`.

| Field | Value |
| --- | --- |
| Address | the computer running OpenRGB, `127.0.0.1` by default |
| Port | `6742` (default) |

## Network

Wake on LAN and My IP need no setup. The Pi-hole keys stay blank until you
fill in these fields:

| Field | Value |
| --- | --- |
| Pi-hole address | the address of the web interface, for example `http://192.168.1.2` or `https://pi.hole` |
| Password or app password | Pi-hole 6: the web interface password or an app password from *Settings → Web interface/API*. Pi-hole 5: the password or the API token from *Settings → API* |
| Pi-hole version | *Detect* (default), or fixed to 5 or 6 |
| Verify HTTPS certificate | Pi-hole 6 ships a self-signed certificate. If you use `https://` and have not replaced it, switch the check off |

## Battery

The values come from UPower, which needs no setup. Headsets that UPower does
not see are added if `headsetcontrol` is installed. Corsair devices on the
wireless receiver come from OpenLinkHub. Leave *OpenLinkHub address* empty if
it runs on this computer on port 27003 as usual. If it is not running, that
source is skipped.

## AI Usage

The data comes from CodexBar, a separate program that runs as a service on
your machine (<https://github.com/steipete/CodexBar>).

| Field | Value |
| --- | --- |
| CodexBar address | where `codexbar serve` runs, `http://127.0.0.1:8790` by default |
| Token file | the file with the line `CODEXBAR_DASHBOARD_TOKEN=…`, the same one the CodexBar service reads. Default `~/.config/codexbar/dashboard.env`. The token itself is never stored |
| Refresh (seconds) | 60 by default |
| Warning from % / Critical from % | 70 and 90 by default |

Without CodexBar the plugin shows only Claude. *Claude directly when CodexBar
is missing* reads the login from `~/.claude/.credentials.json`. It is only
read, never refreshed.

## Instant Replay

Needs the system package `gpu-screen-recorder`, which the installation asks
for. It is currently only in the official Arch repositories. On Debian,
Ubuntu and Fedora the installation of this plugin therefore stops.

On Wayland the desktop portal asks for permission once, on the first start.
*Source* set to automatic uses the portal on Wayland and the first monitor
otherwise. A monitor on Wayland may ask for your password on start, the
portal does not.

The buffer lives in memory. *Buffer in seconds* (60 by default) is how much
can be saved after the fact, and *Quality* decides how much memory that takes:
60 seconds at 40 Mbit/s is about 300 MB. Changes to the buffer apply the next
time the replay starts. Clips go to the *Target folder*, `~/Videos` if empty.
*Start with the app* is off by default, so the recorder only runs after a key
press.

## Speed Test

The built-in measurement needs nothing else. If you choose librespeed-cli or
Ookla speedtest under *Measuring tool*, they have to be installed. Ookla asks
about its licence on the first start, so run it once in a terminal.

*Measure by itself every … hours* is 0 (off) by default. A measurement
transfers as much as the line allows for about 8 seconds, so roughly 1 GB at
1 Gbit/s. It only runs while a tile is visible.

## Spotify

Needs no account. Control runs over MPRIS, the D-Bus standard for media
players on Linux, so it controls the player running on this computer. Under
*Player* you can pick any other MPRIS-capable player instead of Spotify.
*Adjust volume via PipeWire* is on by default and more reliable than the
player's own volume.

**Start playlist** needs the link to the playlist: in Spotify right-click →
*share* → *copy link*, then paste it into the key. There is no dropdown of
your own playlists, because MPRIS does not know any.

## Weather

The data comes from [Open-Meteo](https://open-meteo.com), without an account
and without an API key. Type a city or postal code into *Search location* and
pick the match under *Location*. *Units* switches between °C, km/h and °F,
mph. *Refresh (minutes)* is 10 by default and goes from 5 to 120.

Every assignment can get its own city through *Different location*.

## Timer

Every assignment runs its own clock. Type the countdown duration as `5:00` or
`1:30:00`. `90`, `5m` and `1h30m` work too. To reset, put the same action
with *A press → resets* on the double press of the same key.

The sound is the *Bundled bell*. You can pick your own file instead (WAV,
FLAC, OGG, Opus or MP3) or *No sound*. *Repeat the sound* is on for the alarm
clock and off for the countdown.

Running clocks and times turned on a dial do not survive a backend restart.
After that, whatever is in the form applies again.
