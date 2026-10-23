// SPDX-License-Identifier: GPL-3.0-or-later
use crate::{
    decode::Image,
    graphics::{Renderer, STATUS, TOOLBAR},
    loader::{self, Event, Loader},
    view::View,
};
use std::{
    cell::RefCell, ffi::OsString, fs::File, io::Write, mem::size_of, os::windows::ffi::OsStringExt,
    path::PathBuf, sync::Arc, time::Instant,
};
use windows::{
    Win32::{
        Foundation::*,
        Graphics::{
            Dwm::{DWMWA_USE_IMMERSIVE_DARK_MODE, DwmSetWindowAttribute},
            Gdi::*,
        },
        System::{
            Com::{COINIT_APARTMENTTHREADED, CoInitializeEx, CoUninitialize},
            LibraryLoader::GetModuleHandleW,
        },
        UI::{
            Controls::{DRAWITEMSTRUCT, Dialogs::*, ODS_DISABLED, ODS_FOCUS, ODS_SELECTED},
            HiDpi::*,
            Input::KeyboardAndMouse::*,
            Shell::*,
            WindowsAndMessaging::*,
        },
    },
    core::{BOOL, PCWSTR, w},
};

const OPEN: u16 = 100;
const PREVIOUS: u16 = 101;
const NEXT: u16 = 102;
const FIT: u16 = 103;
const ACTUAL: u16 = 104;
const ROTATE: u16 = 105;
const FULLSCREEN: u16 = 106;
const HELP: u16 = 107;
const ZOOM_IN: u16 = 108;
const ZOOM_OUT: u16 = 109;
const FIRST: u16 = 110;
const LAST: u16 = 111;
const ESCAPE: u16 = 112;

const BUTTONS: &[(u16, &str, i32)] = &[
    (OPEN, "Open", 72),
    (PREVIOUS, "Previous", 84),
    (NEXT, "Next", 64),
    (FIT, "Fit", 52),
    (ACTUAL, "100%", 64),
    (ROTATE, "Rotate", 76),
    (FULLSCREEN, "Full screen", 100),
    (HELP, "Help", 60),
];

fn toolbar_geometry(width: f32, dpi: f32) -> (f32, [RECT; 8]) {
    let left = 14.0 * dpi;
    let mut x = left;
    let mut y = 10.0 * dpi;
    let mut positions = [RECT::default(); 8];
    for (index, &(id, _, width_dip)) in BUTTONS.iter().enumerate() {
        let button_width = width_dip as f32 * dpi;
        if x > left && x + button_width > width - left {
            x = left;
            y += 40.0 * dpi;
        }
        positions[index] = RECT {
            left: x.round() as i32,
            top: y.round() as i32,
            right: (x + button_width).round() as i32,
            bottom: (y + 32.0 * dpi).round() as i32,
        };
        x += button_width + if id == OPEN || id == NEXT { 16.0 } else { 4.0 } * dpi;
    }
    ((y + 42.0 * dpi).max(TOOLBAR * dpi), positions)
}

const HELP_TEXT: PCWSTR = w!(
    "Open a photo or drop it onto the window.\n\nCtrl+O: open\nLeft / Right or Page Up / Page Down: previous / next\nHome / End: first / last\nMouse wheel or + / -: zoom\nDrag: pan\n0: fit to window\n1: actual pixels\nR: rotate clockwise\nF11 or F: full screen\nDouble-click: toggle full screen\nEscape: leave full screen, or close\nTab / Shift+Tab: focus toolbar buttons\n\nFoto never edits your photos. GIF and TIFF display their first frame.\n\nOptional performance log:\nfoto.exe [photo] --timings path.csv"
);

struct Options {
    photo: Option<PathBuf>,
    timings: Option<PathBuf>,
    help: bool,
}

fn options() -> Result<Options, String> {
    let mut result = Options {
        photo: None,
        timings: None,
        help: false,
    };
    let mut args = std::env::args_os().skip(1);
    while let Some(arg) = args.next() {
        if arg == "--timings" {
            result.timings = Some(
                args.next()
                    .ok_or("--timings requires an output file")?
                    .into(),
            );
        } else if arg == "--help" || arg == "-h" {
            result.help = true;
        } else if result.photo.is_none() {
            result.photo = Some(arg.into());
        } else {
            return Err("Use: foto.exe [photo] [--timings path.csv]".into());
        }
    }
    Ok(result)
}

struct Timings {
    file: File,
    start: Instant,
    window_recorded: bool,
}

