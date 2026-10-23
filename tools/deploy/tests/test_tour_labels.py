"""The guided tour (docs/tour.md, canopen-virtual-example "Guide") names the
configurator's controls in bold. Each bold label must still be on the page:
found in the page's files (static/*.js, index.html), so a renamed or removed
control fails here with the label and its chapter. A label counts as found
when it is a whole string or element text of the page (it may be followed by
a bracketed addition, as "Emergency history (newest first)"), not a word
inside a longer text. No browser needed.

Labels that are not the configurator's (the editor's, GitHub's, the tour's
own lead-ins, the hardware list) are in NOT_PAGE."""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TOUR = ROOT / "docs" / "tour.md"
STATIC = ROOT / "tools" / "deploy" / "canworks" / "configurator" / "static"

NOT_PAGE = {
    # OpenPLC Editor and GitHub
    "Build and Upload", "Code → Download ZIP",
    # The tour's own lead-ins and the "What needs hardware" list
    "A deliberate mistake:", "The bit rate check", "slcan adapters", "Bus error states",
    "Commissioning straight from the PC", "J1939 networks", "Real-time timing",
    "The install on a Linux device",
}

BOLD = re.compile(r"\*\*([^*\n]+)\*\*")


def labels():
    """(chapter, label) for each bold label of the tour, in order."""
    chapter = "intro"
    for line in TOUR.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            chapter = line[3:].strip()
        for m in BOLD.finditer(line):
            yield chapter, m.group(1).strip()


def on_page(label, text):
    return re.search(r"[\"'`>]\s*" + re.escape(label) + r"\s*[\"'`<(]", text) is not None


def page_text():
    files = sorted(STATIC.glob("*.js")) + [STATIC / "index.html"]
    return "\n".join(f.read_text(encoding="utf-8") for f in files)


class TourLabels(unittest.TestCase):
    def test_every_bold_label_is_on_the_page(self):
        text = page_text()
        missing = [f"{chapter}: **{label}**" for chapter, label in labels()
                   if label not in NOT_PAGE and not on_page(label, text)]
        self.assertEqual(missing, [], "docs/tour.md names labels the configurator page does not have "
                         "(rename them in the tour, or add a label that is not the page's to NOT_PAGE):\n"
                         + "\n".join(missing))

    def test_allow_list_is_used(self):
        used = {label for _, label in labels()}
        self.assertEqual(sorted(NOT_PAGE - used), [], "NOT_PAGE lists labels the tour no longer has")


if __name__ == "__main__":
    unittest.main()
