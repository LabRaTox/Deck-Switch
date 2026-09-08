# Changelog

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
