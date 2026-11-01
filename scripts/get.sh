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
    command -v curl >/dev/null || fail "curl is needed"
    command -v tar >/dev/null || fail "tar is needed"

    if ! command -v uv >/dev/null && [ ! -x "${HOME}/.local/bin/uv" ]; then
        log "installing uv"
        curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null
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
