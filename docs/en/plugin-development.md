# Writing your own plugins

*[Deutsche Fassung](../de/plugin-development.md)* · Back to the
[overview](../../README.md).

There are four kinds, and the manifest field `type` says which one a plugin
is. **Action plugins** (`action`) drive keys, dials and touch strip
segments. **Icon set plugins** (`iconset`) merely supply SVGs for the icon
picker. **Screensaver plugins** (`screensaver`) paint the whole deck while
the screensaver runs, **wallpaper plugins** (`wallpaper`) paint the
background of the touch strip. The last two do not appear in the action
library, you choose them in the settings.

Plugins live in `~/.local/share/deckswitch/plugins/`. Every folder there
carries a running number, and which plugin is inside is in its
`manifest.json`. The bundled plugins under `backend/plugins/` are built
identically and serve well as templates.

---

## Icon

A plugin may bring an image representing it in the overview:

```json
{ "icon": "icon.png" }
```

256 × 256 pixels, PNG (JPEG, WebP or SVG work too). The file lives in the
plugin directory, and paths pointing outside are rejected by the backend. The
icon appears only in the plugin list and not next to the actions.

On top of that you can give up to three images for the detail view:

```json
{ "screenshots": ["screenshots/deck.png", "screenshots/actions.png"] }
```

Screenshots must be PNG, JPEG or WebP, SVG is not accepted here. With more
than three entries the manifest is invalid and the plugin does not load.

## Action plugin

A minimal example: a plugin with one action that counts up.

```
my-counter/
├── manifest.json
└── plugin.py
```

### manifest.json

```json
{
  "id": "my-counter",
  "name": { "de": "Zähler", "en": "Counter" },
  "version": "1.0.0",
  "type": "action",
  "entry": "plugin.py",
  "class": "CounterPlugin",
  "accent": "#8b5cf6",
  "actions": [
    {
      "id": "count",
      "name": { "de": "Zähler", "en": "Counter" },
      "inputs": ["key", "dial"],
      "default_icon": "number-123",
      "states": [
        { "id": "zero", "name": { "de": "Null", "en": "Zero" } },
        { "id": "counting", "name": { "de": "Zählt", "en": "Counting" } }
      ],
      "settings_schema": [
        {
          "key": "step",
          "type": "number",
          "label": { "de": "Schrittweite", "en": "Step size" },
          "default": 1,
          "min": 1,
          "max": 100
        }
      ]
    }
  ]
}
```

The `settings_schema` matters: **the interface builds its form from that
alone**. A plugin does not have to add anything on the GUI side.

Field types: `text`, `number`, `bool`, `select`, `color`, `path`, `file`,
`hotkey` (a capture field for key combinations), `password`. For `select`
either give fixed `options` or have them filled at runtime through
`options_source` (see below).

A field can carry more than key, type, label and default. `placeholder`
shows a hint in the empty input, `help` an explanation for the field. Both
may be bilingual like `label`. `min`, `max` and `step` limit a `number`
field. `depends_on` shows the field only when other fields have a certain
value, a list there means one of several values:

```json
{
  "key": "interface",
  "type": "select",
  "options_source": "interfaces",
  "depends_on": { "metric": ["net_down", "net_up"] }
}
```

### More manifest fields

These fields apply to every type:

| Field | Meaning |
| --- | --- |
| `description` | full description in the detail view, bilingual if you like |
| `summary` | one sentence for the plugin list. Without it the list shows the description, cut to two lines |
| `author` | who wrote the plugin |
| `category` | where the plugin goes in the overview, default `other` |
| `support` | address for questions and bug reports, shown under *Support* |
| `changelog` | what changed last, shown under *What's new* |
| `license` | licence note, shown in the detail view |
| `accent` | colour of the plugin in the action library and the plugin list |

Allowed values for `category`: `system`, `audio`, `business`, `creative`,
`development`, `engagement`, `finance`, `gaming`, `lighting`, `monitoring`,
`music`, `productivity`, `screensaver`, `smarthome`, `social`, `streaming`,
`utilities`, `video`, `other`. Any other value makes the manifest invalid,
and the plugin does not load.

