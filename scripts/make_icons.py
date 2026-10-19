#!/usr/bin/env python3
"""Generate the configurator's app shortcut icons from the README logo
(scripts/make_logo.py): its two-wire bus with the terminators and the nodes
tapping the line, in the logo's light colours, on a rounded square.

Writes tools/deploy/canworks/configurator/icons/logo.ico (Windows),
logo.icns (macOS) and logo-256.png (Linux). The files are committed, so
building the package needs nothing; run this again after a logo change.

Needs Pillow (development only): python3 -m pip install pillow
Usage: python3 scripts/make_icons.py [OUT_DIR]
"""
import argparse
import pathlib

from PIL import Image, ImageDraw

# The light theme of make_logo.py.
INK, MUTE, CAN_H, CAN_L = "#1a2233", "#5b6678", "#1f5fbf", "#e0782a"
PANEL = "#ffffff"
SIZE = 1024


def draw(size=SIZE):
    """The icon at `size` px, drawn four times larger and scaled down for smooth edges."""
    k = 4
    s = size * k
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    u = s / 64  # the drawing is on a 64 x 64 grid
    d.rounded_rectangle((2 * u, 2 * u, 62 * u, 62 * u), radius=12 * u, fill=PANEL, outline="#dcdcd6", width=round(u))
    y_h, y_l = 24 * u, 31 * u
    left, right = 11 * u, 53 * u
    d.line((left, y_h, right, y_h), fill=CAN_H, width=round(4 * u))
    d.line((left, y_l, right, y_l), fill=CAN_L, width=round(4 * u))
    for x in (7 * u, 53 * u):  # 120 ohm terminators
        d.rounded_rectangle((x, y_h - 5 * u, x + 4 * u, y_l + 5 * u), radius=1.5 * u, fill=MUTE)
    for x in (21 * u, 43 * u):  # two nodes below the bus
        d.line((x - 3 * u, y_h, x - 3 * u, 44 * u), fill=CAN_H, width=round(2.5 * u))
        d.line((x + 3 * u, y_l, x + 3 * u, 44 * u), fill=CAN_L, width=round(2.5 * u))
        d.rounded_rectangle((x - 8 * u, 42 * u, x + 8 * u, 52 * u), radius=3 * u, fill=INK)
    return img.resize((size, size), Image.LANCZOS)


def main():
    root = pathlib.Path(__file__).resolve().parent.parent
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("out", nargs="?", default=root / "tools" / "deploy" / "canworks" / "configurator" / "icons")
    out = pathlib.Path(ap.parse_args().out)
    out.mkdir(parents=True, exist_ok=True)
    big = draw()
    big.resize((256, 256), Image.LANCZOS).save(out / "logo-256.png", optimize=True)
    big.save(out / "logo.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    big.save(out / "logo.icns")
    for name in ("logo-256.png", "logo.ico", "logo.icns"):
        print(out / name)


if __name__ == "__main__":
    main()
