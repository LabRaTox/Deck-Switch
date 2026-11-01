#!/usr/bin/env sh
#
# Removes DECK//SWITCH again, the counterpart to scripts/install.sh.
#
#   ./scripts/delete.sh               remove the program, keep settings and data
#   ./scripts/delete.sh --all         also delete settings, images and plugins
#   ./scripts/delete.sh --all --yes   the same without asking
#
# Stops the service and removes the menu entry and the streamdeck:// handler.
# The program folder only goes if it is the installed one: run from a source
# checkout, this leaves the checkout alone. DECKSWITCH_INSTALL_DIR names the
# folder if it was set for the installation.
#
# Only touches the home folder. The udev rule, the group membership and system
# packages stay, the last lines say how to remove them.
#
# Everything sits in main: the script deletes itself, and a shell reads a
# script piece by piece.

set -eu

log() { printf '\033[1;36m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m!! \033[0m %s\n' "$*" >&2; }
fail() { printf '\033[1;31m!! \033[0m %s\n' "$*" >&2; exit 1; }

main() {
    all=0
    yes=0
    for arg in "$@"; do
        case "$arg" in
            --all) all=1 ;;
            --yes) yes=1 ;;
            *) fail "unknown option: $arg" ;;
        esac
    done

    repo=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd -P)
    data="${XDG_DATA_HOME:-$HOME/.local/share}/deckswitch"
    config="${XDG_CONFIG_HOME:-$HOME/.config}/deckswitch"
    target="${DECKSWITCH_INSTALL_DIR:-$data/app}"
    target=$(CDPATH='' cd -- "$target" 2>/dev/null && pwd -P) || target=""

    if [ "$all" = 1 ] && [ "$yes" = 0 ]; then
        printf 'This deletes your settings, images and plugins in\n  %s\n  %s\n' "$config" "$data"
        (: </dev/tty) 2>/dev/null || fail "no terminal to ask on, use --all --yes"
        printf 'Type yes to go on: '
        read -r answer </dev/tty
        [ "$answer" = "yes" ] || fail "nothing deleted"
    fi

    # Without a user session systemctl fails, the rest still has to happen.
    "$repo/scripts/install-service.sh" --remove || warn "could not remove the service"
    "$repo/scripts/install-desktop-entry.sh" --remove
    "$repo/scripts/install-url-handler.sh" --remove

    # The folder about to go must not be the current one.
    cd /
    if [ "$repo" = "$target" ]; then
        rm -rf -- "$repo"
        log "Program removed"
    else
        warn "kept ${repo}: this is not the installed program"
    fi

    if [ "$all" = 1 ]; then
        rm -rf -- "$data" "$config"
        log "Settings, images and plugins deleted"
    else
        log "Your settings stay in ${config}, your images and plugins in ${data}"
    fi

    cat <<HINWEIS

Left in place, because removing them needs root:
  sudo rm /etc/udev/rules.d/70-streamdeck.rules
  sudo gpasswd -d $(id -un) input
System packages installed for DECK//SWITCH or its plugins stay as well.
HINWEIS
}

main "$@"
