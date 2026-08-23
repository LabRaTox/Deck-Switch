# Decks: hardware, overlay and network

*[Deutsche Fassung](../de/decks.md)* · Back to the [overview](../../README.md).

A "deck" in DECK//SWITCH is not necessarily a device on a USB port. There are
three kinds, and above the level of operating them they are equal: their own
profile with their own page tree, key logic with double press and hold, multi
actions, dial stacks, screen saver. The tiles are drawn in the same chain for
all three.

| Kind | Operated through | What for |
| --- | --- | --- |
| **Hardware** | Elgato Stream Deck on USB | the normal case |
| **Virtual deck** | overlay on your own screen | when the device is out of reach |
| **Network deck** | browser on another machine | when someone else should help out |

## Profiles

A profile is a set of pages of its own. Each deck shows exactly one — with
two devices, each can show a different one.

You pick it above the page tree. The button next to it opens the management:
create, rename, duplicate, delete. A duplicate gets its own pages with their
own ids; folder keys and "go to page" then point inside the copy instead of
back into the original.

The last profile cannot be deleted — a deck without a profile would have no
page and nothing to show. Deleting a profile that a deck is showing moves
that deck to another one.

**Automatically per program.** List programs in the profile management
(`obs`, `code`, …) and the deck switches to that profile by itself as soon as
one of them is in front. When none matches any more, whatever was there
before comes back. Picking a profile by hand wins — it ends the automatic
switch until a pattern matches again.

Matching looks at the window class *and* the title, case-insensitively, as a
substring: `obs` matches `obs` as well as `obs-studio`.

This works on **KDE Plasma** only. Under Wayland no protocol tells an
ordinary application which window has focus; KDE does let scripts into the
compositor, and one of those reports the changes to us. On other desktops the
management says the automation is off, and why.

**Switching from the deck.** The *switch profile* action puts a switch on a
key. With no profile set it goes back to the previous one, so one key per
profile plus one for the way back is enough. While the chosen profile is the
current one, the key gets a border.

## Several decks at once

You can have several Stream Decks connected at the same time. Each device
stands on its own: its own profile, its own brightness, its own screen saver,
its own timings for hold and double press.

They are matched by **serial number**. A deck may sit on a different USB port
or be detected in a different order and still finds its layout again. If a
device turns up that the app has not seen before, it creates an empty profile
for it.

As soon as there is more than one deck, they appear in the header as a
switch. The editor always edits exactly one. Under *settings → decks* you can
rename devices. A deck that is no longer around can be removed there, and its
profile stays.

If you only have one deck, none of this shows up.

## Which Stream Deck?

The interface follows the connected device. Key count, grid layout and
whether there are dials come from what the device reports, not from a fixed
assumption. A Stream Deck XL shows 8 × 4 keys, a Mini 3 × 2, and without
dials the touch strip area disappears entirely.

Development and device testing happened on a **Stream Deck +**. The other
models are tested against faked device reports, never on real hardware.

---

## Virtual deck (overlay)

Under *settings → decks → **+ virtual deck*** you get a deck with a grid of
your choosing (columns, rows, dials, tile size) that sits as an **overlay**
on the screen.

**It is deliberately not a window.** Through `zwlr_layer_shell_v1` the
surface sits on the overlay layer: no entry in the task bar, no Alt-Tab, no
frame, and above all **no focus**. That is where things like this usually
fail. If a click on the key stole the focus, the *type text* action would
type into the deck afterwards instead of the application you came from.
Measured under KWin: the click arrives, the focus stays with the foreground
window.

**Calling it up** works three ways:

* through a **global shortcut**, see below
* through *settings → decks → show overlay*
* through the **virtual deck** action (*Streamdeck* plugin) on a key of the
  real deck, toggling if you like and optionally **at the mouse pointer**

No client protocol on Wayland tells you where the pointer is, and that is on
purpose. KWin knows though, and it may call D-Bus, so we ask ourselves back
through a tiny KWin script. Without KDE the overlay appears at its remembered
spot. Not an error, just less convenient.

### Moving it around

With *appear at pointer* **off** you can put the overlay where it belongs.
The spot is stored and applies every time it comes up:

* **left mouse button** on the border around the tiles
* **right mouse button** anywhere, tiles included. You need that when a
  transparent background and hidden empty tiles leave hardly any free area.