impl Timings {
    fn record(&mut self, event: &str, request: Instant, cached: bool, image: Option<&Image>) {
        let (w, h) = image.map_or((0, 0), Image::size);
        let _ = writeln!(
            self.file,
            "{event},{:.3},{:.3},{cached},{w},{h}",
            self.start.elapsed().as_secs_f64() * 1000.0,
            request.elapsed().as_secs_f64() * 1000.0
        );
        let _ = self.file.flush();
    }
}

struct Font(HFONT);
impl Drop for Font {
    fn drop(&mut self) {
        unsafe {
            let _ = DeleteObject(self.0.into());
        }
    }
}

struct WindowGuard(HWND);

impl Drop for WindowGuard {
    fn drop(&mut self) {
        unsafe {
            if IsWindow(Some(self.0)).as_bool() {
                // The state owner outlives this guard, including initialisation failures.
                SetWindowLongPtrW(self.0, GWLP_USERDATA, 0);
                let _ = DestroyWindow(self.0);
            }
        }
    }
}

struct App {
    hwnd: HWND,
    loader: Option<Loader>,
    renderer: Option<Renderer>,
    image: Option<Arc<Image>>,
    files: Vec<PathBuf>,
    index: usize,
    generation: u64,
    view: View,
    error: Option<String>,
    loading: bool,
    browsing: bool,
    folder_error: Option<String>,
    fullscreen: Option<RECT>,
    previous_style: isize,
    was_maximized: bool,
    dragging: Option<((i32, i32), (f32, f32))>,
    dpi: f32,
    buttons: Vec<(u16, HWND)>,
    font: Option<Font>,
    timings: Option<Timings>,
    requested_at: Instant,
    pending_present: Option<bool>,
    window_title: String,
}

impl App {
    fn new(timings: Option<Timings>) -> Self {
        Self {
            hwnd: HWND::default(),
            loader: None,
            renderer: None,
            image: None,
            files: Vec::new(),
            index: 0,
            generation: 0,
            view: View::default(),
            error: None,
            loading: false,
            browsing: false,
            folder_error: None,
            fullscreen: None,
            previous_style: 0,
            was_maximized: false,
            dragging: None,
            dpi: 1.0,
            buttons: Vec::new(),
            font: None,
            timings,
            requested_at: Instant::now(),
            pending_present: None,
            window_title: String::new(),
        }
    }

    fn bounds(&self) -> RECT {
        let mut bounds = RECT::default();
        unsafe {
            let _ = GetClientRect(self.hwnd, &mut bounds);
        }
        bounds
    }

    fn area(&self) -> (f32, f32, f32) {
        let b = self.bounds();
        let top = if self.fullscreen.is_some() {
            0.0
        } else {
            toolbar_geometry(b.right as f32, self.dpi).0
        };
        let bottom = if self.fullscreen.is_some() {
            b.bottom as f32
        } else {
            b.bottom as f32 - STATUS * self.dpi
        };
        (b.right as f32, (bottom - top).max(1.0), top)
    }

    fn invalidate(&self) {
        unsafe {
            let _ = InvalidateRect(Some(self.hwnd), None, false);
        }
    }

    fn status(&self) -> String {
        if let Some(error) = &self.folder_error {
            return error.clone();
        }
        if self.files.is_empty() {
            return "Ready".into();
        }
        let count = if self.browsing {
            "Browsing folder…".into()
        } else {
            format!("{} / {}", self.index + 1, self.files.len())
        };
        if self.loading {
            return format!("{count}     Opening photo…");
        }
        if self.error.is_some() {
            return format!("{count}     Cannot open this file · Try the next photo or Ctrl+O");
        }
        if let Some(image) = &self.image {
            let area = self.area();
            let scale = self.view.scale(image.size(), (area.0, area.1));
            let dimensions = if image.original == image.size() {
                format!("{} × {}", image.width, image.height)
            } else {
                format!(
                    "{} × {} · reduced preview {} × {}",
                    image.original.0, image.original.1, image.width, image.height
                )
            };
            format!("{count}     {dimensions}     {:.0}%", scale * 100.0)
        } else {
            count
        }
    }

    fn update_title(&mut self) {
        let title = self
            .files
            .get(self.index)
            .and_then(|p| p.file_name())
            .map(|name| {
                format!(
                    "{}{} — Foto",
                    name.to_string_lossy(),
                    if self.loading { " (opening)" } else { "" }
                )
            })
            .unwrap_or_else(|| "Foto".into());
        if title != self.window_title {
            let wide: Vec<u16> = title.encode_utf16().chain(Some(0)).collect();
            unsafe {
                let _ = SetWindowTextW(self.hwnd, PCWSTR(wide.as_ptr()));
            }
            self.window_title = title;
        }
    }

