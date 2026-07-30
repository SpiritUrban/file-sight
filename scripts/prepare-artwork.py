#!/usr/bin/env python
"""Derive the shipped artwork from the source images.

    python scripts/prepare-artwork.py

Sources live in `assets/` and are committed; everything this writes is
reproducible from them, so nobody has to remember what was done by hand.

  assets/logo-source.png  ->  desktop/src-tauri/app-icon.png
  assets/hero-source.png  ->  site/hero-art.png

Two problems are fixed here, both invisible in a preview and fatal in use.

**The logo has a glow around the badge.** An app icon is rendered at 16 px in
a taskbar; padding the mark down to 60% of the canvas and surrounding it with
a soft halo leaves about ten usable pixels and a purple smudge. The badge is
cropped out of the glow and made to fill the canvas.

**The hero art has its lighting baked in.** 90% of its visible pixels are a
white glow and only 5% are the actual lines, which are dark. On the dark
theme that is exactly backwards: a bright haze where the drawing should be,
and invisible line work. The glow is discarded and the drawing is turned into
a pure alpha mask, so the page can colour it per theme with one CSS filter
instead of shipping two images.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[1]
ASSETS = REPO_ROOT / "assets"

LOGO_SOURCE = ASSETS / "logo-source.png"
HERO_SOURCE = ASSETS / "hero-source.png"
LOGO_OUT = REPO_ROOT / "desktop" / "src-tauri" / "app-icon.png"
HERO_OUT = REPO_ROOT / "site" / "hero-art.png"

#: Alpha above which a pixel counts as the solid badge rather than its glow.
SOLID_ALPHA = 200

#: Luminance below which a pixel counts as line work rather than glow.
LINE_LUMINANCE = 160


def crop_logo(source: Path, target: Path, size: int = 1024) -> None:
    image = Image.open(source).convert("RGBA")
    alpha = np.asarray(image)[..., 3]

    solid = alpha >= SOLID_ALPHA
    if not solid.any():
        raise SystemExit(f"{source}: no solid pixels found; is it all glow?")
    rows = np.where(solid.any(axis=1))[0]
    cols = np.where(solid.any(axis=0))[0]
    top, bottom = int(rows.min()), int(rows.max())
    left, right = int(cols.min()), int(cols.max())

    # Square the crop around the badge's centre, so the rounded corners stay
    # symmetric and the icon is not subtly off-centre at small sizes.
    height, width = bottom - top + 1, right - left + 1
    side = max(height, width)
    centre_y, centre_x = (top + bottom) // 2, (left + right) // 2
    half = side // 2
    box = (centre_x - half, centre_y - half, centre_x - half + side, centre_y - half + side)

    cropped = image.crop(box).resize((size, size), Image.LANCZOS)
    cropped.save(target, optimize=True)

    before = image.size[0]
    print(f"logo : {source.name} {before}x{before} -> {target.name} {size}x{size}")
    print(f"       badge occupied {width}x{height} of the source; glow removed")


def flatten_hero(source: Path, target: Path, margin: int = 60) -> None:
    image = Image.open(source).convert("RGBA")
    data = np.asarray(image).astype(np.int16)
    rgb, alpha = data[..., :3], data[..., 3]
    luminance = rgb.mean(axis=2)

    # Keep only what is drawn: visible AND darker than the glow.
    is_line = (alpha > 10) & (luminance < LINE_LUMINANCE)
    if not is_line.any():
        raise SystemExit(f"{source}: found no line work to keep")

    # Opacity from darkness, so anti-aliased edges survive as soft alpha
    # rather than becoming a jagged one-bit mask.
    strength = np.clip((LINE_LUMINANCE - luminance) / LINE_LUMINANCE, 0, 1)
    new_alpha = np.where(is_line, (strength * (alpha / 255.0) * 255), 0)

    # Black, so `filter: invert()` produces clean white on the dark theme.
    flat = np.zeros(data.shape, dtype=np.uint8)
    flat[..., 3] = new_alpha.astype(np.uint8)
    result = Image.fromarray(flat, "RGBA")

    rows = np.where(is_line.any(axis=1))[0]
    top = max(int(rows.min()) - margin, 0)
    bottom = min(int(rows.max()) + margin, image.size[1])
    result = result.crop((0, top, image.size[0], bottom))

    result.save(target, optimize=True)
    kept = is_line.sum() / max((alpha > 10).sum(), 1)
    print(f"hero : {source.name} {image.size[0]}x{image.size[1]} -> {target.name} "
          f"{result.size[0]}x{result.size[1]}")
    print(f"       kept {kept:.0%} of the visible pixels (the drawing), dropped the glow")
    print(f"       {source.stat().st_size / 1048576:.2f} MB -> "
          f"{target.stat().st_size / 1048576:.2f} MB")


def main() -> int:
    missing = [p for p in (LOGO_SOURCE, HERO_SOURCE) if not p.is_file()]
    if missing:
        print("missing source artwork:", file=sys.stderr)
        for path in missing:
            print(f"  {path}", file=sys.stderr)
        return 2

    crop_logo(LOGO_SOURCE, LOGO_OUT)
    flatten_hero(HERO_SOURCE, HERO_OUT)
    print(
        "\nNext: regenerate the icon set from the cropped logo\n"
        "  cd desktop && npx tauri icon src-tauri/app-icon.png"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
