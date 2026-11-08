#!/usr/bin/env bash
#
# Installs or updates DECK//SWITCH from the newest release, for systems
# without the Arch package:
#
#   curl -fsSL https://raw.githubusercontent.com/LabRaTox/Deck-Switch/main/scripts/get.sh | bash
#
# Fetches uv if it is missing, unpacks the release and hands over to
# scripts/install.sh, which does the rest. Run it again to update: settings
# and the virtualenv stay, the code is replaced.
#
#   DECKSWITCH_INSTALL_DIR   where it goes, ~/.local/share/deckswitch/app if unset
#   DECKSWITCH_VERSION       a release such as 1.4.1, the newest if unset
#   DECKSWITCH_REPOSITORY    where releases come from, for testing
#
# Everything sits in main, so a download cut off halfway runs nothing.

set -euo pipefail

#: What a release replaces. Everything else in the folder stays, the
#: virtualenv above all.
CODE_DIRS=(backend docs gui packaging scripts)

log() { printf '\033[1;36m==>\033[0m %s\n' "$*"; }
fail() { printf '\033[1;31m!! \033[0m %s\n' "$*" >&2; exit 1; }

main() {
    local repository="${DECKSWITCH_REPOSITORY:-https://github.com/LabRaTox/Deck-Switch}"
    local target="${DECKSWITCH_INSTALL_DIR:-${XDG_DATA_HOME:-$HOME/.local/share}/deckswitch/app}"
    local version="${DECKSWITCH_VERSION:-}"

    [ "$(uname -m)" = "x86_64" ] || fail "only x86_64 has releases, this is $(uname -m)"
    # The uv installer and install.sh need these too, a minimal system can lack
    # any of them. Better to name it here than to fail on a checksum later.
    local tool
    for tool in curl tar gzip awk sha256sum; do
        command -v "$tool" >/dev/null || fail "${tool} is needed, install it with your package manager"
    done

    if ! command -v uv >/dev/null && [ ! -x "${HOME}/.local/bin/uv" ]; then
        log "installing uv"
        # Fest nach ~/.local/bin: Mit gesetztem XDG_BIN_HOME oder
        # XDG_DATA_HOME legte der Installer uv sonst woanders ab.
        curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR="${HOME}/.local/bin" sh >/dev/null
    fi
    export PATH="${HOME}/.local/bin:${PATH}"
    command -v uv >/dev/null || fail "uv could not be installed"

    if [ -z "$version" ]; then
        # The redirect to the newest tag, which unlike the API has no rate limit.
        local latest
        latest=$(curl -fsSLo /dev/null -w '%{url_effective}' "${repository}/releases/latest")
        version="${latest##*/v}"
    fi
    case "$version" in
        [0-9]*.[0-9]*) ;;
        *) fail "no release found (got '${version}')" ;;
    esac
    log "DECK//SWITCH ${version} into ${target}"

    # Nur einen leeren Ordner oder eine frühere Installation anfassen. Gleich
    # werden darin Ordner gelöscht, und delete.sh entfernt ihn später ganz.
    case "$(cd "$target" 2>/dev/null && pwd -P || echo "$target")" in
        / | "$HOME" | "$(cd "$HOME" && pwd -P)") fail "${target} cannot be the install folder" ;;
    esac
    if [ -d "$target" ] && [ -n "$(ls -A "$target" 2>/dev/null)" ] &&
       [ ! -f "${target}/backend/deckswitch/__init__.py" ]; then
        fail "${target} is not empty and holds no DECK//SWITCH, choose another folder"
    fi

    # Die fertigen Dateien entstehen erst nach dem Veröffentlichen. Fehlen sie
    # noch, bliebe nach dem Löschen unten kein Fenster und keine Oberfläche.
    local asset="${repository}/releases/download/v${version}/deckswitch-${version}-x86_64-linux.tar.gz"
    if ! curl -fsSLI -o /dev/null "$asset"; then
        fail "the files of version ${version} are not ready yet, try again in a few minutes"
    fi

    # Nicht lokal: Die Falle läuft erst, wenn main längst zurück ist.
    WORK=$(mktemp -d)
    trap 'rm -rf "$WORK"' EXIT
    curl -fsSL -o "${WORK}/source.tar.gz" "${repository}/archive/refs/tags/v${version}.tar.gz"
    tar -C "$WORK" -xzf "${WORK}/source.tar.gz" --strip-components=1
    [ -f "${WORK}/scripts/install.sh" ] || fail "the release has no scripts/install.sh"
    rm -f "${WORK}/source.tar.gz"

    mkdir -p "$target"
    local dir
    for dir in "${CODE_DIRS[@]}"; do
        rm -rf "${target:?}/${dir}"
    done
    cp -a "${WORK}/." "$target/"

    cd "$target"
    # Under `curl | bash` stdin is this script. The password prompt talks to
    # the terminal, so hand that over when there is one.
    if (: </dev/tty) 2>/dev/null; then
        ./scripts/install.sh "$@" </dev/tty
    else
        ./scripts/install.sh "$@" </dev/null
    fi
}

main "$@"
