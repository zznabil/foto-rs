use crate::{decode::Image, view::View};
use std::sync::Arc;
use windows::{
    Win32::{
        Foundation::RECT,
        Graphics::{
            Direct2D::{Common::*, *},
            DirectWrite::*,
            Dxgi::Common::DXGI_FORMAT_B8G8R8A8_UNORM,
            Gdi::HDC,
        },
    },
    core::{Result, w},
};
use windows_numerics::Matrix3x2;

pub const TOOLBAR: f32 = 52.0;
pub const STATUS: f32 = 34.0;

pub struct Renderer {
    target: ID2D1DCRenderTarget,
    brush: ID2D1SolidColorBrush,
    text: IDWriteTextFormat,
    heading: IDWriteTextFormat,
    centered: IDWriteTextFormat,
    bitmap: Option<ID2D1Bitmap>,
    uploaded: Option<Arc<Image>>,
}

fn color(value: u32) -> D2D1_COLOR_F {
    D2D1_COLOR_F {
        r: ((value >> 16) & 255) as f32 / 255.0,
        g: ((value >> 8) & 255) as f32 / 255.0,
        b: (value & 255) as f32 / 255.0,
        a: 1.0,
    }
}

fn rect(left: f32, top: f32, right: f32, bottom: f32) -> D2D_RECT_F {
    D2D_RECT_F {
        left,
        top,
        right,
        bottom,
    }
}

pub fn identity() -> Matrix3x2 {
    Matrix3x2 {
        M11: 1.0,
        M12: 0.0,
        M21: 0.0,
        M22: 1.0,
        M31: 0.0,
        M32: 0.0,
    }
}

impl Renderer {
    pub fn new(dpi: f32) -> Result<Self> {
        unsafe {
            let factory: ID2D1Factory = D2D1CreateFactory(D2D1_FACTORY_TYPE_SINGLE_THREADED, None)?;
            // A DC target presents through the native paint DC, including remote or
            // occluded desktops where an HWND swap chain can discard successful draws.
            let target = factory.CreateDCRenderTarget(&D2D1_RENDER_TARGET_PROPERTIES {
                r#type: D2D1_RENDER_TARGET_TYPE_SOFTWARE,
                pixelFormat: D2D1_PIXEL_FORMAT {
                    format: DXGI_FORMAT_B8G8R8A8_UNORM,
                    alphaMode: D2D1_ALPHA_MODE_IGNORE,
                },
                dpiX: 96.0,
                dpiY: 96.0,
                ..Default::default()
            })?;
            target.SetTextAntialiasMode(D2D1_TEXT_ANTIALIAS_MODE_GRAYSCALE);
            let write: IDWriteFactory = DWriteCreateFactory(DWRITE_FACTORY_TYPE_SHARED)?;
            let format = |size, weight| {
                write.CreateTextFormat(
                    w!("Segoe UI"),
                    None,
                    weight,
                    DWRITE_FONT_STYLE_NORMAL,
                    DWRITE_FONT_STRETCH_NORMAL,
                    size * dpi,
                    w!("en-US"),
                )
            };
            let text = format(12.0, DWRITE_FONT_WEIGHT_NORMAL)?;
            let heading = format(38.0, DWRITE_FONT_WEIGHT_LIGHT)?;
            heading.SetTextAlignment(DWRITE_TEXT_ALIGNMENT_CENTER)?;
            let centered = format(15.0, DWRITE_FONT_WEIGHT_NORMAL)?;
            centered.SetTextAlignment(DWRITE_TEXT_ALIGNMENT_CENTER)?;
            let brush = target.CreateSolidColorBrush(&color(0xd5d7dc), None)?;
            Ok(Self {
                target,
                brush,
                text,
                heading,
                centered,
                bitmap: None,
                uploaded: None,
            })
        }
    }

    pub fn bind(&self, dc: HDC, bounds: &RECT) -> Result<()> {
        unsafe { self.target.BindDC(dc, bounds) }
    }

    fn text(&self, value: &str, bounds: D2D_RECT_F, format: &IDWriteTextFormat, tint: u32) {
        unsafe {
            self.brush.SetColor(&color(tint));
            let wide: Vec<u16> = value.encode_utf16().collect();
            self.target.DrawText(
                &wide,
                format,
                &bounds,
                &self.brush,
                D2D1_DRAW_TEXT_OPTIONS_CLIP,
                DWRITE_MEASURING_MODE_NATURAL,
            );
        }
    }

