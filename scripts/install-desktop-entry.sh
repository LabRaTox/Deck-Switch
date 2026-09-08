#!/usr/bin/env sh
#
# Legt den Programmstarter im Anwendungsmenü an — Eintrag und Symbol im
# Benutzerverzeichnis, ohne sudo.
#
#   ./scripts/install-desktop-entry.sh            eintragen
#   ./scripts/install-desktop-entry.sh --remove   wieder entfernen
#
# Das AUR-Paket bringt beides selbst mit. Wer aus dem Checkout arbeitet,
# hatte bis hierher gar nichts im Menü.

set -eu
REPO=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
APPS="$HOME/.local/share/applications"
ICONS="$HOME/.local/share/icons/hicolor"
ENTRY="$APPS/deckswitch.desktop"

# KDE führt einen eigenen Katalog der Desktop-Dateien. Ohne diesen Schritt
# kennt die Fensterleiste den Eintrag nicht und kann dem Fenster kein Symbol
# zuordnen. Muss laufen, *nachdem* die Datei geschrieben oder gelöscht wurde.
katalog_neu_lesen() {
    if command -v kbuildsycoca6 >/dev/null 2>&1; then
        kbuildsycoca6 >/dev/null 2>&1 || true
    fi
}

if [ "${1:-}" = "--remove" ]; then
    rm -f "$ENTRY"
    rm -f "$ICONS/scalable/apps/deckswitch.svg"
    for groesse in 32 128 256; do
        rm -f "$ICONS/${groesse}x${groesse}/apps/deckswitch.png"
    done
    update-desktop-database "$APPS" 2>/dev/null || true
    gtk-update-icon-cache -qtf "$ICONS" 2>/dev/null || true
    katalog_neu_lesen
    printf '\033[32m✔ Programmstarter entfernt\033[0m\n'
    exit 0
fi

# --------------------------------------------------------------- Symbole

# Das SVG ist die Vorlage, die PNGs sind für Menüs, die kein SVG mögen.
# Beide entstehen in scripts/make-icon.py; fehlt eines, wird es einfach
# übersprungen, statt die Installation abzubrechen.
if [ -f "$REPO/gui/public/icon.svg" ]; then
    install -Dm644 "$REPO/gui/public/icon.svg" "$ICONS/scalable/apps/deckswitch.svg"
fi
for groesse in 32 128; do
    QUELLE="$REPO/gui/src-tauri/icons/${groesse}x${groesse}.png"
    [ -f "$QUELLE" ] && install -Dm644 "$QUELLE" \
        "$ICONS/${groesse}x${groesse}/apps/deckswitch.png"
done
# Der Symbol-Zwischenspeicher lässt sich nur bauen, wo eine index.theme
# liegt — im Benutzerverzeichnis gibt es die in der Regel nicht. Eine eigene
# anzulegen wäre gefährlicher als nützlich: Sie würde die systemweite
# Theme-Beschreibung verdecken und könnte fremde Symbole unauffindbar
# machen. Ohne Zwischenspeicher wird das Verzeichnis eben direkt
# durchsucht; gefunden wird das Symbol so oder so.
if [ -f "$ICONS/index.theme" ]; then
    gtk-update-icon-cache -qtf "$ICONS" 2>/dev/null || true
fi

# ---------------------------------------------------------------- Eintrag

# start-gui.sh statt der Binärdatei: Es prüft, ob überhaupt gebaut wurde,
# und meldet ein fehlendes Backend, statt ein leeres Fenster zu zeigen.
mkdir -p "$APPS"
sed "s|__EXEC__|$REPO/scripts/start-gui.sh|" \
    "$REPO/packaging/deckswitch.desktop" > "$ENTRY"
update-desktop-database "$APPS" 2>/dev/null || true
katalog_neu_lesen

printf '\033[32m✔ Programmstarter angelegt\033[0m\n'
echo "  Eintrag: $ENTRY"
echo "  Start:   $REPO/scripts/start-gui.sh"

# Zwei Dinge fehlen dem Menüeintrag gern, und beide fallen erst beim
# Anklicken auf — deshalb hier schon sagen, was noch aussteht.
if [ ! -x "$REPO/gui/src-tauri/target/release/deckswitch" ]; then
    printf '\033[33m  ! Das Fenster ist noch nicht gebaut. Der erste Start aus dem\n    Menü baut es — das dauert Minuten ohne sichtbare Rückmeldung.\n    Besser vorher einmal: ./scripts/start-gui.sh\033[0m\n'
fi
if [ ! -f "$HOME/.config/systemd/user/deckswitch.service" ]; then
    printf '\033[33m  ! Das Backend läuft nicht von allein. Entweder\n    ./scripts/install-service.sh oder vor jedem Start\n    ./scripts/start-backend.sh\033[0m\n'
fi