An action knows these fields besides `id`, `name`, `inputs`,
`default_icon`, `states` and `settings_schema`:

* `description` appears with the action in the library.
* `default_label` is filled in as the label when the action is dropped on a
  key.
* `states[].default_icon` is the icon for one state, as long as the user has
  not picked one. Without it the action's `default_icon` applies.
* `requires` lists what the session has to offer for the action to work.
  If one of them is missing, the action does not appear in the library, and
  a key that already carries it shows the reason. Unknown names count as
  available. The names are `keyboard_input`, `window_control`,
  `global_shortcuts`, `screenshot`, `screen_power`, `session_power`,
  `session_manager`, `overlay`, `ddc`, `audio`, `sound_playback`, `tray`,
  `open_uri` and `process_control`. An entry in a field's `options` can
  carry `requires` as well, the interface then marks only that entry.

### plugin.py

```python
from deckswitch.plugins.base import ActionPlugin


class CounterPlugin(ActionPlugin):
    def on_key_down(self, action_id, settings, ctx):
        step = int(ctx.setting("step", 1))
        ctx.scratch["value"] = ctx.scratch.get("value", 0) + step
        # No request_redraw needed: after every input a redraw happens
        # anyway. For changes *from outside* it would be mandatory.

    def on_dial_rotate(self, action_id, settings, delta, ctx):
        step = int(ctx.setting("step", 1))
        ctx.scratch["value"] = ctx.scratch.get("value", 0) + delta * step

    def get_state(self, action_id, settings, ctx):
        return "zero" if ctx.scratch.get("value", 0) == 0 else "counting"

    def get_label(self, action_id, settings, ctx):
        return str(ctx.scratch.get("value", 0))
```

That is all. Drawing goes through the shared layout: background, icon
(matching the state), label underneath. Icon, sizes, colours and background
are set by the user in the interface, without the plugin doing anything for
it.

## The hooks

All of them are optional. Not every hook may be `async def`, the right
column says which form the app expects.

| Hook | When | Form |
| --- | --- | --- |
| `on_key_down(action_id, settings, ctx)` | key pressed | `def` or `async def` |
| `on_key_up(action_id, settings, ctx)` | key released | `def` or `async def` |
| `on_dial_rotate(action_id, settings, delta, ctx)` | dial turned (`delta` ±) | `def` or `async def` |
| `on_dial_push(action_id, settings, ctx)` | dial pressed | `def` or `async def` |
| `on_touch(action_id, settings, x, y, ctx)` | touch strip touched (segment-relative) | `def` or `async def` |
| `on_tick(action_id, settings, ctx)` | periodically, once per second by default | `def` or `async def` |
| `render(action_id, settings, ctx)` | draw your own image | `def` or `async def` |
| `get_dynamic_options(source, context)` | fill drop-downs at runtime | `def` or `async def` |
| `get_state(action_id, settings, ctx)` | which state applies right now | `def` |
| `get_label(action_id, settings, ctx)` | dynamic text instead of the configured one | `def` |
| `get_status()` | connection state for the plugin list | `def` |
| `on_plugin_config_changed(config)` | global plugin settings changed | `def` |
| `setup()` / `teardown()` | on load/shutdown (open/close connections) | `async def` |
| `gui_command(command, payload)` | an action the interface triggers directly | `async def` |

Hooks marked `def` or `async def` run in a worker thread when they are
synchronous, so a `subprocess.run` never blocks the application. As
`async def` they run in the event loop and must not block it.

The app calls the plain `def` hooks directly and does not await them. They
should answer at once from state the plugin already holds. `get_state` and
`get_label` are called by the standard `render`. If you override `render`,
you decide yourself whether and how you use them.

`setup()`, `teardown()` and `gui_command()` are awaited. A plain `def`
there fails.

One trap: a **synchronous** hook runs in a worker thread, and there is no
event loop there, so `asyncio.create_task` fails with "no running event
loop". Two ways out:

* declare the hook as `async def` where the table allows it (then it runs
  in the loop), or