    pub fn draw(
        &mut self,
        image: Option<&Arc<Image>>,
        view: &View,
        status: &str,
        error: Option<&str>,
        fullscreen: bool,
        dpi: f32,
    ) -> Result<()> {
        unsafe {
            if let Some(image) = image {
                if self
                    .uploaded
                    .as_ref()
                    .is_none_or(|old| !Arc::ptr_eq(old, image))
                {
                    if let Some(bitmap) = self.bitmap.as_ref().filter(|bitmap| {
                        let size = bitmap.GetPixelSize();
                        size.width == image.width && size.height == image.height
                    }) {
                        bitmap.CopyFromMemory(
                            None,
                            image.pixels.as_ptr().cast(),
                            image.width * 4,
                        )?;
                    } else {
                        let bitmap = self.target.CreateBitmap(
                            D2D_SIZE_U {
                                width: image.width,
                                height: image.height,
                            },
                            Some(image.pixels.as_ptr().cast()),
                            image.width * 4,
                            &D2D1_BITMAP_PROPERTIES {
                                pixelFormat: D2D1_PIXEL_FORMAT {
                                    format: DXGI_FORMAT_B8G8R8A8_UNORM,
                                    alphaMode: D2D1_ALPHA_MODE_PREMULTIPLIED,
                                },
                                dpiX: 96.0,
                                dpiY: 96.0,
                            },
                        )?;
                        self.bitmap = Some(bitmap);
                    }
                    self.uploaded = Some(image.clone());
                }
            } else {
                self.bitmap = None;
                self.uploaded = None;
            }
            let size = self.target.GetSize();
            let (top, bottom) = if fullscreen {
                (0.0, size.height)
            } else {
                (
                    TOOLBAR * dpi,
                    (size.height - STATUS * dpi).max(TOOLBAR * dpi),
                )
            };
            self.target.BeginDraw();
            self.target.SetTransform(&identity());
            self.target.Clear(Some(&color(0x111214)));
            self.target.PushAxisAlignedClip(
                &rect(0.0, top, size.width, bottom),
                D2D1_ANTIALIAS_MODE_ALIASED,
            );
            if error.is_none() {
                if let (Some(image), Some(bitmap)) = (image, &self.bitmap) {
                    let scale = view.scale(image.size(), (size.width, bottom - top));
                    let (sin, cos) = (view.turns as f32 * std::f32::consts::FRAC_PI_2).sin_cos();
                    self.target.SetTransform(&Matrix3x2 {
                        M11: cos * scale,
                        M12: sin * scale,
                        M21: -sin * scale,
                        M22: cos * scale,
                        M31: size.width / 2.0 + view.pan.0,
                        M32: (top + bottom) / 2.0 + view.pan.1,
                    });
                    self.target.DrawBitmap(
                        bitmap,
                        Some(&rect(
                            -(image.width as f32) / 2.0,
                            -(image.height as f32) / 2.0,
                            image.width as f32 / 2.0,
                            image.height as f32 / 2.0,
                        )),
                        1.0,
                        D2D1_BITMAP_INTERPOLATION_MODE_LINEAR,
                        None,
                    );
                    self.target.SetTransform(&identity());
                } else {
                    let center = (top + bottom) / 2.0;
                    self.text(
                        "Foto",
                        rect(0.0, center - 78.0 * dpi, size.width, center - 20.0 * dpi),
                        &self.heading,
                        0xe8e9ed,
                    );
                    self.text(
                        if status.contains("Opening") {
                            "Opening photo…"
                        } else {
                            "Drop a photo here"
                        },
                        rect(0.0, center - 5.0 * dpi, size.width, center + 25.0 * dpi),
                        &self.centered,
                        0xa3a6af,
                    );
                    self.text(
                        "Ctrl+O to open   ·   ← → to browse   ·   Scroll to zoom",
                        rect(0.0, center + 36.0 * dpi, size.width, center + 65.0 * dpi),
                        &self.centered,
                        0x717680,
                    );
                }
            } else {
                let center = (top + bottom) / 2.0;
                self.text(
                    "Could not open this photo",
                    rect(
                        20.0 * dpi,
                        center - 50.0 * dpi,
                        size.width - 20.0 * dpi,
                        center,
                    ),
                    &self.centered,
                    0xe8e9ed,
                );
                self.text(
                    error.unwrap_or_default(),
                    rect(
                        40.0 * dpi,
                        center + 2.0 * dpi,
                        size.width - 40.0 * dpi,
                        center + 85.0 * dpi,
                    ),
                    &self.centered,
                    0xa3a6af,
                );
            }
            self.target.PopAxisAlignedClip();
            if !fullscreen {
                self.brush.SetColor(&color(0x191a1d));
                self.target
                    .FillRectangle(&rect(0.0, 0.0, size.width, top), &self.brush);
                self.target
                    .FillRectangle(&rect(0.0, bottom, size.width, size.height), &self.brush);
                self.text(
                    status,
                    rect(
                        18.0 * dpi,
                        bottom + 9.0 * dpi,
                        size.width - 18.0 * dpi,
                        size.height,
                    ),
                    &self.text,
                    0x969ba5,
                );
            }
            self.target.EndDraw(None, None)
        }
    }
}
