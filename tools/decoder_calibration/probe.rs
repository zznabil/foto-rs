// Disposable E057 actual Decoder::load measurement probe.
//
// The parent replaces __DECODE__ with an absolute control or candidate
// decode.rs path before compiling. Every timed load is compared with the
// reference image, so elapsed_ns_per_load includes the full comparator.
#[allow(dead_code)]
#[path = "__DECODE__"]
mod decode;

use std::{
    hint::black_box,
    io::{self, BufRead, Write},
    os::windows::ffi::OsStrExt,
    path::{Path, PathBuf},
    time::{Duration, Instant},
};

const BATCHES: usize = 16;
const DELAY_BATCH: usize = 8;
const MAX_INNER: usize = 4096;
const EXTRA_BYTES: [usize; 2] = [0, 33_554_432];
const DELAY_MS: [u64; 2] = [0, 1000];
const REPEATS: [usize; 2] = [1, 3];

struct Config {
    inner: usize,
    repeats: usize,
    delay_ms: u64,
    extra_bytes: usize,
    corrupt: bool,
}

fn main() {
    if let Err(error) = run() {
        eprintln!("E057_MEASURE_PROBE_ERROR: {error}");
        std::process::exit(2);
    }
}

fn run() -> Result<(), String> {
    let mut args = std::env::args_os().skip(1);
    let path = PathBuf::from(
        args.next()
            .ok_or_else(|| "expected exactly one image path".to_string())?,
    );
    if args.next().is_some() {
        return Err("expected exactly one image path".to_string());
    }
    // Capture the exact UTF-16 argument before any decoder work.  This is
    // outside the timed loop so the long/verbatim spelling reaches both the
    // worker and Decoder unchanged.
    let argument_utf16: Vec<u16> = path.as_os_str().encode_wide().collect();
    let argument_utf16_hex = argument_utf16
        .iter()
        .flat_map(|unit| unit.to_le_bytes())
        .map(|byte| format!("{byte:02x}"))
        .collect::<String>();
    let config = Config::from_environment()?;
    let decoder = decode::Decoder::new().map_err(|error| format!("decoder init: {error}"))?;
    let reference = decoder
        .load(Path::new(&path))
        .map_err(|error| format!("reference decode failed: {error}"))?;
    let extra_memory = vec![0x5a; config.extra_bytes];
    black_box(&extra_memory);

    let loops_per_batch = config
        .inner
        .checked_mul(config.repeats)
        .ok_or_else(|| "inner * repeats overflowed".to_string())?;
    let total_loops = BATCHES
        .checked_mul(loops_per_batch)
        .ok_or_else(|| "total loop count overflowed".to_string())?;
    let mut batch_times_ns = [0u64; BATCHES];
    let mut batch_ranges_ns = [[0u64; 2]; BATCHES];
    let mut observed_sleep_ns = [0u64; 2];
    let mut delay_event_count = 0usize;
    let mut delay_batch_index: isize = -1;
    let mut delay_completed_loads = 0usize;
    let mut loop_count = 0usize;
    let mut final_image = None;
    let timeline = Instant::now();

    for batch in 0..BATCHES {
        let started = elapsed_ns(&timeline)?;
        for iteration in 0..loops_per_batch {
            let image = decoder.load(Path::new(&path)).map_err(|error| {
                format!("batch {batch} iteration {iteration} decode failed: {error}")
            })?;
            compare_image(&reference, &image)
                .map_err(|error| format!("batch {batch} iteration {iteration}: {error}"))?;
            final_image = Some(image);
            loop_count += 1;
        }
        if batch == DELAY_BATCH && config.delay_ms != 0 {
            // The positive delay control is deliberately inside the ninth
            // timed batch (zero-based index 8) and is applied exactly once.
            delay_event_count += 1;
            delay_batch_index = batch as isize;
            delay_completed_loads = loops_per_batch;
            let sleep_started = elapsed_ns(&timeline)?;
            std::thread::sleep(Duration::from_millis(config.delay_ms));
            let sleep_ended = elapsed_ns(&timeline)?;
            if sleep_ended < sleep_started {
                return Err("observed sleep clock moved backwards".to_string());
            }
            observed_sleep_ns = [sleep_started, sleep_ended];
        }
        let ended = elapsed_ns(&timeline)?;
        let duration = ended
            .checked_sub(started)
            .ok_or_else(|| "batch clock moved backwards".to_string())?;
        if duration == 0 {
            return Err("batch duration was zero".to_string());
        }
        batch_ranges_ns[batch] = [started, ended];
        batch_times_ns[batch] = duration;
    }
    if loop_count != total_loops {
        return Err(format!(
            "loop count mismatch: completed {loop_count}, expected {total_loops}"
        ));
    }
    let final_image = final_image.ok_or_else(|| "no final image was decoded".to_string())?;
    let total_time_ns: u128 = batch_times_ns.iter().map(|&value| u128::from(value)).sum();
    let total_loops_u128 = u128::try_from(total_loops)
        .map_err(|_| "total loop count does not fit in u128".to_string())?;
    let elapsed_ns_per_load = u64::try_from(total_time_ns / total_loops_u128)
        .map_err(|_| "mean duration does not fit in u64 nanoseconds".to_string())?;

    let mut stdout = io::stdout().lock();
    writeln!(
        stdout,
        "DECODE {} {} {} {} {} {}",
        reference.width,
        reference.height,
        reference.original.0,
        reference.original.1,
        reference.pixels.len(),
        elapsed_ns_per_load
    )
    .map_err(|error| format!("write decode header: {error}"))?;
    stdout
        .flush()
        .map_err(|error| format!("flush decode header: {error}"))?;

    let mut command = String::new();
    io::stdin()
        .lock()
        .read_line(&mut command)
        .map_err(|error| format!("read GO command: {error}"))?;
    if command.trim_end_matches(&['\r', '\n'][..]) != "GO" {
        return Err("expected GO after decode header".to_string());
    }

    let mut final_image = final_image;
    if config.corrupt {
        if final_image.pixels.is_empty() {
            return Err("cannot corrupt an empty decoded image".to_string());
        }
        final_image.pixels[0] ^= 1;
    }
    stdout
        .write_all(&final_image.pixels)
        .map_err(|error| format!("write pixel payload: {error}"))?;
    stdout
        .flush()
        .map_err(|error| format!("flush pixel payload: {error}"))?;

    eprintln!("BATCH_RANGES_NS {batch_ranges_ns:?}");
    eprintln!("BATCH_TIMES_NS {batch_times_ns:?}");
    eprintln!("OBSERVED_SLEEP_NS {observed_sleep_ns:?}");
    eprintln!("LOOP_COUNT {loop_count}");
    eprintln!("DELAY_EVENT_COUNT {delay_event_count}");
    eprintln!("DELAY_BATCH_INDEX {delay_batch_index}");
    eprintln!("DELAY_COMPLETED_LOADS {delay_completed_loads}");
    eprintln!("ARGUMENT_UTF16_COUNT {}", argument_utf16.len());
    eprintln!("ARGUMENT_UTF16_HEX {argument_utf16_hex}");
    black_box(extra_memory);
    Ok(())
}

