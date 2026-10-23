// SPDX-License-Identifier: GPL-3.0-or-later
use std::{os::windows::ffi::OsStrExt, path::Path, ptr::null};
use windows::{
    Win32::{
        Foundation::{E_INVALIDARG, E_OUTOFMEMORY, GENERIC_READ},
        Graphics::Imaging::*,
        System::Com::{
            CLSCTX_INPROC_SERVER, COINIT_MULTITHREADED, CoCreateInstance, CoInitializeEx,
            CoUninitialize,
            StructuredStorage::{PROPVARIANT, PropVariantClear, PropVariantToUInt32},
        },
        UI::WindowsAndMessaging::{DestroyIcon, HICON, IMAGE_ICON, LR_LOADFROMFILE, LoadImageW},
    },
    core::{Interface, PCWSTR, w},
};

pub const MAX_PIXELS: u64 = 32_000_000;
pub const MAX_EDGE: u32 = 8192;

pub struct Image {
    pub pixels: Vec<u8>,
    pub width: u32,
    pub height: u32,
    pub original: (u32, u32),
}

impl Image {
    pub fn size(&self) -> (u32, u32) {
        (self.width, self.height)
    }
}

/// Each decoding thread owns its COM apartment and codec factory.
pub struct Decoder {
    factory: IWICImagingFactory,
    _apartment: Apartment,
}

struct Apartment;

impl Drop for Apartment {
    fn drop(&mut self) {
        unsafe {
            CoUninitialize();
        }
    }
}

impl Decoder {
    pub fn new() -> windows::core::Result<Self> {
        unsafe {
            CoInitializeEx(None, COINIT_MULTITHREADED).ok()?;
            let apartment = Apartment;
            let factory = CoCreateInstance(&CLSID_WICImagingFactory, None, CLSCTX_INPROC_SERVER)?;
            Ok(Self {
                factory,
                _apartment: apartment,
            })
        }
    }

    pub fn load(&self, path: &Path) -> Result<Image, String> {
        unsafe { self.load_inner(path) }
            .map_err(|e| format!("Windows could not decode this image ({e})."))
    }

