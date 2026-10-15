"""Keyboard-only page access for the task tests (visual-refresh).

KeyboardOnly wraps a Playwright page so a task test can only press keys,
type, wait and read. A pointer action (click, hover, tap, mouse, a locator's
click) raises PointerUsed. step() runs the per-step checks: the accessibility
audit, a visible focus ring and nothing clipped, and keeps a screenshot of
every step, written out when a step fails."""

import contextlib
import os
import re

POINTER = {"click", "dblclick", "hover", "tap", "check", "uncheck", "set_checked", "select_option",
           "drag_and_drop", "drag_to", "mouse", "touchscreen", "set_input_files", "fill"}

# The focused control shows a ring of at least 2 px that reaches 3:1 against
# the background it sits on (WCAG 2.4.11 / 1.4.11).
FOCUS_CHECK = """() => {
  const e = document.activeElement;
  if (!e || e === document.body || e === document.documentElement) return "focus is on the page body";
  const rgb = (c) => (c.match(/[\\d.]+/g) || []).map(Number);
  const lum = ([r, g, b]) => { const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; };
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b); };
  const bgOf = (n) => { for (; n; n = n.parentElement) { const c = rgb(getComputedStyle(n).backgroundColor);
    if (c.length >= 3 && (c.length < 4 || c[3] > 0.5)) return c; } return [255, 255, 255]; };
  // The ring may be drawn on the element or on a direct child (a tree item rings its row).
  const ringed = [e, ...e.children].find((n) => { const c = getComputedStyle(n); return c.outlineStyle !== "none" && parseFloat(c.outlineWidth) >= 2; }) || e;
  const s = getComputedStyle(ringed);
  const name = e.tagName.toLowerCase() + (e.id ? "#" + e.id : "") + " " + (e.getAttribute("aria-label") || e.textContent || "").trim().slice(0, 30);
  if (s.outlineStyle === "none" || parseFloat(s.outlineWidth) < 2) {
    if (!s.boxShadow || s.boxShadow === "none") return name + ": no visible focus ring";
    return null;
  }
  const a = lum(rgb(s.outlineColor)), b = lum(bgOf(ringed === e ? e.parentElement : ringed));
  const ratio = (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
  return ratio < 3 ? name + ": focus ring contrast " + ratio.toFixed(2) + ":1" : null;
}"""


class PointerUsed(AssertionError):
    pass


class _Guard:
    """Passes everything through except pointer actions; locators and
    frames it hands out are guarded too."""

    def __init__(self, target, what):
        object.__setattr__(self, "_t", target)
        object.__setattr__(self, "_what", what)

    def __getattr__(self, name):
        if name in POINTER:
            raise PointerUsed(f"the step used the pointer ({self._what}.{name}); task tests use the keyboard only")
        v = getattr(self._t, name)
        if callable(v) and name in ("locator", "get_by_role", "get_by_text", "get_by_label", "first", "last", "nth", "filter", "frame_locator"):
            return lambda *a, **k: _Guard(v(*a, **k), "locator")
        if name in ("first", "last"):
            return _Guard(v, "locator")
        return v


class KeyboardOnly(_Guard):
    def __init__(self, page, name, audit, fit_check, out_dir=None):
        super().__init__(page, "page")
        object.__setattr__(self, "page_", page)
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "audit", audit)
        object.__setattr__(self, "fit_check", fit_check)
        object.__setattr__(self, "out_dir", out_dir or os.environ.get("CANWORKS_TASK_SHOTS") or os.path.join(os.getcwd(), "task-shots"))
        object.__setattr__(self, "shots", [])

    # -- keys -----------------------------------------------------------------
    def press(self, *keys):
        for k in keys:
            self.page_.keyboard.press(k)

    def type(self, text):
        self.page_.keyboard.type(text)

    def tab_to(self, selector, limit=120, back=False):
        """Tab (or Shift+Tab) until the element matching selector has focus."""
        for _ in range(limit):
            if self.page_.evaluate("(s) => { const e = document.querySelector(s); return !!e && e === document.activeElement; }", selector):
                return
            self.page_.keyboard.press("Shift+Tab" if back else "Tab")
        raise AssertionError(f"{self.name}: {selector} not reached with {'Shift+Tab' if back else 'Tab'} in {limit} presses")

    def focused(self):
        return self.page_.evaluate("() => { const e = document.activeElement; return e ? (e.id || e.getAttribute('aria-label') || e.textContent.trim().slice(0, 40)) : null; }")

    def expect_focus(self, selector):
        ok = self.page_.evaluate("(s) => { const e = document.querySelector(s); return !!e && e === document.activeElement; }", selector)
        if not ok:
            raise AssertionError(f"{self.name}: expected focus on {selector}, it is on {self.focused()!r}")

    # -- steps ----------------------------------------------------------------
    @contextlib.contextmanager
    def step(self, title, focus=True):
        """One step of a task: its actions run inside the block; after it the
        audit, focus and fit checks run and a screenshot is kept."""
        where = f"{self.name}: {title}"
        try:
            yield self
            self.page_.wait_for_timeout(150)
            self.shots.append((title, self.page_.screenshot(full_page=False)))
            self.audit(self.page_, where)
            if focus:
                bad = self.page_.evaluate(FOCUS_CHECK)
                if bad:
                    raise AssertionError(f"{where}: {bad}")
            clipped = self.page_.evaluate(self.fit_check)
            if clipped:
                raise AssertionError(f"{where}: clipped {clipped}")
        except BaseException:
            if not self.shots or self.shots[-1][0] != title:
                with contextlib.suppress(Exception):
                    self.shots.append((title, self.page_.screenshot(full_page=False)))
            self.save_shots()
            raise

    def save_shots(self):
        folder = os.path.join(self.out_dir, re.sub(r"[^\w.-]+", "-", self.name))
        os.makedirs(folder, exist_ok=True)
        for k, (title, png) in enumerate(self.shots, 1):
            with open(os.path.join(folder, "%02d-%s.png" % (k, re.sub(r"[^\w.-]+", "-", title))), "wb") as f:
                f.write(png)
