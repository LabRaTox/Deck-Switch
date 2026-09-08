#!/usr/bin/env sh
#
# One-time setup: check system packages, create the venv, install
# dependencies, build the GUI, install the udev rule.
#
#   ./scripts/setup.sh
#
# Targets CachyOS and Arch Linux only, so pacman is assumed. POSIX sh
# rather than fish: which login shell the user prefers is not this script's
# business, and /bin/sh is guaranteed to exist.

set -eu

REPO=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
cd "$REPO"

step() { printf '\n\033[36m▶ %s\033[0m\n' "$1"; }
ok()   { printf '\033[32m  ✔ %s\033[0m\n' "$1"; }
warn() { printf '\033[33m  ! %s\033[0m\n' "$1"; }
fail() { printf '\033[31m  ✘ %s\033[0m\n' "$1"; }

ask() {
    # Ask a question; assume the default when running non-interactively.
    #
    # $1 the question, $2 the default: "y" means a bare Enter counts as yes.
    # Without that second argument a "[Y/n]" prompt would quietly turn every
    # Enter into a no — exactly the wrong answer for the udev rule.
    if [ ! -t 0 ]; then return 1; fi
    printf '  %s ' "$1"
    read -r answer
    case "$answer" in
        [yYjJ]*) return 0 ;;
        "")      [ "${2:-n}" = y ] ;;
        *)       return 1 ;;
    esac
}

# --------------------------------------------------------------- Packages

step "Checking system packages"

if ! command -v pacman >/dev/null 2>&1; then
    fail "pacman not found."
    echo "  This project targets CachyOS and Arch Linux. On another"
    echo "  distribution, install the equivalents of these by hand and"
    echo "  skip this script:"
    echo "    python, nodejs, npm, rust, base-devel, webkit2gtk-4.1,"
    echo "    hidapi, libusb, noto-fonts, wireplumber, libpulse,"
    echo "    libxkbcommon, pipewire-audio"
    exit 1
fi

# libxkbcommon: Zeichen → Taste für „Text tippen" und Tastenkombinationen.
# pipewire-audio: pw-play für das Soundboard.
# qt6-declarative + layer-shell-qt: das virtuelle Deck als Overlay.
# cairo: cairosvg lädt libcairo.so.2 zur Laufzeit. Auf einem Desktop-System
#   ist es über andere Pakete längst da — auf einer schlanken Installation
#   nicht, und dann startet das Backend nicht.
PACKAGES="python webkit2gtk-4.1 base-devel rust hidapi libusb nodejs npm noto-fonts wireplumber libpulse libxkbcommon pipewire-audio qt6-declarative layer-shell-qt cairo"

MISSING=""
for pkg in $PACKAGES; do
    pacman -Q "$pkg" >/dev/null 2>&1 || MISSING="$MISSING $pkg"
done

if [ -n "$MISSING" ]; then
    warn "Missing:$MISSING"
    echo "  Install with:"
    printf '    sudo pacman -S --needed%s\n' "$MISSING"
    if ask "Install now? [y/N]"; then
        # shellcheck disable=SC2086
        sudo pacman -S --needed $MISSING
    else
        warn "Skipped — the build may fail without these packages."
    fi
else
    ok "All required packages present"
fi

for tool in wpctl pactl; do
    command -v "$tool" >/dev/null 2>&1 || \
        warn "$tool not found — the audio plugin will be limited"
done

# ------------------------------------------------------ Python environment

step "Setting up the Python environment"
if [ ! -d .venv ]; then
    python3 -m venv .venv
    ok ".venv created"
else
    ok ".venv already exists"
fi

# The venv is never activated — the direct path works in any shell.
./.venv/bin/pip install --quiet --upgrade pip
./.venv/bin/pip install --quiet -e backend
ok "Backend dependencies installed"

# --------------------------------------------------------------------- GUI

step "Building the GUI"
if command -v npm >/dev/null 2>&1; then
    (cd gui && npm install --silent && npm run build)
    ok "GUI built into gui/dist"
else
    fail "npm is missing — cannot build the GUI"
fi

# ------------------------------------------------------------ Tauri window

step "Building the application window"
# Das Fenster ist der reguläre Weg in die Anwendung, also gehört sein Bau
# ins Setup. Sonst baut ihn der erste Klick im Anwendungsmenü — minutenlang
# und ohne sichtbare Rückmeldung.
if [ -x gui/src-tauri/target/release/deckswitch ]; then
    ok "Window already built"
