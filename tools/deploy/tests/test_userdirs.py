"""Atomic writes that survive another program holding the file open on
Windows (windows-safe-new-config 1.3)."""

import os
import unittest
from unittest import mock

from canworks import userdirs

from .helpers import tmpdir


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


class ReplaceFile(unittest.TestCase):
    def setUp(self):
        self.dir = tmpdir(self)
        self.path = os.path.join(self.dir, "configuration.json")
        self.tmp = self.path + ".tmp"
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("old")
        with open(self.tmp, "w", encoding="utf-8") as f:
            f.write("new")
        self.now = [0.0]
        self.sleeps = []
        self.real = os.replace

    def held(self, tries):
        """os.replace refused `tries` times, as Windows does while a scanner has the file open."""
        calls = []

        def replace(src, dst):
            calls.append(dst)
            if tries is None or len(calls) <= tries:
                raise PermissionError(13, "Access is denied")
            self.real(src, dst)
        return calls, replace

    def run_replace(self, replace, **kw):
        def sleep(s):
            self.sleeps.append(s)
            self.now[0] += s
        with mock.patch.object(userdirs.os, "replace", replace), mock.patch.object(userdirs.os, "name", "nt"), \
                mock.patch.object(userdirs.time, "sleep", sleep), \
                mock.patch.object(userdirs.time, "monotonic", lambda: self.now[0]):
            userdirs.replace_file(self.tmp, self.path, **kw)

    def test_held_briefly(self):
        calls, replace = self.held(5)
        self.run_replace(replace)
        self.assertEqual(len(calls), 6)
        self.assertEqual(read(self.path), "new")
        self.assertFalse(os.path.exists(self.tmp))
        self.assertEqual(self.sleeps[:3], [0.02, 0.04, 0.08])

    def test_held_for_two_seconds(self):
        calls, replace = self.held(None)
        replace_after = []

        def let_go(src, dst):
            if self.now[0] >= 2.0:
                replace_after.append(self.now[0])
                return self.real(src, dst)
            return replace(src, dst)
        self.run_replace(let_go)
        self.assertEqual(read(self.path), "new")
        self.assertTrue(replace_after)
        self.assertLessEqual(max(self.sleeps), 0.5)

    def test_held_too_long(self):
        calls, replace = self.held(None)
        with self.assertRaises(userdirs.FileLockedError) as e:
            self.run_replace(replace)
        self.assertGreaterEqual(self.now[0], 5.0)
        self.assertLess(self.now[0], 6.0)
        self.assertIn(self.path, str(e.exception))
        self.assertIn("held open by another program", str(e.exception))
        self.assertIsInstance(e.exception, PermissionError)
        self.assertEqual(read(self.path), "old")
        self.assertFalse(os.path.exists(self.tmp))

    def test_held_too_long_written_in_place(self):
        calls, replace = self.held(None)
        self.run_replace(replace, in_place=True)
        self.assertEqual(read(self.path), "new")
        self.assertFalse(os.path.exists(self.tmp))

    def test_shorter_deadline(self):
        calls, replace = self.held(None)
        with self.assertRaises(userdirs.FileLockedError):
            self.run_replace(replace, deadline_s=1.0)
        self.assertLess(self.now[0], 2.0)

    def test_not_windows_fails_at_once(self):
        calls, replace = self.held(None)
        with mock.patch.object(userdirs.os, "replace", replace), mock.patch.object(userdirs.os, "name", "posix"):
            with self.assertRaises(PermissionError) as e:
                userdirs.replace_file(self.tmp, self.path)
        self.assertNotIsInstance(e.exception, userdirs.FileLockedError)
        self.assertEqual(len(calls), 1)
        self.assertFalse(os.path.exists(self.tmp))