    fn update_buttons(&self) {
        unsafe {
            for &(id, button) in &self.buttons {
                let enabled = match id {
                    PREVIOUS => self.index > 0 && !self.browsing,
                    NEXT => self.index + 1 < self.files.len() && !self.browsing,
                    FIT | ACTUAL | ROTATE => {
                        self.image.is_some() && !self.loading && self.error.is_none()
                    }
                    _ => true,
                };
                let _ = EnableWindow(button, enabled);
                let _ = InvalidateRect(Some(button), None, false);
            }
        }
    }

    fn create_buttons(&mut self) -> windows::core::Result<()> {
        unsafe {
            for &(id, label, _) in BUTTONS {
                let wide: Vec<u16> = label.encode_utf16().chain(Some(0)).collect();
                let button = CreateWindowExW(
                    WINDOW_EX_STYLE::default(),
                    w!("BUTTON"),
                    PCWSTR(wide.as_ptr()),
                    WS_CHILD | WS_VISIBLE | WS_TABSTOP | WINDOW_STYLE(BS_OWNERDRAW as u32),
                    0,
                    0,
                    0,
                    0,
                    Some(self.hwnd),
                    Some(HMENU(id as usize as *mut _)),
                    None,
                    None,
                )?;
                self.buttons.push((id, button));
            }
            self.set_font();
            self.layout();
            self.update_buttons();
            Ok(())
        }
    }

    fn set_font(&mut self) {
        unsafe {
            let font = CreateFontW(
                -(13.0 * self.dpi).round() as i32,
                0,
                0,
                0,
                400,
                0,
                0,
                0,
                DEFAULT_CHARSET,
                OUT_DEFAULT_PRECIS,
                CLIP_DEFAULT_PRECIS,
                CLEARTYPE_QUALITY,
                DEFAULT_PITCH.0 as u32,
                w!("Segoe UI"),
            );
            if !font.is_invalid() {
                for &(_, button) in &self.buttons {
                    SendMessageW(
                        button,
                        WM_SETFONT,
                        Some(WPARAM(font.0 as usize)),
                        Some(LPARAM(1)),
                    );
                }
                self.font = Some(Font(font));
            }
        }
    }

    fn layout(&mut self) {
        let (_, positions) = toolbar_geometry(self.bounds().right as f32, self.dpi);
        unsafe {
            for (&(_, button), r) in self.buttons.iter().zip(positions) {
                let _ = ShowWindow(
                    button,
                    if self.fullscreen.is_some() {
                        SW_HIDE
                    } else {
                        SW_SHOWNA
                    },
                );
                let _ = SetWindowPos(
                    button,
                    None,
                    r.left,
                    r.top,
                    r.right - r.left,
                    r.bottom - r.top,
                    SWP_NOZORDER | SWP_NOACTIVATE,
                );
            }
        }
        self.clamp_pan();
        self.invalidate();
    }

    fn open(&mut self, path: PathBuf) {
        self.files = vec![std::path::absolute(&path).unwrap_or(path)];
        self.index = 0;
        self.browsing = true;
        self.folder_error = None;
        self.select(true, None);
    }

    fn select(&mut self, scan: bool, previous: Option<PathBuf>) {
        let Some(path) = self.files.get(self.index).cloned() else {
            return;
        };
        let Some(loader) = &self.loader else { return };
        self.requested_at = Instant::now();
        let previous = previous.and_then(|path| {
            if !self.loading && self.error.is_none() {
                self.image.as_ref().map(|image| (path, image.clone()))
            } else {
                None
            }
        });
        let (generation, cached) = loader.request(path, scan, previous);
        self.generation = generation;
        self.error = None;
        self.loading = cached.is_none();
        self.pending_present = Some(cached.is_some());
        if let Some(image) = cached {
            self.image = Some(image);
            self.view.reset();
            self.prefetch();
        }
        self.update_title();
        self.update_buttons();
        self.invalidate();
    }

    fn prefetch(&self) {
        if self.loading || self.browsing {
            return;
        }
        let mut neighbors = Vec::new();
        if self.index + 1 < self.files.len() {
            neighbors.push(self.files[self.index + 1].clone());
        }
        if self.index > 0 {
            neighbors.push(self.files[self.index - 1].clone());
        }
        if let Some(loader) = &self.loader {
            loader.prefetch(self.generation, neighbors);
        }
    }

