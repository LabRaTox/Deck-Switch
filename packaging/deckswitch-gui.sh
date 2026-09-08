#!/usr/bin/env sh
#
# Startet das Fenster — der Befehl, den das Paket als `deckswitch-gui`
# installiert und den auch der Menüeintrag aufruft.
#
# Das Fenster selbst liegt unter /usr/lib/deckswitch/, weil es kein Programm
# ist, das man von Hand aufruft: Ohne die Behandlung hier unten geht es auf
# manchen Rechnern gar nicht erst auf. Es heisst dort `deckswitch` und nicht
# `deckswitch-gui`, weil GTK die Fensterklasse aus dem Dateinamen ableitet
# und `StartupWMClass` in der .desktop-Datei darauf zeigt. Der Pfad ist über
# DECKSWITCH_GUI_BINARY umstellbar — daran hängt scripts/start-gui.sh, das
# dieselbe Behandlung für die selbst gebaute Datei im Checkout braucht.
#
# Hintergrund: WebKitGTK und Wayland vertragen sich nicht auf jedem Treiber.
# Das Fenster bricht dann nach einer halben Sekunde mit „Gdk-Message: Error
# 71 (Protokollfehler) dispatching to Wayland display" ab. Mit NVIDIA unter
# KDE ist das reproduzierbar; es hilft, den DMABUF-Renderer abzuschalten.
#
# Geraten wird trotzdem nicht: Beim ersten Mal wird gemessen, und was dabei
# herauskam, landet mit einer Signatur des Systems in einer Notiz. Solange
# Sitzungsart, Grafiktreiber und WebKit-Version dieselben sind, startet das
# Fenster danach sofort richtig. Ändert sich eines davon, wird neu gemessen.

set -eu
BINARY="${DECKSWITCH_GUI_BINARY:-/usr/lib/deckswitch/deckswitch}"
NOTIZ="${XDG_CACHE_HOME:-$HOME/.cache}/deckswitch/fensterstart"

if [ ! -x "$BINARY" ]; then
    printf 'Das Fenster fehlt: %s\n' "$BINARY" >&2
    exit 1
fi

# Wer den Schalter selbst setzt, behält das letzte Wort.
if [ -n "${WEBKIT_DISABLE_DMABUF_RENDERER:-}" ]; then
    exec "$BINARY" "$@"
fi

# -------------------------------------------------------------- Signatur

# Nur Dinge, die den Fehler tatsächlich bestimmen, und nur solche, die ohne
# spürbare Verzögerung zu haben sind — zusammen unter fünf Millisekunden.
# Ein Programm aufzurufen, das Pakete abfragt, wäre hier schon zu langsam.
signatur() {
    printf '%s|%s|%s' \
        "${XDG_SESSION_TYPE:-unbekannt}" \
        "$(cat /sys/module/nvidia/version 2>/dev/null || echo ohne-nvidia)" \
        "$(ls /usr/lib/libwebkit2gtk-4.1.so.*.*.* 2>/dev/null | tail -1)"
}
JETZT=$(signatur)

# ------------------------------------------------------------ Notiz lesen

# Nur verwenden, wenn die Signatur noch passt. Nach einem Treiberwechsel
# steht dort etwas anderes, und dann wird lieber neu gemessen als eine alte
# Antwort auf eine neue Frage angewandt.
GEMERKT=""
if [ -r "$NOTIZ" ]; then
    ALT=$(sed -n 's/^signatur=//p' "$NOTIZ" 2>/dev/null || true)
    if [ "$ALT" = "$JETZT" ]; then
        GEMERKT=$(sed -n 's/^dmabuf_aus=//p' "$NOTIZ" 2>/dev/null || true)
    fi
fi

notieren() {
    verzeichnis=$(dirname "$NOTIZ")
    mkdir -p "$verzeichnis" 2>/dev/null || return 0
    {
        printf '# Von DECK//SWITCH gemessen, nicht von Hand gepflegt.\n'
        printf '# Löschen ist harmlos — dann wird beim nächsten Start neu gemessen.\n'
        printf 'signatur=%s\n' "$JETZT"
        printf 'dmabuf_aus=%s\n' "$1"
    } > "$NOTIZ" 2>/dev/null || true
}

# ---------------------------------------------------------------- Starten

#: Ergebnis des letzten Versuchs — vom Aufruf gesetzt, unten ausgewertet.
CODE=0
SOFORT_WEG=nein
DAUER=0

versuch() {
    modus=$1
    shift
    begonnen=$(date +%s)
    set +e
    if [ "$modus" = ohne-dmabuf ]; then
        WEBKIT_DISABLE_DMABUF_RENDERER=1 "$BINARY" "$@"
    else
        "$BINARY" "$@"
    fi
    CODE=$?
    set -e
    DAUER=$(( $(date +%s) - begonnen ))
    # Ein Absturz nach Stunden ist kein Startproblem, sondern ein Absturz —
    # nur der Fehlschlag in den ersten Sekunden zählt als Fehlstart.
    if [ "$CODE" -ne 0 ] && [ "$DAUER" -lt 5 ]; then
        SOFORT_WEG=ja
    else
        SOFORT_WEG=nein
    fi
}

if [ "$GEMERKT" = ja ]; then
    versuch ohne-dmabuf "$@"
    # Auch die Notiz kann falsch liegen — dann eben doch wieder messen.
    if [ "$SOFORT_WEG" = ja ]; then
        versuch normal "$@"
        if [ "$DAUER" -ge 5 ]; then notieren nein; fi
    fi
    exit "$CODE"
fi

versuch normal "$@"
if [ "$SOFORT_WEG" = ja ]; then
    printf 'Das Fenster ging sofort wieder zu — zweiter Versuch ohne DMABUF-Renderer.\n' >&2
    versuch ohne-dmabuf "$@"
    if [ "$DAUER" -ge 5 ]; then notieren ja; fi
    exit "$CODE"
fi

# Es lief ohne Zutun — auch das ist ein Messergebnis und wird festgehalten.
#
# Die Bedingung ist wichtig: Läuft bereits ein Fenster, beendet sich dieser
# Aufruf nach Sekundenbruchteilen mit Erfolg, weil das Fenster nur nach vorn
# geholt wird. Das ist keine Messung — daraus „der Schalter war nicht nötig"
# zu schließen, wäre schlicht falsch.
if [ "$DAUER" -ge 5 ]; then notieren nein; fi
exit "$CODE"
