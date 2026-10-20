use crate::decode::{Decoder, Image};
use std::{
    collections::VecDeque,
    os::windows::ffi::OsStrExt,
    path::{Path, PathBuf},
    sync::{
        Arc, Condvar, Mutex,
        atomic::{AtomicBool, AtomicU64, Ordering},
        mpsc::{self, Receiver, Sender},
    },
    thread,
};
use windows::{
    Win32::{
        Foundation::{HWND, LPARAM, WPARAM},
        System::Threading::{GetCurrentThread, SetThreadPriority, THREAD_PRIORITY_BELOW_NORMAL},
        UI::{
            Shell::StrCmpLogicalW,
            WindowsAndMessaging::{PostMessageW, WM_APP},
        },
    },
    core::PCWSTR,
};

pub const READY: u32 = WM_APP + 1;
const CACHE_BYTES: usize = 192 * 1024 * 1024;
const CACHE_ITEMS: usize = 5;

pub enum Event {
    Image {
        generation: u64,
        result: Result<Arc<Image>, String>,
    },
    Directory {
        generation: u64,
        files: Result<Vec<PathBuf>, String>,
    },
}

struct Request {
    generation: u64,
    path: PathBuf,
    scan: bool,
    decode: bool,
}

struct Prefetch {
    generation: u64,
    paths: Vec<PathBuf>,
}

/// A single replaceable job prevents rapid key presses from building a backlog.
struct Slot<T> {
    state: Mutex<(Option<T>, bool)>,
    ready: Condvar,
}

impl<T> Slot<T> {
    fn new() -> Self {
        Self {
            state: Mutex::new((None, false)),
            ready: Condvar::new(),
        }
    }
    fn set(&self, job: T) {
        let mut state = self.state.lock().unwrap();
        if !state.1 {
            state.0 = Some(job);
            self.ready.notify_one();
        }
    }
    fn take(&self) -> Option<T> {
        let mut state = self.state.lock().unwrap();
        while state.0.is_none() && !state.1 {
            state = self.ready.wait(state).unwrap();
        }
        if state.1 { None } else { state.0.take() }
    }
    fn close(&self) {
        let mut state = self.state.lock().unwrap();
        *state = (None, true);
        self.ready.notify_all();
    }
}

struct Cache {
    entries: VecDeque<(PathBuf, Arc<Image>)>,
    bytes: usize,
    limit: usize,
}

impl Cache {
    fn new(limit: usize) -> Self {
        Self {
            entries: VecDeque::new(),
            bytes: 0,
            limit,
        }
    }
    fn get(&mut self, path: &Path) -> Option<Arc<Image>> {
        let index = self.entries.iter().position(|(p, _)| p == path)?;
        let entry = self.entries.remove(index)?;
        let image = entry.1.clone();
        self.entries.push_back(entry);
        Some(image)
    }
    fn select(
        &mut self,
        path: &Path,
        previous: Option<(PathBuf, Arc<Image>)>,
    ) -> Option<Arc<Image>> {
        // Acquire the selected image before reinserting the previous display.
        // Prefetch may have evicted it while the UI still owned its pixel bytes.
        // Reuse that allocation instead of decoding it again on a direction change.
        let image = self.get(path);
        if let Some((old_path, old_image)) = previous {
            self.insert(old_path, old_image);
        }
        image
    }

    fn insert(&mut self, path: PathBuf, image: Arc<Image>) {
        if let Some(index) = self.entries.iter().position(|(p, _)| *p == path) {
            self.bytes -= self.entries.remove(index).unwrap().1.pixels.len();
        }
        if image.pixels.len() > self.limit {
            return;
        }
        while self.bytes + image.pixels.len() > self.limit || self.entries.len() >= CACHE_ITEMS {
            let Some((_, old)) = self.entries.pop_front() else {
                break;
            };
            self.bytes -= old.pixels.len();
        }
        self.bytes += image.pixels.len();
        self.entries.push_back((path, image));
    }
    fn clear(&mut self) {
        self.entries.clear();
        self.bytes = 0;
    }
}

struct Shared {
    generation: AtomicU64,
    closed: AtomicBool,
    cache: Mutex<Cache>,
    foreground: Slot<Request>,
    prefetch: Slot<Prefetch>,
    events: Sender<Event>,
    hwnd: usize,
}

impl Shared {
    fn current(&self, generation: u64) -> bool {
        !self.closed.load(Ordering::Relaxed)
            && self.generation.load(Ordering::Relaxed) == generation
    }
    fn emit(&self, event: Event) {
        if !self.closed.load(Ordering::Relaxed) && self.events.send(event).is_ok() {
            unsafe {
                let _ = PostMessageW(Some(HWND(self.hwnd as *mut _)), READY, WPARAM(0), LPARAM(0));
            }
        }
    }
    fn store(&self, generation: u64, path: PathBuf, image: Arc<Image>) {
        let mut cache = self.cache.lock().unwrap();
        if self.current(generation) {
            cache.insert(path, image);
        }
    }
}

pub struct Loader {
    shared: Arc<Shared>,
    pub events: Receiver<Event>,
}

