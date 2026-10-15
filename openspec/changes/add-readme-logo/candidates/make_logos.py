#!/usr/bin/env python3
"""Generate the README logo candidates (light and dark SVG per option).

Text is converted to outlines with fontTools so the SVGs render the same
everywhere (GitHub serves README images through <img>, which can't load
web fonts). Fonts: Inter Display (SIL OFL) and DejaVu Sans Mono
(Bitstream Vera licence); only outlines end up in the SVGs.

Usage: python3 make_logos.py [OUT_DIR] [--inter DIR] [--mono FILE]
"""
import argparse
import pathlib

from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont

THEMES = {
    "light": {"ink": "#1a2233", "mute": "#5b6678", "a": "#1f5fbf", "b": "#e0782a", "bg": "#ffffff", "soft": "#e8eef8"},
    "dark": {"ink": "#e6edf3", "mute": "#8b96a8", "a": "#6ea0f0", "b": "#f2a25c", "bg": "#0d1117", "soft": "#1b2638"},
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


# --- Option A: "Bus" -------------------------------------------------------
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


# --- Option B: "Signal" ----------------------------------------------------
# Icon: the differential CAN signal. CAN_H rises and CAN_L falls on dominant
# bits and both rest in the middle when recessive, which draws an eye shape.
def wave(bits, x, w, mid, amp, up, slope):
    step = w / len(bits)
    pts, cx = [(x, mid)], x
    level = mid
    for b in bits:
        target = (mid - amp if up else mid + amp) if b == 0 else mid
        if target != level:
            pts.append((cx - slope / 2, level))
            pts.append((cx + slope / 2, target))
            level = target
        cx += step
    pts.append((cx, level))
    return "M" + " L".join(f"{px:.1f},{py:.1f}" for px, py in pts)


def signal_icon(t, x, y, s):
    bits = [1, 0, 1, 0, 0, 1]  # 0 = dominant
    pad, gap = s * 0.15, s * 0.035
    mid, amp = y + s / 2, s * 0.2
    hp = wave(bits, x + pad, s - 2 * pad, mid - gap, amp - gap, True, s * 0.07)
    lp = wave(bits, x + pad, s - 2 * pad, mid + gap, amp - gap, False, s * 0.07)
    sw = s * 0.06
    return "\n".join([
        f'<rect x="{x}" y="{y}" width="{s}" height="{s}" rx="{s * 0.22:.1f}" fill="{t["soft"]}"/>',
        f'<path d="{lp}" fill="none" stroke="{t["b"]}" stroke-width="{sw:.1f}" stroke-linejoin="round" stroke-linecap="round"/>',
        f'<path d="{hp}" fill="none" stroke="{t["a"]}" stroke-width="{sw:.1f}" stroke-linejoin="round" stroke-linecap="round"/>',
    ])


def signal(t, F):
    s = 140
    size, x0, base = 92, 20 + s + 34, 20 + s / 2 + 33
    d, w = F.bold.text("canworks", x0, base, size, -0.02)
    W, H = x0 + w + 30, s + 40
    body = signal_icon(t, 20, 20, s) + f'\n<path fill="{t["ink"]}" d="{d}"/>'
    return svg(W, H, body, "canworks")


# --- Option C: "Nut" -------------------------------------------------------
# Icon: a hex nut (the "works") threaded onto the two-wire bus (the "CAN").
def nut_icon(t, x, y, s):
    cx, cy, r = x + s / 2, y + s / 2, s * 0.42
    import math
    hexp = " ".join(
        f"{cx + r * math.cos(math.radians(30 + 60 * i)):.1f},{cy + r * math.sin(math.radians(30 + 60 * i)):.1f}" for i in range(6)
    )
    hole = r * 0.46
    g = s * 0.075
    return "\n".join([
        f'<polygon points="{hexp}" fill="{t["ink"]}" stroke="{t["ink"]}" stroke-width="{s * 0.06:.1f}" stroke-linejoin="round"/>',
        f'<circle cx="{cx}" cy="{cy}" r="{hole:.1f}" fill="{t["bg"]}"/>',
        f'<line x1="{x}" y1="{cy - g:.1f}" x2="{x + s}" y2="{cy - g:.1f}" stroke="{t["a"]}" stroke-width="{s * 0.06:.1f}" stroke-linecap="round"/>',
        f'<line x1="{x}" y1="{cy + g:.1f}" x2="{x + s}" y2="{cy + g:.1f}" stroke="{t["b"]}" stroke-width="{s * 0.06:.1f}" stroke-linecap="round"/>',
    ])


def nut(t, F):
    s = 140
    size, x0, base = 92, 20 + s + 30, 20 + s / 2 + 33
    d1, w1 = F.bold.text("can", x0, base, size, -0.02)
    d2, w2 = F.light.text("works", x0 + w1 + 2, base, size, -0.02)
    W, H = x0 + w1 + w2 + 30, s + 40
    body = nut_icon(t, 20, 20, s) + f'\n<path fill="{t["ink"]}" d="{d1}"/>\n<path fill="{t["mute"]}" d="{d2}"/>'
    return svg(W, H, body, "canworks")


# --- Option D: "Frame" -----------------------------------------------------
# Wordmark laid out as a CAN frame in a trace view: SOF bit, "can" in the
# identifier field, "works" in the data field, CRC and ACK ticks, bit clock
# above.
def frame(t, F):
    size, base = 72, 112
    pad = 18
    x = 30
    parts = []
    # SOF
    parts.append(f'<rect x="{x}" y="58" width="10" height="72" rx="3" fill="{t["b"]}"/>')
    x += 22
    d_id, wid = F.mono.text("can", x + pad, base, size)
    parts.append(f'<rect x="{x}" y="58" width="{wid + 2 * pad:.1f}" height="72" rx="10" fill="{t["a"]}"/>')
    parts.append(f'<path fill="{t["bg"]}" d="{d_id}"/>')
    lab_id = x
    x += wid + 2 * pad + 10
    d_dt, wdt = F.mono.text("works", x + pad, base, size)
    parts.append(f'<rect x="{x}" y="58" width="{wdt + 2 * pad:.1f}" height="72" rx="10" fill="none" stroke="{t["ink"]}" stroke-width="4"/>')
    parts.append(f'<path fill="{t["ink"]}" d="{d_dt}"/>')
    lab_dt = x
    x += wdt + 2 * pad + 10
    for i in range(3):  # CRC / ACK / EOF ticks
        parts.append(f'<rect x="{x + i * 16}" y="{58 + (0 if i < 2 else 36)}" width="10" height="{72 if i < 2 else 36}" rx="3" fill="{t["mute"]}"/>')
    right = x + 42
    # bit clock
    n = int((right - 30) // 12)
    ticks = " ".join(f"M{30 + i * 12 + 3},36 v{8 if i % 8 else 14}" for i in range(n + 1))
    parts.append(f'<path d="{ticks}" stroke="{t["mute"]}" stroke-width="2" stroke-linecap="round"/>')
    d1, _ = F.mono.text("ID", lab_id + 4, 162, 18)
    d2, _ = F.mono.text("DATA", lab_dt + 4, 162, 18)
    parts.append(f'<path fill="{t["mute"]}" d="{d1} {d2}"/>')
    return svg(right + 30, 180, "\n".join(parts), "canworks")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out", nargs="?", default=str(pathlib.Path(__file__).parent))
    ap.add_argument("--inter", default="/usr/share/fonts/opentype/inter")
    ap.add_argument("--mono", default="/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf")
    a = ap.parse_args()

    class F:
        bold = Font(f"{a.inter}/InterDisplay-Bold.otf")
        light = Font(f"{a.inter}/InterDisplay-Light.otf")
        mono = Font(a.mono)

    out = pathlib.Path(a.out)
    for name, fn in {"a-bus": bus, "b-signal": signal, "c-nut": nut, "d-frame": frame}.items():
        for theme, t in THEMES.items():
            (out / f"logo-{name}-{theme}.svg").write_text(fn(t, F))
    # square icons for the options that have one (favicon, social preview)
    for name, fn in {"b-signal": signal_icon, "c-nut": nut_icon}.items():
        for theme, t in THEMES.items():
            (out / f"icon-{name}-{theme}.svg").write_text(svg(160, 160, fn(t, 10, 10, 140), "canworks"))


if __name__ == "__main__":
    main()