* use `self.run_async(coro)`. That helper works from any thread, including
  your own watcher threads and the plain `def` hooks.

### Showing connection state

Plugins depending on something external report their state to the interface,
where it appears as a green or grey dot in the plugin list:

```python
def get_status(self):
    if self.connected:
        return {"connected": True, "detail": f"{self.host} · {len(self.scenes)} scenes"}
    return {"connected": False, "detail": "unreachable"}

# Report on every change (thread-safe):
self.services.runtime.publish_plugin_status(self.manifest.id)
```

If there is no connection to speak of, just leave `get_status` out. The
interface then shows nothing there.

### The context (`ctx`)

The same action can be assigned several times, one key per output device
say. The `ctx` tells you which assignment is up:

* `ctx.index`, `ctx.input_type` (`"key"`/`"dial"`), `ctx.page_id`,
  `ctx.profile_id`
* `ctx.key` is a stable name for the assignment (page, input type, index),
  for example as `owner` for the soundboard
* `ctx.size` is the drawing area: on a Stream Deck + `(120, 120)` for keys
  and `(200, 100)` per segment. Virtual decks can use other sizes
* `ctx.setting(name, default)` gets a setting with a fallback
* `ctx.slot` is the whole assignment, `ctx.appearance` its look
  (background, icon, label)
* `ctx.is_long_press` is `True` when the hold branch of a key fires
* `ctx.scratch` is free scratch space and survives between calls
* `ctx.request_redraw()` redraws exactly this tile immediately
* `ctx.services` are audio, icons, rendering, runtime and the system services
* `ctx.deck_serial` says which deck the assignment sits on
* `ctx.frame_time` is the runtime in seconds, animated images pick their
  frame from it

Press, double press and hold of one key are separate assignments, and each
gets its own `ctx.scratch`. What the press branch stores there, the hold
branch does not see.

**Important with several decks:** `ctx.services.runtime` points at *the deck
the press happened on*. Navigating through `self.services.runtime` lands on
the primary deck instead. With a single device that is the same thing, with
two it is wrong. Rule of thumb: anything to do with an assignment goes
through `ctx.services.runtime`; everything else (reporting errors, saving
the config) may go through `self.services.runtime`.

## State from outside

If something changes without the user doing anything, the display should not
wait for the next tick. That is what `request_redraw` is for, and it is
thread-safe, so it may be called from a watcher thread:

```python
async def setup(self):
    self.services.audio.add_listener(self._on_change)

def _on_change(self, event, facility):
    self.services.runtime.request_redraw()   # redraw everything
```

`ctx.request_redraw()` redraws only the one tile and is therefore preferable
whenever it is clear which one is affected.

## Drop-downs at runtime

When the options are only known during operation (audio devices, OBS
scenes), set `options_source` in the manifest and resolve it in the plugin:

```json
{ "key": "sink", "type": "select", "options_source": "sinks" }
```

```python
def get_dynamic_options(self, source, context=None):
    if source == "sinks":
        return [{"value": s.name, "label": s.description}
                for s in self.services.audio.list_sinks()]
    return []
```

If a list depends on another field, say the filters of *one* source or the
sources of *one* scene, you declare that in the manifest:

```json
{
  "key": "filter",
  "type": "select",
  "options_source": "filters",
  "options_depend_on": ["source"]
}
```

The settings already made then arrive as `context`, and the interface
reloads the list as soon as the field above changes.

## Drawing yourself

You only need this when the standard layout does not suffice, for a level bar
for
instance:

```python
def render(self, action_id, settings, ctx):
    render = self.services.render
    image = render.background(ctx.size, ctx.appearance, accent="#8b5cf6")
    render.draw_bar(image, 0.6, color="#8b5cf6")
    render.draw_text_at(image, "60%", x=ctx.size[0] - 12, y=8, align="right")
    return image
```

Building blocks in the render service: `background`, `compose` (icon + label
as in the standard layout), `bar_box`, `draw_bar`, `draw_meter` (level meter
from -60 to 0 dBFS), `draw_text`, `draw_text_at`, `draw_badge`, `blank`,
`empty_slot`, `error_slot`.

