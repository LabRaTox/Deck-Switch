#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
  tauri::Builder::default()
    // Nur ein Fenster. Wer die App ein zweites Mal startet — über das
    // Symbol im Systemabschnitt, den Menüeintrag oder das Terminal —
    // bekommt das vorhandene Fenster nach vorn geholt, statt ein weiteres
    // daneben.
    .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
      use tauri::Manager;
      if let Some(fenster) = app.get_webview_window("main") {
        let _ = fenster.unminimize();
        let _ = fenster.show();
        let _ = fenster.set_focus();
        // Unter Wayland darf sich ein Fenster nicht selbst nach vorn
        // holen — `set_focus` bleibt dort wirkungslos, gemessen unter
        // KWin. Der vorgesehene Weg ist, um Aufmerksamkeit zu bitten:
        // Die Fensterleiste hebt den Eintrag dann hervor, und der Nutzer
        // entscheidet. Unter X11 greift schon `set_focus`, dann stört
        // die Bitte nicht.
        let _ = fenster.request_user_attention(Some(tauri::UserAttentionType::Informational));
      }
    }))
    .setup(|app| {
      if cfg!(debug_assertions) {
        app.handle().plugin(
          tauri_plugin_log::Builder::default()
            .level(log::LevelFilter::Info)
            .build(),
        )?;
      }
      Ok(())
    })
    .run(tauri::generate_context!())
    .expect("error while running tauri application");
}
