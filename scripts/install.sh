#!/usr/bin/env bash
#
# DECK//SWITCH installer. One run should leave a working installation with
# nothing left to do by hand:
#
#   - fetches the finished window, interface and wheels of this version
#   - installs what the system lacks, asks for the password once, for all of it
#   - sets up the Python environment
#   - builds the window in a git checkout, if the toolchain is there
#   - gives access to the Stream Deck and the virtual keyboard
#   - adds the menu entry and the streamdeck:// links
#   - starts the backend, now and at every login
#
# Works on Arch, Debian, Ubuntu and Fedora. Running it again is safe.
#
# Options:
#   --no-root       change nothing that needs root, print what is left instead
#   --no-download   take nothing from the release, build everything here
#   --no-start      install everything, but do not start the service
#   --no-autostart  start now, but not at the next login

set -euo pipefail

REPO=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$REPO"

DO_ROOT=1
DO_DOWNLOAD=1
DO_START=1
DO_ENABLE=1
for arg in "$@"; do
    case "$arg" in
        --no-root) DO_ROOT=0 ;;
        --no-download) DO_DOWNLOAD=0 ;;
        --no-start) DO_START=0 ;;
        --no-autostart) DO_ENABLE=0 ;;
        -h|--help) sed -n '2,20p' "$0" | sed 's/^# \?//'; exit 0 ;;
        *) printf 'unknown option: %s\n' "$arg" >&2; exit 2 ;;
    esac
done

log() { printf '\033[1;36m==>\033[0m %s\n' "$*"; }
step() { printf '\n\033[1;36m==>\033[0m \033[1m%s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m!! \033[0m %s\n' "$*" >&2; }
fail() { printf '\033[1;31m!! \033[0m %s\n' "$*" >&2; exit 1; }

#: Wheels aus dem Release passen nur zu genau dieser Python-Fassung.
PYTHON_VERSION="3.13"
VERSION=$(sed -n 's/^__version__ = "\(.*\)"$/\1/p' backend/deckswitch/__init__.py)
BINARY="gui/src-tauri/target/release/deckswitch"
WHEELS=".wheels"

#: Unterwegs gesammelt und am Ende wiederholt, damit eine Warnung aus Schritt
#: zwei nicht weggescrollt ist.
NOTES=()
note() { NOTES+=("$1"); warn "$1"; }

# ---------------------------------------------------------------- Pakete

# Laufzeit: USB, Rendering, Tastatur, Klang, Fenster, Overlay, Schrift.
# Bau: nur nötig, wenn evdev und xkbcommon nicht fertig aus dem Release kommen.
# 64-Bit-time_t hat unter Debian und Ubuntu Bibliotheken umbenannt, die alten
# Namen lassen sich dort nicht mehr installieren. Deshalb wird nachgesehen.
if command -v pacman >/dev/null; then
    FAMILY=arch
    RUNTIME="hidapi libusb cairo libxkbcommon noto-fonts wireplumber libpulse pipewire-audio qt6-declarative layer-shell-qt webkit2gtk-4.1 xdg-utils curl"
    BUILD="gcc pkgconf linux-api-headers"
elif command -v apt-get >/dev/null; then
    FAMILY=debian
    RUNTIME="libhidapi-libusb0 libusb-1.0-0 libcairo2 libxkbcommon0 fonts-noto-core wireplumber pulseaudio-utils pipewire-bin qml-qt6 qt6-qpa-plugins qml6-module-qtquick qml6-module-qtquick-window qml6-module-qtqml-workerscript qml6-module-org-kde-layershell libwebkit2gtk-4.1-0 libayatana-appindicator3-1 xdg-utils curl"
    BUILD="gcc libc6-dev linux-libc-dev pkg-config libxkbcommon-dev"
