#!/usr/bin/env python3
"""Run one shard of a unittest suite, so CI can spread it over parallel jobs.

  test_shard.py --shard K/N --start DIR --top DIR [--pattern P ...] [--exclude REGEX]
                [--contains REGEX]

Discovers the tests like `python -m unittest discover -s DIR -t DIR -p P`
(once per --pattern, default test*.py), drops modules whose name matches
--exclude, and splits the test classes over N shards: whole classes only (their
setUpClass runs once), largest first onto the shard with the fewest tests, so
the split is the same on every runner. Runs shard K (1-based) verbosely and
exits non-zero on a failure or error, or when the shard is empty.

With --contains, runs nothing: exits 0 when shard K has a test whose id
(module.Class.test_name) matches REGEX, 1 otherwise (CI installs a tool only
on the shard whose tests use it).
"""

import argparse
import re
import sys
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


def split(sizes, n):
    """Class ids per shard: largest first onto the shard with the fewest tests."""
    shards = [[] for _ in range(n)]
    load = [0] * n
    for key in sorted(sizes, key=lambda k: (-sizes[k], k)):
        i = load.index(min(load))
        shards[i].append(key)
        load[i] += sizes[key]
    return shards


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--shard", required=True, help="K/N, e.g. 1/3")
    p.add_argument("--start", required=True)
    p.add_argument("--top", required=True)
    p.add_argument("--pattern", action="append")
    p.add_argument("--exclude", help="skip test modules whose name matches this regex")
    p.add_argument("--contains", help="run nothing; exit 0 when the shard has a test id matching this regex")
    a = p.parse_args(argv)
    k, n = (int(x) for x in a.shard.split("/"))
    if not 1 <= k <= n:
        p.error("--shard must be K/N with 1 <= K <= N")
    if a.top not in sys.path:
        sys.path.insert(0, a.top)
    found = classes(a.start, a.top, a.pattern or ["test*.py"], a.exclude)
    mine = split({key: len(tests) for key, tests in found.items()}, n)[k - 1]
    if a.contains:
        hit = [t.id() for key in mine for t in found[key] if re.search(a.contains, t.id())]
        print(f"shard {k}/{n}: {', '.join(hit) if hit else 'no test'} matching {a.contains!r}", flush=True)
        return 0 if hit else 1
    total = sum(len(v) for v in found.values())
    count = sum(len(found[key]) for key in mine)
    print(f"shard {k}/{n}: {count} of {total} tests in {len(mine)} classes", flush=True)
    if not mine:
        print("empty shard: raise the number of tests or lower N", file=sys.stderr)
        return 1
    suite = unittest.TestSuite(t for key in sorted(mine) for t in found[key])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