    unsafe fn load_inner(&self, path: &Path) -> windows::core::Result<Image> {
        // WIC objects never cross threads. Only owned pixel bytes leave this method.
        unsafe {
            // Rust filesystem calls support extended paths, but WIC receives the
            // raw UTF-16 name. Resolve long names here, off the UI thread.
            let extended = if path.as_os_str().encode_wide().count() >= 260 {
                std::fs::canonicalize(path).ok()
            } else {
                None
            };
            let path = extended.as_deref().unwrap_or(path);
            let wide: Vec<u16> = path.as_os_str().encode_wide().chain(Some(0)).collect();
            let (mut source, orientation): (IWICBitmapSource, u32) = if path
                .extension()
                .is_some_and(|e| e.eq_ignore_ascii_case("ico"))
            {
                let icon = LoadImageW(
                    None,
                    PCWSTR(wide.as_ptr()),
                    IMAGE_ICON,
                    0,
                    0,
                    LR_LOADFROMFILE,
                )?;
                let bitmap = self.factory.CreateBitmapFromHICON(HICON(icon.0));
                let _ = DestroyIcon(HICON(icon.0));
                (bitmap?.cast()?, 1)
            } else {
                let decoder = self.factory.CreateDecoderFromFilename(
                    PCWSTR(wide.as_ptr()),
                    None,
                    GENERIC_READ,
                    WICDecodeMetadataCacheOnDemand,
                )?;
                let frame = decoder.GetFrame(0)?;
                let orientation = exif_orientation(&frame);
                (frame.cast()?, orientation)
            };
            let transform = match orientation {
                2 => WICBitmapTransformFlipHorizontal,
                3 => WICBitmapTransformRotate180,
                4 => WICBitmapTransformFlipVertical,
                5 => WICBitmapTransformOptions(
                    WICBitmapTransformRotate270.0 | WICBitmapTransformFlipHorizontal.0,
                ),
                6 => WICBitmapTransformRotate90,
                7 => WICBitmapTransformOptions(
                    WICBitmapTransformRotate90.0 | WICBitmapTransformFlipHorizontal.0,
                ),
                8 => WICBitmapTransformRotate270,
                _ => WICBitmapTransformRotate0,
            };
            let (mut width, mut height) = (0, 0);
            source.GetSize(&mut width, &mut height)?;
            let original = if matches!(orientation, 5..=8) {
                (height, width)
            } else {
                (width, height)
            };
            let size = bounded_size(width, height).ok_or_else(|| {
                windows::core::Error::new(E_INVALIDARG, "Invalid image dimensions")
            })?;
            if size != (width, height) {
                let scaler = self.factory.CreateBitmapScaler()?;
                scaler.Initialize(&source, size.0, size.1, WICBitmapInterpolationModeFant)?;
                source = scaler.cast()?;
                (width, height) = size;
                if transform != WICBitmapTransformRotate0 {
                    // Materialize bounded rows once; rotation otherwise re-runs the scaler per column.
                    source = self
                        .factory
                        .CreateBitmapFromSource(&source, WICBitmapCacheOnLoad)?
                        .cast()?;
                }
            }
            // Scale in decoder scanline order before a rotation makes rows nonlocal.
            if transform != WICBitmapTransformRotate0 {
                let rotator = self.factory.CreateBitmapFlipRotator()?;
                rotator.Initialize(&source, transform)?;
                source = rotator.cast()?;
                source.GetSize(&mut width, &mut height)?;
            }
            let converter = self.factory.CreateFormatConverter()?;
            converter.Initialize(
                &source,
                &GUID_WICPixelFormat32bppPBGRA,
                WICBitmapDitherTypeNone,
                None,
                0.0,
                WICBitmapPaletteTypeCustom,
            )?;
            let length = width as usize * height as usize * 4;
            let mut pixels = Vec::new();
            pixels.try_reserve_exact(length).map_err(|_| {
                windows::core::Error::new(E_OUTOFMEMORY, "Not enough memory for this image")
            })?;
            pixels.resize(length, 0);
            converter.CopyPixels(null(), width * 4, &mut pixels)?;
            Ok(Image {
                pixels,
                width,
                height,
                original,
            })
        }
    }
}

unsafe fn exif_orientation(frame: &IWICBitmapFrameDecode) -> u32 {
    unsafe {
        let Ok(reader) = frame.GetMetadataQueryReader() else {
            return 1;
        };
        for query in [w!("/app1/ifd/{ushort=274}"), w!("/ifd/{ushort=274}")] {
            let mut value = PROPVARIANT::default();
            let found = reader.GetMetadataByName(query, &mut value).is_ok();
            let orientation = if found {
                PropVariantToUInt32(&value).unwrap_or(1)
            } else {
                1
            };
            let _ = PropVariantClear(&mut value);
            if found {
                return orientation;
            }
        }
        1
    }
}

