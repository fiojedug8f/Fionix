"""Generate Fionix's placeholder art (background + application icon).

The generated files are committed to the repository, so end users never need
Pillow.  Run this script only when the art direction changes::

    python tools/generate_assets.py
"""

from __future__ import annotations

import math
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
ICONS = ASSETS / "icons"

BACKGROUND_SIZE = (2400, 1500)


def _vertical_gradient(size: tuple[int, int], top: str, bottom: str) -> Image.Image:
    width, height = size
    gradient = Image.new("RGB", (1, height))
    draw = ImageDraw.Draw(gradient)
    top_rgb = Image.new("RGB", (1, 1), top).getpixel((0, 0))
    bottom_rgb = Image.new("RGB", (1, 1), bottom).getpixel((0, 0))
    for y in range(height):
        t = y / max(1, height - 1)
        eased = t**1.15
        color = tuple(
            int(round(top_rgb[i] * (1 - eased) + bottom_rgb[i] * eased))
            for i in range(3)
        )
        draw.point((0, y), fill=color)
    return gradient.resize(size, Image.Resampling.BICUBIC)


def _smoothstep(edge0: float, edge1: float, value: float) -> float:
    t = max(0.0, min(1.0, (value - edge0) / (edge1 - edge0)))
    return t * t * (3 - 2 * t)


def _radial_glow(
    size: tuple[int, int],
    center: tuple[float, float],
    radius: float,
    color: tuple[int, int, int],
    strength: float,
) -> Image.Image:
    """A seam-free soft orb on a transparent canvas."""
    canvas_w, canvas_h = size
    mask_side = 320
    mask = Image.new("L", (mask_side, mask_side), 0)
    pixels = []
    for y in range(mask_side):
        ny = (y + 0.5) / mask_side * 2 - 1
        for x in range(mask_side):
            nx = (x + 0.5) / mask_side * 2 - 1
            distance = math.hypot(nx, ny)
            falloff = 1 - _smoothstep(0.0, 1.0, distance)
            pixels.append(int(255 * strength * falloff**1.7))
    mask.putdata(pixels)

    diameter = int(radius * 2)
    mask = mask.resize((diameter, diameter), Image.Resampling.LANCZOS)
    orb = Image.new("RGBA", (diameter, diameter), color + (0,))
    orb.putalpha(mask)

    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    x = int(center[0] * canvas_w - diameter / 2)
    y = int(center[1] * canvas_h - diameter / 2)
    layer.alpha_composite(orb, (x, y))
    return layer