While you drag, the overlay steps back and jumps to the new spot when you let
go. It does not glide along, because a layer shell surface cannot be moved
while it runs. `Window::setMargins` from layer-shell-qt remembers the value
and emits it as a signal, but never reaches the live Wayland surface. So the
app rebuilds it at the new spot.

### Settings

In the editor the grid and the overlay switches are on the right in the page
properties. Tile size is continuous, and there are two switches:

* **Transparent background.** Without a plate underneath, only the tiles
  float over the screen.
* **Hide empty tiles.** Unassigned slots stay invisible and take no clicks.
  Their space stays reserved though, so the other tiles do not jump around
  every time you assign something.

### Shortcut

Below that is the **shortcut** that fetches this particular overlay and sends
it away again, from anywhere and without opening the interface. If you only
have a virtual deck, you need it: a deck without a case has no other handle.
Press *record* and type the combination. You can also write into the field by
hand (`ctrl+alt+d`), because the browser catches some combinations before the
page sees them.

The shortcut is registered with Plasma (`kglobalaccel`). That has three
consequences worth knowing:

* It then also shows up in the **KDE system settings** under *shortcuts →
  DECK//SWITCH* and can be changed there.
* A **combination that is already taken is refused**, not taken away. Below
  the field you then see who owns it, for instance "KWin — peek at desktop".
  If you want it anyway, remove it there first.
* When the backend quits, the shortcut is free again. Nothing is left behind
  with no program behind it.

`AltGr` does not work. In Qt that is not a modifier level a global shortcut
can express. An empty field means: no shortcut.

The tiles get **rounded corners with real transparency**. The rounding
happens while drawing and not in the overlay, because Qt can only clip
rectangles and the corners would stay as squares.

There is no **brightness** here. An overlay has no backlight to dim, and both
conceivable translations would be worse than none: as opacity the tile
becomes see-through and unreadable on a light background, as darkening the
colours no longer match the preview. The slider is switched off.

**Requirements:** `qt6-declarative` (which brings `qml6`) and
`layer-shell-qt`. If one of them is missing, the interface says so in plain
words.

---

## Network deck

A network deck is operated by **someone else on the same network** in a
browser. It is meant for the moderator who should help out during a stream
without walking over to your machine. They see this one deck and cannot
change anything about it.

You create one under *settings → decks → **+ network deck***. Assigning works
like any other deck, and the editor shows grid, password and address on the
right.

### Setting it up

1. Create the deck and assign the keys.
2. Set a **password** under *access* in the editor, at least 4 characters.
3. Pass the **address** shown there to your guest, for example
   `http://192.168.178.37:8771/deck/net-a1b2c3d4`.

Your guest opens the address, enters the password and has the deck in front
of them. Nothing to install. The page is a single file without libraries and
runs on a phone, a tablet and a borrowed laptop.

Press and release go to the backend separately, so hold, double press and
push-to-talk work exactly as on the device. Dials get − and + with repeat
while held.

If a firewall is running, the port needs to be open. Better for your own
subnet only than for everything:

```sh
sudo ufw allow from 192.168.178.0/24 to any port 8771 proto tcp
```

### How it is secured

The regular server that serves the interface binds **only to `127.0.0.1`**
and stays there. It may do everything: change assignments, install plugins,
export the configuration, credentials in the plugin settings included. That
does not belong on a network.

What goes onto the network is a **second, deliberately tiny application** on
its own port, 8771 by default. It can do three things: sign in, show tiles,
press keys. There simply is no endpoint that could change anything. The
protection lies in what is absent and not in a rule somebody softens later.

On top of that:

* The **password** is only stored derived (PBKDF2-HMAC-SHA256, 210,000
  rounds, its own salt). There is no plain text in the config file.
* After signing in a **token** applies, twelve hours, tied to exactly one
  deck.
* A **password change disconnects everyone** currently connected.
* After five failed attempts the address is **locked** for five minutes, and
  every failed attempt costs an extra half second.
* **Without a password a deck is not offered at all.** If no network deck is
  active any more, the server stops listening entirely. An open port with no
  purpose is attack surface without benefit.

What this does **not** do: the connection is unencrypted. On your own network
that is fine. Over foreign networks or the internet a network deck has no
business.