impl Loader {
    pub fn new(hwnd: HWND) -> std::io::Result<Self> {
        let (tx, events) = mpsc::channel();
        let shared = Arc::new(Shared {
            generation: AtomicU64::new(0),
            closed: AtomicBool::new(false),
            cache: Mutex::new(Cache::new(CACHE_BYTES)),
            foreground: Slot::new(),
            prefetch: Slot::new(),
            events: tx,
            hwnd: hwnd.0 as usize,
        });
        let worker = shared.clone();
        thread::Builder::new()
            .name("foto-decode".into())
            .spawn(move || foreground(worker))?;
        let worker = shared.clone();
        if let Err(error) = thread::Builder::new()
            .name("foto-prefetch".into())
            .spawn(move || prefetch(worker))
        {
            shared.closed.store(true, Ordering::Relaxed);
            shared.foreground.close();
            return Err(error);
        }
        Ok(Self { shared, events })
    }

    pub fn request(
        &self,
        path: PathBuf,
        scan: bool,
        previous: Option<(PathBuf, Arc<Image>)>,
    ) -> (u64, Option<Arc<Image>>) {
        let generation = self.shared.generation.fetch_add(1, Ordering::Relaxed) + 1;
        let mut cache = self.shared.cache.lock().unwrap();
        // Reopening a file explicitly refreshes externally edited photos.
        if scan {
            cache.clear();
        }
        let image = cache.select(&path, if scan { None } else { previous });
        drop(cache);
        self.shared.foreground.set(Request {
            generation,
            path,
            scan,
            decode: image.is_none(),
        });
        (generation, image)
    }

    pub fn prefetch(&self, generation: u64, paths: Vec<PathBuf>) {
        self.shared.prefetch.set(Prefetch { generation, paths });
    }
}

impl Drop for Loader {
    fn drop(&mut self) {
        self.shared.closed.store(true, Ordering::Relaxed);
        self.shared.foreground.close();
        self.shared.prefetch.close();
    }
}

fn foreground(shared: Arc<Shared>) {
    let decoder = Decoder::new().map_err(|e| e.to_string());
    while let Some(request) = shared.foreground.take() {
        let Request {
            generation,
            path,
            scan,
            decode,
        } = request;
        if !shared.current(generation) {
            continue;
        }
        if decode {
            let cached = shared.cache.lock().unwrap().get(&path);
            let result = match cached {
                Some(image) => Ok(image),
                None => decoder
                    .as_ref()
                    .map_err(Clone::clone)
                    .and_then(|d| d.load(&path))
                    .map(Arc::new),
            };
            if !shared.current(generation) {
                continue;
            }
            if let Ok(ref image) = result {
                shared.store(generation, path.clone(), image.clone());
            }
            shared.emit(Event::Image { generation, result });
        }
        // The first image is delivered before its directory is enumerated or sorted.
        if scan && shared.current(generation) {
            let files = scan_directory(&path, || shared.current(generation));
            if shared.current(generation) {
                shared.emit(Event::Directory { generation, files });
            }
        }
    }
}

fn prefetch(shared: Arc<Shared>) {
    unsafe {
        let _ = SetThreadPriority(GetCurrentThread(), THREAD_PRIORITY_BELOW_NORMAL);
    }
    let Ok(decoder) = Decoder::new() else { return };
    while let Some(job) = shared.prefetch.take() {
        for path in job.paths {
            if !shared.current(job.generation) {
                break;
            }
            if shared.cache.lock().unwrap().get(&path).is_some() {
                continue;
            }
            if let Ok(image) = decoder.load(&path) {
                shared.store(job.generation, path, Arc::new(image));
            }
        }
    }
}

fn scan_directory(path: &Path, current: impl Fn() -> bool) -> Result<Vec<PathBuf>, String> {
    let parent = path.parent().unwrap_or_else(|| Path::new("."));
    let entries =
        std::fs::read_dir(parent).map_err(|e| format!("Cannot browse this folder: {e}"))?;
    let mut files = Vec::new();
    for entry in entries {
        if !current() {
            return Ok(Vec::new());
        }
        let Ok(entry) = entry else { continue };
        if supported(&entry.path()) && entry.file_type().is_ok_and(|t| t.is_file()) {
            files.push(entry.path());
        }
    }
    if !files.iter().any(|p| p == path) {
        // Windows accepts alternate filename casing. Resolve the selected name on
        // this worker, then preserve the caller's path without adding a duplicate.
        let selected = std::fs::canonicalize(path).ok();
        let existing = selected.as_ref().and_then(|selected| {
            files.iter().position(|candidate| {
                candidate.file_name() == selected.file_name()
                    && std::fs::canonicalize(candidate).as_ref().ok() == Some(selected)
            })
        });
        if let Some(index) = existing {
            files[index] = path.to_owned();
        } else {
            files.push(path.to_owned());
        }
    }
    let mut keyed: Vec<_> = files
        .into_iter()
        .map(|p| {
            let name: Vec<u16> = p
                .file_name()
                .unwrap_or_default()
                .encode_wide()
                .chain(Some(0))
                .collect();
            (name, p)
        })
        .collect();
    keyed.sort_unstable_by(|(a, pa), (b, pb)| {
        unsafe { StrCmpLogicalW(PCWSTR(a.as_ptr()), PCWSTR(b.as_ptr())) }
            .cmp(&0)
            .then_with(|| pa.cmp(pb))
    });
    Ok(keyed.into_iter().map(|(_, p)| p).collect())
}

