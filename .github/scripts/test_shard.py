#!/usr/bin/env python3
"""Run one shard of a unittest suite, so CI can spread it over parallel jobs.

  test_shard.py --shard K/N --start DIR --top DIR [--pattern P ...] [--exclude REGEX]
                [--contains REGEX] [--timings FILE] [--together REGEX]
                [--jobs N|auto] [--split-over SECONDS] [--serial REGEX]

Discovers the tests like `python -m unittest discover -s DIR -t DIR -p P`
(once per --pattern, default test*.py), drops modules whose name matches
--exclude, and splits the test classes over N shards: whole classes only (their
setUpClass runs once), largest first onto the shard with the fewest tests, so
the split is the same on every runner. Runs shard K (1-based) verbosely and
exits non-zero on a failure or error, or when the shard is empty.

With --timings, a class's size is its recorded seconds in FILE ({class id:
seconds}) instead of its test count; a class FILE does not name counts as the
median recorded class. After the run, the shard prints its classes' seconds
as one "class times:" JSON line, the values to merge into FILE.

With --together, the classes whose id matches REGEX go to one shard as one
unit (CI builds what they need only on that shard).

With --split-over (needs --timings), a class whose recorded seconds exceed it
is cut into parts of whole test methods, about that long each, which can land
on different shards or workers; each part runs the class's setUpClass itself.
Classes matched by --together are never cut.

With --jobs (default: the CPU count), the shard's parts are split again, the
same way, over that many worker processes that run at the same time, each with
its own temporary folder and its number in CANWORKS_TEST_WORKER. Each worker's
log is printed whole when it ends; the run fails when a worker fails, errors or
ends without a result. --jobs 1 runs in this process. With --serial, the
classes whose id matches REGEX run after the workers, alone, in one more worker.

With --contains, runs nothing: exits 0 when shard K has a test whose id
(module.Class.test_name) matches REGEX, 1 otherwise (CI installs a tool only
on the shard whose tests use it).
"""

import argparse
import json
import math
import os
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
import unittest


def flatten(suite):
    for t in suite:
        if isinstance(t, unittest.TestSuite):
            yield from flatten(t)
        else:
            yield t


def classes(start, top, patterns, exclude=None):
    """{class id: [tests]} for every test found, in discovery order."""
    found = {}
    for pattern in patterns:
        for t in flatten(unittest.TestLoader().discover(start, pattern=pattern, top_level_dir=top)):
            if isinstance(t, unittest.loader._FailedTest):
                key = "failed." + t.id()  # an import error: one shard reports it
            else:
                key = f"{type(t).__module__}.{type(t).__qualname__}"
                if exclude and re.search(exclude, type(t).__module__):
                    continue
            tests = found.setdefault(key, [])
            if t.id() not in {x.id() for x in tests}:
                tests.append(t)
    return found


def split(sizes, n, together=None):
    """Class ids per shard: largest first onto the lightest shard (tests or seconds).
    Classes whose id matches `together` are one unit on one shard."""
    units = {key: [key] for key in sizes}
    if together:
        group = sorted(k for k in sizes if re.search(together, k))
        if group:
            for k in group:
                del units[k]
            units[group[0]] = group
    size = {u: sum(sizes[k] for k in keys) for u, keys in units.items()}
    shards = [[] for _ in range(n)]
    load = [0] * n
    for u in sorted(units, key=lambda k: (-size[k], k)):
        i = load.index(min(load))
        shards[i].extend(units[u])
        load[i] += size[u]
    return shards


def sizes_from(found, timings):
    """{class id: size}: recorded seconds, the median for unknown classes; test counts without timings."""
    if timings is None:
        return {key: len(tests) for key, tests in found.items()}
    known = [float(v) for v in timings.values()]
    default = statistics.median(known) if known else 1.0
    return {key: float(timings.get(key, default)) for key in found}