pub fn bounded_size(width: u32, height: u32) -> Option<(u32, u32)> {
    if width == 0 || height == 0 {
        return None;
    }
    let scale = (MAX_EDGE as f64 / width.max(height) as f64)
        .min((MAX_PIXELS as f64 / (width as f64 * height as f64)).sqrt())
        .min(1.0);
    Some((
        (width as f64 * scale).floor().max(1.0) as u32,
        (height as f64 * scale).floor().max(1.0) as u32,
    ))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn fixture(name: &str) -> std::path::PathBuf {
        Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("tests/fixtures")
            .join(name)
    }

    #[test]
    fn decodes_real_formats_and_rejects_corrupt_or_missing_files() {
        let decoder = Decoder::new().unwrap();
        for name in [
            "colors.png",
            "colors.bmp",
            "colors.tiff",
            "colors.ico",
            "animated.gif",
        ] {
            let image = decoder
                .load(&fixture(name))
                .unwrap_or_else(|e| panic!("{name}: {e}"));
            assert!(image.width > 0 && image.height > 0, "{name}");
            assert_eq!(
                image.pixels.len(),
                image.width as usize * image.height as usize * 4
            );
        }
        assert!(decoder.load(&fixture("broken.jpg")).is_err());
        assert!(decoder.load(&fixture("missing.png")).is_err());
    }

    #[test]
    fn decoder_premultiplies_alpha_and_uses_the_first_gif_frame() {
        let decoder = Decoder::new().unwrap();
        let alpha = decoder.load(&fixture("alpha.png")).unwrap();
        assert_eq!(alpha.size(), (2, 1));
        for (actual, expected) in alpha.pixels[..4].iter().zip([25u8, 50, 100, 128]) {
            assert!(actual.abs_diff(expected) <= 1);
        }
        let gif = decoder.load(&fixture("animated.gif")).unwrap();
        assert_eq!(&gif.pixels[..4], &[0, 0, 255, 255]);
    }

    #[test]
    fn every_exif_orientation_has_the_correct_dimensions_and_corner_pixels() {
        let decoder = Decoder::new().unwrap();
        let expected = [
            [0, 1, 2, 3],
            [1, 0, 3, 2],
            [3, 2, 1, 0],
            [2, 3, 0, 1],
            [0, 2, 1, 3],
            [2, 0, 3, 1],
            [3, 1, 2, 0],
            [1, 3, 0, 2],
        ];
        let colors = [[0u8, 0, 255], [0, 255, 0], [255, 0, 0], [0, 255, 255]];
        for orientation in 1..=8 {
            let image = decoder
                .load(&fixture(&format!("orientation-{orientation}.jpg")))
                .unwrap();
            assert_eq!(
                image.size(),
                if orientation <= 4 { (64, 48) } else { (48, 64) }
            );
            for (corner, (x, y)) in [
                (image.width / 4, image.height / 4),
                (image.width * 3 / 4, image.height / 4),
                (image.width / 4, image.height * 3 / 4),
                (image.width * 3 / 4, image.height * 3 / 4),
            ]
            .into_iter()
            .enumerate()
            {
                let offset = ((y * image.width + x) * 4) as usize;
                let color = colors[expected[orientation - 1][corner]];
                assert!(
                    image.pixels[offset..offset + 3]
                        .iter()
                        .zip(color)
                        .all(|(a, b)| a.abs_diff(b) < 5),
                    "orientation {orientation}, corner {corner}: {:?} != {color:?}",
                    &image.pixels[offset..offset + 3]
                );
            }
        }
    }

    #[test]
    fn decoder_scales_real_images_before_allocating_the_pixel_buffer() {
        let decoder = Decoder::new().unwrap();
        let wide = decoder.load(&fixture("wide.png")).unwrap();
        assert_eq!(wide.original, (9000, 2));
        assert_eq!(wide.size(), (8192, 1));
    }

    #[test]
    fn decodes_a_normal_windows_path_longer_than_max_path() {
        let root = std::env::temp_dir().join(format!("foto-long-{}", std::process::id()));
        let a = root.join("a".repeat(90));
        let b = a.join("b".repeat(90));
        let c = b.join("c".repeat(90));
        std::fs::create_dir_all(&c).unwrap();
        let path = c.join("photo.png");
        std::fs::copy(fixture("colors.png"), &path).unwrap();
        assert!(path.as_os_str().encode_wide().count() > 260);
        let image = Decoder::new().unwrap().load(&path).unwrap();
        assert_eq!(image.size(), (64, 48));
        assert_eq!(&image.pixels[..4], &[0, 0, 255, 255]);
        std::fs::remove_file(path).unwrap();
        for directory in [c, b, a, root] {
            std::fs::remove_dir(directory).unwrap();
        }
    }

    #[test]
    fn huge_and_extreme_images_stay_within_the_allocation_budget() {
        assert_eq!(bounded_size(640, 480), Some((640, 480)));
        assert_eq!(bounded_size(0, 400), None);
        for (w, h) in [
            (100_000, 100_000),
            (u32::MAX, 1),
            (6000, 4000),
            (9000, 9000),
        ] {
            let (w, h) = bounded_size(w, h).unwrap();
            assert!(w > 0 && h > 0 && w <= MAX_EDGE && h <= MAX_EDGE);
            assert!(w as u64 * h as u64 <= MAX_PIXELS);
        }
    }
}