Often the standard layout is almost right and only needs an addition. Then
`render_slot(ctx, state=…, label_override=…, accent=…, icon_override=…,
reserve_bottom=…)` draws it, and you paint on top. `icon_override` puts a
finished image in place of the icon (a cover, a server logo),
`icon_px(ctx.size, ctx.appearance.icon_size)` gives the matching edge
length. `reserve_bottom` keeps room at the bottom so the label does not sit
under a bar, `bar_reserve(ctx.size, box)` computes that room for a bar in
`box`:

```python
def render(self, action_id, settings, ctx):
    render = self.services.render
    box = render.bar_box(ctx.size)
    image = render.render_slot(
        ctx,
        state=self.get_state(action_id, settings, ctx),
        reserve_bottom=render.bar_reserve(ctx.size, box),
    )
    render.draw_bar(image, 0.6, box=box)
    return image
```

Important: **take the background from `ctx.appearance`**, do not fill hard
black. Otherwise the plugin ignores the user's settings.

## Services

* `services.audio` (PipeWire): `get_volume`, `set_volume`, `change_volume`,
  `toggle_mute`, `set_mute`, `list_sinks`, `list_sources`,
  `get_default_sink`, `get_default_source`, `switch_output`, `list_streams`,
  `move_stream`, `add_listener`. Single application streams by their index:
  `set_stream_volume`, `change_stream_volume`, `toggle_stream_mute`
* `services.icons`: `resolve(icon_ref, size=…)`, `list_icons(set_id)`
  (names in an icon set), `system_iconset` (ID of the built-in set)
* `services.render`: see above
* `services.runtime`: `request_redraw`, `navigate`, `navigate_home`,
  `navigate_back`, `current_page_id`, `page_number`, `sibling_pages`,
  `step_page`, `notify`, `save_config`, `publish_plugin_status`; through
  `ctx` additionally `switch_profile(name)` (empty name goes back to the
  previous profile), `device_settings` (brightness etc. of this deck),
  `cycle_stack` and the chain control `run_steps` / `stop_steps` /
  `steps_running`
* `services.input` is the virtual keyboard: `send_combo("ctrl+shift+f5")`,
  `hold_combo(combo, pressed)` for push-to-talk, `type_text(text)`,
  `available()`. The character-to-key mapping comes from the active keyboard
  layout, not from an assumption.
* `services.media` is the currently running player over MPRIS:
  `await control("play_pause"|"next"|…)`, `await refresh()`,
  `await list_players()`, `state` (playing, title, artist)
* `services.desktop` covers session and windows: `await
  power("lock"|"suspend"|…)`, `await invoke_shortcut(component, name)` for
  global shortcuts, `await list_components()`, `await
  list_shortcuts(component)`, `screenshot(mode)`,
  `close_application(pattern, force=False)` (returns how many processes were
  ended)
* `services.sound` is the soundboard: `play(path, owner=ctx.key, sink=…)`,
  `toggle`, `stop`, `stop_all`, `is_playing(ctx.key)`, `available()`
* `services.overlay` shows the overlay of a virtual deck: `is_visible(deck)`,
  `await toggle(deck)`, `await show(deck)`, `hide(deck)`. `deck` is the key
  of the deck as in `ctx.deck_serial`
* `services.config` is the entire configuration (read-only)
* `services.plugin_dir` is the plugin's own folder, for bundled files
* `self.plugin_config` holds this plugin's global settings

Calls with `await` are coroutines. From a synchronous hook you start them
with `self.run_async(…)`. `available()` of input and sound returns a pair
`(ok, reason)`, with the reason as text for the interface.

## Global plugin settings

Anything not belonging to a single assignment (server address, credentials)
belongs in the manifest's `config_schema`. The interface shows it under
*Plugins → \<plugin\> → Plugin settings*, the plugin reads it through
`self.plugin_config`.

## Reporting errors

`self.notify_error("…")` writes to the log **and** to the error display in
the interface. `self.notify_info("…")` is meant for expected states, a
service that is not running or a missing player. It only goes to the log,
the interface does not show it.