elif command -v rpm-ostree >/dev/null && [ -e /run/ostree-booted ]; then
    FAMILY=ostree
    RUNTIME="hidapi wireplumber pipewire-utils pulseaudio-utils webkit2gtk4.1 qt6-qtdeclarative-devel layer-shell-qt"
    BUILD="gcc kernel-headers pkgconf-pkg-config libxkbcommon-devel"
elif command -v dnf >/dev/null; then
    FAMILY=fedora
    RUNTIME="hidapi libusb1 cairo libxkbcommon google-noto-sans-fonts wireplumber pipewire-utils pulseaudio-utils qt6-qtdeclarative-devel layer-shell-qt webkit2gtk4.1 libayatana-appindicator-gtk3 xdg-utils curl"
    BUILD="gcc glibc-devel kernel-headers pkgconf-pkg-config libxkbcommon-devel"
else
    FAMILY=unknown
    RUNTIME=""
    BUILD=""
fi

# Was davon fehlt. Unbekannte Namen fallen unter Debian heraus: Ubuntu 22.04
# hat zum Beispiel kein layer-shell-qt, und ein einziger unbekannter Name ließe
# apt alles abbrechen. Das Overlay fehlt dann eben, die Sitzungsanzeige sagt es.
missing_packages() {
    local name
    for name in "$@"; do
        case "$FAMILY" in
            arch) pacman -Q "$name" >/dev/null 2>&1 || echo "$name" ;;
            debian)
                if ! dpkg-query -W -f='${Status}' "$name" 2>/dev/null | grep -q "ok installed" &&
                   apt-cache show "$name" >/dev/null 2>&1; then
                    echo "$name"
                fi
                ;;
            fedora|ostree) rpm -q "$name" >/dev/null 2>&1 || echo "$name" ;;
        esac
    done
}

# ---------------------------------------------------------- Prüfen und laden

step "Checking what is here"
log "system: ${FAMILY}"
[ "$FAMILY" != unknown ] || note "unknown distribution, install the equivalents by hand:
    hidapi, libusb, cairo, libxkbcommon, wireplumber, pipewire, webkit2gtk-4.1"

if ! command -v uv >/dev/null; then
    [ -x "${HOME}/.local/bin/uv" ] || fail "'uv' not found. Install it with: curl -LsSf https://astral.sh/uv/install.sh | sh"
    PATH="${HOME}/.local/bin:${PATH}"
fi
log "uv: $(command -v uv)"

step "Finished files of version ${VERSION}"
RELEASE=""
DOWNLOAD=$(mktemp -d)
ROOT_SCRIPT=$(mktemp)
trap 'rm -rf "$DOWNLOAD" "$ROOT_SCRIPT"' EXIT
if [ "$DO_DOWNLOAD" = 1 ]; then
    if ./scripts/fetch-release.sh "$VERSION" "$DOWNLOAD" 2>/dev/null; then
        log "downloaded"
        RELEASE=$DOWNLOAD
        rm -rf "$WHEELS"
        cp -a "${RELEASE}/wheels" "$WHEELS"
    else
        log "none for this version, building here instead"
    fi
else
    log "skipped (--no-download)"
fi

# ---------------------------------------------------------------------- root

# Alles, was root braucht, landet in einem Skript: So fragt das Passwort
# einmal und nicht drei Mal, und wer es nicht geben will, bekommt alles auf
# einmal zu lesen.
step "System packages and device access"

NEEDED=$RUNTIME
[ -n "$RELEASE" ] || NEEDED="$NEEDED $BUILD"
# shellcheck disable=SC2086
MISSING=$(missing_packages $NEEDED | tr '\n' ' ')
MISSING=${MISSING% }

