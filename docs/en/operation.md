# Using DECK//SWITCH

*[Deutsche Fassung](../de/operation.md)* · Back to the
[overview](../../README.md).

## Editor

The actions of all plugins sit on the left, the deck in your device's
geometry in the middle, and the properties of the selected position on the
right.

* Drag an action from the left column onto a key or a dial.
* Assignments can be swapped among each other by drag and drop.
* ▶ on a tile fires the action without touching the device.
* The tile preview comes from the backend. It shows exactly what is on the
  device.

## Pages and folders

Both are the same thing: a page with or without a parent. The page tree next
to the deck shows what belongs where. Sub-pages sit framed underneath their
page, the branch of the open page is highlighted, and ↳ creates a sub-page
directly. Rename by double click or F2, collapse branches with ▾. For jumping
around there are the actions of the *Streamdeck* plugin: folder, home, back,
page indicator, go to page, next and previous page.

**Order** you change by dragging within the tree. Dropped above or below a
row it re-sorts, dropped onto the middle of a row it becomes a sub-page.
Without a mouse the same works with `Alt` + `↑↓` to move and `Alt` + `←→` to
outdent and indent. The order applies on the device as well: swiping and
next/previous page follow it.

**Swiping the touch strip** pages between the pages on the same level. Left
goes forward, right goes back. Tapping stays with the action on that segment,
only swipe gestures go to the device. Threshold, wrap-around and switching it
off are in the settings under *Touch strip*.

## Key logic: press, double press, hold

Every key can carry three actions. In the properties panel you switch between
them with the three tabs, and a dot on a tab shows which branch is used.

The rule: **if you do not put anything on a second branch, nothing waits.** A
key with only one action still fires the moment you press it. Only a used
double press buys the waiting time needed to tell whether a second press
follows, 280 ms by default. A used hold moves the main action to the release.
There is no way around it, because you only know afterwards whether a second
press comes. Elgato faces the same trade-off.

That has a practical consequence. Push-to-talk needs a real press *and*
release, so those actions belong on a key without double press and without
hold.

A key press always stays with the assignment it started on. Opening a folder
does not then fire the key that happens to sit in the same spot on the new
page.

## Multi actions

The *multi action* runs several steps one after another: start a program,
wait a moment, send a hotkey, type text. The steps are a list in the
properties. You fill it the same way you fill the deck, by **dragging actions
from the left column straight into the list**. They drop in front of the step
the pointer is over, or at the end if you aim below the last one. If you
prefer clicking, use *+ action*. Sorting also works by dragging or with `Alt`
+ `↑↓`.

A **pause** is its own step and not a property of the action before it. That
way you can move it, use it several times and switch it off on its own. Every
step has a checkbox: switched-off steps stay in the list but do not run. When
you are hunting for the step that hangs, that is worth more than deleting it.

*Repeat* runs the chain in a loop until you press again. The **toggle**
(*multi action (toggle)*) has two chains: the first press runs one, the next
runs the other, each with its own icon. Chains inside chains do not exist.
That would be a loop nobody stops.

## Dials

**Assigning rotation directions.** Normally a dial's action gets the rotation
as a delta and adjusts continuously: volume, brightness, position. You can
also give **each rotation direction its own action**. Every turn then acts
like a short press on it, left for "previous track", right for "next track".
The tabs for this are under *dial assignment*, right next to *press*.

* **It fires every _n_ detents**, two by default. A quick turn produces a
  dozen detents in no time, and "next track" must not fire a dozen times.
  Counting beats throttling by time: the same hand movement always gives the
  same result, however fast it was. Changing direction resets the counter.
* **The directions are independent.** If only one is assigned, the other
  still goes to the base action. If you want nothing at all on the press, put
  the *empty* action from the Streamdeck plugin on the base slot.

**Dial stack.** A dial can carry several assignments on top of each other. On
the device a **long press** moves to the next entry, a short press still
fires the action. Every entry is a full assignment with its own icon, label
and settings. In the editor you pick at the top which one you are editing. A
dial without a stack behaves as before, the press fires straight away.

## The look of a key

Icon, label and background are in the properties panel under *appearance*.

**Label.** Besides text, size, colour and position there is the **font**
(anything fontconfig knows), **bold**, *italic*, underline and alignment
left, centre or right. Everything is drawn in the backend, so the preview in
the GUI shows exactly what lands on the device.

**Background image per key.** Under *background* there is **image** next to
colour, gradient, texture and accent: upload one or pick from your own
images, plus fitting (fill, contain, stretch) and opacity. Below full opacity
the app lays the image onto the base colour instead of making it transparent.
There is nothing behind a key, so it would only come out darker.

**Animated key images.** GIFs and animated WebP/PNG play on the key, as an
icon and as a background. Only what actually moves is played. Every tile goes
to the deck over USB on its own, and bandwidth is this device's scarcest
resource. Frame rate and on/off are in the settings, 10 frames per second by
default. The display duration comes from the file and not from a fixed rate.

**Design a key image.** The button opens a small workshop: pick an image,
zoom, move, rotate, background as a colour or gradient, text with font, size,
colour, position and outline. Out comes a finished PNG of 288 × 288 pixels
that you use either as the **key image** (background, icon and label are then
off) or as the **icon**.

## Screen saver and wallpaper

Both live in the **settings** rather than under the actions. They belong to
the whole device and not to a single key.

The **screen saver** puts *one* image across all keys and the touch strip
after an idle time you set. The app renders the image onto a surface in
device proportions and only then cuts it up, so it runs across the gaps. The
preview shows exactly that, black gaps included. Animated GIFs play, and any
input ends the screen saver.

The **touch strip wallpaper** belongs to the *page*, and each one can have
its own. You set it in the editor: select no key, and the properties on the
right show the page.

It replaces the background of the segments wherever the segment has no
background of its own. If you deliberately give a dial a colour or a
gradient, that stays. Opacity lets the image step back so icons and labels
stay readable.

A few ready-made images are one command away:

```sh
./scripts/make-wallpapers.py     # eight strips, straight into the picker
```

The sizes: a key is 120 × 120 pixels, the touch strip 800 × 100. One segment
of it is 200 × 100, the same number Elgato's SDK gives.

Both take either an uploaded image or a plugin. Plugins for this carry
`"type": "screensaver"` or `"type": "wallpaper"` in the manifest, inherit
from `CanvasPlugin` and get nothing but a canvas. How the result is spread
across keys and segments is the app's job. `plugin-sources/clock-saver/` is a
complete example.

## The tray icon

While the backend runs, an icon appears in the system tray. It shows the
device state, coloured when connected and grey when not, and offers:

* **Left click** opens the interface
* **Right click** opens a menu (open interface, reconnect device, quit)
* **Scrolling** over the icon adjusts the deck brightness

Behind it is a StatusNotifierItem over D-Bus, the standard KDE Plasma, Waybar
and GNOME (with an extension) understand. That way the backend needs neither
GTK nor Qt. If there is no matching tray or no session at all, on a server or
a TTY, the icon simply does not appear. Device control keeps running. You can
switch it off with `--no-tray`.

> **Careful with other deck software.** Access to the device is exclusive. If
> StreamController or Elgato's own software runs alongside, only one of them
> gets the deck. The other reports "no device connected". If you have both
> installed, let only one start automatically.
