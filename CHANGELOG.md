# Changelog

## 1.4.0 · 24 October 2026

### New

- Everything the backend shows in the window follows the language setting:
  error messages, hints, reasons why a feature is missing. Error responses
  carry a code next to the text
- Plugins translate their texts through `self.t()` with their own
  `locales/de.json` and `locales/en.json`. Plugins that use it need
  DECK//SWITCH 1.4.0 or newer
- A thumbs down in the store asks for a short reason first. On your own
  plugin the rating shows only the numbers

### Changed

- Sliders and text fields save while you drag or type, but no more often
  than needed, and the last value always arrives
- Closing a program by pattern counts programs instead of processes, so
  Discord, Steam or VS Code with their many helper processes can be closed
- The API answers only for 127.0.0.1, localhost and ::1. Network decks are
  not affected

### Fixed

- A busy port for network decks no longer takes the whole backend down
- After switching a network deck off, a restart of the service shut the
  backend down without resetting the device
- Moving over from the old `streamdeck-app` folders works again
- A broken configuration is reported instead of being replaced silently
- Typing fast into a label no longer loses characters
- A broken sound file no longer restarts the player in an endless loop
- Plugin updates load all modules and texts of the new version
- Forgotten decks stop running in the background
- A screensaver that crashes no longer freezes the deck
- Input devices like EasyEffects or Bluetooth microphones are recognised as
  inputs, and the keyboard layout is detected correctly without KDE
- Store archives with more than one plugin or with a different plugin ID are
  refused

## 1.3.5 — 11 October 2026

### New

- Virtual decks can close themselves after a click on a tile. The switch
  **Close deck after click** stands with the other overlay settings and
  takes effect on release, so holding a key keeps working
- The window brings the backend along. When it is not running, the launcher
  starts it through the systemd unit if there is one, otherwise directly,
  and waits for it briefly. Starting the app no longer ends at a note
  telling you to start the backend first
- Profile management picks programs from a dropdown of the installed ones.
  The list comes from the desktop entries of the Free Desktop standard,
  which every distribution fills the same way; names can still be entered
  by hand

### Changed

- Profile management is a split view: the names on the left, the details of
  the chosen one on the right, in a window of fixed height whose columns
  scroll when there is too much
- The deck switcher in the top bar groups by kind. One deck of a kind stays
  a single switch, several of a kind share a dropdown

### Fixed

- Links to the outside open in the browser again. Since the app has its own
  window, buttons like **Go to review**, the GitHub sign-in for the store or
  a plugin's source did nothing at all when clicked

## 1.3.0 — 8 September 2026

### New

- DECK//SWITCH has an entry in the application menu, with its icon. The
  setup script creates it; `install-desktop-entry.sh` adds or removes it
  on its own
- Backup archive: configuration *and* your uploaded images in one ZIP file,
  and a way back from it. The existing JSON export only ever held the
  configuration, so a key pointing at an uploaded icon came back empty
- Earlier states of the configuration are listed in the settings and can be
  restored — they were already being written to disk, but nothing led back
  to them
- A single profile can be exported and imported, together with the images
  used in it. It is always added on the other side, never replacing anything
- The tray icon opens the window instead of a browser tab, and a second
  start brings the existing window forward instead of opening another one
- The setup script now also offers the `input` group, registers the
  `streamdeck://` handler, builds the window and asks about autostart —
  everything the AUR package brings along

### Changed

- The key grid follows the window width. A Stream Deck XL needs 726 px and
  had only 564, so two of its eight columns were cut off; keys now shrink
  down to a readable size and the area scrolls below that
- The touchstrip is exactly as wide as the key grid above it and shrinks
  along with it, instead of standing at a fixed 532 px
- The window starts at 1760×980 and cannot be pulled below 1400×760 — a
  Stream Deck+ with its dials needs that much before anything has to scroll
- Old states are cleaned up automatically: kept for a week, the last day
  hourly, older days once each
- The **default icon set** setting is gone. The built-in symbols — folder,
  back, menu — belong to the program and always come from Tabler now.
  Uploaded icon sets are for the keys and are picked per assignment
- The background editor lost its **kind** dropdown; the tiles cover every
  kind, including a new one for your own image, and the active one is marked

### Fixed

- The window no longer fails to open on Wayland with NVIDIA. The first
  attempt is measured, and if it dies within seconds the window starts over
  with the DMABUF renderer off. The outcome is written down, so it happens
  only once per driver
- The AUR package installs the window through that same start script instead
  of calling the binary directly, and keeps the binary under `/usr/lib`
  where its file name still matches `StartupWMClass`
- Keys no longer draw a dark gap between the tile and its own coloured
  frame — the ring for hover, selection and drop no longer takes up space
- Empty keys drew two outlines at once

## 1.1.0 — 24 August 2026

### New

- Plugins are installed from the built-in store
- Store ratings: thumbs up or down, one vote per account
- Plugin cards show when a newer version is in the store, and can
  update all of them at once
- Profiles can be created, copied and switched. On KDE they follow the
  program in the foreground if you want them to
- Volume can be set to a fixed percentage

### Fixed

- On a fresh install the deck settings could not be changed while no
  device was plugged in
- Twitch and YouTube logins were lost after a restart
- Links in hint texts are clickable

## 1.0.0 — 19 August 2026

First release.

- Keys and dials, pages and folders, multi-actions
- Built-in plugins: audio, multimedia, soundboard, system, streamdeck
- Plugins to install: OBS, Spotify, Discord, weather, clock screensaver
- Screensavers, wallpapers, custom key images
- Virtual decks as an overlay, network decks
- Plugin store to browse, install and submit
- AUR package
