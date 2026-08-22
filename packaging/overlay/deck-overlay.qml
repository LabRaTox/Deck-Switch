/*
 * DECK//SWITCH — das virtuelle Deck als Overlay.
 *
 * Bewusst *kein* Fenster: Über ``zwlr_layer_shell_v1`` liegt diese Fläche
 * auf der Overlay-Ebene, hat keinen Eintrag in der Fensterleiste, taucht in
 * Alt+Tab nicht auf und kann den Tastaturfokus gar nicht bekommen
 * (``keyboardInteractivity: None``). Genau darauf kommt es an: Ein Klick
 * auf eine Taste darf den Fokus nicht stehlen, sonst tippte eine
 * Hotkey-Aktion hier hinein statt in die Anwendung, aus der man kam.
 * Am 2026-08-16 unter KWin gemessen — Klick kommt an, Fokus bleibt.
 *
 * Die Kacheln kommen fertig gerendert vom Backend; hier wird nichts
 * gezeichnet, nur angezeigt und zurückgemeldet. Deshalb sieht das Overlay
 * exakt aus wie das echte Deck.
 *
 * Aufruf:
 *   qml6 deck-overlay.qml -- --deck <serial> --base http://127.0.0.1:8770
 */
import QtQuick
import QtQuick.Window
import org.kde.layershell as LayerShell

