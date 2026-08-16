# Decks: hardware, overlay and network

*[Deutsche Fassung](../de/decks.md)* · Back to the
[overview](../../README.md).

In DECK//SWITCH a "deck" is not necessarily a device on your USB port. There
are three kinds, and above the input layer they are equivalent: each has its
own profile with its own page tree, key logic with double press and hold,
multi actions, dial stacks, screen saver. The tiles of all three come out of
the same rendering chain.

| Kind | Operated via | What for |
| --- | --- | --- |
| **Hardware** | an Elgato Stream Deck on USB | the normal case |
| **Virtual deck** | an overlay on your own screen | when the device is out of reach |
| **Network deck** | a browser on another machine | when someone else should join in |

## Several decks at once

Any number of Stream Decks can be connected at the same time. Each device
stands on its own: its own profile, its own brightness, its own screen
saver, its own timings for hold and double press.

They are matched by **serial number**. A deck may therefore sit on a
different USB port or be detected in a different order and still find its
layout again. When a previously unknown device turns up, the app creates an
empty profile for it.

The header shows the decks as a switcher as soon as there is more than one —
the editor always edits exactly one. Under *Settings → Decks* devices can be
renamed; a deck that is gone can be removed there (its profile is kept).

If you only have one deck you notice none of this.

## Which Stream Deck?

The interface follows the connected device: key count, grid layout and the
presence of dials come from the device report, not from a fixed assumption.
A Stream Deck XL shows 8 × 4 keys, a Mini 3 × 2, and without dials the touch
strip area disappears entirely. Developed and tested on real hardware with
the **Stream Deck +**; the other models are tested against simulated device
reports but never against the actual thing.

---

## Virtual deck (overlay)

Under *Settings → Decks → **+ Virtual deck*** you get a deck with a freely
chosen grid (columns, rows, dials, tile size) that sits as an **overlay** on
top of your screen.

**It is deliberately not a window.** Through `zwlr_layer_shell_v1` the
surface lives on the overlay layer: no entry in the task bar, no Alt-Tab, no
frame — and above all **no focus**. That is the point where such a thing
usually fails: if clicking a key stole the focus, the *type text* action
would afterwards type into the deck instead of the application you came
from. Measured under KWin — the click arrives, the focus stays with the
foreground window.

**Summoning it** works two ways:

* via *Settings → Decks → Show overlay*
* via the **Virtual deck** action (plugin *Streamdeck*) on a key of the real
  deck — optionally toggling, and optionally **at the mouse pointer**

No client protocol reveals the pointer position under Wayland; that is by
design. KWin knows it, though, and KWin scripts may call D-Bus, so we ask
ourselves back through a tiny KWin script. Without KDE the overlay appears
at its remembered place — not a fault, just less convenient.

### Moving and placing it

With *Appear at mouse pointer* switched **off**, the overlay can be put
where it belongs — the spot is stored and used on every further call:

* **left mouse button** on the margin around the tiles
* **right mouse button** anywhere, including on the tiles — necessary when a
  transparent background and hidden empty tiles leave hardly any free area

While dragging, the overlay steps back and jumps to the new place when you
let go. It does not glide along: a layer-shell surface cannot be moved while
it is up — `Window::setMargins` from layer-shell-qt stores the value and
emits a signal, but never reaches the running Wayland surface. So it is
rebuilt at the new position instead.

### Settings

In the editor, grid and overlay switches sit on the right in the page
properties. The tile size is continuous; there are two switches next to it:

* **Transparent background** — without a plate underneath, only the tiles
  float above the screen.
* **Hide empty tiles** — unassigned slots stay invisible and take no clicks
  either. Their space is kept, though, so the remaining tiles do not jump
  around whenever something is assigned.

The tiles get **rounded corners with real transparency** — the rounding
happens during rendering, not in the overlay, because Qt can only clip
rectangularly and the corners would otherwise stay square.

There is no **brightness** here: an overlay has no backlight to dim. Both
conceivable translations are worse than none — as opacity the tile becomes
translucent and unreadable on a light background, as dimming the colours no
longer match the preview. The slider is therefore disabled.

**Requirements:** `qt6-declarative` (which brings `qml6`) and
`layer-shell-qt`. If either is missing, the interface says so plainly
instead of offering a button that does nothing.

A global **keyboard shortcut** for summoning it is still missing. The clean
route would be the `org.freedesktop.portal.GlobalShortcuts` portal; KDE's
`kglobalaccel` accepts the registration but never delivers the signal
(measured).

---

## Network deck

A network deck is operated **from another machine on the same network** in a
browser — meant for the moderator who should join in during a stream without
walking over to your machine. They see exactly this one deck and cannot
change anything about it.

Create it under *Settings → Decks → **+ Network deck***. Assign it like any
other deck; in the editor, grid, password and address sit on the right.

### Setting it up

1. Create the deck and assign its keys.
2. In the editor under *Access*, set a **password** (at least 4 characters).
3. Pass the displayed **address** to your guest, for example
   `http://192.168.178.37:8771/deck/net-a1b2c3d4`.

The guest opens the address, enters the password and has the deck in front
of them. Nothing to install — the page is a single file without libraries
and runs on phones, tablets and borrowed laptops.

Press and release are sent separately, so hold, double press and
push-to-talk behave exactly as they do on the device. Dials have − and +
with repetition while held.

If a firewall is running, the port needs to be open — better for your own
subnet only than for everyone:

```sh
sudo ufw allow from 192.168.178.0/24 to any port 8771 proto tcp
```

### How it is secured

The regular server serving the interface binds **exclusively to
`127.0.0.1`**, and it stays that way. It may do everything: change layouts,
install plugins, export the configuration — including the credentials in the
plugin settings. Something like that does not belong on the network.

What goes onto the network instead is a **second, deliberately tiny
application** on its own port (8771 by default). It can do three things: log
in, show tiles, press keys. There simply is no endpoint that could change
anything — the protection lies in what is absent, not in a rule someone
might soften later.

On top of that:

* The **password** is only stored derived (PBKDF2-HMAC-SHA256, 210,000
  rounds, its own salt) — no plain text in the configuration file.
* After logging in a **token** applies, twelve hours, bound to exactly one
  deck.
* A **password change disconnects everyone** currently connected.
* After five failed attempts the address is **locked out** for five minutes;
  every failed attempt costs an extra half second anyway.
* **Without a password a deck is not offered at all.** Once no network deck
  is active any more, the server stops listening entirely — an open port
  without purpose is attack surface without benefit.

What this does **not** provide: the connection is unencrypted. On your own
network that is acceptable — across foreign networks, let alone the
internet, a network deck does not belong.
