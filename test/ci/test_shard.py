"""The CI test sharding (.github/scripts/test_shard.py)."""

import contextlib
import importlib.util
import io
import os
import tempfile
import textwrap
import unittest

_path = os.path.join(os.path.dirname(__file__), "..", "..", ".github", "scripts", "test_shard.py")
_spec = importlib.util.spec_from_file_location("test_shard", _path)
shard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(shard)


class Split(unittest.TestCase):
    def test_every_class_in_exactly_one_shard(self):
        sizes = {f"m.C{i}": i % 7 + 1 for i in range(30)}
        for n in (1, 2, 3, 5):
            shards = shard.split(sizes, n)
            flat = [k for s in shards for k in s]
            self.assertEqual(sorted(flat), sorted(sizes), n)

    def test_balanced_by_test_count(self):
        shards = shard.split({"a": 6, "b": 5, "c": 4, "d": 3, "e": 2}, 2)
        loads = sorted(sum({"a": 6, "b": 5, "c": 4, "d": 3, "e": 2}[k] for k in s) for s in shards)
        self.assertEqual(sum(loads), 20)
        self.assertLessEqual(loads[1] - loads[0], 2)

    def test_same_split_every_time(self):
        sizes = {"x.A": 3, "x.B": 3, "y.A": 3}
        self.assertEqual(shard.split(sizes, 2), shard.split(dict(reversed(list(sizes.items()))), 2))


class Run(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        # a new package name per test: discovery imports it, and sys.modules keeps it
        self.pkg = "shardpkg_" + os.path.basename(self.dir).replace("-", "_")
        os.makedirs(os.path.join(self.dir, self.pkg))
        open(os.path.join(self.dir, self.pkg, "__init__.py"), "w").close()
        for name, body in (
            ("test_one", "class A(unittest.TestCase):\n    def test_a(self): pass\n    def test_b(self): pass\n"),
            ("test_two", "class B(unittest.TestCase):\n    def test_c(self): pass\n"),
            ("test_page", "class P(unittest.TestCase):\n    def test_p(self): pass\n"),
            ("test_bad", "class Bad(unittest.TestCase):\n    def test_x(self): self.fail('boom')\n"),
        ):
            with open(os.path.join(self.dir, self.pkg, name + ".py"), "w") as f:
                f.write("import unittest\n" + textwrap.dedent(body))

    def run_shard(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = shard.main(["--start", os.path.join(self.dir, self.pkg), "--top", self.dir, *args])
        return rc, out.getvalue() + err.getvalue()

    def test_shards_cover_the_suite_once(self):
        ran = []
        for k in (1, 2):
            _, log = self.run_shard("--shard", f"{k}/2", "--exclude", "test_bad$")
            ran += [line.split(" ")[0] for line in log.splitlines() if line.startswith("test_")]
        self.assertEqual(sorted(ran), ["test_a", "test_b", "test_c", "test_p"])

    def test_pattern_and_exclude(self):
        rc, log = self.run_shard("--shard", "1/1", "--pattern", "test_one.py", "--pattern", "test_page.py")
        self.assertEqual(rc, 0)
        self.assertIn("3 of 3 tests", log)
        rc, log = self.run_shard("--shard", "1/1", "--exclude", "test_(page|bad)$")
        self.assertIn("3 of 3 tests", log)

    def test_failure_fails_the_shard(self):
        rc, _ = self.run_shard("--shard", "1/1", "--pattern", "test_bad.py")
        self.assertEqual(rc, 1)

    def test_empty_shard_fails(self):
        rc, log = self.run_shard("--shard", "2/2", "--pattern", "test_two.py")
        self.assertEqual(rc, 1)
        self.assertIn("empty shard", log)


if __name__ == "__main__":
    unittest.main()
