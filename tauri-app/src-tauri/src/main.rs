// Prevents additional console window on Windows in release.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::sync::Mutex;
use std::time::{Duration, Instant};

use once_cell::sync::OnceCell;
use tauri::{AppHandle, Manager, RunEvent, WebviewUrl, WebviewWindowBuilder};
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;
use tauri_plugin_updater::UpdaterExt;

/// Holds the running sidecar child so we can kill it on shutdown.
static SIDECAR: OnceCell<Mutex<Option<CommandChild>>> = OnceCell::new();

fn sidecar_slot() -> &'static Mutex<Option<CommandChild>> {
    SIDECAR.get_or_init(|| Mutex::new(None))
}

/// Spawn the PyInstaller-built sidecar and return the port it's listening on.
fn spawn_sidecar(app: &AppHandle) -> Result<u16, String> {
    let port = portpicker::pick_unused_port()
        .ok_or_else(|| "Could not find a free TCP port".to_string())?;

    log::info!("Starting refchecker-server sidecar on port {port}");

    let sidecar = app
        .shell()
        .sidecar("refchecker-server")
        .map_err(|e| format!("sidecar() lookup failed: {e}"))?
        .args([
            "--host",
            "127.0.0.1",
            "--port",
            &port.to_string(),
        ]);

    let (mut rx, child) = sidecar
        .spawn()
        .map_err(|e| format!("Failed to spawn sidecar: {e}"))?;

    *sidecar_slot().lock().unwrap() = Some(child);

    tauri::async_runtime::spawn(async move {
        while let Some(event) = rx.recv().await {
            match event {
                CommandEvent::Stdout(line) => {
                    log::info!("[sidecar] {}", String::from_utf8_lossy(&line).trim_end());
                }
                CommandEvent::Stderr(line) => {
                    log::warn!("[sidecar] {}", String::from_utf8_lossy(&line).trim_end());
                }
                CommandEvent::Error(err) => {
                    log::error!("[sidecar] error event: {err}");
                }
                CommandEvent::Terminated(payload) => {
                    log::warn!(
                        "[sidecar] terminated: code={:?} signal={:?}",
                        payload.code, payload.signal
                    );
                    break;
                }
                _ => {}
            }
        }
    });

    // Block-poll the health endpoint until it answers or we time out.
    let deadline = Instant::now() + Duration::from_secs(60);
    let url = format!("http://127.0.0.1:{port}/api/health");
    let client = reqwest::blocking::Client::builder()
        .timeout(Duration::from_millis(500))
        .build()
        .map_err(|e| format!("reqwest client: {e}"))?;

    loop {
        if Instant::now() >= deadline {
            return Err(format!(
                "Sidecar did not become healthy on http://127.0.0.1:{port}/api/health within 60s"
            ));
        }
        match client.get(&url).send() {
            Ok(resp) if resp.status().is_success() => {
                log::info!("Sidecar healthy on port {port}");
                return Ok(port);
            }
            Ok(resp) => {
                log::debug!("health check non-2xx: {}", resp.status());
            }
            Err(e) => {
                log::debug!("health check pending: {e}");
            }
        }
        std::thread::sleep(Duration::from_millis(300));
    }
}

fn kill_sidecar() {
    if let Some(slot) = SIDECAR.get() {
        if let Some(child) = slot.lock().unwrap().take() {
            log::info!("Killing refchecker-server sidecar");
            let _ = child.kill();
        }
    }
}

/// Check for an available release on the configured updater endpoint and,
/// if the user accepts, download + install it and restart the app.
///
/// Runs on a background async task so it never blocks the sidecar boot.
/// Failures (no network, bad signature, manifest 404) are logged and
/// swallowed — the user can still keep using the current install.
async fn check_for_update(app: AppHandle) {
    let updater = match app.updater() {
        Ok(u) => u,
        Err(e) => {
            log::warn!("Updater unavailable: {e}");
            return;
        }
    };

    match updater.check().await {
        Ok(Some(update)) => {
            log::info!(
                "Update available: {} → {} ({})",
                update.current_version,
                update.version,
                update.date.map(|d| d.to_string()).unwrap_or_default()
            );

            let mut downloaded: u64 = 0;
            let result = update
                .download_and_install(
                    |chunk, total| {
                        downloaded += chunk as u64;
                        if let Some(total) = total {
                            log::info!("Updater: {downloaded}/{total} bytes");
                        }
                    },
                    || log::info!("Updater: download complete"),
                )
                .await;

            match result {
                Ok(()) => {
                    log::info!("Update installed. Restarting…");
                    app.restart();
                }
                Err(e) => log::error!("Update install failed: {e}"),
            }
        }
        Ok(None) => log::info!("Already on the latest version"),
        Err(e) => log::warn!("Update check failed: {e}"),
    }
}

fn run() {
    env_logger::Builder::from_env(env_logger::Env::default().default_filter_or("info"))
        .format_timestamp_secs()
        .init();

    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .setup(|app| {
            let handle = app.handle().clone();

            // Background update check — does not block sidecar start.
            // The native "An update is available" dialog (configured via
            // plugins.updater.dialog in tauri.conf.json) handles user prompt.
            let update_handle = handle.clone();
            tauri::async_runtime::spawn(async move {
                check_for_update(update_handle).await;
            });

            // Spawn the Python sidecar on a worker thread.
            std::thread::spawn(move || {
                match spawn_sidecar(&handle) {
                    Ok(port) => {
                        let url = format!("http://127.0.0.1:{port}/");
                        log::info!("Loading frontend from {url}");

                        if let Some(main) = handle.get_webview_window("main") {
                            if let Err(e) = main.eval(&format!(
                                "window.location.replace('{url}');"
                            )) {
                                log::error!("Failed to navigate main window: {e}");
                            }
                        } else {
                            let _ = WebviewWindowBuilder::new(
                                &handle,
                                "main",
                                WebviewUrl::External(url.parse().unwrap()),
                            )
                            .title("RefChecker")
                            .inner_size(1280.0, 820.0)
                            .min_inner_size(960.0, 600.0)
                            .build();
                        }
                    }
                    Err(e) => {
                        log::error!("Sidecar failed to start: {e}");
                        if let Some(main) = handle.get_webview_window("main") {
                            let safe = e.replace('\\', "\\\\").replace('\'', "\\'");
                            let _ = main.eval(&format!(
                                "var el=document.getElementById('err');if(el){{el.textContent='{safe}';}}"
                            ));
                        }
                    }
                }
            });

            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|_app_handle, event| {
            if let RunEvent::ExitRequested { .. } | RunEvent::Exit = event {
                kill_sidecar();
            }
        });
}

fn main() {
    run();
}
