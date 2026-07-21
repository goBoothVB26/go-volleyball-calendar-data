"""Create a solid-white silhouette version of a logo for dark-mode use.

Takes a logo PNG with a transparent background (e.g. one already run
through make_logos_transparent.py) and recolors every visible pixel to
white while preserving its alpha/transparency -- turning a black or
dark-colored wordmark into a white one that's actually visible sitting
directly on a dark background (no backing plate).

Usage:
    python scripts/make_logo_white.py path/to/logos/govb.png

Writes <name>-white.png next to the original (e.g. govb-white.png).
"""

import sys
from pathlib import Path

from PIL import Image


def make_white(path: Path) -> Path:
    img = Image.open(path).convert("RGBA")
    px = img.load()
    w, h = img.size
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            if a > 0:
                px[x, y] = (255, 255, 255, a)
    out = path.with_name(path.stem + "-white" + path.suffix)
    img.save(out)
    return out


def main():
    if len(sys.argv) != 2:
        sys.exit("usage: python scripts/make_logo_white.py <logo.png>")
    src = Path(sys.argv[1])
    if not src.exists():
        sys.exit(f"not found: {src}")
    out = make_white(src)
    print(f"  {src.name} -> {out.name}")


if __name__ == "__main__":
    main()