    fn drain(&mut self) {
        while let Some(event) = self
            .loader
            .as_ref()
            .and_then(|loader| loader.events.try_recv().ok())
        {
            match event {
                Event::Image { generation, result } if generation == self.generation => {
                    self.loading = false;
                    match result {
                        Ok(image) => {
                            self.image = Some(image);
                            self.view.reset();
                            self.prefetch();
                        }
                        Err(error) => {
                            self.error = Some(error);
                            self.image = None;
                            self.pending_present = None;
                            if let Some(timings) = &mut self.timings {
                                timings.record("error", self.requested_at, false, None);
                            }
                        }
                    }
                }
                Event::Directory { generation, files } if generation == self.generation => {
                    self.browsing = false;
                    match files {
                        Ok(files) => {
                            let selected = self.files.get(self.index).cloned();
                            self.index = selected
                                .and_then(|path| files.iter().position(|p| *p == path))
                                .unwrap_or(0);
                            self.files = files;
                            self.prefetch();
                        }
                        Err(error) => self.folder_error = Some(error),
                    }
                }
                _ => {}
            }
        }
        self.update_title();
        self.update_buttons();
        self.invalidate();
    }

    fn clamp_pan(&mut self) {
        if let Some(image) = &self.image {
            let area = self.area();
            self.view.clamp_pan(image.size(), (area.0, area.1));
        }
    }

    fn zoom(&mut self, factor: f32, anchor: Option<(f32, f32)>) {
        if self.loading || self.error.is_some() {
            return;
        }
        if let Some(image) = &self.image {
            let area = self.area();
            let scale = self.view.scale(image.size(), (area.0, area.1));
            self.view
                .zoom_at(scale, factor, anchor.unwrap_or((0.0, 0.0)));
            self.clamp_pan();
            self.invalidate();
        }
    }

    fn command(&mut self, command: u16) {
        match command {
            PREVIOUS | NEXT | FIRST | LAST if !self.files.is_empty() && !self.browsing => {
                let next = match command {
                    PREVIOUS => self.index.saturating_sub(1),
                    NEXT => (self.index + 1).min(self.files.len() - 1),
                    FIRST => 0,
                    _ => self.files.len() - 1,
                };
                if next != self.index {
                    let previous = self.files.get(self.index).cloned();
                    self.index = next;
                    self.select(false, previous);
                }
            }
            FIT => {
                self.view.zoom = None;
                self.view.pan = (0.0, 0.0);
            }
            ACTUAL => {
                self.view.zoom = Some(1.0);
                self.view.pan = (0.0, 0.0);
            }
            ROTATE => {
                self.view.turns = (self.view.turns + 1) % 4;
                self.view.pan = (0.0, 0.0);
                self.clamp_pan();
            }
            ZOOM_IN => self.zoom(1.25, None),
            ZOOM_OUT => self.zoom(0.8, None),
            FULLSCREEN => self.toggle_fullscreen(),
            ESCAPE if self.fullscreen.is_some() => self.toggle_fullscreen(),
            _ => {}
        }
        self.invalidate();
    }

    fn toggle_fullscreen(&mut self) {
        unsafe {
            if let Some(rect) = self.fullscreen.take() {
                SetWindowLongPtrW(self.hwnd, GWL_STYLE, self.previous_style);
                let _ = SetWindowPos(
                    self.hwnd,
                    None,
                    rect.left,
                    rect.top,
                    rect.right - rect.left,
                    rect.bottom - rect.top,
                    SWP_FRAMECHANGED | SWP_NOZORDER | SWP_NOACTIVATE,
                );
                if self.was_maximized {
                    let _ = ShowWindow(self.hwnd, SW_MAXIMIZE);
                }
            } else {
                let mut rect = RECT::default();
                let _ = GetWindowRect(self.hwnd, &mut rect);
                self.was_maximized = IsZoomed(self.hwnd).as_bool();
                self.previous_style = GetWindowLongPtrW(self.hwnd, GWL_STYLE);
                let monitor = MonitorFromWindow(self.hwnd, MONITOR_DEFAULTTONEAREST);
                let mut info = MONITORINFO {
                    cbSize: size_of::<MONITORINFO>() as u32,
                    ..Default::default()
                };
                if !GetMonitorInfoW(monitor, &mut info).as_bool() {
                    return;
                }
                self.fullscreen = Some(rect);
                SetWindowLongPtrW(
                    self.hwnd,
                    GWL_STYLE,
                    self.previous_style & !(WS_OVERLAPPEDWINDOW.0 as isize),
                );
                let r = info.rcMonitor;
                let _ = SetWindowPos(
                    self.hwnd,
                    None,
                    r.left,
                    r.top,
                    r.right - r.left,
                    r.bottom - r.top,
                    SWP_FRAMECHANGED | SWP_NOZORDER | SWP_NOACTIVATE,
                );
                let _ = SetFocus(Some(self.hwnd));
            }
        }
        self.layout();
    }