If a hook raises, the runtime catches it and lists the error in the
interface. A red error tile on the device comes only from a failing
`render`, and that includes `get_state` and `get_label` called inside it.
The same tile appears when `render` returns something other than an image.
If an input hook, `on_tick` or `on_plugin_config_changed` fails, the error
is recorded and the tile is redrawn as usual. A broken plugin therefore
never takes the whole application down.

## Translating texts

Everything a person gets to see belongs in language files in the plugin
folder: error messages, status lines, hints, texts on keys and on the touch
strip. The manifest is already bilingual, this covers everything else.

```
my-counter/
  locales/
    de.json
    en.json
```

```json
// locales/de.json
{ "nicht_erreichbar": "{dienst} ist nicht erreichbar", "zaehler": "Zähler" }

// locales/en.json
{ "nicht_erreichbar": "{dienst} is not reachable", "zaehler": "Counter" }
```

The code only names the key:

```python
self.notify_error(self.t("nicht_erreichbar", dienst="OBS"))
```

`self.t()` uses the language set in the app. If a text is missing, the
English one is used, then the German one, and finally the key itself.
Helper modules without `self` use `plugin_text` from
`deckswitch.plugins.base` with their own folder and the plugin ID.

Log lines stay untranslated, they only appear in the journal.

## Rotation directions

A dial can carry a separate action per rotation direction. If one is
assigned, it receives the turn **like a short key press**, that is
`on_key_down` and `on_key_up`, not `on_dial_rotate`. An action answering
only `on_dial_rotate` is therefore unsuitable as a direction assignment;
anyone wanting to offer both answers both hooks.

As long as no direction is assigned, nothing changes: `on_dial_rotate` keeps
receiving every delta.

## What plugins need to know about multi actions

A multi action calls perfectly ordinary actions, exactly as a key press
would: first `on_key_down`, then `on_key_up`. A plugin needs to prepare
nothing for that. Two things are worth knowing all the same:

* Every step gets **its own `ctx.scratch`**. An action keeping its state
  there (a toggle, say) therefore counts separately per step.
* A chain runs as a task of its own and can be **cancelled at any time**.
  Anyone starting something in a hook that needs cleaning up should not
  defer that to a later hook call.

## No icon

`IconRef(kind="none")` explicitly means "no icon here", not even the
`default_icon` from the manifest. That is what you need when you set a
finished key image as the background. Icon and text are already part of it.

## Icon set plugin

Nothing but a manifest and a directory of SVGs:

```json
{
  "id": "iconset-mine",
  "name": "My icons",
  "version": "1.0.0",
  "type": "iconset",
  "license": "CC-BY-4.0",
  "icons_dir": "icons"
}
```

The file name without its extension is the icon name. SVGs working with
`stroke="currentColor"` or `fill="currentColor"` can be recoloured in the
interface. All others are tinted through their alpha mask.

## Screensaver and wallpaper plugins

Both get a canvas instead of a key. The class inherits from
`ScreensaverPlugin` or `WallpaperPlugin` from `deckswitch.plugins.base`.
Both names stand for the same base class `CanvasPlugin`, and the loader
refuses a class of these types that does not inherit from it. `entry` and
`class` are required as with an action plugin.

```python
import time

from PIL import Image

from deckswitch.plugins.base import ScreensaverPlugin


class SimpleClock(ScreensaverPlugin):
    interval_s = 30.0

    def render(self, size, elapsed_s):
        image = Image.new("RGBA", size, (0, 0, 0, 255))
        height = size[1] // 4
        self.services.render.draw_text(
            image, time.strftime("%H:%M"), y=(size[1] - height) // 2, size=height
        )
        return image
```

`render(size, elapsed_s)` returns an image of the size `size`. The app cuts
it up for keys and touch strip itself. `elapsed_s` counts the seconds since
the screensaver started. `render` is called synchronously, so it is a plain
`def`.

* `interval_s` is the gap between two images in seconds. `0` draws once and
  leaves the image standing.