else
    echo "  The first Rust build takes a few minutes."
    # Scheitert der Bau — kein Rust, abgebrochene Installation, kein Netz —
    # ist das ärgerlich, aber kein Grund, hier stehenzubleiben: Danach kommt
    # die udev-Regel, und ohne die gehört das Deck root. Also weitermachen
    # und am Ende sagen, was fehlt.
    if (cd gui && npx tauri build --no-bundle); then
        ok "Window built into gui/src-tauri/target/release"
    else
        warn "Window could not be built — the browser interface works anyway."
        echo "  Retry later with:  ./scripts/start-gui.sh"
    fi
fi

# -------------------------------------------------------------------- udev

step "Device access (udev)"
if [ -f /etc/udev/rules.d/70-streamdeck.rules ]; then
    ok "udev rule already installed"
else
    echo "  Without the udev rule the Stream Deck is only reachable as root."
    if ask "Install the rule now (needs sudo)? [Y/n]" y || [ ! -t 0 ]; then
        sudo install -m 644 packaging/70-streamdeck.rules /etc/udev/rules.d/
        sudo udevadm control --reload-rules
        sudo udevadm trigger --subsystem-match=usb --subsystem-match=hidraw
        ok "Rule installed — unplug and replug the Stream Deck once"
    fi
fi

# ------------------------------------------------------------ Input group

step "Keyboard input (uinput)"
# Die udev-Regel oben gibt der Gruppe `input` Zugriff auf /dev/uinput. Wer
# nicht in der Gruppe ist, hat davon nichts: Die virtuelle Tastatur hinter
# „Tastenkombination" und „Text tippen" bleibt dann stumm. Das AUR-Paket
# sagt das nach der Installation; hier stand es bisher nirgends.
if id -nG 2>/dev/null | tr ' ' '\n' | grep -qx input; then
    ok "You are in the 'input' group"
else
    echo "  Hotkeys and 'type text' need /dev/uinput, which belongs to the"
    echo "  'input' group. Without it those actions stay silent."
    if ask "Add $(id -un) to the group now (needs sudo)? [Y/n]" y || [ ! -t 0 ]; then
        sudo usermod -aG input "$(id -un)"
        warn "Group added — takes effect after your next login"
    else
        warn "Skipped — hotkeys and 'type text' will not work yet"
    fi
fi

# ----------------------------------------------------------------- Desktop

step "Application menu"
# Braucht kein sudo — Eintrag und Symbol landen unter ~/.local/share.
sh "$REPO/scripts/install-desktop-entry.sh" >/dev/null
ok "DECK//SWITCH is in the application menu"

# Registriert streamdeck://-Adressen. Installiert wird davon nichts von
# allein: Der Handler reicht die Anfrage ans Backend weiter, das sie in der
# Oberfläche zur Bestätigung vorlegt.
sh "$REPO/scripts/install-url-handler.sh" >/dev/null 2>&1 \
    && ok "streamdeck:// links are registered" \
    || warn "streamdeck:// could not be registered (xdg-utils missing?)"

# ------------------------------------------------------------- Autostart

step "Start at login"
# Anders als alles davor ist das eine Geschmacksfrage, keine Voraussetzung —
# deshalb ist die Vorgabe hier „nein". Dieselbe Unit legt auch der Schalter
# in den Einstellungen an.
if systemctl --user is-enabled deckswitch.service >/dev/null 2>&1; then
    ok "Service is already set up"
elif ! command -v systemctl >/dev/null 2>&1; then
    warn "systemd not found — skipping"
else
    echo "  Starts the backend automatically when you log in."
    if ask "Set that up now? [y/N]"; then
        sh "$REPO/scripts/install-service.sh" >/dev/null
        ok "Service installed and started"
    else
        echo "  Later with:  ./scripts/install-service.sh"
    fi
fi

# -------------------------------------------------------------------- Done

step "Done"
echo "  Start the backend:  ./scripts/start-backend.sh"
echo "  GUI in a browser:   http://127.0.0.1:8770"
echo "  GUI as a window:    ./scripts/start-gui.sh"
echo "  Start at login:     ./scripts/install-service.sh"
echo "  Menu entry away:    ./scripts/install-desktop-entry.sh --remove"
echo "  URL handler away:   ./scripts/install-url-handler.sh --remove"