# Ohne Paketlisten kennt apt-cache gar nichts, und alles fiele aus dem Filter.
if [ "$FAMILY" = debian ] && ! ls /var/lib/apt/lists/*_Packages* >/dev/null 2>&1; then
    note "apt has no package lists yet, run 'sudo apt update' and this installer again"
fi

{
    echo "set -e"
    if [ -n "$MISSING" ]; then
        case "$FAMILY" in
            arch) echo "pacman -S --needed --noconfirm $MISSING" ;;
            debian)
                echo "apt-get update -qq"
                echo "DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends $MISSING"
                ;;
            fedora) echo "dnf install -y --skip-unavailable $MISSING" ;;
        esac
    fi
    if ! cmp -s packaging/70-streamdeck.rules /etc/udev/rules.d/70-streamdeck.rules; then
        echo "install -D -m 644 '${REPO}/packaging/70-streamdeck.rules' /etc/udev/rules.d/70-streamdeck.rules"
        # Im Container gibt es kein udev, das ist kein Grund abzubrechen.
        echo "udevadm control --reload-rules 2>/dev/null || true"
        echo "udevadm trigger --subsystem-match=usb --subsystem-match=hidraw --subsystem-match=misc 2>/dev/null || true"
    fi
    if ! id -nG | tr ' ' '\n' | grep -qx input; then
        # Fast überall legt udev die Gruppe an, verlassen kann man sich nicht.
        # -f: Gibt es sie schon, ist das kein Fehler.
        echo "groupadd -rf input"
        echo "usermod -aG input '$(id -un)'"
    fi
} > "$ROOT_SCRIPT"

# Ein Image lässt sich nicht vom Skript aus ändern, Pakete kommen dort erst
# mit dem nächsten Start an.
if [ "$FAMILY" = ostree ] && [ -n "$MISSING" ]; then
    note "this system boots an image, install the packages yourself and restart:
    sudo rpm-ostree install ${MISSING}"
fi

if [ "$(wc -l < "$ROOT_SCRIPT")" -le 1 ]; then
    log "nothing to do"
elif [ "$DO_ROOT" = 0 ]; then
    note "skipped (--no-root), this is left to run as root:
$(sed -e '1d' -e 's/^/    /' "$ROOT_SCRIPT")"
else
    [ -z "$MISSING" ] || log "installing: ${MISSING}"
    log "changing the system, this needs your password once"
    IN_GROUP_BEFORE=$(grep -c usermod "$ROOT_SCRIPT" || true)
    if [ "$(id -u)" = 0 ]; then
        sh "$ROOT_SCRIPT" && ROOT_OK=1 || ROOT_OK=0
    elif [ -t 0 ] && command -v sudo >/dev/null; then
        sudo sh "$ROOT_SCRIPT" && ROOT_OK=1 || ROOT_OK=0
    elif sudo -n true 2>/dev/null; then
        sudo -n sh "$ROOT_SCRIPT" && ROOT_OK=1 || ROOT_OK=0
    elif command -v pkexec >/dev/null && [ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]; then
        pkexec sh "$ROOT_SCRIPT" && ROOT_OK=1 || ROOT_OK=0
    else
        ROOT_OK=0
    fi
    if [ "$ROOT_OK" = 1 ]; then
        log "done"
        [ "$IN_GROUP_BEFORE" = 0 ] || note "hotkeys and 'type text' work after your next login, the 'input' group takes effect then"
        note "if the Stream Deck is plugged in, unplug it and plug it back in once"
    else
        note "this could not run as root. Run it yourself, then run this installer again:
$(sed -e '1d' -e 's/^/    sudo /' "$ROOT_SCRIPT")"
    fi
fi

# --------------------------------------------------------------------- Python

step "Python environment"
if [ ! -x .venv/bin/python ]; then
    # Festgelegt, weil uv sonst die neueste Fassung nimmt, für die es noch
    # keine fertigen Pakete gibt.
    uv venv --quiet --python "$PYTHON_VERSION" .venv
    log "created on Python ${PYTHON_VERSION}"
fi
# Die Wheels zuerst: Danach sieht die Auflösung beide Pakete als erfüllt an und
# greift nicht zum Quellarchiv, das einen Compiler bräuchte. Passt die venv
# nicht, etwa eine ältere auf anderer Python, baut die Auflösung wie gehabt.
if [ -d "$WHEELS" ]; then
    uv pip install --quiet --python .venv/bin/python --no-deps "$WHEELS"/*.whl 2>/dev/null ||
        log "the finished wheels do not fit this Python, building them"
fi
# xkbcommon folgt der Fassung der Bibliothek: Ab 1.5 kompiliert es nicht gegen
# eine ältere, wie sie Ubuntu 22.04 hat. Zählt nur, wenn hier gebaut wird.
PIN=()
if ! .venv/bin/python -c "import xkbcommon" 2>/dev/null &&
   command -v pkg-config >/dev/null && ! pkg-config --atleast-version=1.5 xkbcommon; then
    PIN=("xkbcommon<1.5")
fi
uv pip install --quiet --python .venv/bin/python -e backend "${PIN[@]}"
log "backend dependencies ready"

# --------------------------------------------------------------------- Fenster

step "Application window"
# Im Git-Checkout wird gebaut, wer daran arbeitet, will seinen eigenen Stand.
if [ -d .git ] && command -v npm >/dev/null && command -v cargo >/dev/null; then
    if [ -x "$BINARY" ] && [ "$BINARY" -nt gui/package.json ] && [ -d gui/dist ]; then
        log "already built"
    else
        log "building, the first time takes a few minutes"
        (cd gui && npm install --silent && npx tauri build --no-bundle) ||
            note "the window failed to build, http://127.0.0.1:8770 works anyway"
    fi
elif [ -n "$RELEASE" ]; then
    mkdir -p "$(dirname "$BINARY")"
    install -m755 "${RELEASE}/deckswitch" "$BINARY"
    rm -rf gui/dist
    cp -a "${RELEASE}/dist" gui/dist
    log "taken from the release"
elif command -v npm >/dev/null && command -v cargo >/dev/null; then
    log "building, the first time takes a few minutes"
    (cd gui && npm install --silent && npx tauri build --no-bundle) ||
        note "the window failed to build, and the interface with it"
else
    note "this version has no finished window, and building one takes npm and cargo"
fi

# Eine geladene Datei bringt ihren Code mit, nicht ihre Bibliotheken.
if [ -x "$BINARY" ] && ldd "$BINARY" 2>/dev/null | grep -q "not found"; then
    note "the window is missing a library: $(ldd "$BINARY" | awk '/not found/ {print $1}' | head -3 | tr '\n' ' ')"
fi

# --------------------------------------------------------------------- Desktop

step "Desktop integration"
./scripts/install-desktop-entry.sh >/dev/null && log "menu entry added" ||
    note "the menu entry could not be added"
./scripts/install-url-handler.sh >/dev/null 2>&1 && log "streamdeck:// links registered" ||
    note "streamdeck:// links could not be registered"

# ---------------------------------------------------------------------- Dienst

step "Service"
if [ "$DO_START" = 0 ]; then
    log "not started (--no-start)"
elif ! systemctl --user show-environment >/dev/null 2>&1; then
    note "no systemd user session, start it yourself: ./scripts/start-backend.sh"
elif [ "$DO_ENABLE" = 0 ]; then
    ./scripts/install-service.sh --no-enable >/dev/null
    log "running, but not at the next login (--no-autostart)"
else
    ./scripts/install-service.sh >/dev/null
    log "running, and again at every login"
fi

# ---------------------------------------------------------------------- Ende

printf '\n\033[1;32m==>\033[0m \033[1mInstallation complete.\033[0m\n\n'
printf '  Open it    "DECK//SWITCH" in the application menu\n'
printf '  In a browser  http://127.0.0.1:8770\n'
printf '  Logs       journalctl --user -u deckswitch -f\n'

if [ ${#NOTES[@]} -gt 0 ]; then
    printf '\n\033[1;33m%s point(s) worth reading:\033[0m\n' "${#NOTES[@]}"
    for n in "${NOTES[@]}"; do printf '  - %s\n' "$n"; done
fi
printf '\n'
