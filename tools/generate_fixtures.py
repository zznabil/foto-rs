# SPDX-License-Identifier: GPL-3.0-or-later
"""Regenerate synthetic decoder fixtures. Development only; requires Pillow."""
import argparse
from pathlib import Path
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"

def generate_fixtures():
    FIXTURES.mkdir(parents=True, exist_ok=True)

    base = Image.new("RGB", (64, 48))
    draw = ImageDraw.Draw(base)
    for bounds, color in [((0, 0, 31, 23), "red"), ((32, 0, 63, 23), (0, 255, 0)),
                          ((0, 24, 31, 47), "blue"), ((32, 24, 63, 47), "yellow")]:
        draw.rectangle(bounds, fill=color)
    for orientation in range(1, 9):
        exif = Image.Exif()
        exif[274] = orientation
        base.save(FIXTURES / f"orientation-{orientation}.jpg", quality=100, subsampling=0, exif=exif)
    for extension in ("png", "bmp", "tiff", "ico"):
        base.save(FIXTURES / f"colors.{extension}")
    alpha = Image.new("RGBA", (2, 1), (200, 100, 50, 128))
    alpha.save(FIXTURES / "alpha.png")
    first = Image.new("RGB", (16, 16), "red")
    first.save(FIXTURES / "animated.gif", save_all=True,
               append_images=[Image.new("RGB", (16, 16), "blue")], duration=100, loop=0)
    Image.new("RGB", (9000, 2), "red").save(FIXTURES / "wide.png")
    (FIXTURES / "broken.jpg").write_bytes(b"This is not an image.\x00\xff")



def generate_benchmarks():
    # Larger local-only images exercise real decode, upload and navigation costs.
    bench = ROOT / "artifacts" / "photos"
    bench.mkdir(parents=True, exist_ok=True)
    for number, tint in [(1, (28, 100, 200)), (2, (180, 80, 35)), (10, (40, 150, 90))]:
        gradient = Image.linear_gradient("L").resize((6000, 4000))
        image = Image.merge("RGB", tuple(gradient.point(lambda x, t=t: (x + t) // 2) for t in tint))
        d = ImageDraw.Draw(image)
        d.rectangle((0, 0, 1499, 999), fill="red")
        d.rectangle((4500, 0, 5999, 999), fill=(0, 255, 0))
        d.rectangle((0, 3000, 1499, 3999), fill="blue")
        d.rectangle((4500, 3000, 5999, 3999), fill="yellow")
        d.text((2700, 1900), f"Foto test {number}", fill="white", font_size=90)
        image.save(bench / f"photo{number}.jpg", quality=94)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--bench-only', action='store_true', help='Keep committed decoder fixtures unchanged')
    args = parser.parse_args()
    if not args.bench_only:
        generate_fixtures()
        print(f"Fixtures: {FIXTURES}")
    generate_benchmarks()
    print(f"24 MP benchmark images: {ROOT / 'artifacts/photos'}")