#[cfg(test)]
mod bounded_size_contract_tests {
    use super::bounded_size;

    // Independent fixed contract: do not import production constants or reproduce its float formula.
    const CONTRACT_MAX_EDGE: u32 = 8_192;
    const CONTRACT_MAX_PIXELS: u64 = 32_000_000;
    const BOUNDARY: [u32; 9] = [1, 8_191, 8_192, 8_193, 5_656, 5_657, 3_906, 3_907, u32::MAX];

    fn next_nonzero(state: &mut u64) -> u32 {
        *state = state
            .wrapping_mul(6_364_136_223_846_793_005)
            .wrapping_add(1);
        ((*state >> 32) as u32).max(1)
    }

    fn check_pair(width: u32, height: u32) {
        let result = bounded_size(width, height).expect("E_POSITIVE_INPUT_MUST_RETURN_SIZE");
        assert!(result.0 > 0 && result.1 > 0, "E_OUTPUT_MUST_STAY_POSITIVE");
        assert!(
            result.0 <= width && result.1 <= height,
            "E_OUTPUT_MUST_NOT_ENLARGE"
        );
        assert!(
            result.0 <= CONTRACT_MAX_EDGE && result.1 <= CONTRACT_MAX_EDGE,
            "E_OUTPUT_EDGE_CONTRACT"
        );
        assert!(
            result.0 as u64 * result.1 as u64 <= CONTRACT_MAX_PIXELS,
            "E_OUTPUT_PIXEL_CONTRACT"
        );
        assert_eq!(
            bounded_size(height, width),
            Some((result.1, result.0)),
            "E_SYMMETRY_CONTRACT"
        );
        if width <= CONTRACT_MAX_EDGE
            && height <= CONTRACT_MAX_EDGE
            && width as u64 * height as u64 <= CONTRACT_MAX_PIXELS
        {
            assert_eq!(result, (width, height), "E_FITTING_IMAGE_MUST_BE_PRESERVED");
        }
    }

    #[test]
    fn bounded_size_fixed_integer_contract_and_boundaries() {
        assert_eq!(bounded_size(0, 0), None, "E_ZERO_DIMENSIONS_MUST_REJECT");
        assert_eq!(bounded_size(0, 1), None, "E_ZERO_WIDTH_MUST_REJECT");
        assert_eq!(bounded_size(1, 0), None, "E_ZERO_HEIGHT_MUST_REJECT");
        assert_eq!(bounded_size(8_191, 1), Some((8_191, 1)), "E_EDGE_8191");
        assert_eq!(bounded_size(8_192, 1), Some((8_192, 1)), "E_EDGE_8192");
        assert_eq!(
            bounded_size(8_193, 1),
            Some((8_192, 1)),
            "E_EDGE_8193_MUST_SCALE"
        );
        assert_eq!(
            bounded_size(5_656, 5_656),
            Some((5_656, 5_656)),
            "E_PIXEL_CAP_5656_FITS"
        );
        assert_eq!(
            bounded_size(5_657, 5_657),
            Some((5_656, 5_656)),
            "E_PIXEL_CAP_5657_MUST_SCALE"
        );
        assert_eq!(
            bounded_size(u32::MAX, 1),
            Some((8_192, 1)),
            "E_SKINNY_U32_MAX"
        );
        assert_eq!(
            bounded_size(1, u32::MAX),
            Some((1, 8_192)),
            "E_SKINNY_SYMMETRY"
        );
        check_pair(8_000, 4_000);
        check_pair(8_000, 4_001);
        for width in BOUNDARY {
            for height in BOUNDARY {
                check_pair(width, height);
            }
        }

        let mut state = 0x9e37_79b9_7f4a_7c15;
        for i in 0usize..50_000 {
            let width = if i % 11 < BOUNDARY.len() {
                BOUNDARY[i % BOUNDARY.len()]
            } else {
                next_nonzero(&mut state)
            };
            let height = if i % 13 < BOUNDARY.len() {
                BOUNDARY[(i * 7 + 3) % BOUNDARY.len()]
            } else {
                next_nonzero(&mut state)
            };
            check_pair(width, height);
        }
    }
}
