// SPDX-License-Identifier: GPL-3.0-or-later
#![windows_subsystem = "windows"]

mod app;
mod decode;
mod graphics;
mod loader;
mod view;

fn main() {
    if let Err(error) = app::run() {
        let text: Vec<u16> = format!("Foto could not start.\n\n{error}")
            .encode_utf16()
            .chain(Some(0))
            .collect();
        unsafe {
            windows::Win32::UI::WindowsAndMessaging::MessageBoxW(
                None,
                windows::core::PCWSTR(text.as_ptr()),
                windows::core::w!("Foto"),
                windows::Win32::UI::WindowsAndMessaging::MB_OK
                    | windows::Win32::UI::WindowsAndMessaging::MB_ICONERROR,
            );
        }
        std::process::exit(1);
    }
}