Window {
    id: root
    visible: true
    color: "transparent"

    // -- Einstellungen von der Kommandozeile ------------------------------
    //
    // Gelesen wird hier, in den Vorgabewerten selbst — *nicht* in
    // ``Component.onCompleted``. Das läuft nämlich erst, wenn die Kacheln
    // schon erzeugt sind: Sie hatten dann bereits mit dem geratenen Raster
    // Bilder angefordert, die es bei kleineren Decks gar nicht gibt. Am
    // 2026-08-21 gemessen — ein 3×2-Deck holte sich zwei 404, weil die
    // Vorgabe 4×2 lautete, und genau das stand auch im Journal.
    function argument(name, standard) {
        var argv = Qt.application.arguments
        var i = argv.indexOf(name)
        return (i >= 0 && i + 1 < argv.length) ? argv[i + 1] : standard
    }
    function zahl(name, standard) {
        var wert = parseInt(root.argument(name, ""))
        return isNaN(wert) ? standard : wert
    }

    /* Ein geratenes Raster darf keine Bilder anfordern.
     *
     * Ein Riegel „Nummer < Spalten × Reihen" wäre wirkungslos: Genau so
     * viele Kacheln legt der Repeater ja an, die Bedingung ist immer wahr
     * (am 2026-08-21 gemessen — die 404 blieben). Es zählt allein, ob das
     * Raster *belegt* ist: entweder weil das Backend es beim Start
     * mitgegeben hat, oder weil inzwischen echte Daten da sind.
     */
    readonly property bool rasterVomStart: root.argument("--columns", "") !== ""
    property bool datenDa: false
    readonly property bool rasterGesichert: root.rasterVomStart || root.datenDa

    property string basis: root.argument("--base", "http://127.0.0.1:8770")
    property string deck: root.argument("--deck", "")
    property int spalten: root.zahl("--columns", 4)
    property int reihen: root.zahl("--rows", 2)
    property int dials: root.zahl("--dials", 0)
    property int kachel: 120
    property int abstand: 8
    property int rand: 12
    property real deckkraft: 1.0
    property int fassung: -1
    property bool durchsichtig: false
    property bool leereAusblenden: false
    /** Welche Plätze belegt sind — nur die zeigt ein aufgeräumtes Overlay. */
    property var belegt: ({})

    // Größe ergibt sich aus dem Raster — das Overlay ist so groß wie nötig.
    width: rand * 2 + spalten * kachel + (spalten - 1) * abstand
    height: rand * 2 + reihen * kachel + (reihen - 1) * abstand
            + (dials > 0 ? abstand + Math.round(kachel / 2) : 0)

    /* Zwei Wege zum selben Ziel — je nachdem, worauf die Sitzung läuft.
     *
     * Unter Wayland trägt ``zwlr_layer_shell_v1`` das Overlay. Unter X11
     * gibt es das Protokoll nicht, dafür aber die alten Fenster-Hinweise,
     * und die können hier alles, worauf es ankommt. Am 2026-08-21 unter
     * XWayland nachgemessen (``xprop``):
     *
     *   _NET_WM_STATE   = _NET_WM_STATE_ABOVE, _NET_WM_STATE_STAYS_ON_TOP
     *   _NET_WM_WINDOW_TYPE = _NET_WM_WINDOW_TYPE_UTILITY
     *   WM_HINTS: Client accepts input or input focus: False
     *
     * Der letzte Punkt ist der entscheidende: Ein Klick auf eine Kachel
     * lässt den Tastaturfokus stehen, wo er war — geprüft, indem das
     * aktive Fenster vor und nach einem Klick verglichen wurde. Genau
     * darauf beruht das ganze Overlay, denn sonst tippte eine
     * Hotkey-Aktion hier hinein statt in die Anwendung davor.
     *
     * Beides steht nebeneinander in derselben Datei: Unter X11 laufen die
     * LayerShell-Zuweisungen ins Leere, unter Wayland die Flags. Das ist
     * gemessen und wirft keine Fehler. Der Import von LayerShellQt bleibt
     * dabei nötig, auch auf einem reinen X11-Desktop — das Paket
     * ``layer-shell-qt`` ist deshalb weiterhin eine harte Abhängigkeit.
     */
    flags: Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
           | Qt.WindowDoesNotAcceptFocus

    LayerShell.Window.layer: LayerShell.Window.LayerOverlay
    LayerShell.Window.keyboardInteractivity: LayerShell.Window.KeyboardInteractivityNone
    LayerShell.Window.anchors: LayerShell.Window.AnchorTop | LayerShell.Window.AnchorLeft
    LayerShell.Window.margins: Qt.rect(zielX, zielY, 0, 0)
    LayerShell.Window.exclusionZone: 0
    LayerShell.Window.scope: "deckswitch-overlay"

    property int zielX: root.zahl("--x", 200)
    property int zielY: root.zahl("--y", 200)

    /* Die Stelle — und zwar auf genau einem Weg, nicht auf beiden.
     *
     * Unter Wayland positionieren die Ränder der Layer-Surface (oben),
     * unter X11 die gewöhnliche Fensterposition. Beides gleichzeitig zu
     * setzen ist *nicht* unschädlich, wie hier zuerst angenommen: Am
     * 2026-08-22 wurde gemeldet, dass das Overlay danach nur noch auf
     * dem linken Monitor erschien und den oberen Bildschirmrand nicht mehr
     * erreichte. Qt ordnet ein Fenster über ``x``/``y`` einem Bildschirm
     * zu — auf einer Layer-Surface nagelt das die Fläche auf den ersten
     * Ausgang fest und verschiebt sie gegen ihre Ränder.
     *
     * Welcher Weg gilt, sagt das Backend mit ``--x11``: Es hat die
     * Sitzung ohnehin schon abgetastet und weiß es genauer als wir hier.
     */
    readonly property bool aufX11: Qt.application.arguments.indexOf("--x11") >= 0

    Binding {
        target: root
        property: "x"
        value: root.zielX
        when: root.aufX11
    }
    Binding {
        target: root
        property: "y"
        value: root.zielY
        when: root.aufX11
    }

    /* Verschieben ohne Fensterrahmen.
     *
     * Ein Layer-Shell-Fenster hat keine Titelleiste, und der Fenstermanager
     * verschiebt es auch nicht — die Stelle bestimmt allein ``margins``.
     * Die lässt sich im Betrieb aber nicht ändern: ``Window::setMargins``
     * aus layer-shell-qt 6.7.4 merkt sich den Wert und meldet ihn als
     * Signal, erreicht die laufende Wayland-Surface damit aber nicht
     * (am 2026-08-16 am Maschinencode nachgesehen und dreimal gemessen —
     * das Fenster blieb jedes Mal stehen).
     *
     * Also wird hier nur der Weg gesammelt und beim Loslassen gemeldet; das
     * Backend baut das Overlay an der neuen Stelle neu auf. Solange gezogen
     * wird, tritt es zurück — damit sichtbar ist, dass es am Zeiger hängt
     * und nicht bloß klemmt.
     *
     * Gerechnet wird mit dem Weg seit dem letzten Ereignis: Eine absolute
     * Zeigerposition kennt ein Wayland-Client von sich aus nicht.
     */
    property bool wirdGezogen: false

    component Zieher: MouseArea {
        property real griffX: 0
        property real griffY: 0

        onPressed: function (maus) {
            griffX = maus.x
            griffY = maus.y
            root.wirdGezogen = true
        }
        onPositionChanged: function (maus) {
            if (!pressed)
                return
            root.zielX = Math.max(0, root.zielX + (maus.x - griffX))
            root.zielY = Math.max(0, root.zielY + (maus.y - griffY))
            // Griff nachziehen. Ohne das zählt jedes Ereignis den ganzen
            // bisherigen Weg noch einmal mit, und das Overlay schießt um ein
            // Vielfaches der Mausbewegung davon — gemessen am 2026-08-16:
            // 200 px Zug ergaben 2100 px Versatz.
            griffX = maus.x
            griffY = maus.y
        }
        onReleased: {
            root.wirdGezogen = false
            root.merkePosition()
        }
        onCanceled: root.wirdGezogen = false
    }

    // -- Verbindung zum Backend -------------------------------------------

    function hole(pfad, fertig) {
        var anfrage = new XMLHttpRequest()
        anfrage.onreadystatechange = function () {
            if (anfrage.readyState === XMLHttpRequest.DONE && anfrage.status === 200 && fertig)
                fertig(anfrage.responseText)
        }
        anfrage.open("GET", basis + pfad)
        anfrage.send()
    }

    function schicke(pfad, koerper) {
        var anfrage = new XMLHttpRequest()
        anfrage.open("POST", basis + pfad)
        anfrage.setRequestHeader("Content-Type", "application/json")
        anfrage.send(JSON.stringify(koerper))
    }

    function eingabe(art, index, aktion, delta) {
        schicke("/api/decks/" + deck + "/input",
                { input_type: art, index: index, action: aktion, delta: delta || 0 })
    }

    /* Erst beim Loslassen melden, nicht während des Ziehens: Sonst schriebe
     * jede Mausbewegung die Konfiguration auf die Platte. */
    function merkePosition() {
        schicke("/api/decks/" + deck + "/overlay/position",
                { x: Math.round(zielX), y: Math.round(zielY) })
    }

    /* Nur laden, was sich geändert hat: Das Backend zählt je Kachel eine
     * Fassung hoch. Ohne das lüde das Overlay zehnmal je Sekunde ein
     * Dutzend PNGs, die alle gleich aussehen. */
    property var fassungen: ({})

    function aktualisiere() {
        hole("/api/decks/" + deck + "/tiles", function (text) {
            var daten = JSON.parse(text)
            if (daten.revision === root.fassung) {
                // Nichts Neues — aber das Raster ist damit bestätigt.
                root.datenDa = true
                return
            }
            root.fassung = daten.revision
            root.spalten = daten.columns
            root.reihen = daten.rows
            root.dials = daten.dials
            root.kachel = daten.tile_size
            root.deckkraft = Math.max(0.15, daten.brightness / 100)
            root.durchsichtig = !!daten.transparent
            root.leereAusblenden = !!daten.hide_empty

            // Genau hier und keine Zeile früher: Jetzt stimmt das Raster,
            // und erst jetzt dürfen die Kacheln Bilder anfordern. Stand das
            // eine Zeile weiter oben, lud der Repeater noch mit dem
            // geratenen Raster — am 2026-08-21 waren das zwei 404.
            root.datenDa = true

            var belegtNeu = {}
            var liste = daten.filled || []
            for (var j = 0; j < liste.length; j++)
                belegtNeu[liste[j]] = true
            root.belegt = belegtNeu

            var neu = daten.versions || {}
            for (var schluessel in neu) {
                if (root.fassungen[schluessel] !== neu[schluessel]) {
                    root.fassungen[schluessel] = neu[schluessel]
                    root.markiere(schluessel, neu[schluessel])
                }
            }
        })
    }

    signal kachelGeaendert(string schluessel, int fassung)
    function markiere(schluessel, fassung) { kachelGeaendert(schluessel, fassung) }

    Timer {
        interval: 250
        running: true
        repeat: true
        onTriggered: root.aktualisiere()
    }

    // -- Darstellung -------------------------------------------------------

    // Beim Ziehen treten Grund und Kacheln zurück (siehe unten). Bewusst
    // nicht über ``Window.opacity``: Ob eine Layer-Surface die überhaupt
    // umsetzt, hängt am Compositor — die Deckkraft der Elemente malt Qt
    // selbst und wirkt darum sicher.

    // Der Grund unter den Kacheln. Durchsichtig geschaltet schweben nur
    // die Kacheln über dem Bildschirm — dann ist auch der Rahmen weg.
    Rectangle {
        anchors.fill: parent
        radius: 16
        visible: !root.durchsichtig
        color: "#0e0e11"
        opacity: root.wirdGezogen ? 0.5 : 0.92
        Behavior on opacity { NumberAnimation { duration: 80 } }
        border.color: "#2a2a31"
        border.width: 1
    }

    // Der Rand rings um die Kacheln ist die Greiffläche für die linke Taste.
    // Sie steht vor den Kacheln im Baum und liegt damit darunter — auf einer
    // Kachel gewinnt deren eigene Fläche, und ein Tastendruck bleibt ein
    // Tastendruck.
    Zieher {
        anchors.fill: parent
        acceptedButtons: Qt.LeftButton
        cursorShape: Qt.SizeAllCursor
    }

    Column {
        anchors.centerIn: parent
        spacing: root.abstand
        // Zeigt an, dass das Deck am Zeiger hängt: Das Fenster selbst kann
        // der Bewegung nicht folgen, es springt erst beim Loslassen.
        opacity: root.wirdGezogen ? 0.55 : 1.0
        Behavior on opacity { NumberAnimation { duration: 80 } }

        Grid {
            columns: root.spalten
            spacing: root.abstand

            Repeater {
                model: root.spalten * root.reihen
                delegate: Kachel {
                    art: "key"
                    nummer: index
                    breite: root.kachel
                    hoehe: root.kachel
                }
            }
        }

        Row {
            spacing: root.abstand
            visible: root.dials > 0
            Repeater {
                model: root.dials
                delegate: Kachel {
                    art: "dial"
                    nummer: index
                    breite: root.kachel
                    hoehe: Math.round(root.kachel / 2)
                    raddreht: true
                }
            }
        }
    }

    // Mit der rechten Taste lässt sich das Overlay auch auf den Kacheln
    // packen. Nötig, weil bei durchsichtigem Grund und ausgeblendeten leeren
    // Kacheln kaum noch freie Fläche übrig ist, an der man es greifen könnte.
    // Die linke Taste nimmt diese Fläche nicht an und fällt deshalb durch —
    // die Kacheln darunter bekommen ihre Klicks unverändert.
    Zieher {
        anchors.fill: parent
        acceptedButtons: Qt.RightButton
        z: 10
    }

    // -- Eine Kachel -------------------------------------------------------

    component Kachel: Rectangle {
        id: feld
        property string art: "key"
        property int nummer: 0
        property int breite: 120
        property int hoehe: 120
        property bool raddreht: false
        property int fassung: 0

        /** Unbelegte Kacheln verschwinden auf Wunsch — der Platz bleibt,
            damit die übrigen nicht bei jeder Belegung springen. */
        readonly property bool zeigen:
            !root.leereAusblenden || root.belegt[art + ":" + nummer] === true

        width: breite
        height: hoehe
        // Keine eigene Fläche: Das Bild bringt seinen Hintergrund mit, und
        // zwar mit runden Ecken und echter Transparenz dahinter. Eine
        // Platte darunter würde in genau diesen Ecken wieder hervorschauen.
        radius: Math.round(Math.min(breite, hoehe) * 0.12)
        color: "transparent"
        // Voll deckend: Die Helligkeit steckt im gerenderten Bild, genau
        // wie beim echten Gerät. Als Deckkraft umgesetzt wäre die Kachel
        // durchscheinend und auf hellem Grund kaum zu lesen.
        opacity: zeigen ? 1 : 0
        // Kein Rahmen: Er säße auf den runden Ecken des Bildes und liefe
        // daneben. Das Überfahren zeigt sich stattdessen an der Kachel
        // selbst — siehe unten.
        border.width: 0

        Image {
            id: bild
            anchors.fill: parent
            fillMode: Image.PreserveAspectFit
            cache: false
            asynchronous: true
            // Auch bei falsch geratenem Raster nie über die vorhandenen
            // Kacheln hinausfragen — sonst beantwortet das Backend Anfragen
            // mit 404, und im Journal steht ein Fehler, der keiner ist.
            source: root.deck && root.rasterGesichert
                ? root.basis + "/api/decks/" + root.deck + "/tile/" + feld.art
                  + "/" + feld.nummer + ".png?v=" + feld.fassung
                : ""
        }

        /* Rückmeldung ohne Hardware: Man sieht keine Taste einsinken und
           spürt keinen Druckpunkt, also muss die Kachel es zeigen. Ein
           dünner Rahmen reicht dafür nicht — er verschwindet auf dunklen
           Kacheln fast völlig. Deshalb dreierlei zugleich: größer werden,
           aufhellen und einen Schein bekommen — aber jedes davon nur
           angedeutet. Zusammen genügt das; einzeln aufgedreht wirkt schon
           das Überfahren wie ein Druck. */
        scale: maus.pressed ? 0.975 : (maus.containsMouse ? 1.02 : 1.0)
        Behavior on scale { NumberAnimation { duration: 90; easing.type: Easing.OutCubic } }
        z: maus.containsMouse ? 1 : 0   // beim Vergrößern nicht unter die Nachbarn

        // Der Schein liegt *hinter* dem Bild und tritt an den Rändern hervor.
        Rectangle {
            anchors.fill: parent
            anchors.margins: -2
            radius: parent.radius + 2
            color: "#3b82f6"
            opacity: maus.containsMouse ? 0.22 : 0
            visible: feld.zeigen
            z: -1
            Behavior on opacity { NumberAnimation { duration: 90 } }
        }

        // Aufhellen: legt sich über das Bild und hebt auch dunkle Kacheln.
        Rectangle {
            anchors.fill: parent
            radius: parent.radius
            color: "#ffffff"
            opacity: maus.pressed ? 0.02 : (maus.containsMouse ? 0.07 : 0)
            visible: feld.zeigen
            Behavior on opacity { NumberAnimation { duration: 90 } }
        }

        MouseArea {
            id: maus
            anchors.fill: parent
            hoverEnabled: true
            // Eine ausgeblendete Kachel nimmt auch keine Klicks — sonst
            // finge sie Klicks für das Fenster darunter ab.
            enabled: feld.zeigen
            acceptedButtons: Qt.LeftButton
            onPressed: root.eingabe(feld.art, feld.nummer, "down")
            onReleased: root.eingabe(feld.art, feld.nummer, "up")
            onWheel: function (rad) {
                if (!feld.raddreht)
                    return
                root.eingabe("dial", feld.nummer, "rotate", rad.angleDelta.y > 0 ? 1 : -1)
            }
        }

        Connections {
            target: root
            function onKachelGeaendert(schluessel, fassung) {
                if (schluessel === feld.art + ":" + feld.nummer)
                    feld.fassung = fassung
            }
        }
    }

    // -- Start -------------------------------------------------------------

    // Alles von der Kommandozeile steht schon in den Vorgabewerten oben —
    // hier bleibt nur, die ersten echten Daten zu holen.
    Component.onCompleted: root.aktualisiere()
}