    fn paint(&mut self) {
        unsafe {
            let mut paint = PAINTSTRUCT::default();
            let dc = BeginPaint(self.hwnd, &mut paint);
            let b = self.bounds();
            let status = self.status();
            let toolbar = self
                .fullscreen
                .is_none()
                .then(|| toolbar_geometry(b.right as f32, self.dpi).0);
            if b.right <= 0 || b.bottom <= 0 {
                let _ = EndPaint(self.hwnd, &paint);
                return;
            }
            let result = (|| {
                if self.renderer.is_none() {
                    self.renderer = Some(Renderer::new(self.dpi)?);
                }
                self.renderer.as_ref().unwrap().bind(dc, &b)?;
                self.renderer.as_mut().unwrap().draw(
                    self.image.as_ref(),
                    &self.view,
                    &status,
                    self.error.as_deref(),
                    toolbar,
                    self.dpi,
                )
            })();
            match result {
                Ok(()) => {
                    if let Some(timings) = &mut self.timings {
                        if !timings.window_recorded {
                            timings.record("window", timings.start, false, None);
                            timings.window_recorded = true;
                        }
                        if !self.loading && self.error.is_none() && self.image.is_some() {
                            if let Some(cached) = self.pending_present.take() {
                                timings.record(
                                    "image",
                                    self.requested_at,
                                    cached,
                                    self.image.as_deref(),
                                );
                            }
                        }
                    }
                }
                Err(error) => {
                    self.renderer = None;
                    let brush = CreateSolidBrush(rgb(0x111214));
                    FillRect(dc, &b, brush);
                    let _ = DeleteObject(brush.into());
                    SetTextColor(dc, rgb(0xe8e9ed));
                    SetBkMode(dc, TRANSPARENT);
                    let mut text: Vec<u16> =
                        format!("Cannot draw the photo. Resize the window to retry.\n{error}")
                            .encode_utf16()
                            .collect();
                    let mut r = b;
                    DrawTextW(dc, &mut text, &mut r, DT_CENTER | DT_VCENTER | DT_WORDBREAK);
                    if let Some(timings) = &mut self.timings {
                        timings.record("graphics_error", self.requested_at, false, None);
                    }
                }
            }
            let _ = EndPaint(self.hwnd, &paint);
        }
    }
}

fn rgb(value: u32) -> COLORREF {
    COLORREF(((value & 255) << 16) | (value & 0xff00) | ((value >> 16) & 255))
}

unsafe fn draw_button(item: &DRAWITEMSTRUCT, font: Option<HFONT>) {
    unsafe {
        let disabled = item.itemState.0 & ODS_DISABLED.0 != 0;
        let pressed = item.itemState.0 & ODS_SELECTED.0 != 0;
        let focused = item.itemState.0 & ODS_FOCUS.0 != 0;
        let tint = if pressed {
            0x3b3e45
        } else if focused {
            0x303239
        } else {
            0x24262b
        };
        let brush = CreateSolidBrush(rgb(tint));
        FillRect(item.hDC, &item.rcItem, brush);
        let _ = DeleteObject(brush.into());
        let previous = font.map(|font| SelectObject(item.hDC, font.into()));
        SetBkMode(item.hDC, TRANSPARENT);
        SetTextColor(item.hDC, rgb(if disabled { 0x626670 } else { 0xe2e4e9 }));
        let mut text = [0u16; 64];
        let length = GetWindowTextW(item.hwndItem, &mut text);
        let mut r = item.rcItem;
        DrawTextW(
            item.hDC,
            &mut text[..length as usize],
            &mut r,
            DT_CENTER | DT_VCENTER | DT_SINGLELINE | DT_NOPREFIX,
        );
        if focused {
            let _ = DrawFocusRect(item.hDC, &item.rcItem);
        }
        if let Some(previous) = previous {
            SelectObject(item.hDC, previous);
        }
    }
}

fn open_dialog(hwnd: HWND) -> Option<PathBuf> {
    let mut path = vec![0u16; 32768];
    let filter: Vec<u16> = "Photos\0*.jpg;*.jpeg;*.jfif;*.png;*.bmp;*.gif;*.tif;*.tiff;*.ico;*.webp;*.heic;*.heif;*.jxr;*.wdp\0All files\0*.*\0\0".encode_utf16().collect();
    let mut dialog = OPENFILENAMEW {
        lStructSize: size_of::<OPENFILENAMEW>() as u32,
        hwndOwner: hwnd,
        lpstrFilter: PCWSTR(filter.as_ptr()),
        lpstrFile: windows::core::PWSTR(path.as_mut_ptr()),
        nMaxFile: path.len() as u32,
        lpstrTitle: w!("Open a photo"),
        Flags: OFN_FILEMUSTEXIST | OFN_PATHMUSTEXIST | OFN_EXPLORER | OFN_NOCHANGEDIR,
        ..Default::default()
    };
    if unsafe { GetOpenFileNameW(&mut dialog) }.as_bool() {
        let end = path.iter().position(|c| *c == 0).unwrap_or(path.len());
        Some(PathBuf::from(OsString::from_wide(&path[..end])))
    } else {
        None
    }
}

