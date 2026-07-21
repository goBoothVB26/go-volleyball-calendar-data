"""Strip near-white backgrounds from logo images, saving transparent PNGs.

Usage:
    pip install Pillow
    python scripts/make_logos_transparent.py path/to/logos/

Every .png/.jpg/.jpeg in the folder is processed IN PLACE (jpgs are
rewritten as .png next to the original, since JPEG can't hold
transparency). Only pixels connected to the image border are cleared, so
white areas INSIDE the logo artwork (letters, highlights) are preserved.

Tune TOLERANCE if a logo's background is off-white/cream: higher clears
more aggressively.
"""

import sys
from pathlib import Path

from PIL import Image

TOLERANCE = 30  # 0-255; how far from pure white still counts as background


def _is_bg(pixel, tolerance=TOLERANCE):
    r, g, b = pixel[:3]
    return r >= 255 - tolerance and g >= 255 - tolerance and b >= 255 - tolerance


def make_transparent(path: Path) -> Path:
    img = Image.open(path).convert("RGBA")
    px = img.load()
    w, h = img.size

    # Flood fill from every border pixel that looks like background.
    seen = [[False] * w for _ in range(h)]
    stack = [(x, y) for x in range(w) for y in (0, h - 1)] + \
            [(x, y) for y in range(h) for x in (0, w - 1)]
    while stack:
        x, y = stack.pop()
        if x < 0 or y < 0 or x >= w or y >= h or seen[y][x]:
            continue
        seen[y][x] = True
        if not _is_bg(px[x, y]):
            continue
        px[x, y] = (255, 255, 255, 0)
        stack.extend([(x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)])

    out = path.with_suffix(".png")
    img.save(out)
    if out != path:
        path.unlink()
    return out


def main():
    if len(sys.argv) != 2:
        sys.exit("usage: python scripts/make_logos_transparent.py <logos-folder>")
    folder = Path(sys.argv[1])
    images = [p for p in folder.iterdir()
              if p.suffix.lower() in (".png", ".jpg", ".jpeg")]
    if not images:
        sys.exit(f"no images found in {folder}")
    for p in images:
        out = make_transparent(p)
        print(f"  {p.name} -> {out.name}")
    print(f"{len(images)} logo(s) processed.")


if __name__ == "__main__":
    main()