* If a screensaver returns `None`, the previous image stays.
* `self.deck_layout` says where the tiles sit on the canvas:
  `deck_layout.keys` is a list of `(x, y, w, h)` per key in reading order,
  `deck_layout.strip` the rectangle of the touch strip. Anyone showing
  something per key needs this, otherwise the content lands in the gaps
  between the keys.
* A wallpaper plugin gets only the strip as its canvas, `deck_layout` stays
  `None` there. The app draws it with `elapsed_s` 0 and does not repeat it
  by `interval_s`. A wallpaper has to return an image.

`setup()`, `teardown()`, `on_plugin_config_changed()`, `self.t()` and
`self.plugin_config` work as with an action plugin.

## Packaging and installing

The ID may contain lower-case letters, digits, dot, underscore and hyphen,
starts with a letter or a digit and is at most 64 characters long
(`^[a-z0-9][a-z0-9._-]{0,63}$`). IDs of the bundled plugins are taken. All
types except `iconset` need `entry` and `class`.

Locally the app installs only ZIP archives. The `manifest.json` lies in the
root of the archive, in a single folder or one level deeper. An archive
holds exactly one plugin. It may be at most 64 MB, and at most 256 MB
unpacked. The app does not accept more than 20,000 entries. Symbolic links, paths with
`..` and backslashes in names are refused.

How to install is described in [Plugins](plugins.md#installing-plugins),
the links for the browser under
[streamdeck:// links](plugins.md#streamdeck-links).

### Minimum app version

If your plugin needs a newer DECK//SWITCH, put that version into the
manifest as a string:

```json
{ "min_app_version": "1.4.0" }
```

The field is optional. If the running app is older, it refuses the
installation, from a ZIP as well as from an address or the store, and the
message names the required version. In the plugin list the button of
such an update stays disabled and shows the hint "Needs DECK//SWITCH
{version} or newer".

A plugin that uses `self.t()` needs at least `"1.4.0"`.

## Trying it out

```sh
./scripts/start-backend.sh --verbose
```

In the interface then *Plugins → Check for new plugins*. That button loads
only plugins that are new, have disappeared or carry a different `version`
in their manifest. A code change without a new version number is not picked
up, so restart the backend after code changes.

## Dependencies

Any plugin can name the packages it needs. They go into the manifest, the
installer does the rest.

```json
"dependencies": {
  "python": ["icalendar>=6.0"],
  "system": ["ffmpeg", {"arch": "python-gobject", "debian": "python3-gi", "fedora": "python3-gobject", "suse": "python3-gobject"}]
}
```

* **`python`** names packages from PyPI in the usual notation with a version.
  Direct addresses are rejected. No special rights are needed: `uv` puts
  finished wheels into `<plugins>/.deps/<id>/`, so a package without a wheel
  does not work. The folder goes to the end of `sys.path` when the plugin
  loads. A plugin can add packages that way but never replace one of the
  backend's, and the folder leaves with the plugin. If two plugins ask for
  different versions of a package, they share the one that loaded first.
* **`system`** names packages of the distribution. A plain name applies
  everywhere. Where names differ, an object gives one per family: `arch`,
  `debian` (Ubuntu too), `fedora` and `suse` (openSUSE). If the name for a family is missing, the
  installation stops there. If a package is missing, `pkexec` asks for the
  password and pacman, apt, dnf or zypper install it. On an image-based Fedora such as
  Bazzite the message names the `rpm-ostree` command instead. Without one of
  these package managers each name is looked for as a program.

**The installation stops until everything is there.** If something cannot be
installed, the plugin is not installed, an older version stays in place, and
the error names the command to run by hand.

Name only packages you trust, with a lower version bound.

## Submitting

Once the plugin is done you can put it into the store through *Plugins →
Submit a plugin*. You need to be signed in to the store for that. Drop an
archive into the field; ZIP, TAR, tar.gz and tgz all work.

The store looks at the Python source and notes what stands out: addresses,
network libraries, program calls, code generated at runtime. Everyone who
wants to install your plugin gets to see those findings. If your plugin
reaches out to the network, say what for in the description.
