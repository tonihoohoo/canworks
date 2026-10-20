#!/usr/bin/env python3
"""Generate the app icons from the README logo (scripts/make_logo.py): the
logo's blue "can" over its two-wire bus with the terminators and two nodes,
on a rounded square; at 32 px and below the "c" over the two wires, which
stays readable where "can" would not (app-icon-from-logo).

Writes, under tools/deploy/canworks/configurator/:
  icons/logo.ico       Windows shortcut (16-32 px small form, 48-256 px large)
  icons/logo.icns      macOS app
  icons/logo-256.png   Linux .desktop entry
  static/favicon.svg   browser tab (small form, dark colours in dark mode)
  static/apple-touch-icon.png  180 px, Safari Add to Dock and phones

The letters are the outlined glyphs of docs/images/logo-light.svg, so no font
is needed. The files are committed, so building the package needs nothing;
run this again after a logo change.

Needs resvg-py and Pillow (development only):
  python3 -m pip install resvg-py pillow
Usage: python3 scripts/make_icons.py [CONFIGURATOR_DIR]
"""
import argparse
import io
import pathlib
import re

from PIL import Image
from resvg_py import svg_to_bytes

ROOT = pathlib.Path(__file__).resolve().parent.parent

# The light and dark themes of make_logo.py, plus the tile.
THEMES = {
    "light": {"panel": "#ffffff", "edge": "#dcdcd6", "ink": "#1a2233", "mute": "#5b6678", "a": "#1f5fbf", "b": "#e0782a"},
    "dark": {"panel": "#161b26", "edge": "#2a3242", "ink": "#e6edf3", "mute": "#8b96a8", "a": "#6ea0f0", "b": "#f2a25c"},
}
SMALL_SIZES = (16, 24, 32)
LARGE_SIZES = (48, 64, 128, 256)


def glyphs(logo=ROOT / "docs" / "images" / "logo-light.svg"):
    """The outlines of "c" and "can" from the logo's first (blue) path, with their bounding boxes."""
    d = re.findall(r'd="([^"]+)"', logo.read_text())[0]
    can = d
    c = d.split(" M")[0]

    def box(path):
        """Bounding box of the points of an absolute path (M L Q C H V Z, as fontTools writes it)."""
        xs, ys, x, y = [], [], 0.0, 0.0
        for cmd, args in re.findall(r"([MLQCHVZ])([^MLQCHVZ]*)", path):
            nums = [float(n) for n in re.findall(r"-?\d+(?:\.\d+)?", args)]
            if cmd == "H":
                x = nums[-1]
            elif cmd == "V":
                y = nums[-1]
            elif nums:
                xs += nums[0::2]
                ys += nums[1::2]
                x, y = nums[-2], nums[-1]
            xs.append(x)
            ys.append(y)
        return min(xs), min(ys), max(xs), max(ys)

    return (c, box(c)), (can, box(can))


def place(glyph, x, y, height):
    """`glyph` scaled to `height` units with its top-left corner at x, y."""
    d, (x0, y0, x1, y1) = glyph
    k = height / (y1 - y0)
    return k * (x1 - x0), (f'<path class="a" transform="translate({x:g} {y:g}) scale({k:.5f}) '
                           f'translate({-x0:g} {-y0:g})" d="{d}"/>')


def bus(y_h, y_l, left, right, width, nodes=(), node_y=0, node_w=0, node_h=0):
    """The two wires (CAN_H blue, CAN_L amber), the 120 ohm terminators and the nodes below."""
    out = [f'<line class="sa" x1="{left}" y1="{y_h}" x2="{right}" y2="{y_h}" stroke-width="{width}"/>',
           f'<line class="sb" x1="{left}" y1="{y_l}" x2="{right}" y2="{y_l}" stroke-width="{width}"/>']
    if nodes:
        for x in (left - 4, right):
            out.append(f'<rect class="m" x="{x}" y="{y_h - 5}" width="4" height="{y_l - y_h + 10}" rx="1.5"/>')
    for x in nodes:
        out += [f'<line class="sa" x1="{x - 3}" y1="{y_h}" x2="{x - 3}" y2="{node_y}" stroke-width="2.5"/>',
                f'<line class="sb" x1="{x + 3}" y1="{y_l}" x2="{x + 3}" y2="{node_y}" stroke-width="2.5"/>',
                f'<rect class="i" x="{x - node_w / 2:g}" y="{node_y - 2}" width="{node_w}" height="{node_h}" rx="3"/>']
    return "".join(out)


def body(small):
    """The icon on a 64 x 64 grid: the small form ("c" over two wires) or the large ("can" over the bus)."""
    c, can = glyphs()
    tile = '<rect class="p" x="2" y="2" width="60" height="60" rx="12" stroke-width="1"/>'
    if small:
        w, letter = place(c, 0, 0, 31)
        _, letter = place(c, 32 - w / 2, 8, 31)
        return tile + letter + bus(46, 54, 8, 56, 5)
    w, _ = place(can, 0, 0, 14)
    _, word = place(can, 32 - w / 2, 16, 14)
    return tile + word + bus(40, 46, 10, 54, 3, nodes=(22, 42), node_y=54, node_w=12, node_h=6)


def style(theme):
    t = THEMES[theme]
    return (f".p{{fill:{t['panel']};stroke:{t['edge']}}}.a{{fill:{t['a']}}}.m{{fill:{t['mute']}}}"
            f".i{{fill:{t['ink']}}}.sa{{stroke:{t['a']}}}.sb{{stroke:{t['b']}}}")


def svg(small, themed=False):
    """Light colours; with `themed`, the dark colours too under prefers-color-scheme: dark."""
    css = style("light")
    if themed:
        css += "@media (prefers-color-scheme:dark){%s}" % style("dark")
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
            f"<style>{css}</style>{body(small)}</svg>\n")


def png(small, size):
    return Image.open(io.BytesIO(bytes(svg_to_bytes(svg_string=svg(small), width=size, height=size)))).convert("RGBA")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("out", nargs="?", default=ROOT / "tools" / "deploy" / "canworks" / "configurator")
    out = pathlib.Path(ap.parse_args().out)
    icons, static = out / "icons", out / "static"
    icons.mkdir(parents=True, exist_ok=True)
    static.mkdir(parents=True, exist_ok=True)
    big = png(False, 1024)
    big.resize((256, 256), Image.LANCZOS).save(icons / "logo-256.png", optimize=True)
    big.save(icons / "logo.icns")
    frames = [png(True, s) for s in SMALL_SIZES] + [png(False, s) for s in LARGE_SIZES]
    frames[-1].save(icons / "logo.ico", sizes=[f.size for f in frames], append_images=frames[:-1])
    png(False, 180).save(static / "apple-touch-icon.png", optimize=True)
    (static / "favicon.svg").write_text(svg(True, themed=True))
    for p in (icons / "logo.ico", icons / "logo.icns", icons / "logo-256.png",
              static / "favicon.svg", static / "apple-touch-icon.png"):
        print(p)


if __name__ == "__main__":
    main()
