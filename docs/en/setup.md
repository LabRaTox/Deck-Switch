# Installation and setup

*[Deutsche Fassung](../de/setup.md)* · Back to the
[overview](../../README.md).

## With one command (all distributions)

```sh
curl -fsSL https://raw.githubusercontent.com/LabRaTox/Deck-Switch/main/scripts/get.sh | bash
```

This fetches `uv` if it is missing, unpacks the newest release into
`~/.local/share/deckswitch/app` and starts the installer. It needs no Node, no
Rust and no compiler, the window and the interface come finished with the
release. It asks for your password once, for everything that needs root:
missing system packages, the udev rule and the `input` group. After that the
backend runs, now and at every login, and DECK//SWITCH is in the application
menu. Run the same command again to update, the settings stay.

The menu entry *Help* in the window leads to the repository, the Discord
community and the *About* page with the version.

To remove it again:

```sh
~/.local/share/deckswitch/app/scripts/delete.sh
```

Your settings stay in `~/.config/deckswitch/`, your images and plugins in
`~/.local/share/deckswitch/`. With `--all` they go as well, after a question.

Runs through on Arch, Debian 12 and 13, Ubuntu 22.04, 24.04 and 25.04,
Fedora 42 and 43, openSUSE Tumbleweed and Leap 15.6. On an
image-based Fedora such as Bazzite the installer names the `rpm-ostree` command
instead, because a package only arrives there with the next boot. Without a
`layer-shell`, as on GNOME or Ubuntu, the virtual deck runs over XWayland
instead, and it keeps out of the task list and of your keyboard focus just the
same.

On Arch and CachyOS the package below is the better way, because pacman then
manages it.

## Arch and CachyOS

DECK//SWITCH is not in the AUR yet, the package is attached to the GitHub
release. It puts the udev rule and the systemd unit where they belong.

The library for the Deck comes first, because it only exists in the AUR. With
`paru` or `yay`, `paru -S python-elgato-streamdeck` is enough, otherwise:

```sh
git clone https://aur.archlinux.org/python-elgato-streamdeck.git
cd python-elgato-streamdeck
makepkg -si
cd ..
```

Then download and install the package. Passing the address straight to
`pacman -U` does not work, pacman looks for a signature there:

```sh
curl -fLO https://github.com/LabRaTox/Deck-Switch/releases/download/v1.4.2/deckswitch-1.4.2-1-x86_64.pkg.tar.zst
sudo pacman -U ./deckswitch-1.4.2-1-x86_64.pkg.tar.zst
systemctl --user enable --now deckswitch.service
```

Then add yourself to the `input` group once and log in again. You need it for
the actions *Hotkey* and *Type text*:

```sh
sudo usermod -aG input "$USER"
```

To update, download the new package file and install it the same way. Building
it yourself works too, the library has to be there for that as well:

```sh
git clone https://github.com/LabRaTox/Deck-Switch.git
cd Deck-Switch/packaging/aur
makepkg -si
```

## From the repository

For hacking on it:

```sh
git clone https://github.com/LabRaTox/Deck-Switch.git
cd Deck-Switch
./scripts/install.sh
```

`install.sh` does the same as the one-line install, with one difference. It
does not fetch `uv`. If `uv` is missing, it stops and prints the command to
install it. In a git checkout it builds the window itself if `npm` and
`cargo` are there. Running it again is safe.

| Option | |
| --- | --- |
| `--no-root` | change nothing that needs root, print what is left instead |
| `--no-download` | take nothing from the release, build everything here |
| `--no-start` | install everything, but do not start the service |
| `--no-autostart` | start now, but not at the next login |

The interface then runs at <http://127.0.0.1:8770>, or as its own window:

```sh
./scripts/start-gui.sh
```

## Device access (udev)

Without the udev rule the HID node belongs to root, so only root could talk
to the device. `install.sh` sets it up; by hand it goes like this:

