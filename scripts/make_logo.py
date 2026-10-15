#!/usr/bin/env python3
"""Generate the README logo (docs/images/logo-light.svg and logo-dark.svg).

Text is converted to outlines with fontTools so the SVGs render the same
everywhere (GitHub serves README images through <img>, which can't load
web fonts). Fonts: Inter Display Bold (SIL OFL); only outlines
end up in the SVGs.

Needs fontTools (development only): python3 -m pip install fonttools
Usage: python3 scripts/make_logo.py [OUT_DIR] [--inter DIR]
"""
import argparse
import pathlib

from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont

THEMES = {
    "light": {"ink": "#1a2233", "mute": "#5b6678", "a": "#1f5fbf", "b": "#e0782a"},
    "dark": {"ink": "#e6edf3", "mute": "#8b96a8", "a": "#6ea0f0", "b": "#f2a25c"},
}


class Font:
    def __init__(self, path):
        self.f = TTFont(path)
        self.gs = self.f.getGlyphSet()
        self.cmap = self.f.getBestCmap()
        self.upm = self.f["head"].unitsPerEm

    def text(self, s, x, y, size, tracking=0.0):
        """Return (svg path d, advance width) for s with baseline at y."""
        k = size / self.upm
        d, cx = [], x
        for ch in s:
            g = self.cmap[ord(ch)]
            pen = SVGPathPen(self.gs)
            self.gs[g].draw(TransformPen(pen, (k, 0, 0, -k, cx, y)))
            d.append(pen.getCommands())
            cx += self.gs[g].width * k + tracking * size
        return " ".join(d), cx - x - tracking * size

    def width(self, s, size, tracking=0.0):
        return self.text(s, 0, 0, size, tracking)[1]


def svg(w, h, body, title):
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w:g} {h:g}" width="{w:g}" height="{h:g}" '
        f'role="img" aria-label="{title}"><title>{title}</title>\n{body}\n</svg>\n'
    )


# Wordmark sitting on a two-wire bus (CAN_H / CAN_L) with termination at both
# ends and three nodes tapping the line.
def bus(t, F):
    size, x0, base = 96, 40, 104
    d_can, wc = F.bold.text("can", x0, base, size, -0.02)
    d_works, ww = F.bold.text("works", x0 + wc - 0.02 * size + 2, base, size, -0.02)
    right = x0 + wc + ww + 2
    W, H = right + 40, 190
    yH, yL = 138, 154
    parts = [
        f'<path fill="{t["a"]}" d="{d_can}"/>',
        f'<path fill="{t["ink"]}" d="{d_works}"/>',
        f'<line x1="{x0 - 12}" y1="{yH}" x2="{right + 12}" y2="{yH}" stroke="{t["a"]}" stroke-width="6" stroke-linecap="round"/>',
        f'<line x1="{x0 - 12}" y1="{yL}" x2="{right + 12}" y2="{yL}" stroke="{t["b"]}" stroke-width="6" stroke-linecap="round"/>',
    ]
    for xe in (x0 - 22, right + 14):  # 120 ohm terminators
        parts.append(f'<rect x="{xe}" y="{yH - 8}" width="8" height="{yL - yH + 16}" rx="3" fill="{t["mute"]}"/>')
    for xn in (x0 + wc * 0.5, x0 + wc + ww * 0.42, right - 34):  # nodes below the bus
        parts.append(f'<line x1="{xn - 5}" y1="{yH}" x2="{xn - 5}" y2="170" stroke="{t["a"]}" stroke-width="4"/>')
        parts.append(f'<line x1="{xn + 5}" y1="{yL}" x2="{xn + 5}" y2="170" stroke="{t["b"]}" stroke-width="4"/>')
        parts.append(f'<rect x="{xn - 18}" y="168" width="36" height="18" rx="5" fill="{t["ink"]}"/>')
    return svg(W, H, "\n".join(parts), "canworks")


def main():
    root = pathlib.Path(__file__).resolve().parent.parent
    ap = argparse.ArgumentParser()
    ap.add_argument("out", nargs="?", default=str(root / "docs" / "images"))
    ap.add_argument("--inter", default="/usr/share/fonts/opentype/inter")
    a = ap.parse_args()

    class F:
        bold = Font(f"{a.inter}/InterDisplay-Bold.otf")

    out = pathlib.Path(a.out)
    for theme, t in THEMES.items():
        (out / f"logo-{theme}.svg").write_text(bus(t, F))


if __name__ == "__main__":
    main()
