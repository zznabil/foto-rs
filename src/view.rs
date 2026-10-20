//! Image coordinates are physical pixels. No timer or animation is needed.

#[derive(Clone, Copy, Debug, Default)]
pub struct View {
    pub zoom: Option<f32>,
    pub pan: (f32, f32),
    pub turns: u8,
}

impl View {
    pub fn reset(&mut self) {
        *self = Self::default();
    }

    pub fn dimensions(&self, width: u32, height: u32) -> (f32, f32) {
        if self.turns % 2 == 0 {
            (width as f32, height as f32)
        } else {
            (height as f32, width as f32)
        }
    }

    pub fn scale(&self, image: (u32, u32), area: (f32, f32)) -> f32 {
        let (w, h) = self.dimensions(image.0, image.1);
        self.zoom
            .unwrap_or_else(|| (area.0 / w).min(area.1 / h).min(1.0))
            .max(0.001)
    }

    pub fn zoom_at(&mut self, current: f32, factor: f32, anchor: (f32, f32)) {
        let next = (current * factor).clamp(0.01, 64.0);
        let ratio = next / current;
        self.pan.0 = anchor.0 - (anchor.0 - self.pan.0) * ratio;
        self.pan.1 = anchor.1 - (anchor.1 - self.pan.1) * ratio;
        self.zoom = Some(next);
    }

    pub fn clamp_pan(&mut self, image: (u32, u32), area: (f32, f32)) {
        let (w, h) = self.dimensions(image.0, image.1);
        let scale = self.scale(image, area);
        let max_x = ((w * scale - area.0) / 2.0).max(0.0);
        let max_y = ((h * scale - area.1) / 2.0).max(0.0);
        self.pan.0 = self.pan.0.clamp(-max_x, max_x);
        self.pan.1 = self.pan.1.clamp(-max_y, max_y);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn fit_preserves_small_images_and_handles_rotated_portraits() {
        let mut v = View::default();
        assert_eq!(v.scale((400, 200), (1200.0, 800.0)), 1.0);
        assert_eq!(v.scale((4000, 2000), (1000.0, 800.0)), 0.25);
        v.turns = 1;
        assert_eq!(v.scale((4000, 2000), (1000.0, 800.0)), 0.2);
    }

    #[test]
    fn zoom_keeps_the_pixel_under_the_pointer_fixed() {
        let mut v = View {
            pan: (13.0, -7.0),
            ..Default::default()
        };
        let anchor = (100.0, 40.0);
        let pixel = ((anchor.0 - v.pan.0) / 0.5, (anchor.1 - v.pan.1) / 0.5);
        v.zoom_at(0.5, 1.25, anchor);
        let scale = v.zoom.unwrap();
        assert!((pixel.0 * scale + v.pan.0 - anchor.0).abs() < 0.001);
        assert!((pixel.1 * scale + v.pan.1 - anchor.1).abs() < 0.001);
    }

    #[test]
    fn panning_cannot_lose_the_image_outside_the_window() {
        let mut v = View {
            zoom: Some(1.0),
            pan: (9999.0, -9999.0),
            turns: 0,
        };
        v.clamp_pan((2000, 1000), (1000.0, 800.0));
        assert_eq!(v.pan, (500.0, -100.0));
        v.reset();
        assert_eq!(v.pan, (0.0, 0.0));
        assert!(v.zoom.is_none());
    }
}