```sh
sudo install -m 644 packaging/70-streamdeck.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules
sudo udevadm trigger --subsystem-match=usb --subsystem-match=hidraw --subsystem-match=misc
```

Then unplug the Stream Deck once and plug it back in.

The same rule also sets up access to `/dev/uinput`. That is the virtual
keyboard behind **hotkey** and **type text**. Your user needs to be in the
`input` group for it. `install.sh` adds you; by
hand it goes like this:

```sh
groups | grep -q input || sudo usermod -aG input "$USER"
```

Group membership only takes effect after your next login. You can see whether
it worked in the interface: the settings of a hotkey action spell out what is
missing.

## When the window does not open

On some drivers WebKitGTK and Wayland do not get along: the window closes
after half a second and the terminal says `Gdk-Message: Error 71 (protocol
error) dispatching to Wayland display`. With NVIDIA under KDE this happens
every time.

This is dealt with: if the first attempt dies right away, the window starts
over with the DMABUF renderer switched off. That lives in
`packaging/deckswitch-gui.sh`, the same script the package installs as
`deckswitch-gui` and that `scripts/start-gui.sh` calls in a checkout, so an
installed copy behaves exactly the same.

It only happens once, though. The outcome is written down, together with a
signature of the system, in

```
~/.cache/deckswitch/fensterstart
```

The signature holds the session type, the version of the NVIDIA kernel
module (or "no NVIDIA") and the WebKit version. As long as those three stay
the same, the window starts correctly right away, without the brief failed
attempt. If one of them changes, after an NVIDIA driver update for instance,
the note is discarded and measured again. An update of Mesa or of the AMD or
Intel driver does not change the signature and is not noticed. The note is
only written after the window has run for at least 5 seconds. Deleting the
file is harmless at any time.

To skip the detour from the start, set the switch yourself:

```sh
export WEBKIT_DISABLE_DMABUF_RENDERER=1
```

## In the application menu

`install.sh` creates the launcher along the way. By hand:

```sh
./scripts/install-desktop-entry.sh            # add it
./scripts/install-desktop-entry.sh --remove   # take it out again
```

Entry and icon go to `~/.local/share`, so no sudo is involved. The launcher
runs `scripts/start-gui.sh`, which brings the backend along if it isn't
running yet. It first tries `systemctl --user start deckswitch.service`.
Only if that fails does it start the backend itself, from the `.venv` of the
checkout or as `/usr/bin/deckswitch`. Started that way it keeps running after
the window closes, until you log out. The service below also starts it at
login, before any window, and restarts it after a crash. The Arch package
ships the entry anyway.

## Start at login

The easiest way is the **Start at login** switch in the settings. It creates
the systemd service and turns it on or off. The same from the command line:

```sh
./scripts/install-service.sh               # set up, start now and at login
./scripts/install-service.sh --no-enable   # set up and start, but not at login
./scripts/install-service.sh --remove      # remove again
```

## Backup, restore, hand over

In the settings under **Backup & restore**:

| | |
| --- | --- |
| **Export configuration** | The configuration as JSON, small and readable, but without your uploaded images |
| **Backup archive** | Configuration *and* all your own images in one ZIP file. This is the one for a move or a real backup |
| **Earlier states** | Before every overwrite DECK//SWITCH keeps a copy of the configuration, at most one per hour. Each copy stays for 24 hours, after that only the last one of each day, and after 7 days it is deleted. At most thirty stay in total. This is the way back |

A single profile goes out through the profile manager: **Export** next to the
profile packs it together with the images used in it. **Import profile** adds
it on the other side, nothing is overwritten, and a name that already exists
gets a number.

Not included are the soundboard's sounds: you point at them by arbitrary
paths, so they live somewhere on your disk rather than in the application's
data directory. The references survive a backup, the files themselves you back
up like your other own files. Plugins you installed later are not included
either, get those from the store after restoring.