fn keyboard(key: u32) -> Option<u16> {
    let ctrl = unsafe { GetKeyState(VK_CONTROL.0 as i32) } < 0;
    if ctrl {
        return if key == b'O' as u32 { Some(OPEN) } else { None };
    }
    Some(match key {
        0x25 | 0x21 => PREVIOUS,
        0x27 | 0x22 | 0x20 => NEXT,
        0x24 => FIRST,
        0x23 => LAST,
        0x6b | 0xbb => ZOOM_IN,
        0x6d | 0xbd => ZOOM_OUT,
        0x30 | 0x60 => FIT,
        0x31 | 0x61 => ACTUAL,
        0x52 => ROTATE,
        0x7a | 0x46 => FULLSCREEN,
        0x1b => ESCAPE,
        0x70 => HELP,
        _ => return None,
    })
}

fn point(value: LPARAM) -> (i32, i32) {
    (
        value.0 as u16 as i16 as i32,
        (value.0 >> 16) as u16 as i16 as i32,
    )
}

unsafe extern "system" fn window_proc(hwnd: HWND, message: u32, wp: WPARAM, lp: LPARAM) -> LRESULT {
    unsafe {
        if message == WM_NCCREATE {
            let create = &*(lp.0 as *const CREATESTRUCTW);
            SetWindowLongPtrW(hwnd, GWLP_USERDATA, create.lpCreateParams as isize);
            let state = &*(create.lpCreateParams as *const RefCell<App>);
            let mut app = state.borrow_mut();
            app.hwnd = hwnd;
            app.dpi = GetDpiForWindow(hwnd).max(96) as f32 / 96.0;
            drop(app);
            return DefWindowProcW(hwnd, message, wp, lp);
        }
        if message == WM_NCDESTROY {
            SetWindowLongPtrW(hwnd, GWLP_USERDATA, 0);
            return DefWindowProcW(hwnd, message, wp, lp);
        }
        if message == WM_DESTROY {
            PostQuitMessage(0);
            return LRESULT(0);
        }
        let pointer = GetWindowLongPtrW(hwnd, GWLP_USERDATA) as *const RefCell<App>;
        if pointer.is_null() {
            return DefWindowProcW(hwnd, message, wp, lp);
        }
        let state = &*pointer;
        // Native modal dialogs run their own message loop. Hold no App borrow here.
        if message == WM_COMMAND && wp.0 as u16 == OPEN {
            if let Some(path) = open_dialog(hwnd) {
                if let Ok(mut app) = state.try_borrow_mut() {
                    app.open(path);
                }
            }
            return LRESULT(0);
        }
        if message == WM_COMMAND && wp.0 as u16 == HELP {
            MessageBoxW(Some(hwnd), HELP_TEXT, w!("Foto · controls"), MB_OK);
            return LRESULT(0);
        }
        if message == WM_COMMAND && wp.0 as u16 == ESCAPE {
            let close = state.try_borrow().is_ok_and(|app| app.fullscreen.is_none());
            if close {
                let _ = DestroyWindow(hwnd);
                return LRESULT(0);
            }
        }
        if message == WM_CLOSE {
            let _ = DestroyWindow(hwnd);
            return LRESULT(0);
        }
        // Synchronous Win32 callbacks may re-enter. Never create aliased Rust references.
        let Ok(mut app) = state.try_borrow_mut() else {
            return DefWindowProcW(hwnd, message, wp, lp);
        };
        match message {
            WM_ERASEBKGND => return LRESULT(1),
            WM_PAINT => {
                app.paint();
                return LRESULT(0);
            }
            WM_SIZE => {
                if wp.0 != SIZE_MINIMIZED as usize {
                    app.layout();
                }
                return LRESULT(0);
            }
            WM_DPICHANGED => {
                app.dpi = (wp.0 & 0xffff) as f32 / 96.0;
                app.renderer = None;
                app.set_font();
                let r = &*(lp.0 as *const RECT);
                let _ = SetWindowPos(
                    hwnd,
                    None,
                    r.left,
                    r.top,
                    r.right - r.left,
                    r.bottom - r.top,
                    SWP_NOZORDER | SWP_NOACTIVATE,
                );
                app.layout();
                return LRESULT(0);
            }
            WM_GETMINMAXINFO if app.fullscreen.is_none() => {
                let info = &mut *(lp.0 as *mut MINMAXINFO);
                info.ptMinTrackSize = POINT {
                    x: (360.0 * app.dpi) as i32,
                    y: (320.0 * app.dpi) as i32,
                };
                return LRESULT(0);
            }
            WM_DRAWITEM if lp.0 != 0 => {
                draw_button(
                    &*(lp.0 as *const DRAWITEMSTRUCT),
                    app.font.as_ref().map(|font| font.0),
                );
                return LRESULT(1);
            }
            WM_COMMAND => {
                app.command(wp.0 as u16);
                return LRESULT(0);
            }
            loader::READY => {
                app.drain();
                return LRESULT(0);
            }
            WM_DROPFILES => {
                let drop = HDROP(wp.0 as *mut _);
                let count = DragQueryFileW(drop, 0, None);
                let mut path = vec![0u16; count as usize + 1];
                DragQueryFileW(drop, 0, Some(&mut path));
                DragFinish(drop);
                if count > 0 {
                    app.open(PathBuf::from(OsString::from_wide(&path[..count as usize])));
                }
                return LRESULT(0);
            }
            WM_LBUTTONDBLCLK => {
                let (_, y) = point(lp);
                let area = app.area();
                if y as f32 >= area.2 && (y as f32) < area.2 + area.1 {
                    app.toggle_fullscreen();
                }
                return LRESULT(0);
            }
            WM_LBUTTONDOWN if app.image.is_some() && !app.loading => {
                let p = point(lp);
                let area = app.area();
                if p.1 as f32 >= area.2 && (p.1 as f32) < area.2 + area.1 {
                    app.dragging = Some((p, app.view.pan));
                    SetCapture(hwnd);
                    let _ = SetFocus(Some(hwnd));
                }
                return LRESULT(0);
            }
            WM_MOUSEMOVE if app.dragging.is_some() => {
                let p = point(lp);
                let (origin, pan) = app.dragging.unwrap();
                app.view.pan = (
                    pan.0 + (p.0 - origin.0) as f32,
                    pan.1 + (p.1 - origin.1) as f32,
                );
                app.clamp_pan();
                app.invalidate();
                return LRESULT(0);
            }
            WM_LBUTTONUP => {
                app.dragging = None;
                let _ = ReleaseCapture();
                return LRESULT(0);
            }
            WM_CAPTURECHANGED => {
                app.dragging = None;
                return LRESULT(0);
            }
            WM_MOUSEWHEEL => {
                let delta = (wp.0 >> 16) as u16 as i16 as f32 / 120.0;
                let (x, y) = point(lp);
                let mut p = POINT { x, y };
                let _ = ScreenToClient(hwnd, &mut p);
                let area = app.area();
                if p.y as f32 >= area.2 && (p.y as f32) < area.2 + area.1 {
                    app.zoom(
                        1.2_f32.powf(delta),
                        Some((
                            p.x as f32 - area.0 / 2.0,
                            p.y as f32 - area.2 - area.1 / 2.0,
                        )),
                    );
                }
                return LRESULT(0);
            }
            WM_SETCURSOR if lp.0 as u16 == HTCLIENT as u16 && app.image.is_some() => {
                let cursor = LoadCursorW(
                    None,
                    if app.dragging.is_some() {
                        IDC_SIZEALL
                    } else {
                        IDC_ARROW
                    },
                );
                if let Ok(cursor) = cursor {
                    SetCursor(Some(cursor));
                }
                return LRESULT(1);
            }
            _ => {}
        }
        drop(app);
        DefWindowProcW(hwnd, message, wp, lp)
    }
}

