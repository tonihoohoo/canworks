"""The CI test sharding (.github/scripts/test_shard.py)."""

import contextlib
import importlib.util
import io
import json
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


    def test_together_on_one_shard(self):
        sizes = {f"m.C{i}": 10 for i in range(9)}
        sizes.update({"p.Parity": 10, "q.Parity": 10, "r.Into": 10})
        for n in (2, 3):
            shards = shard.split(sizes, n, r"^(p|q)\.Parity$|^r\.Into$")
            holding = [s for s in shards if "p.Parity" in s]
            self.assertEqual(len(holding), 1)
            self.assertTrue({"q.Parity", "r.Into"} <= set(holding[0]), shards)
            self.assertEqual(sorted(k for s in shards for k in s), sorted(sizes))


class Timings(unittest.TestCase):
    def test_split_by_recorded_seconds(self):
        found = {"m.Slow": [1], "m.A": [1, 2, 3, 4], "m.B": [1, 2, 3, 4], "m.C": [1, 2, 3, 4]}
        sizes = shard.sizes_from(found, {"m.Slow": 90, "m.A": 30, "m.B": 30, "m.C": 30})
        shards = shard.split(sizes, 2)
        self.assertIn(["m.Slow"], shards)  # by count it would share a shard; by time it fills one

    def test_unknown_class_counts_as_median(self):
        sizes = shard.sizes_from({"m.A": [1], "m.B": [1], "m.C": [1], "m.New": [1]},
                                 {"m.A": 10, "m.B": 20, "m.C": 60})
        self.assertEqual(sizes["m.New"], 20)

    def test_balance_within_a_third(self):
        rec = {f"m.C{i}": s for i, s in enumerate([51, 44, 38, 30, 27, 22, 20, 18, 15, 12, 9, 8, 6, 5, 3])}
        shards = shard.split(shard.sizes_from({k: [1] for k in rec}, rec), 3)
        loads = [sum(rec[k] for k in s) for s in shards]
        self.assertLessEqual(max(loads), min(loads) * 4 / 3)


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

    def test_contains_names_one_shard_and_runs_nothing(self):
        hits = []
        for k in (1, 2):
            rc, log = self.run_shard("--shard", f"{k}/2", "--exclude", "test_bad$", "--contains", r"\.test_two\.B\.test_c$")
            self.assertNotIn("ok", log)
            if rc == 0:
                hits.append(k)
        self.assertEqual(len(hits), 1)


if __name__ == "__main__":
    unittest.main()

    def test_timings_file_and_class_times(self):
        path = os.path.join(self.dir, "times.json")
        with open(path, "w") as f:
            json.dump({f"{self.pkg}.test_one.A": 5, f"{self.pkg}.test_two.B": 1}, f)
        rc, log = self.run_shard("--shard", "1/1", "--exclude", "test_bad$", "--timings", path)
        self.assertEqual(rc, 0)
        line = [x for x in log.splitlines() if x.startswith("class times: ")][0]
        times = json.loads(line[len("class times: "):])
        self.assertEqual(sorted(times), sorted([f"{self.pkg}.test_one.A", f"{self.pkg}.test_two.B", f"{self.pkg}.test_page.P"]))
