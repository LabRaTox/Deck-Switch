// Reine Fenster-Shell — die gesamte Fachlogik liegt im Python-Backend
// bzw. im React-Frontend.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    // Der Name muss zu `[lib] name` in der Cargo.toml passen. Bei der
    // Umbenennung auf DECK//SWITCH blieb hier `streamdeck_app_lib` stehen —
    // aufgefallen ist das nie, weil ein Release-Bau der Fenster-Shell
    // seither niemand gemacht hat.
    deckswitch_lib::run();
}