pub fn run() -> Result<(), Box<dyn std::error::Error>> {
    let started = Instant::now();
    let options = options()?;
    if options.help {
        unsafe {
            MessageBoxW(None, HELP_TEXT, w!("Foto · controls"), MB_OK);
        }
        return Ok(());
    }
    let timings = options
        .timings
        .map(|path| -> std::io::Result<_> {
            let mut file = File::options().write(true).create_new(true).open(path)?;
            writeln!(file, "event,elapsed_ms,request_ms,cached,width,height")?;
            Ok(Timings {
                file,
                start: started,
                window_recorded: false,
            })
        })
        .transpose()?;
    unsafe {
        let _ = SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2);
        CoInitializeEx(None, COINIT_APARTMENTTHREADED).ok()?;
        let result = run_window(options.photo, timings);
        CoUninitialize();
        result
    }
}

unsafe fn run_window(
    photo: Option<PathBuf>,
    timings: Option<Timings>,
) -> Result<(), Box<dyn std::error::Error>> {
    unsafe {
        let instance = HINSTANCE(GetModuleHandleW(None)?.0);
        let class = w!("Foto.Native.Viewer");
        let wc = WNDCLASSW {
            hInstance: instance,
            lpszClassName: class,
            lpfnWndProc: Some(window_proc),
            style: CS_DBLCLKS | CS_HREDRAW | CS_VREDRAW,
            hCursor: LoadCursorW(None, IDC_ARROW)?,
            ..Default::default()
        };
        if RegisterClassW(&wc) == 0 {
            return Err(windows::core::Error::from_thread().into());
        }
        let state = Box::new(RefCell::new(App::new(timings)));
        let hwnd = CreateWindowExW(
            WS_EX_ACCEPTFILES,
            class,
            w!("Foto"),
            WS_OVERLAPPEDWINDOW | WS_CLIPCHILDREN,
            CW_USEDEFAULT,
            CW_USEDEFAULT,
            1100,
            780,
            None,
            None,
            Some(instance),
            Some((&*state as *const RefCell<App>).cast()),
        )?;
        let _window = WindowGuard(hwnd);
        {
            let mut app = state.borrow_mut();
            app.hwnd = hwnd;
            app.dpi = GetDpiForWindow(hwnd) as f32 / 96.0;
            app.loader = Some(Loader::new(hwnd)?);
            app.create_buttons()?;
            if let Some(photo) = photo {
                app.open(photo);
            }
        }
        let dark = BOOL(1);
        let _ = DwmSetWindowAttribute(
            hwnd,
            DWMWA_USE_IMMERSIVE_DARK_MODE,
            (&dark as *const BOOL).cast(),
            size_of::<BOOL>() as u32,
        );
        let _ = ShowWindow(hwnd, SW_SHOW);
        let _ = UpdateWindow(hwnd);
        let mut message = MSG::default();
        loop {
            let result = GetMessageW(&mut message, None, 0, 0);
            if result.0 == -1 {
                return Err(windows::core::Error::from_thread().into());
            }
            if result.0 == 0 {
                break;
            }
            if message.message == WM_KEYDOWN {
                // Owner-drawn buttons do not acquire the dialog manager's default
                // pushbutton behaviour. Enter still activates the focused control.
                if message.wParam.0 == VK_RETURN.0 as usize
                    && GetParent(message.hwnd).ok() == Some(hwnd)
                    && IsWindowEnabled(message.hwnd).as_bool()
                {
                    SendMessageW(message.hwnd, BM_CLICK, None, None);
                    continue;
                }
                if let Some(command) = keyboard(message.wParam.0 as u32) {
                    // A held toggle key changes state once, not on every repeat.
                    if command == FULLSCREEN && message.lParam.0 & (1 << 30) != 0 {
                        continue;
                    }
                    // Space activates a focused native button. Other shortcuts stay global.
                    if message.wParam.0 != VK_SPACE.0 as usize || message.hwnd == hwnd {
                        SendMessageW(
                            hwnd,
                            WM_COMMAND,
                            Some(WPARAM(command as usize)),
                            Some(LPARAM(0)),
                        );
                        continue;
                    }
                }
            }
            if !IsDialogMessageW(hwnd, &message).as_bool() {
                let _ = TranslateMessage(&message);
                DispatchMessageW(&message);
            }
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn toolbar_wraps_without_overlap_or_clipping_on_narrow_high_dpi_windows() {
        for dpi in [1.0, 1.25, 1.5, 2.0] {
            for width_dip in [340.0, 360.0, 512.0, 760.0, 1100.0] {
                let width = width_dip * dpi;
                let (height, buttons) = toolbar_geometry(width, dpi);
                for (index, button) in buttons.iter().enumerate() {
                    assert!(button.left >= 0 && button.right <= width.round() as i32);
                    assert!(button.top >= 0 && button.bottom <= height.round() as i32);
                    for other in &buttons[index + 1..] {
                        assert!(
                            button.right <= other.left
                                || other.right <= button.left
                                || button.bottom <= other.top
                                || other.bottom <= button.top
                        );
                    }
                }
            }
        }
        assert_eq!(toolbar_geometry(1100.0, 1.0).0, TOOLBAR);
        assert!(toolbar_geometry(1024.0, 2.0).0 > TOOLBAR * 2.0);
    }
}
