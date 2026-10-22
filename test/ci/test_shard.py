"""The CI test sharding (.github/scripts/test_shard.py)."""

import contextlib
import importlib.util
import io
import json
import os
import re
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
            # No test ran (the temporary package's name can hold "ok").
            self.assertNotRegex(log, r"(?m)\.\.\. ok$|^OK\b|^Ran [1-9]")
            if rc == 0:
                hits.append(k)
        self.assertEqual(len(hits), 1)


    def test_timings_file_and_class_times(self):
        path = os.path.join(self.dir, "times.json")
        with open(path, "w") as f:
            json.dump({f"{self.pkg}.test_one.A": 5, f"{self.pkg}.test_two.B": 1}, f)
        rc, log = self.run_shard("--shard", "1/1", "--exclude", "test_bad$", "--timings", path)
        self.assertEqual(rc, 0)
        line = [x for x in log.splitlines() if x.startswith("class times: ")][0]
        times = json.loads(line[len("class times: "):])
        self.assertEqual(sorted(times), sorted([f"{self.pkg}.test_one.A", f"{self.pkg}.test_two.B", f"{self.pkg}.test_page.P"]))

    def ran(self, log):
        return sorted(line.split(" ")[0] for line in log.splitlines() if re.match(r"test_\w+ \(", line))

    def test_workers_run_every_test_once(self):
        rc, log = self.run_shard("--shard", "1/1", "--exclude", "test_bad$", "--jobs", "3")
        self.assertEqual(rc, 0, log)
        self.assertIn("3 workers", log)
        self.assertEqual(self.ran(log), ["test_a", "test_b", "test_c", "test_p"])
        self.assertEqual(log.count("== worker "), 3)
        times = json.loads([x for x in log.splitlines() if x.startswith("class times: ")][0][len("class times: "):])
        self.assertEqual(len(times), 3)

    def test_a_failing_worker_fails_the_run(self):
        rc, log = self.run_shard("--shard", "1/1", "--jobs", "4")
        self.assertEqual(rc, 1)
        self.assertIn("boom", log)
        self.assertIn("boom", log[log.index("== failed workers =="):])  # repeated at the end
        self.assertEqual(self.ran(log), ["test_a", "test_b", "test_c", "test_p", "test_x"])

    def test_a_worker_that_dies_fails_the_run(self):
        with open(os.path.join(self.dir, self.pkg, "test_die.py"), "w") as f:
            f.write("import os, unittest\nclass D(unittest.TestCase):\n    def test_d(self): os._exit(3)\n")
        rc, log = self.run_shard("--shard", "1/1", "--exclude", "test_bad$", "--jobs", "2")
        self.assertEqual(rc, 1)
        self.assertIn("ended without a result (exit 3)", log)

    def test_workers_have_their_own_temporary_folder(self):
        with open(os.path.join(self.dir, self.pkg, "test_tmp.py"), "w") as f:
            f.write(textwrap.dedent("""\
                import os, tempfile, unittest
                class T1(unittest.TestCase):
                    def test_t1(self): print("TMP", os.environ["CANWORKS_TEST_WORKER"], tempfile.gettempdir())
                class T2(unittest.TestCase):
                    def test_t2(self): print("TMP", os.environ["CANWORKS_TEST_WORKER"], tempfile.gettempdir())
                """))
        rc, log = self.run_shard("--shard", "1/1", "--pattern", "test_tmp.py", "--jobs", "2")
        self.assertEqual(rc, 0, log)
        seen = re.findall(r"TMP (\d) (\S+)", log)  # printed after the test's "... " on its line
        self.assertEqual(sorted(w for w, _ in seen), ["1", "2"])
        self.assertNotEqual(seen[0][1], seen[1][1])

    def test_workers_see_no_terminal_and_absolute_module_paths(self):
        with open(os.path.join(self.dir, self.pkg, "test_env.py"), "w") as f:
            f.write(textwrap.dedent("""\
                import os, sys, unittest
                class E1(unittest.TestCase):
                    def test_e1(self): print("ENV", sys.stdin.isatty(), sys.stdin.read() == "", os.path.isabs(__file__))
                class E2(unittest.TestCase):
                    def test_e2(self): pass
                """))
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):  # --top relative, as CI passes it
            rc = shard.main(["--start", os.path.join(self.dir, self.pkg), "--top", os.path.relpath(self.dir),
                             "--shard", "1/1", "--pattern", "test_env.py", "--jobs", "2"])
        self.assertEqual(rc, 0, out.getvalue())
        self.assertIn("ENV False True True", out.getvalue())

    def test_split_class_runs_each_method_once_with_its_own_setup(self):
        with open(os.path.join(self.dir, self.pkg, "test_big.py"), "w") as f:
            f.write(textwrap.dedent("""\
                import unittest
                class Big(unittest.TestCase):
                    @classmethod
                    def setUpClass(cls): print("SETUP")
                """) + "".join(f"    def test_m{i}(self): pass\n" for i in range(6)))
        path = os.path.join(self.dir, "times.json")
        with open(path, "w") as f:
            json.dump({f"{self.pkg}.test_big.Big": 90}, f)
        rc, log = self.run_shard("--shard", "1/1", "--pattern", "test_big.py", "--timings", path,
                                 "--split-over", "30", "--jobs", "3")
        self.assertEqual(rc, 0, log)
        self.assertEqual(self.ran(log), [f"test_m{i}" for i in range(6)])
        self.assertEqual(log.count("SETUP"), 3)
        times = json.loads([x for x in log.splitlines() if x.startswith("class times: ")][0][len("class times: "):])
        self.assertEqual(list(times), [f"{self.pkg}.test_big.Big"])

    def test_serial_classes_run_after_the_workers(self):
        rc, log = self.run_shard("--shard", "1/1", "--exclude", "test_bad$", "--jobs", "2", "--serial", r"\.test_page\.P$")
        self.assertEqual(rc, 0, log)
        self.assertIn("then 1 alone", log)
        self.assertEqual(self.ran(log), ["test_a", "test_b", "test_c", "test_p"])
        self.assertGreater(log.index("test_p ("), max(log.index("test_a ("), log.index("test_c (")))


class Parts(unittest.TestCase):
    def test_large_class_cut_into_parts(self):
        found = {"m.Big": list(range(7)), "m.Small": [1]}
        tests, size = shard.parts(found, {"m.Big": 100, "m.Small": 5}, 30)
        self.assertEqual(sorted(tests), ["m.Big[1/4]", "m.Big[2/4]", "m.Big[3/4]", "m.Big[4/4]", "m.Small"])
        self.assertEqual(sorted(t for k, v in tests.items() if k.startswith("m.Big") for t in v), list(range(7)))
        self.assertEqual(size["m.Big[1/4]"], 25)

    def test_no_more_parts_than_tests_and_together_never_cut(self):
        tests, _ = shard.parts({"m.Two": [1, 2], "p.Parity": [1, 2, 3]}, {"m.Two": 300, "p.Parity": 300}, 30,
                               r"^p\.Parity$")
        self.assertEqual(sorted(tests), ["m.Two[1/2]", "m.Two[2/2]", "p.Parity"])

    def test_without_a_limit_nothing_is_cut(self):
        tests, size = shard.parts({"m.Big": [1, 2, 3]}, {"m.Big": 1000})
        self.assertEqual(tests, {"m.Big": [1, 2, 3]})


if __name__ == "__main__":
    unittest.main()
