"""The PC tools release notes: template coverage, "What's new" entries and the
banned-word check (scripts/release_notes.py)."""

import importlib.util
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..", "..")
SCRIPT = os.path.join(ROOT, "scripts", "release_notes.py")
WORKFLOW = os.path.join(ROOT, ".github", "workflows", "release-deploy.yml")
PYPROJECT = os.path.join(ROOT, "tools", "deploy", "pyproject.toml")
spec = importlib.util.spec_from_file_location("release_notes", SCRIPT)
release_notes = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release_notes)


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


class TemplateCoverageTest(unittest.TestCase):
    """The template names everything a release ships, so a change to what
    ships cannot merge without updating the description."""

    def setUp(self):
        self.template = read(release_notes.TEMPLATE)
        self.workflow = read(WORKFLOW)

    def test_release_assets(self):
        create = re.search(r"gh release create .*?(?<!\\)\n", self.workflow, re.S).group(0)
        assets = re.findall(r"dist/(\S+)", create)
        self.assertTrue(assets)
        for asset in assets:
            name = "canworks-{version}-py3-none-any.whl" if asset == "*.whl" else asset
            self.assertIn(name, self.template, "the release attaches %s; name it in %s"
                          % (asset, os.path.relpath(release_notes.TEMPLATE, ROOT)))

    def test_container_images(self):
        images = set(re.findall(r'repo="ghcr\.io/.*/([a-z0-9-]+)"\s*$', self.workflow, re.M))
        self.assertGreaterEqual(images, {"canworks-sim-runtime", "canworks-bridge"})
        for image in images:
            self.assertIn("ghcr.io/{owner}/%s:{version}" % image, self.template,
                          "the release publishes the image %s; name it in the release notes template" % image)

    def test_commands(self):
        scripts = re.search(r"^\[project\.scripts\]\n(.*?)(?:\n\[|\Z)", read(PYPROJECT), re.S | re.M).group(1)
        commands = re.findall(r"^([a-z0-9-]+)\s*=", scripts, re.M)
        self.assertIn("canworks-config", commands)
        for command in commands:
            self.assertIn("`%s`" % command, self.template,
                          "the wheel installs %s; name it in the release notes template" % command)

    def test_placeholders_filled(self):
        text = release_notes.render_template(self.template, "1.2.3", "Owner/canworks")
        self.assertNotIn("{", text)
        self.assertIn("uv tool install --python 3.12 canworks-1.2.3-py3-none-any.whl", text)
        self.assertIn("ghcr.io/owner/canworks-sim-runtime:1.2.3", text)
        self.assertIn("https://github.com/Owner/canworks/blob/deploy-v1.2.3/docs/install-pc.md", text)


class AfterParagraphTest(unittest.TestCase):
    def test_paragraph(self):
        body = "marker\n\nBefore: old.\n\nAfter: new things\non two lines.\n\nHow: code."
        self.assertEqual(release_notes.after_paragraph(body), "New things on two lines.")

    def test_crlf_and_last_paragraph(self):
        self.assertEqual(release_notes.after_paragraph("Before: a\r\n\r\nAfter: b\r\nc"), "B c")

    def test_bold_label(self):
        self.assertEqual(release_notes.after_paragraph("**After:** shiny"), "Shiny")

    def test_missing(self):
        self.assertIsNone(release_notes.after_paragraph("Just a description."))
        self.assertIsNone(release_notes.after_paragraph(None))
        self.assertIsNone(release_notes.after_paragraph("Afterwards: no"))


PULLS = {
    101: {"title": "Trace: decode PDOs", "html_url": "https://github.com/o/r/pull/101",
          "body": "Before: raw.\n\nAfter: decoded values.\n\nHow: code."},
    102: {"title": "Configurator: import DBC", "html_url": "https://github.com/o/r/pull/102", "body": "No paragraphs."},
}


def fake_fetch(repo, number):
    return PULLS[number]


class EntriesTest(unittest.TestCase):
    def test_entries(self):
        items = release_notes.entries([("abc1234", "Trace: decode PDOs (#101)"),
                                       ("def5678", "Configurator: import DBC (#102)"),
                                       ("0a0b0c0", "Fix a typo on main")], "o/r", fetch=fake_fetch)
        self.assertEqual(items, [
            ("PR #101", "- **[Trace: decode PDOs](https://github.com/o/r/pull/101)**: Decoded values."),
            ("PR #102", "- **[Configurator: import DBC](https://github.com/o/r/pull/102)**"),
            ("commit 0a0b0c0", "- Fix a typo on main"),
        ])

    def test_compose(self):
        items = [("PR #1", "- one")]
        text = release_notes.compose("Header\n", items, "o/r", "deploy-v0.1.0", "0.2.0")
        self.assertEqual(text, "Header\n\n## What's new\n\n- one\n\n"
                               "**Full changelog**: https://github.com/o/r/compare/deploy-v0.1.0...deploy-v0.2.0\n")
        self.assertEqual(release_notes.compose("Header\n", [], "o/r", None, "0.2.0"), "Header\n")
        self.assertIn("No pull requests since deploy-v0.1.0.",
                      release_notes.compose("Header\n", [], "o/r", "deploy-v0.1.0", "0.2.0"))


class BannedWordsTest(unittest.TestCase):
    def setUp(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        self.words = os.path.join(d, "words.txt")
        with open(self.words, "w") as f:
            f.write("# test list\nforbiddenthing\n")
        old = os.environ.get("BANNED_WORDS_FILE")
        os.environ["BANNED_WORDS_FILE"] = self.words
        self.addCleanup(lambda: os.environ.pop("BANNED_WORDS_FILE") if old is None
                        else os.environ.__setitem__("BANNED_WORDS_FILE", old))

    def test_finding_names_the_pr_not_the_word(self):
        items = [("PR #7", "- **[Fine](u)**: ok"), ("PR #8", "- **[Uses ForbiddenThing](u)**")]
        findings = release_notes.banned_findings("Header", items)
        self.assertEqual(findings, ["PR #8"])
        self.assertNotIn("forbidden", " ".join(findings).lower())

    def test_clean(self):
        self.assertEqual(release_notes.banned_findings("Header", [("PR #7", "- ok")]), [])

    def test_template_is_clean_with_the_ci_list(self):
        # CI passes its own list in BANNED_WORDS; here the test list must not match the template.
        self.assertEqual(release_notes.banned_findings(read(release_notes.TEMPLATE), []), [])


class CommandLineTest(unittest.TestCase):
    def test_first_release_without_previous(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        out = os.path.join(d, "notes.md")
        env = dict(os.environ, BANNED_WORDS_FILE="", BANNED_WORDS="", HOME=d)
        r = subprocess.run([sys.executable, SCRIPT, "--version", "9.9.9", "--repo", "o/r", "--sha", "HEAD",
                            "--out", out], capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        text = read(out)
        self.assertIn("canworks-9.9.9-py3-none-any.whl", text)
        self.assertNotIn("What's new", text)


if __name__ == "__main__":
    unittest.main()
