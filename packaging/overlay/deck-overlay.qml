/*
 * Das Overlay als Layer-Surface: kein Fenster, kein Eintrag in der
 * Fensterleiste und kein Tastaturfokus. Der Rest steht in ``DeckOverlay.qml``.
 */
import org.kde.layershell as LayerShell

DeckOverlay {
    LayerShell.Window.layer: LayerShell.Window.LayerOverlay
    LayerShell.Window.keyboardInteractivity: LayerShell.Window.KeyboardInteractivityNone
    LayerShell.Window.anchors: LayerShell.Window.AnchorTop | LayerShell.Window.AnchorLeft
    LayerShell.Window.margins: Qt.rect(zielX, zielY, 0, 0)
    LayerShell.Window.exclusionZone: 0
    LayerShell.Window.scope: "deckswitch-overlay"
}