def _sine_ribbon(
    size: tuple[int, int],
    start: tuple[float, float],
    end: tuple[float, float],
    amplitude: float,
    color: tuple[int, int, int],
    opacity: int,
) -> Image.Image:
    """A gently curved, blurred line used as a light streak."""
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    steps = 160
    points = []
    for i in range(steps + 1):
        t = i / steps
        x = (start[0] + (end[0] - start[0]) * t) * size[0]
        curve = math.sin(t * math.pi * 2.1) * amplitude * size[1]
        y = (start[1] + (end[1] - start[1]) * t) * size[1] + curve
        points.append((x, y))
    for width, alpha in ((14, opacity // 4), (5, opacity // 2), (2, opacity)):
        draw.line(points, fill=color + (alpha,), width=width, joint="curve")
    return layer.filter(ImageFilter.GaussianBlur(9))


def _add_noise(image: Image.Image, amount: float = 0.05) -> Image.Image:
    noise = Image.effect_noise((image.width // 3, image.height // 3), 34)
    noise = noise.convert("L").resize(image.size, Image.Resampling.NEAREST)
    noise_rgb = Image.merge("RGB", (noise, noise, noise))
    return Image.blend(image, noise_rgb, amount)


def build_background() -> Image.Image:
    size = BACKGROUND_SIZE
    random.seed(7)

    canvas = _vertical_gradient(size, "#0B0918", "#05040D").convert("RGBA")

    orbs = [
        # (centre, radius, colour, strength)
        ((0.80, 0.04), 0.58 * size[0], (116, 63, 255), 0.82),
        ((0.99, 0.46), 0.42 * size[0], (47, 98, 238), 0.58),
        ((0.10, 0.98), 0.52 * size[0], (50, 58, 196), 0.44),
        ((0.66, 0.82), 0.34 * size[0], (18, 145, 172), 0.20),
        ((0.32, 0.02), 0.28 * size[0], (117, 36, 196), 0.34),
    ]
    for center, radius, color, strength in orbs:
        canvas = Image.alpha_composite(
            canvas, _radial_glow(size, center, radius, color, strength)
        )

    # A single quiet light streak adds movement without stealing attention.
    canvas = Image.alpha_composite(
        canvas,
        _sine_ribbon(
            size,
            start=(0.02, 0.22),
            end=(0.98, 0.10),
            amplitude=0.035,
            color=(196, 181, 253),
            opacity=64,
        ),
    )
    canvas = Image.alpha_composite(
        canvas,
        _sine_ribbon(
            size,
            start=(0.10, 0.88),
            end=(0.86, 0.74),
            amplitude=0.03,
            color=(34, 211, 238),
            opacity=28,
        ),
    )

    # Fine dust particles.
    particles = Image.new("RGBA", size, (0, 0, 0, 0))
    particle_draw = ImageDraw.Draw(particles)
    for _ in range(110):
        x = random.uniform(0, size[0])
        y = random.uniform(0, size[1])
        radius = random.choice((1, 1, 1, 2, 2, 3))
        alpha = random.randint(18, 80)
        particle_draw.ellipse(
            (x, y, x + radius, y + radius), fill=(205, 198, 255, alpha)
        )
    particles = particles.filter(ImageFilter.GaussianBlur(1.2))
    canvas = Image.alpha_composite(canvas, particles)

    vignette = Image.new("L", size, 0)
    vignette_draw = ImageDraw.Draw(vignette)
    vignette_draw.ellipse(
        (-size[0] * 0.25, -size[1] * 0.35, size[0] * 1.25, size[1] * 1.35),
        fill=255,
    )
    vignette = vignette.filter(ImageFilter.GaussianBlur(size[0] // 8))
    shade = Image.new("RGBA", size, (2, 2, 8, 150))
    shade.putalpha(Image.eval(vignette, lambda value: int((255 - value) * 0.9)))
    canvas = Image.alpha_composite(canvas, shade)

    # A calm, darker centre keeps UI text readable on top of the art.
    centre_shade = Image.new("RGBA", size, (0, 0, 0, 0))
    centre = Image.radial_gradient("L").resize(size, Image.Resampling.BICUBIC)
    alpha = Image.eval(centre, lambda value: int((255 - value) * 0.20))
    centre_shade.putalpha(alpha)
    canvas = Image.alpha_composite(canvas, centre_shade)

    # Global tint keeps the art firmly in "dark premium" territory.
    canvas = Image.alpha_composite(canvas, Image.new("RGBA", size, (4, 4, 11, 34)))

    rgb = _add_noise(canvas.convert("RGB"), 0.035)
    return rgb.filter(ImageFilter.GaussianBlur(0.4))


def _diagonal_gradient(size: int) -> Image.Image:
    """Three-stop violet-to-blue gradient running top-left -> bottom-right."""
    colors = ("#8B5CF6", "#6D3FF0", "#2563EB")
    stops = (0.0, 0.52, 1.0)
    small = 192
    image = Image.new("RGB", (small, small))
    pixels = image.load()
    for y in range(small):
        for x in range(small):
            t = min(1.0, (x + y) / (2 * (small - 1)))
            if t <= stops[1]:
                local = t / stops[1]
                a, b = colors[0], colors[1]
            else:
                local = (t - stops[1]) / (stops[2] - stops[1])
                a, b = colors[1], colors[2]
            rgb_a = tuple(int(a[i : i + 2], 16) for i in (1, 3, 5))
            rgb_b = tuple(int(b[i : i + 2], 16) for i in (1, 3, 5))
            pixels[x, y] = tuple(
                int(rgb_a[i] * (1 - local) + rgb_b[i] * local) for i in range(3)
            )
    return image.resize((size, size), Image.Resampling.BICUBIC)


def _four_point_star(draw: ImageDraw.ImageDraw, cx: float, cy: float, r: float, fill):
    points = [
        (cx, cy - r),
        (cx + r * 0.22, cy - r * 0.22),
        (cx + r, cy),
        (cx + r * 0.22, cy + r * 0.22),
        (cx, cy + r),
        (cx - r * 0.22, cy + r * 0.22),
        (cx - r, cy),
        (cx - r * 0.22, cy - r * 0.22),
    ]
    draw.polygon(points, fill=fill)


def build_icon(size: int = 512) -> Image.Image:
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    radius = int(size * 0.25)
    gradient = _diagonal_gradient(size).convert("RGBA")

    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, size - 1, size - 1), radius=radius, fill=255
    )
    canvas.paste(gradient, (0, 0), mask)

    # Inner highlight along the top edge.
    highlight = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    hdraw = ImageDraw.Draw(highlight)
    hdraw.rounded_rectangle(
        (int(size * 0.035), int(size * 0.035), int(size * 0.965), int(size * 0.965)),
        radius=int(radius * 0.9),
        outline=(255, 255, 255, 50),
        width=max(1, size // 160),
    )
    canvas = Image.alpha_composite(canvas, highlight)

    # Soft glow in the upper-right corner.
    glow = _radial_glow(
        (size, size), (0.72, 0.22), size * 0.62, (34, 211, 238), 0.42
    )
    glow_alpha = Image.composite(
        glow.getchannel("A"), Image.new("L", (size, size), 0), mask
    )
    glow.putalpha(glow_alpha)
    canvas = Image.alpha_composite(canvas, glow)

    white = (250, 248, 255, 255)
    stem_w = int(size * 0.095)
    stem = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    sdraw = ImageDraw.Draw(stem)
    left = int(size * 0.31)
    top = int(size * 0.235)
    bottom = int(size * 0.79)
    sdraw.rounded_rectangle(
        (left, top, left + stem_w, bottom), radius=stem_w // 2, fill=white
    )
    bar_right = int(size * 0.70)
    bar_h = int(size * 0.085)
    sdraw.rounded_rectangle(
        (left, top, bar_right, top + bar_h), radius=bar_h // 2, fill=white
    )
    mid_right = int(size * 0.62)
    sdraw.rounded_rectangle(
        (left, int(size * 0.455), mid_right, int(size * 0.455) + bar_h),
        radius=bar_h // 2,
        fill=white,
    )
    canvas = Image.alpha_composite(canvas, stem)

    # A small four-point spark completes the wordmark ("Fionix" = a spark).
    sparkle = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    sparkle_draw = ImageDraw.Draw(sparkle)
    star_x, star_y = size * 0.77, size * 0.265
    _four_point_star(
        sparkle_draw, star_x, star_y, size * 0.095, (110, 231, 255, 70)
    )
    _four_point_star(
        sparkle_draw, star_x, star_y, size * 0.058, (242, 250, 255, 255)
    )
    _four_point_star(
        sparkle_draw,
        size * 0.85,
        size * 0.20,
        size * 0.022,
        (221, 245, 255, 210),
    )
    canvas = Image.alpha_composite(canvas, sparkle.filter(ImageFilter.GaussianBlur(1.2)))

    # Clip everything to the rounded tile once more.
    clipped = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    clipped.paste(canvas, (0, 0), mask)
    return clipped


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    ICONS.mkdir(parents=True, exist_ok=True)

    background = build_background()
    background.save(ASSETS / "background.png", optimize=True)
    print(f"Wrote {ASSETS / 'background.png'} ({background.size[0]}x{background.size[1]})")

    icon = build_icon(512)
    icon.save(ICONS / "fionix.png", optimize=True)
    icon.save(
        ICONS / "fionix.ico",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    print(f"Wrote {ICONS / 'fionix.png'} and fionix.ico")


if __name__ == "__main__":
    main()
