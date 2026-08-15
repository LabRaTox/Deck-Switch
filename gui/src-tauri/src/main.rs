// Reine Fenster-Shell — die gesamte Fachlogik liegt im Python-Backend
// bzw. im React-Frontend.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    streamdeck_app_lib::run();
}
