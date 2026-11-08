# Plugins

*[Deutsche Fassung](../de/plugins.md)* · Back to the [overview](../../README.md).

The built-in plugins ship with the app. Everything else comes from the store,
on the web at <https://streamdeckstore.labratox.de> and inside the app under
*Plugins*. Some store plugins need a one-time setup, see
[Setting up store plugins](store-plugin-setup.md).

## Built-in plugins

| Plugin | Actions |
| --- | --- |
| **Audio** | volume (dial with bar and level meter), set volume to a fixed percentage, microphone mute (push-to-talk too), switch output device, per-app volume |
| **Multi action** | multi action, multi action (toggle) |
| **Soundboard** | play sound (with its own output device), stop everything |
| **System** | start and stop programs, open folder/file/link, shell command, hotkey (as a toggle and as push-to-talk too), type text, multimedia, windows and desktops, screenshot, session (lock, displays off and on, suspend, hibernate, log out, restart, shut down), system values (CPU, RAM, swap, GPU, VRAM, CPU/GPU/SSD temperature, disk space, network), monitor brightness over DDC/CI |
| **Streamdeck** | folder, home, back, page indicator, go to page, page through, switch profile, brightness, empty (placeholder), virtual deck |
| **Tabler icons** | not an action plugin, but the icon set that ships with the app |

They are required in practice but ordinary plugins technically. In the source
tree they live in `backend/plugins/`, in an installed app in
`/usr/share/deckswitch/plugins/`. Never in `~/.local/share/deckswitch/plugins/`,
and in the GUI they show up in the plugin list like any other.

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

Under Plasma this triggers KDE's own global shortcuts: maximise, tile, move to
screen 2, switch desktop, and whatever else is registered. On a default
installation that is around 170 entries for KWin alone. On Wayland it is the
clean way, because moving windows from outside does not exist there. And you
do not even need to have assigned those shortcuts yourself.

Under Hyprland and Sway the action talks to the compositor directly. Neither
offers a list of named actions, so the app brings a fixed set of commands.
Both get fullscreen, close window, toggle floating, moving the window in four
directions, going to workspace 1 to 10 and moving the window there. Hyprland
adds maximise, pin and centre (both for floating windows only) and moving the
workspace to the next screen. Sway adds pin to all workspaces, toggle split
and moving the window to the next screen. On other desktops the action is not
available.

### Session

Knows lock, displays off and on, suspend, hibernate, restart, shut down and
log out. Log out, restart and shut down also come in a variant *with prompt*,
which shows Plasma's confirmation. The prompt variants and logging out
without one need Plasma's session manager. Displays off and on work under
Plasma (through `kscreen-doctor`), Hyprland and Sway.

On top of that **press twice** is the default. The first press only arms the
key and shows "Sure?", the second one runs it. An accidental shutdown would be
the most expensive misfire this device can offer.

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

**Level meter.** *Volume* and *Set volume* show what is coming out of the
device right now: from -60 to 0 dBFS, yellow from -12, red from -3, with a
white mark for the last peak. The value follows the volume control. It only
measures while the meter is visible, and the output can still go to sleep
meanwhile. Turn it off per assignment with the *Level meter* switch. While
muted it stays empty.

**Switch output device** does not only set the default sink, it pulls all
running streams along. Otherwise the music already playing would stay on the
old device. If you only want new playback on the new device, switch off *Move
running streams* in the assignment.

**Set volume** jumps to a fixed percentage with one press. One key for 20%,
one for 50%, one for 100%. A muted device is unmuted by default (*Unmute when
set*). Otherwise the bar would show the value while nothing could be heard.
While that value is the current one, the key gets a border. On a dial both
apply: rotating steps through the volume as usual, pressing jumps to the
fixed value.

**State from outside.** If somebody changes the volume in the system
settings, OBS switches the scene or Discord mutes itself, the affected key
redraws immediately. For that, `pactl subscribe` and the event channels of
obs-websocket and Discord RPC are running. The one-second tick is only the
safety net.

## What your session cannot do

An action or an option can depend on something the desktop has to provide,
for example window control or the session manager. A plugin declares that in
its manifest (`requires`). If your session lacks it, the action is missing
from the action library. On a key that already has it, the inspector says
"Has no effect in this session" with the reason. Options in a dropdown work
the same way: they disappear, except the one already chosen, which stays
marked "(has no effect in this session)".

## The plugin list

Under *Plugins* the installed plugins and the tiles from the store sit in one
list. At the top you choose the type (*Plugins*, *Icons*, *Screensavers*,
*Wallpapers*), on the left a category, *All* or *Installed*. The numbers next
to them count what the search field (*Search plugins*) leaves over, so you see
where the matches are even under another tab. *Sort* orders the list *A to Z*,
*Z to A*, *Newest first* or *Best rated*.

