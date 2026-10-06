"""scripts/check-banned-words.py on a scratch git repository."""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest

SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "scripts", "check-banned-words.py")
WORDS = "# test list\nfoo-?bar\n\\bsecretname\\b\n"


class BannedWords(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir)
        self.list = os.path.join(self.dir, "words.txt")
        with open(self.list, "w") as f:
            f.write(WORDS)
        self.repo = os.path.join(self.dir, "repo")
        os.mkdir(self.repo)
        self.git("init", "-q", "-b", "main")
        self.write("ok.txt", "nothing to see\n")
        self.commit("first")

    def git(self, *args):
        return subprocess.run(["git", "-c", "user.name=T", "-c", "user.email=t@example.com"] + list(args),
                              cwd=self.repo, check=True, stdout=subprocess.PIPE).stdout.decode()

    def write(self, name, text, mode="w"):
        path = os.path.join(self.repo, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, mode) as f:
            f.write(text)

    def commit(self, message):
        self.git("add", "-A")
        self.git("commit", "-q", "-m", message)

    def run_check(self, *args, env=None):
        e = dict(os.environ, BANNED_WORDS_FILE=self.list, HOME=self.dir)
        e.pop("BANNED_WORDS", None)
        e.update(env or {})
        r = subprocess.run([sys.executable, SCRIPT] + list(args), cwd=self.repo, env=e,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)
        return r.returncode, r.stdout

    def test_clean(self):
        self.assertEqual(self.run_check("--files")[0], 0)

    def test_content_name_and_binary(self):
        self.write("docs/a.md", "line one\nsee FOO-BAR here\n")
        self.write("FooBar.png", b"\x89PNG\x00foobar\x00", "wb")
        self.write("archive/old.md", "foobar\n")
        self.commit("add")
        code, out = self.run_check("--files", "--exclude", "archive")
        self.assertEqual(code, 1)
        self.assertIn("docs/a.md:2: banned word (list line 2)", out)
        self.assertIn("FooBar.png: banned word in the file name", out)
        self.assertIn("FooBar.png:1:", out)
        self.assertNotIn("archive/", out)
        # The matched text is never printed.
        self.assertNotIn("FOO-BAR", out)

    def test_word_boundary(self):
        self.write("a.txt", "secretnames are fine\n")
        self.commit("add")
        self.assertEqual(self.run_check("--files")[0], 0)

    def test_range_messages_and_authors(self):
        base = self.git("rev-parse", "HEAD").strip()
        self.write("b.txt", "x\n")
        self.commit("fix for SecretName")
        code, out = self.run_check("--range", base + "..HEAD")
        self.assertEqual(code, 1)
        self.assertIn("message", out)
        subprocess.run(["git", "-c", "user.name=T", "-c", "user.email=foobar@example.com", "commit", "-q",
                        "--allow-empty", "-m", "clean"], cwd=self.repo, check=True)
        code, out = self.run_check("--range", "HEAD~1..HEAD")
        self.assertEqual(code, 1)
        self.assertIn("author/committer", out)

    def test_range_without_base(self):
        for r in ("..HEAD", "0000000000000000000000000000000000000000..HEAD"):
            code, out = self.run_check("--range", r)
            self.assertEqual(code, 0, out)
            self.assertIn("commits not checked", out)

    def test_staged_and_env_text(self):
        self.write("c.txt", "foo bar is fine, foobar is not\n")
        self.git("add", "c.txt")
        self.assertEqual(self.run_check("--staged")[0], 1)
        self.assertEqual(self.run_check("--env-text", "PR_BODY", env={"PR_BODY": "about foobar"})[0], 1)
        self.assertEqual(self.run_check("--env-text", "PR_BODY", env={"PR_BODY": "clean"})[0], 0)

    def test_list_from_env_and_none(self):
        env = {"BANNED_WORDS_FILE": "", "BANNED_WORDS": "nothinghere\n"}
        self.assertEqual(self.run_check("--files", env=env)[0], 0)
        code, out = self.run_check("--files", env={"BANNED_WORDS_FILE": ""})
        self.assertEqual(code, 0)
        self.assertIn("skipped", out)


if __name__ == "__main__":
    unittest.main()
