"""README.md must not drift from the repository. Every relative link must
reach a file (and a heading or <a id> in it when it has an anchor), every
`canworks-...` command it names must exist, every `--option` in code
must be one the PC tools or install scripts take, and the bold configurator labels of its
Configurator section must still be on the page (as docs/tour.md's are, see
test_tour_labels.py). No dependencies, so it runs in spec-check with the
tour's check.

Bold text in the Configurator section that is not a page label (the bullets'
own lead-ins) is in NOT_PAGE."""

import re
import unittest
from pathlib import Path

try:
    from .test_tour_labels import on_page, page_text
except ImportError:  # run as a script in spec-check
    from test_tour_labels import on_page, page_text

ROOT = Path(__file__).resolve().parents[3]
README = ROOT / "README.md"
TOOLS = ROOT / "tools" / "deploy" / "canworks"
SCRIPTS = ROOT / "scripts"
PYPROJECT = ROOT / "tools" / "deploy" / "pyproject.toml"
# The Devices page's action names come from the plan the PC tools make.
DEVICE_PLAN = TOOLS / "devices" / "plan.py"

# Commands that are not PC tools' entry points: they run on the bridge's device.
DEVICE_COMMANDS = {"canworks-bridge", "canworks-canopen-sim"}
# Names that look like commands but are not: the Claude skill.
# File names, not commands: the adapter server file canworks-adapter-<version>.pyz.
NOT_COMMANDS = {"canworks-datasheet-notes", "canworks-adapter-"}

NOT_PAGE = {
    # The Configurator bullets' lead-ins
    "Configure", "Commission", "Devices", "Trace", "Project target", "Exports",
    "Device notes", "Save and problems:", "Lists:", "Any window size:",
    "Small things done once:", "Messages:", "Access:", "Commission a CANopen device",
    # Example labels with versions or project names in them
    "Update 0.93.4 → 0.98.0", "This project's bridge",
}

LINK = re.compile(r"\]\(([^)\s]+)\)|(?:src|srcset)=\"([^\"]+)\"")
HEADING = re.compile(r"^#{1,6}\s+(.*?)\s*$", re.M)
ANCHOR_ID = re.compile(r"<a\s+id=\"([^\"]+)\"")
COMMAND = re.compile(r"`(canworks-[a-z0-9-]+)")
CODE = re.compile(r"`([^`\n]+)`")
OPTION = re.compile(r"(?<![\w-])(--[a-z][a-z0-9-]*)")
BOLD = re.compile(r"\*\*([^*\n]+)\*\*")


def slug(heading):
    """GitHub's anchor for a heading."""
    text = re.sub(r"<[^>]+>", "", heading)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = text.replace("`", "").strip().lower()
    text = re.sub(r"[^\w\- ]", "", text)
    return text.replace(" ", "-")


def anchors(path):
    text = path.read_text(encoding="utf-8")
    found = set(ANCHOR_ID.findall(text))
    counts = {}
    for heading in HEADING.findall(text):
        s = slug(heading)
        n = counts.get(s, 0)
        counts[s] = n + 1
        found.add(s if n == 0 else f"{s}-{n}")
    return found


def readme():
    return README.read_text(encoding="utf-8")


def configurator_section(text):
    start = text.index("\n### Configurator\n")
    return text[start:text.index("\n### ", start + 1)]


class Readme(unittest.TestCase):
    def test_links_reach_a_file_and_anchor(self):
        broken = []
        for m in LINK.finditer(readme()):
            target = m.group(1) or m.group(2)
            if re.match(r"[a-z]+:", target):
                continue
            path, _, anchor = target.partition("#")
            file = README if not path else ROOT / path
            if not file.exists():
                broken.append(f"{target}: no such file")
            elif anchor and file.suffix == ".md" and anchor not in anchors(file):
                broken.append(f"{target}: no such heading")
        self.assertEqual(broken, [], "README.md links to files or headings that are gone:\n" + "\n".join(broken))

    def test_commands_exist(self):
        scripts = set(re.findall(r"^(canworks-[a-z0-9-]+) =", PYPROJECT.read_text(encoding="utf-8"), re.M))
        named = set(COMMAND.findall(readme())) - NOT_COMMANDS
        self.assertEqual(sorted(named - scripts - DEVICE_COMMANDS), [],
                         "README.md names commands the PC tools do not install")

    def test_options_exist(self):
        sources = list(TOOLS.rglob("*.py")) + [f for f in SCRIPTS.iterdir() if f.suffix in (".sh", ".ps1")]
        known = set()
        for f in sources:
            known.update(OPTION.findall(f.read_text(encoding="utf-8")))
        # uv's own options, in the development commands
        named = {o for code in CODE.findall(readme()) if not code.startswith("uv ")
                 for o in OPTION.findall(code)}
        self.assertEqual(sorted(named - known), [], "README.md names options no PC tool or install script takes")

    def test_configurator_labels_are_on_the_page(self):
        text = page_text() + DEVICE_PLAN.read_text(encoding="utf-8")
        labels = [m.group(1).strip() for m in BOLD.finditer(configurator_section(readme()))]
        missing = [label for label in labels if label not in NOT_PAGE and not on_page(label, text)]
        self.assertEqual(missing, [], "README.md's Configurator section names labels the page does not have "
                         "(rename them, or add a label that is not the page's to NOT_PAGE):\n" + "\n".join(missing))

    def test_allow_list_is_used(self):
        labels = {m.group(1).strip() for m in BOLD.finditer(configurator_section(readme()))}
        self.assertEqual(sorted(NOT_PAGE - labels), [], "NOT_PAGE lists labels the README no longer has")


if __name__ == "__main__":
    unittest.main()