Clicking a plugin's name opens its detail page. There the author's name is a
link. A click filters the list to that author's plugins, and a chip *Only by …*
above the list brings everything back. Built-in plugins have no such link.

Every installed plugin has a switch that turns it on and off. *Plugin
settings* appears while it is on and the plugin has settings. Built-in plugins
carry the *Built in* badge. The others have a *Remove* button. Removing asks
first, because assignments using that plugin are deleted along with it.

*Check for new plugins* picks up what has been added on disk and refreshes the
store catalogue. Running plugins are left alone.

### Updates

If the store has a newer version of an installed plugin, its card gets a
button with the new version number. With several of them a bar above the list
offers *Update all*. A version that needs a newer app cannot be installed: the
button stays disabled and says "Needs DECK//SWITCH … or newer". The installer
refuses such a plugin from every other source as well.

## Installing plugins

Tiles from the **store** have a dashed border and an *Install* button. Before
you click, you see what the store's scan found in the source, on the tile and
on the detail page.

The store checks every download. The catalogue names a SHA-256 checksum for
each version, and the archive is only unpacked if it matches. If the catalogue
names none, nothing is installed. The plugin ID in the archive also has to
match the plugin you asked for.

The store comes with a GitHub sign-in (*Sign in to the store*). You need it
to **submit** your own plugins and to **rate**. Browsing and installing work
without.

Next to that, *Install plugins* offers two more ways, plus links from the
browser:

1. **Install from a URL**: a ZIP from an http(s) address
2. **Drop a plugin archive (.zip) here, or click**: a ZIP by drag and drop or
   file picker
3. **`streamdeck://` link** in the browser (see below)

Plugins are installed into `~/.local/share/deckswitch/plugins/`. The folders
there are named after a running number (`0001`, `0002`, …) and not after the
plugin's id. That way no archive decides what a folder on your disk is
called. Which plugin sits in which folder is in its `manifest.json`.

If a plugin brings dependencies, they show on its detail page and install
along with it. Python packages come from PyPI through `uv`, only as
ready-made wheels, into a folder of their own per plugin under
`~/.local/share/deckswitch/plugins/.deps/`. They leave with the plugin. System
packages are named per distribution family (Arch, Debian and Ubuntu, Fedora, openSUSE),
and the system asks for your password. On an image-based Fedora such as
Bazzite a package only arrives with the next boot, so there it is always a
manual step. If something cannot be installed, the plugin stays out and the
message names the command.

Built-in plugins can neither be overwritten nor removed.

### The store detail page

Next to the description and *What's new* the detail page lists the
*Versions* once there is more than one, with date, downloads, the state if
it is not approved, and the moderator's note. Under *Rating* you recommend a
plugin or not, and you can add a text of up to 500 characters. A thumbs down
needs a short note on what is wrong. Your own plugins you cannot rate. The
detail page of an installed plugin from the store shows the rating too.

### Submitting your own plugins

*Submit a plugin* opens a field you drop an archive into. ZIP, TAR, tar.gz
and tgz all work: the store accepts what it can open for review. What ships
later is always a ZIP, because that is what the installer can unpack.

The same window lists your previous submissions with their state (*awaiting
review*, *approved*, *rejected*, *withdrawn*, *blocked*) and the moderator's
note. Versions awaiting review, rejected or approved have a button, and what
it does depends on the state:

* **Awaiting review or rejected:** *Delete*. The version is deleted, its
  archive with it, and the version number is free again. Handy when you
  uploaded too early.
* **Approved:** *Withdraw*. It only leaves the catalogue. Anyone who already
  installed it can still download it. Otherwise a fresh install would suddenly
  face an address that no longer exists.

Withdrawn and blocked versions have no button. A block was decided by a
moderator, and nothing you click changes it.

### streamdeck:// links

These let you install plugins straight from the browser. The installer and
the AUR package register the handler. Only in a bare source checkout do you
register it yourself:

```sh
./scripts/install-url-handler.sh     # register once
```

After that a link of this form

```
streamdeck://install?url=https://example.com/my-plugin.zip
```

creates a **request** that you confirm in the interface, including the
address it came from. So clicking a link installs nothing by itself. That is
deliberate: a plugin is program code running with your rights, and no random
web page may trigger that without asking. Unconfirmed requests expire after
ten minutes.

A link can carry the expected checksum as `&sha256=…`. The request then shows
"Announced checksum: …", and the archive is only unpacked if it matches.
Without it the request says "No checksum: whatever is at that address will
be installed."

If the backend is not running, the handler says so with a desktop
notification.

## Arranging them

In the editor's action library you drag the plugins by the handle (⠿) into
the order you want. The handle is hidden while you search. The order is
stored in the config. Newly installed plugins land at the end, so an order you
settled on does not shift by itself.

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
