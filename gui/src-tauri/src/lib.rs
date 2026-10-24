use std::collections::HashSet;
use std::io::Read;
use std::path::PathBuf;
use std::sync::Mutex;

use tauri::{DragDropEvent, Manager};

/// Größte Datei, die sich ins Fenster ziehen lässt. Plugin-Archive und
/// Symbole sind klein; die Grenze verhindert nur, dass ein versehentlich
/// gezogenes Video komplett in den Speicher wandert.
const MAX_ABLEGEN: u64 = 64 * 1024 * 1024;

/// Pfade, die gerade wirklich ins Fenster gezogen wurden.
///
/// Nur diese darf die Seite lesen. Ohne die Liste könnte jedes Skript im
/// Fenster jede Datei des Benutzers anfordern.
#[derive(Default)]
struct Abgelegt(Mutex<HashSet<PathBuf>>);

fn merke_abgelegte(app: &tauri::AppHandle, ereignis: &DragDropEvent) {
  if let DragDropEvent::Drop { paths, .. } = ereignis {
    if let Some(stand) = app.try_state::<Abgelegt>() {
      if let Ok(mut liste) = stand.0.lock() {
        liste.clear();
        liste.extend(paths.iter().cloned());
      }
    }
  }
}

/// Liest eine Datei, die aus dem Dateimanager ins Fenster gezogen wurde.
///
/// WebKitGTK reicht beim Ablegen keine Datei an die Seite weiter, sondern nur
/// ihren Pfad als `text/uri-list` (gemessen mit Dolphin unter Plasma 6). Die
/// Seite kann einen `file://`-Pfad nicht selbst öffnen, also liest das
/// Fenster die Datei und gibt den Inhalt zurück. Nur Pfade aus dem letzten
/// Ablegen, nur gewöhnliche Dateien bis `MAX_ABLEGEN`.
///
/// Fehler kommen als Kennung zurück (`not-dropped`, `not-a-file`,
/// `too-large`, `io:…`); den Text dazu stellt die Oberfläche in ihrer
/// Sprache.
#[tauri::command]
fn lies_abgelegte_datei(
  pfad: String,
  abgelegt: tauri::State<'_, Abgelegt>,
) -> Result<tauri::ipc::Response, String> {
  let weg = PathBuf::from(&pfad);
  let frei = abgelegt
    .0
    .lock()
    .map(|mut liste| liste.remove(&weg))
    .unwrap_or(false);
  if !frei {
    return Err("not-dropped".into());
  }
  // Vor dem Öffnen prüfen: Eine benannte Pipe ließe `open` sonst hängen.
  let info = std::fs::metadata(&weg).map_err(|e| format!("io:{e}"))?;
  if !info.is_file() {
    return Err("not-a-file".into());
  }
  if info.len() > MAX_ABLEGEN {
    return Err("too-large".into());
  }
  let datei = std::fs::File::open(&weg).map_err(|e| format!("io:{e}"))?;
  // Mit Obergrenze lesen: Die Größe von eben kann inzwischen eine andere
  // sein, und manche Dateien melden gar keine.
  let mut daten = Vec::new();
  datei
    .take(MAX_ABLEGEN + 1)
    .read_to_end(&mut daten)
    .map_err(|e| format!("io:{e}"))?;
  if daten.len() as u64 > MAX_ABLEGEN {
    return Err("too-large".into());
  }
  Ok(tauri::ipc::Response::new(daten))
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
  tauri::Builder::default()
    .manage(Abgelegt::default())
    .invoke_handler(tauri::generate_handler![lies_abgelegte_datei])
    // Ob das Ablegen am Fenster oder am Webview gemeldet wird, hängt davon
    // ab, wie das Fenster gebaut ist. Beide Wege merken sich die Pfade.
    .on_window_event(|fenster, ereignis| {
      if let tauri::WindowEvent::DragDrop(ablegen) = ereignis {
        merke_abgelegte(fenster.app_handle(), ablegen);
      }
    })
    .on_webview_event(|webview, ereignis| {
      if let tauri::WebviewEvent::DragDrop(ablegen) = ereignis {
        merke_abgelegte(webview.app_handle(), ablegen);
      }
    })
    // Nur ein Fenster. Wer die App ein zweites Mal startet — über das
    // Symbol im Systemabschnitt, den Menüeintrag oder das Terminal —
    // bekommt das vorhandene Fenster nach vorn geholt, statt ein weiteres
    // daneben.
    .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
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
    // Links nach draußen — Store, GitHub, Quelltext — öffnet das Fenster
    // nicht selbst: WebKitGTK verwirft `target="_blank"` ohne Meldung. Der
    // Opener reicht sie an den Standardbrowser weiter.
    .plugin(tauri_plugin_opener::init())
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
