# Using DECK//SWITCH

*[Deutsche Fassung](../de/operation.md)* · Back to the
[overview](../../README.md).

## Editor

The actions of all plugins on the left, the deck in device geometry in the
middle, the properties of the selected position on the right.

* Drag an action from the left column onto a key or a dial.
* Assignments can be swapped among each other by drag & drop.
* ▶ on a tile fires the action without touching the device.
* The tile preview is rendered by the backend — it shows exactly what is on
  the device.

## Pages and folders

Both are the same thing: a page with or without a parent. The page tree next
to the deck shows the relationship: sub-pages sit framed underneath their
page, the branch of the open page is highlighted, and ↳ creates a sub-page
directly. Rename by double click or F2, collapse branches with ▾. For
jumping around there are the actions of the *Streamdeck* plugin (folder,
home, back, page indicator, go to page, next/previous page).

**Order** — drag within the tree: dropped above or below a row it re-sorts,
dropped onto the middle of a row it becomes a sub-page. Without a mouse the
same works with `Alt` + `↑↓` (move) and `Alt` + `←→` (outdent and indent).
The order applies on the device as well — swiping and next/previous page
follow it.

**Swiping the touch strip** pages through the pages on the same level: left
goes forward, right goes back. Tapping stays with the action on the segment
— only swipe gestures go to the device. Threshold, wrap-around and switching
it off live in the settings under *Touch strip*.

## Key logic: press, double press, hold

Every key can carry three actions. In the properties panel the three tabs
switch between them; a dot on a tab shows which branch is assigned.

The principle behind it: **if you assign nothing second, nothing waits.** A
key with only one action still fires the moment it is pressed. Only an
assigned double press buys the delay needed to tell whether a second press
follows (280 ms by default); an assigned hold moves the main action to the
release. There is no other way — whether a second press is coming is only
known afterwards — and Elgato faces the same trade-off.

Practical consequence: push-to-talk actions, which need a real press *and*
release, belong on a key without double press and without hold.

A key press always stays with the assignment it started on: opening a folder
does not retroactively fire the key that sits in the same place on the new
page.

## Multi actions

The *multi action* runs several steps in sequence: launch a program, wait a
moment, send a hotkey, type text. The steps are a list in the properties.
It is filled like the deck itself: **drag actions from the left column
straight into the list** — they are dropped before the step under the
pointer, and at the end for anything below the last one. If you prefer
clicking, use *+ Action*. Sorting also works by dragging or with `Alt` +
`↑↓`.

A **pause** is a step of its own and not a property of the action before it
— that way it can be moved, used several times and switched off
individually. Every step has a checkbox: disabled steps stay in place but do
not run. When hunting for the step that misbehaves, that is worth more than
deleting it.

*Repeat* runs the chain in a loop until pressed again. The **toggle**
(*multi action (toggle)*) has two chains: the first press runs one, the next
runs the other — with its own icon per direction. Chains inside chains are
not possible; that would be a loop nobody stops any more.

## Dials

**Assigning rotation directions** — normally a dial's action receives the
rotation as a delta and adjusts continuously: volume, brightness, position.
You can also assign **a separate action per rotation direction**; then every
turn acts like a short press on it — left "previous track", right "next
track". The tabs for that sit under *Dial assignment*, right next to
*Press*.

* **Fires every _n_ detents** (2 by default). A brisk turn produces a dozen
  detents in no time, and "next track" must not fire a dozen times. Counted
  rather than throttled by time: the same hand movement always leads to the
  same result, no matter how fast it was. Changing direction resets the
  counter.
* **The directions are independent.** If only one is assigned, the other
  still goes to the base action. If you want nothing at all on the press,
  put the *Empty* action from the Streamdeck plugin on the base slot.

**Dial stack** — several assignments can sit on top of each other on one
dial. On the device a **long press** advances to the next entry, a short
press still fires the action. Every entry is a full assignment with its own
icon, label and settings; in the editor you pick at the top which one you
are editing. A dial without a stack behaves unchanged — there the press
fires immediately.

## The look of a key

Icon, label and background live in the properties panel under *Appearance*.

**Label** — besides text, size, colour and position there is the **font
family** (anything fontconfig knows), **bold**, *italic*, underline and
left/centre/right alignment. Rendering happens in the backend, so the
preview in the interface shows exactly what is on the device.

**Background image per key** — under *Background*, next to colour, gradient,
texture and accent there is also **image**: upload one or pick from your own
images, plus fitting (fill, contain, stretch) and opacity. Below full
opacity the image is laid onto the base tone rather than simply made
translucent — there is nothing behind a key, so it would only arrive darker.

**Animated key images** — GIFs (and animated WebP/PNG) play on the key, both
as icon and as background. Only what actually moves is played: every tile
travels to the deck individually over USB, and bandwidth is this device's
scarcest resource. Frame rate and on/off live in the settings (10 frames per
second by default). Frame duration comes from the file, not from a fixed
rate.

**Design a key image** — the button opens a small workshop: pick an image,
zoom, move, rotate, background as colour or gradient, text with font, size,
colour, position and outline. The result is a finished PNG (288 × 288) taken
over either as the **key image** (background, icon and label off) or as the
**icon**.

## Screen saver and wallpaper

Both live in the **settings**, not among the actions — they belong to the
whole device and to no single key.

The **screen saver** puts *one* image across all keys and the touch strip
after an adjustable idle time. The motif is computed onto a surface in
device proportions and only then cut apart, so it runs across the gaps; the
preview shows exactly that, including the black seams. Animated GIFs play,
any input ends the saver.

The **touch strip wallpaper** belongs to the *page* — every page can have
its own. It is set in the editor: select no key, then the properties on the
right show the page instead of an assignment.

It replaces the ground of the segments everywhere no dedicated background
was chosen for that segment. Anyone deliberately giving a dial a colour or a
gradient keeps it. Opacity lets the image step back so icons and labels stay
readable.

A few ready-made motifs are available on request:

```sh
./scripts/make-wallpapers.py     # eight strips, straight into the picker
```

Dimensions: a key is 120 × 120 pixels, the touch strip 800 × 100 (one
segment of it 200 × 100 — the number Elgato's SDK quotes as well).

Both take either an uploaded image or a plugin. Plugins for this carry
`"type": "screensaver"` or `"type": "wallpaper"` in the manifest, inherit
from `CanvasPlugin` and get nothing but a canvas — how the result is
distributed across keys and segments is the app's business.
`plugin-sources/clock-saver/` is a complete example.

## The tray icon

While the backend runs, an icon appears in the system tray. It shows the
device state — coloured when connected, grey when not — and offers:

* **Left click** opens the interface
* **Right click** opens a menu (open interface, reconnect device, quit)
* **Scrolling** over the icon adjusts the deck's brightness

Technically this is a StatusNotifierItem over D-Bus — the standard KDE
Plasma, Waybar and GNOME (with an extension) understand. That way the
backend needs neither GTK nor Qt. If there is no suitable panel or no
session at all (server, TTY), the icon is quietly skipped; device control
carries on unchanged. It can be switched off with `--no-tray`.

> **Careful with other deck software:** access to the device is exclusive.
> If StreamController or Elgato's own software runs alongside, only one of
> them gets the deck — the other reports "no device connected". If you have
> both installed, only let one start automatically.
