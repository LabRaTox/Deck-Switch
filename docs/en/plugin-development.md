# Writing your own plugins

*[Deutsche Fassung](../de/plugin-development.md)* · Back to the
[overview](../../README.md).

There are two kinds: **action plugins** drive keys, dials and touch strip
segments, **icon set plugins** merely supply SVGs for the icon picker.

Plugins live in `~/.local/share/deckswitch/plugins/<plugin-id>/`. The
bundled plugins under `backend/plugins/` are built identically and serve
well as templates.

---

## Icon

A plugin may bring an image representing it in the overview:

```json
{ "icon": "icon.png" }
```

256 × 256 pixels, PNG (JPEG, WebP or SVG work too). The file lives in the
plugin directory; paths pointing outside are rejected by the backend. The
icon appears only in the plugin list, not next to the actions.

## Action plugin

Minimal example — a plugin with one action that counts up:

```
counter/
├── manifest.json
└── plugin.py
```

### manifest.json

```json
{
  "id": "counter",
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
(matching the state), label underneath — icon, sizes, colours and background
are set by the user in the interface, without the plugin doing anything for
it.

## The hooks

All of them are optional, all may be `def` **or** `async def`. Synchronous
hooks run in a worker thread — a `subprocess.run` therefore never blocks the
application.

| Hook | When |
| --- | --- |
| `on_key_down(action_id, settings, ctx)` | key pressed |
| `on_key_up(action_id, settings, ctx)` | key released |
| `on_dial_rotate(action_id, settings, delta, ctx)` | dial turned (`delta` ±) |
| `on_dial_push(action_id, settings, ctx)` | dial pressed |
| `on_touch(action_id, settings, x, y, ctx)` | touch strip touched (segment-relative) |
| `on_tick(action_id, settings, ctx)` | periodically, once per second by default |
| `get_state(action_id, settings, ctx)` | which state applies right now |
| `get_label(action_id, settings, ctx)` | dynamic text instead of the configured one |
| `render(action_id, settings, ctx)` | draw your own image |
| `setup()` / `teardown()` | on load/shutdown (open/close connections) |
| `on_plugin_config_changed(config)` | global plugin settings changed |
| `get_status()` | connection state for the plugin list |
| `get_dynamic_options(source, context)` | fill drop-downs at runtime |
| `gui_command(command, payload)` | an action the interface triggers directly |

One trap: a **synchronous** hook runs in a worker thread, and there is no
event loop there — `asyncio.create_task` then fails with "no running event
loop". Two ways out:

* declare the hook as `async def` (then it runs in the loop), or
* use `self.run_async(coro)`. That helper works from any thread and is the
  right route inside `render`, where an `async def` is out of the question.

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

If there is no connection to speak of, leave `get_status` out — then the
interface shows nothing rather than pretending a meaning.

### The context (`ctx`)

The same action can be assigned several times — one key per output device,
say. The `ctx` tells you which assignment is up:

* `ctx.index`, `ctx.input_type` (`"key"`/`"dial"`), `ctx.page_id`
* `ctx.size` — drawing area: `(120, 120)` for keys, `(200, 100)` per segment
* `ctx.setting(name, default)` — a setting with a fallback
* `ctx.scratch` — free scratch space, survives between calls
* `ctx.request_redraw()` — redraw exactly this tile immediately
* `ctx.services` — audio, icons, rendering, runtime and the system services
* `ctx.deck_serial` — which deck the assignment sits on
* `ctx.frame_time` — runtime in seconds; animated images pick their frame
  from it

**Important with several decks:** `ctx.services.runtime` points at *the deck
the press happened on*. Navigating through `self.services.runtime` lands on
the primary deck instead — with a single device that is the same thing, with
two it is wrong. Rule of thumb: anything to do with an assignment goes
through `ctx.services.runtime`; everything else (reporting errors, saving
the config) may go through `self.services.runtime`.

## State from outside

If something changes without the user doing anything, the display should not
wait for the next tick. That is what `request_redraw` is for — and it is
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

If a list depends on another field — the filters of *one* source, the
sources of *one* scene — that is declared in the manifest:

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

Only needed when the standard layout does not suffice — for a level bar, for
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
as in the standard layout), `bar_box`, `draw_bar`, `draw_text`,
`draw_text_at`, `draw_badge`, `blank`, `empty_slot`.

Important: **take the background from `ctx.appearance`**, do not fill hard
black — otherwise the plugin ignores the user's settings.

## Services

* `services.audio` — PipeWire: `get_volume`, `set_volume`, `change_volume`,
  `toggle_mute`, `list_sinks`, `list_sources`, `switch_output`,
  `list_streams`, `add_listener`
* `services.icons` — `resolve(icon_ref, size=…)`, `list_icons`
* `services.render` — see above
* `services.runtime` — `request_redraw`, `navigate`, `navigate_home`,
  `navigate_back`, `page_number`, `step_page`, `notify`, `save_config`;
  through `ctx` additionally `device_settings` (brightness etc. of this
  deck), `cycle_stack` and the chain control `run_steps` / `stop_steps` /
  `steps_running`
* `services.input` — virtual keyboard: `send_combo("ctrl+shift+f5")`,
  `hold_combo(combo, pressed)` for push-to-talk, `type_text(text)`,
  `available()`. The character-to-key mapping comes from the active keyboard
  layout, not from an assumption.
* `services.media` — the currently running player over MPRIS:
  `control("play_pause"|"next"|…)`, `refresh()`, `list_players()`, `state`
  (playing, title, artist)
* `services.desktop` — session and windows: `power("lock"|"suspend"|…)`,
  `invoke_shortcut(component, name)` for KDE's global shortcuts,
  `list_shortcuts(component)`, `screenshot(mode)`, `close_application()`
* `services.sound` — soundboard: `play(path, owner=ctx.key, sink=…)`,
  `toggle`, `stop`, `stop_all`, `is_playing(ctx.key)`
* `services.config` — the entire configuration (read-only)
* `self.plugin_config` — this plugin's global settings

## Global plugin settings

Anything not belonging to a single assignment (server address, credentials)
belongs in the manifest's `config_schema`. The interface shows it under
*Plugins → \<plugin\> → Plugin settings*, the plugin reads it through
`self.plugin_config`.

## Reporting errors

`self.notify_error("…")` writes to the log **and** to the error display in
the interface. If a hook raises, the runtime catches it, shows a red error
tile on the device and lists the error in the interface — a broken plugin
therefore never takes the whole application down.

## Rotation directions

A dial can carry a separate action per rotation direction. If one is
assigned, it receives the turn **like a short key press** — that is
`on_key_down` and `on_key_up`, not `on_dial_rotate`. An action answering
only `on_dial_rotate` is therefore unsuitable as a direction assignment;
anyone wanting to offer both answers both hooks.

Conversely: as long as no direction is assigned, nothing changes —
`on_dial_rotate` keeps receiving every delta.

## What plugins need to know about multi actions

A multi action calls perfectly ordinary actions — exactly as a key press
would: first `on_key_down`, then `on_key_up`. A plugin needs to prepare
nothing for that. Two things are worth knowing all the same:

* Every step gets **its own `ctx.scratch`**. An action keeping its state
  there (a toggle, say) therefore counts separately per step.
* A chain runs as a task of its own and can be **cancelled at any time**.
  Anyone starting something in a hook that needs cleaning up should not
  defer that to a later hook call.

## No icon

`IconRef(kind="none")` explicitly means "no icon here" — not even the
`default_icon` from the manifest. That is what you need when setting a
finished key image as the background; icon and text are already part of it.

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
interface; all others are tinted through their alpha mask.

## Trying it out

```sh
./scripts/start-backend.sh --verbose
```

In the interface, *Plugins → Reload plugins*. Because Python caches modules
it has already imported, restarting the backend is the more reliable route
after code changes.
