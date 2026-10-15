"""State colours in the configurator's style sheet (visual-refresh): every
state colour reaches 4.5:1 as text against the page, panel and hover
backgrounds and against the warning and error tints, in both themes, and
the Auto theme's dark block matches Dark. No browser needed."""

import re
import unittest
from pathlib import Path

CSS = Path(__file__).resolve().parents[1] / "canworks" / "configurator" / "static" / "style.css"
STATES = ("--st-ok", "--st-busy", "--st-warn", "--st-error", "--st-off")
BACKGROUNDS = ("--bg", "--panel", "--hover", "--st-warn-bg", "--st-error-bg")


def luminance(hex_colour):
    h = hex_colour.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    rgb = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def ratio(a, b):
    la, lb = luminance(a), luminance(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def block(css, selector_regex):
    m = re.search(selector_regex + r"\s*\{([^}]*)\}", css)
    assert m, selector_regex
    return dict(re.findall(r"(--[\w-]+)\s*:\s*(#[0-9a-fA-F]{3,6})\b", m.group(1)))


def themes():
    css = CSS.read_text()
    light = block(css, r"(?m)^:root")
    dark = {**light, **block(css, r':root\[data-theme="dark"\]')}
    auto = {**light, **block(css, r':root:not\(\[data-theme="light"\]\):not\(\[data-theme="dark"\]\)')}
    return {"Light": light, "Dark": dark, "Auto dark": auto}


class StateColours(unittest.TestCase):
    def test_every_theme_defines_the_state_tokens(self):
        for name, t in themes().items():
            for token in STATES + BACKGROUNDS:
                self.assertIn(token, t, f"{name} theme has no {token}")

    def test_text_contrast(self):
        for name, t in themes().items():
            for state in STATES:
                for bg in BACKGROUNDS:
                    r = ratio(t[state], t[bg])
                    self.assertGreaterEqual(r, 4.5, f"{name} theme: {state} {t[state]} on {bg} {t[bg]} is {r:.2f}:1, needs 4.5:1")

    def test_auto_dark_matches_dark(self):
        t = themes()
        for token in STATES + BACKGROUNDS:
            self.assertEqual(t["Auto dark"][token].lower(), t["Dark"][token].lower(), f"Auto dark and Dark differ in {token}")

    def test_contrast_helper(self):
        self.assertAlmostEqual(ratio("#000000", "#ffffff"), 21.0, places=1)
        self.assertAlmostEqual(ratio("#777777", "#ffffff"), 4.48, places=2)


if __name__ == "__main__":
    unittest.main()