impl Config {
    fn from_environment() -> Result<Self, String> {
        let inner = parse_env_usize("FOTO_E057_INNER")?;
        if !(1..=MAX_INNER).contains(&inner) {
            return Err(format!("FOTO_E057_INNER must be in 1..={MAX_INNER}"));
        }
        let repeats = parse_env_usize("FOTO_E057_REPEATS")?;
        if !REPEATS.contains(&repeats) {
            return Err("FOTO_E057_REPEATS must be 1 or 3".to_string());
        }
        let delay_ms = parse_env_u64("FOTO_E057_DELAY_MS")?;
        if !DELAY_MS.contains(&delay_ms) {
            return Err("FOTO_E057_DELAY_MS must be 0 or 1000".to_string());
        }
        let extra_bytes = parse_env_usize("FOTO_E057_EXTRA_BYTES")?;
        if !EXTRA_BYTES.contains(&extra_bytes) {
            return Err("FOTO_E057_EXTRA_BYTES must be 0 or 33554432".to_string());
        }
        let corrupt = match std::env::var("FOTO_E057_CORRUPT") {
            Ok(value) if value == "1" => true,
            Ok(value) if value == "0" => false,
            Ok(_) => return Err("FOTO_E057_CORRUPT must be 0 or 1".to_string()),
            Err(std::env::VarError::NotPresent) => false,
            Err(error) => return Err(format!("read FOTO_E057_CORRUPT: {error}")),
        };
        Ok(Self {
            inner,
            repeats,
            delay_ms,
            extra_bytes,
            corrupt,
        })
    }
}

fn elapsed_ns(origin: &Instant) -> Result<u64, String> {
    u64::try_from(origin.elapsed().as_nanos())
        .map_err(|_| "monotonic timestamp does not fit in u64 nanoseconds".to_string())
}

fn parse_env_usize(name: &str) -> Result<usize, String> {
    std::env::var(name)
        .map_err(|_| format!("missing {name}"))?
        .parse::<usize>()
        .map_err(|_| format!("{name} must be an unsigned integer"))
}

fn parse_env_u64(name: &str) -> Result<u64, String> {
    std::env::var(name)
        .map_err(|_| format!("missing {name}"))?
        .parse::<u64>()
        .map_err(|_| format!("{name} must be an unsigned integer"))
}

fn compare_image(expected: &decode::Image, actual: &decode::Image) -> Result<(), String> {
    if actual.size() != expected.size() {
        return Err(format!(
            "dimension mismatch: expected {:?}, got {:?}",
            expected.size(),
            actual.size()
        ));
    }
    if actual.original != expected.original {
        return Err(format!(
            "original dimension mismatch: expected {:?}, got {:?}",
            expected.original, actual.original
        ));
    }
    if actual.pixels.len() != expected.pixels.len() {
        return Err(format!(
            "pixel length mismatch: expected {}, got {}",
            expected.pixels.len(),
            actual.pixels.len()
        ));
    }
    if actual.pixels != expected.pixels {
        return Err("FULL_PBGRA_BYTE_PARITY_FAILED".to_string());
    }
    Ok(())
}