def parts(found, sizes, split_over=None, together=None):
    """({part id: [tests]}, {part id: size}): every class, and each class over
    `split_over` cut into consecutive runs of its tests ("Class[2/3]")."""
    tests, size = {}, {}
    for key, ts in found.items():
        n = 1
        if split_over and not (together and re.search(together, key)):
            n = min(len(ts), math.ceil(sizes[key] / split_over))
        if n <= 1:
            tests[key], size[key] = ts, sizes[key]
            continue
        for i in range(n):
            part = f"{key}[{i + 1}/{n}]"
            tests[part] = ts[len(ts) * i // n:len(ts) * (i + 1) // n]
            size[part] = sizes[key] / n
    return tests, size


def test_name(test):
    """The name loadTestsFromName() finds this test by (an import failure: its module)."""
    if isinstance(test, unittest.loader._FailedTest):
        return test._testMethodName
    return f"{type(test).__module__}.{type(test).__qualname__}.{test._testMethodName}"


class TimedResult(unittest.TextTestResult):
    """Adds up the seconds each test class took (its tests and setUpClass)."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.class_seconds = {}
        self._mark = time.monotonic()

    def _key(self, test):
        return f"{type(test).__module__}.{type(test).__qualname__}"

    def stopTest(self, test):
        super().stopTest(test)
        now = time.monotonic()
        key = self._key(test)
        self.class_seconds[key] = self.class_seconds.get(key, 0.0) + now - self._mark
        self._mark = now


def run_here(tests):
    """Run the tests in this process; (passed, class times)."""
    suite = unittest.TestSuite(tests)
    result = unittest.TextTestRunner(verbosity=2, resultclass=TimedResult).run(suite)
    return result.wasSuccessful(), result.class_seconds


def worker(names_file, result_file):
    """A worker process: run the named tests, write {"ok", "ran", "times"}."""
    with open(names_file) as f:
        names = json.load(f)
    loader = unittest.TestLoader()
    tests = [t for name in names for t in flatten(loader.loadTestsFromName(name))]
    ok, times = run_here(tests)
    with open(result_file, "w") as f:
        json.dump({"ok": ok, "ran": len(tests), "times": times}, f)
    return 0 if ok else 1


def run_workers(groups, top, base):
    """Run each group of test names in its own process at the same time; (passed, class times)."""
    procs = []
    for i, names in enumerate(groups, 1):
        wdir = os.path.join(base, f"worker{i}")
        os.makedirs(os.path.join(wdir, "tmp"))
        with open(os.path.join(wdir, "names.json"), "w") as f:
            json.dump(names, f)
        env = dict(os.environ, CANWORKS_TEST_WORKER=str(i), TMPDIR=os.path.join(wdir, "tmp"),
                   TEMP=os.path.join(wdir, "tmp"), TMP=os.path.join(wdir, "tmp"), PYTHONUNBUFFERED="1")
        log = open(os.path.join(wdir, "log.txt"), "w")
        proc = subprocess.Popen([sys.executable, os.path.abspath(__file__), "--worker", os.path.join(wdir, "names.json"),
                                 "--result", os.path.join(wdir, "result.json"), "--top", top],
                                stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, env=env)
        procs.append((i, proc, log, wdir, time.monotonic()))
    ok, times, waiting, said, failed = True, {}, list(procs), time.monotonic(), []
    while waiting:
        for item in list(waiting):
            i, proc, log, wdir, start = item
            if proc.poll() is None:
                continue
            waiting.remove(item)
            log.close()
            print(f"== worker {i}/{len(groups)}: {len(groups[i - 1])} tests, exit {proc.returncode}, "
                  f"{time.monotonic() - start:.0f} s ==", flush=True)
            with open(os.path.join(wdir, "log.txt"), errors="replace") as f:
                text = f.read()
            sys.stdout.write(text)
            sys.stdout.flush()
            try:
                with open(os.path.join(wdir, "result.json")) as f:
                    result = json.load(f)
            except (OSError, ValueError):
                print(f"worker {i} ended without a result (exit {proc.returncode})", file=sys.stderr, flush=True)
                failed.append(f"worker {i} ended without a result (exit {proc.returncode}); its log is above")
                ok = False
                continue
            if not (result["ok"] and proc.returncode == 0):
                # unittest's failure report starts at its first "=====" line
                start = text.find("\n" + "=" * 70 + "\n")
                failed.append(f"worker {i}:" + (text[start:] if start >= 0 else f" exit {proc.returncode}\n"))
            ok = ok and result["ok"] and proc.returncode == 0
            for key, v in result["times"].items():
                times[key] = times.get(key, 0.0) + v
        if waiting:
            if time.monotonic() - said >= 60:  # a hung worker shows in the log before the job's time limit
                said = time.monotonic()
                print("(workers still running: %s)" % ", ".join(str(item[0]) for item in waiting), flush=True)
            time.sleep(0.2)
    if failed:
        # again at the end, where the log's tail shows it
        print("== failed workers ==\n" + "\n".join(failed), flush=True)
    return ok, times


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--shard", help="K/N, e.g. 1/3")
    p.add_argument("--start")
    p.add_argument("--top", required=True)
    p.add_argument("--pattern", action="append")
    p.add_argument("--exclude", help="skip test modules whose name matches this regex")
    p.add_argument("--contains", help="run nothing; exit 0 when the shard has a test id matching this regex")
    p.add_argument("--timings", help="JSON file {class id: seconds}: split by recorded time")
    p.add_argument("--together", help="keep the classes whose id matches this regex on one shard")
    p.add_argument("--split-over", type=float, help="cut classes recorded as longer than this many seconds")
    p.add_argument("--jobs", default="auto", help="worker processes in this shard (default: auto, the CPU count)")
    p.add_argument("--serial", help="run the classes whose id matches this regex alone after the workers")
    p.add_argument("--worker", help=argparse.SUPPRESS)
    p.add_argument("--result", help=argparse.SUPPRESS)
    a = p.parse_args(argv)
    if a.top not in sys.path:
        sys.path.insert(0, a.top)
    if a.worker:
        return worker(a.worker, a.result)
    if not a.shard or not a.start:
        p.error("--shard and --start are required")
    k, n = (int(x) for x in a.shard.split("/"))
    if not 1 <= k <= n:
        p.error("--shard must be K/N with 1 <= K <= N")
    jobs = (os.cpu_count() or 1) if a.jobs == "auto" else int(a.jobs)
    if jobs < 1:
        p.error("--jobs must be 1 or more")
    found = classes(a.start, a.top, a.pattern or ["test*.py"], a.exclude)
    timings = None
    if a.timings:
        with open(a.timings) as f:
            timings = json.load(f)
    sizes = sizes_from(found, timings)
    tests, size = parts(found, sizes, a.split_over if timings is not None else None, a.together)
    mine = split(size, n, a.together)[k - 1]
    if a.contains:
        hit = [t.id() for key in mine for t in tests[key] if re.search(a.contains, t.id())]
        print(f"shard {k}/{n}: {', '.join(hit) if hit else 'no test'} matching {a.contains!r}", flush=True)
        return 0 if hit else 1
    total = sum(len(v) for v in found.values())
    count = sum(len(tests[key]) for key in mine)
    print(f"shard {k}/{n}: {count} of {total} tests in {len(mine)} classes and parts", flush=True)
    if not mine:
        print("empty shard: raise the number of tests or lower N", file=sys.stderr)
        return 1
    serial = sorted(key for key in mine if a.serial and re.search(a.serial, key))
    pooled = [key for key in mine if key not in serial]
    jobs = min(jobs, len(pooled))
    if jobs <= 1 and not serial:
        ok, times = run_here([t for key in sorted(mine) for t in tests[key]])
    else:
        groups = [sorted(g) for g in split({key: size[key] for key in pooled}, jobs)] if pooled else []
        print(f"{len(groups)} workers" + (f", then {len(serial)} alone" if serial else ""), flush=True)
        base = tempfile.mkdtemp(prefix="test_shard-")
        try:
            names = [[test_name(t) for key in g for t in tests[key]] for g in groups]
            ok, times = run_workers(names, a.top, os.path.join(base, "pool")) if names else (True, {})
            if serial:
                ok2, times2 = run_workers([[test_name(t) for key in serial for t in tests[key]]], a.top,
                                          os.path.join(base, "serial"))
                ok = ok and ok2
                times.update(times2)
        finally:
            shutil.rmtree(base, ignore_errors=True)
        longest = sorted(((size[key], key) for key in mine), reverse=True)[:5]
        print("longest recorded parts: " + ", ".join(f"{key} {s:.0f} s" for s, key in longest), flush=True)
    times = {key: round(v, 1) for key, v in sorted(times.items())}
    print("class times: " + json.dumps(times), flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