fn supported(path: &Path) -> bool {
    path.extension().and_then(|e| e.to_str()).is_some_and(|e| {
        matches!(
            e.to_ascii_lowercase().as_str(),
            "jpg"
                | "jpeg"
                | "jfif"
                | "png"
                | "bmp"
                | "gif"
                | "tif"
                | "tiff"
                | "ico"
                | "wdp"
                | "jxr"
                | "heic"
                | "heif"
                | "webp"
        )
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    fn image(bytes: usize) -> Arc<Image> {
        Arc::new(Image {
            pixels: vec![0; bytes],
            width: 1,
            height: 1,
            original: (1, 1),
        })
    }

    #[test]
    fn cache_evicts_the_least_recently_used_image_within_its_byte_budget() {
        let mut cache = Cache::new(12);
        cache.insert("a".into(), image(4));
        cache.insert("b".into(), image(4));
        cache.insert("c".into(), image(4));
        assert!(cache.get(Path::new("a")).is_some());
        cache.insert("d".into(), image(4));
        assert!(cache.get(Path::new("b")).is_none());
        assert!(cache.get(Path::new("a")).is_some());
        cache.insert("too-large".into(), image(16));
        assert!(cache.get(Path::new("too-large")).is_none());
        assert_eq!(cache.bytes, 12);
    }

    #[test]
    fn navigating_reuses_evicted_display_pixels_without_losing_the_selected_image() {
        let mut cache = Cache::new(8);
        let old = image(4);
        let selected = image(4);
        cache.insert("old".into(), old.clone());
        cache.insert("next".into(), selected.clone());
        cache.insert("other".into(), image(4));
        assert!(cache.get(Path::new("old")).is_none());
        let result = cache.select(Path::new("next"), Some(("old".into(), old.clone())));
        assert!(Arc::ptr_eq(&result.unwrap(), &selected));
        assert!(Arc::ptr_eq(&cache.get(Path::new("old")).unwrap(), &old));
        assert_eq!(cache.bytes, 8);
        assert!(cache.get(Path::new("other")).is_none());
    }

    #[test]
    fn rapid_requests_replace_queued_work_and_closed_slots_never_run_it() {
        let slot = Slot::new();
        slot.set(1);
        slot.set(2);
        slot.set(3);
        assert_eq!(slot.take(), Some(3));
        slot.set(4);
        slot.close();
        assert_eq!(slot.take(), None);
    }

    #[test]
    fn alternate_windows_filename_casing_does_not_duplicate_the_selected_photo() {
        let folder = std::env::temp_dir().join(format!("foto-case-{}", std::process::id()));
        std::fs::create_dir(&folder).unwrap();
        let original = folder.join("photo1.png");
        let next = folder.join("photo2.png");
        std::fs::write(&original, []).unwrap();
        std::fs::write(&next, []).unwrap();
        let selected = folder.join("PHOTO1.PNG");
        assert!(
            selected.is_file(),
            "This regression needs Windows filename semantics"
        );
        let files = scan_directory(&selected, || true).unwrap();
        assert_eq!(files, vec![selected, next.clone()]);
        std::fs::remove_file(original).unwrap();
        std::fs::remove_file(next).unwrap();
        std::fs::remove_dir(folder).unwrap();
    }

    #[test]
    fn directory_sort_matches_explorer_numbers_and_keeps_unicode_names() {
        let folder = std::env::temp_dir().join(format!("foto-sort-{}", std::process::id()));
        std::fs::create_dir(&folder).unwrap();
        for name in [
            "photo10.jpg",
            "photo2.jpg",
            "photo1.jpg",
            "猫.png",
            "ignore.txt",
        ] {
            std::fs::write(folder.join(name), []).unwrap();
        }
        std::fs::create_dir(folder.join("folder.jpg")).unwrap();
        let files = scan_directory(&folder.join("photo2.jpg"), || true).unwrap();
        let names: Vec<_> = files
            .iter()
            .map(|p| p.file_name().unwrap().to_string_lossy().into_owned())
            .collect();
        assert_eq!(&names[..3], ["photo1.jpg", "photo2.jpg", "photo10.jpg"]);
        assert!(names.contains(&"猫.png".to_string()));
        assert_eq!(names.len(), 4);
        for name in [
            "photo10.jpg",
            "photo2.jpg",
            "photo1.jpg",
            "猫.png",
            "ignore.txt",
        ] {
            std::fs::remove_file(folder.join(name)).unwrap();
        }
        std::fs::remove_dir(folder.join("folder.jpg")).unwrap();
        std::fs::remove_dir(folder).unwrap();
    }
}
