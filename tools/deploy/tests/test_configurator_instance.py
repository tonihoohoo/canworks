"""canworks-config's start and stop (configurator-quit-and-background):
one configurator per user (instance.json, /api/instance/start), stopping when
the last page is closed, the background start with its log, the address
shown when no browser opened, and the session cookie per port. No browser
opens and no window is shown: webbrowser.open and the message window are
stubbed, and the times are short."""

import contextlib
import http.client
import http.cookiejar
import io
import json
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
import unittest
import urllib.request
from unittest import mock

from canworks.configurator import launch, server as srv
from canworks.localbus import core as core_mod

from .helpers import tmpdir
from .test_configurator_server import DEPLOY, FIXTURE

POSIX = unittest.skipIf(os.name == "nt", "POSIX sessions and file modes")


def post(port, path, body=None, headers=None):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    h = {"Host": "127.0.0.1:%d" % port, "Content-Type": "application/json"}
    h.update(headers or {})
    c.request("POST", path, json.dumps(body if body is not None else {}), h)
    r = c.getresponse()
    data = r.read()
    c.close()
    try:
        return r.status, json.loads(data.decode()) if data else {}
    except ValueError:
        return r.status, data


class Base(unittest.TestCase):
    """A configurator in this process, served as main() serves it, with its
    instance file in a settings folder of the test's own."""

    def setUp(self):
        self.dir = tmpdir(self)
        p = mock.patch.dict(os.environ, {"CANWORKS_CONFIG_DIR": os.path.join(self.dir, "cfg")})
        p.start()
        self.addCleanup(p.stop)
        self.project = os.path.join(self.dir, "rtd-monitor")
        shutil.copytree(FIXTURE, self.project)

    def start(self, publish=True, stop_unused=False, **times):
        server = srv.Server()
        if publish:
            server.publish(launch.instance_path())
        server.stop_unused = stop_unused
        server.closed_s, server.silent_s, server.startup_s = (times.get("closed", 0.3), times.get("silent", 30),
                                                             times.get("startup", 30))
        server.no_page_s, server.tick_s = times.get("no_page", 30), 0.05
        server.start_watch()
        t = threading.Thread(target=srv.serve, args=(server,), daemon=True)
        t.start()
        self.addCleanup(lambda: (server.shutdown(), t.join(5)) if t.is_alive() else None)
        server.thread = t
        return server

    def api(self, server, method, path, body=None):
        c = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=10)
        c.request(method, path, json.dumps(body) if body is not None else None,
                  {"Host": "127.0.0.1:%d" % server.server_port, srv.TOKEN_HEADER: server.token,
                   "Content-Type": "application/json"})
        r = c.getresponse()
        data = json.loads(r.read() or b"{}")
        c.close()
        self.assertEqual(r.status, 200, data)
        return data

    def beat(self, server, page, unsaved=False):
        return self.api(server, "POST", "/api/heartbeat", {"page": page, "unsaved": unsaved})

    def beacon(self, server, page, cookie=True):
        name = "%s_%d" % (srv.COOKIE, server.server_port)
        return post(server.server_port, "/api/page/closed", {"page": page},
                    {"Cookie": "%s=%s" % (name, server.token)} if cookie else {})

    def instance(self, server, path, body):
        return post(server.server_port, path, body, {launch.HEADER: server.instance_secret})

    def stops_within(self, server, seconds):
        server.thread.join(seconds)
        return not server.thread.is_alive()


class InstanceFile(Base):
    def test_written_for_this_user_and_removed_on_close(self):
        server = self.start()
        path = launch.instance_path()
        doc = launch.read_instance(path)
        self.assertEqual((doc["pid"], doc["port"]), (os.getpid(), server.server_port))
        self.assertEqual(doc["secret"], server.instance_secret)
        self.assertNotEqual(doc["secret"], server.token)
        if os.name != "nt":
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
        # O_EXCL: a second configurator does not overwrite it.
        with self.assertRaises(FileExistsError):
            launch.write_instance(path, 1, "x")
        self.api(server, "POST", "/api/quit", {})
        self.assertTrue(self.stops_within(server, 5))
        self.assertFalse(os.path.exists(path))

    def test_secret_needed(self):
        server = self.start()
        self.assertEqual(post(server.server_port, "/api/instance/start", {})[0], 403)
        self.assertEqual(post(server.server_port, "/api/instance/start", {}, {launch.HEADER: "wrong"})[0], 403)
        # The session token is not the secret either.
        self.assertEqual(post(server.server_port, "/api/instance/start", {}, {launch.HEADER: server.token})[0], 403)

    def test_new_start_address_works_once(self):
        server = self.start()
        status, data = self.instance(server, "/api/instance/start", {"browser": False})
        self.assertEqual(status, 200, data)
        url = data["url"]
        self.assertTrue(url.startswith("http://127.0.0.1:%d/?code=" % server.server_port))
        code = url.split("code=")[1]
        self.assertEqual(self.instance(server, "/api/instance/page", {"code": code}), (200, {"opened": False}))
        c = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=10)
        for want in (303, 403):
            c.request("GET", "/?code=" + code, headers={"Host": "127.0.0.1:%d" % server.server_port})
            r = c.getresponse()
            r.read()
            self.assertEqual(r.status, want)
        c.close()
        self.assertEqual(self.instance(server, "/api/instance/page", {"code": code}), (200, {"opened": True}))

    def test_path_opens_at_once_without_unsaved_changes(self):
        server = self.start()
        epoch = self.beat(server, "a")["epoch"]
        status, data = self.instance(server, "/api/instance/start", {"path": self.project})
        self.assertEqual(status, 200, data)
        state = self.api(server, "GET", "/api/state")
        self.assertEqual((state["mode"], state["folder"]), ("project", self.project))
        self.assertEqual(self.beat(server, "a")["epoch"], epoch + 1)  # the page reloads
        status, data = self.instance(server, "/api/instance/start", {"path": os.path.join(self.project, "project.json")})
        self.assertEqual(status, 422, data)
        self.assertIn("is not a folder", data["error"])

    def test_path_queued_while_a_page_has_unsaved_changes(self):
        server = self.start()
        self.beat(server, "editing", unsaved=True)
        status, _ = self.instance(server, "/api/instance/start", {"path": self.project})
        self.assertEqual(status, 200)
        self.assertIsNone(self.api(server, "GET", "/api/state")["mode"])  # not opened
        # The page with unsaved changes asks; a new page says where it waits.
        req = self.beat(server, "editing", unsaved=True)["open"]
        self.assertEqual(req["path"], self.project)
        new = self.beat(server, "new")
        self.assertEqual((new["open"], new["waiting"]), (None, self.project))
        self.api(server, "POST", "/api/second_start/done", {"id": req["id"]})
        self.assertIsNone(self.beat(server, "editing", unsaved=True)["open"])


class SecondStart(Base):
    def run_main(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), \
                mock.patch.object(srv.Server, "serve_forever", side_effect=AssertionError("a second server")):
            code = srv.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_opens_a_page_of_the_running_one(self):
        server = self.start()
        code, out, _ = self.run_main("--no-browser")
        self.assertEqual(code, 0)
        self.assertIn("http://127.0.0.1:%d/?code=" % server.server_port, out)
        # With the browser: it prints the address, asks the browser and
        # returns without waiting for the page (skip-reinstall-faster-start).
        with mock.patch("webbrowser.open") as opened, mock.patch.object(launch, "message_window") as window:
            began = time.monotonic()
            code, out, _ = self.run_main("--foreground", self.project)
        self.assertEqual(code, 0)
        self.assertLess(time.monotonic() - began, 5)
        url = opened.call_args[0][0]
        self.assertIn("canworks configurator: %s" % url, out)
        self.assertEqual(self.api(server, "GET", "/api/state")["folder"], self.project)
        # Nothing opened it: the running configurator logs the address; a
        # terminal start shows no window (the address is in the terminal).
        server.no_page_s = 0
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            server._report_unopened()
        self.assertIn(launch.NO_BROWSER % url, out.getvalue())
        window.assert_not_called()

    def test_from_shortcut_while_running(self):
        server = self.start()
        with mock.patch("webbrowser.open") as opened, mock.patch.object(launch, "message_window") as window:
            code, out, _ = self.run_main("--from-shortcut")
            self.assertEqual(code, 0)
            self.assertEqual(out, "")  # no terminal to print to
            url = opened.call_args[0][0]
            # No page came: the address in the log and, from the shortcut, a window.
            server.no_page_s = 0
            with contextlib.redirect_stdout(io.StringIO()):
                server._report_unopened()
            deadline = time.monotonic() + 5
            while not window.called and time.monotonic() < deadline:
                time.sleep(0.02)
        window.assert_called_once_with(url)

    def test_refused_path(self):
        self.start()
        code, _, err = self.run_main("--no-browser", os.path.join(self.project, "project.json"))
        self.assertEqual(code, 2)
        self.assertIn("is not a folder", err)

    def test_stale_instance_file_ignored(self):
        # A configurator that no longer runs.
        p = subprocess.Popen([sys.executable, "-c", "pass"])
        p.wait()
        os.makedirs(os.path.dirname(launch.instance_path()))
        with open(launch.instance_path(), "w") as f:
            json.dump({"pid": p.pid, "port": 1, "secret": "old"}, f)
        self.assertIsNone(launch.running())
        # One that runs (this process) but does not answer: given up on after ASK_S.
        port = srv.Server()
        free = port.server_port
        port.server_close()
        t = time.monotonic()
        self.assertIsNone(launch.hand_over({"pid": os.getpid(), "port": free, "secret": "x"}, None, browser=False))
        self.assertLess(time.monotonic() - t, launch.ASK_S + 1)

    def test_stale_file_replaced_by_a_new_configurator(self):
        p = subprocess.Popen([sys.executable, "-c", "pass"])
        p.wait()
        os.makedirs(os.path.dirname(launch.instance_path()))
        with open(launch.instance_path(), "w") as f:
            json.dump({"pid": p.pid, "port": 1, "secret": "old"}, f)
        proc, url, start = self.subprocess_config("--no-browser")
        doc = launch.read_instance()
        # The new configurator's file: its starter's id, its port, and the pid
        # of the server itself, alive (on Windows proc.pid is a venv
        # launcher's, not the configurator's: launch.spawn).
        self.assertEqual((doc["start"], doc["port"]), (start, int(url.split(":")[2].split("/")[0])))
        self.assertNotEqual(doc["pid"], p.pid)
        self.assertEqual(launch.running(), doc)
        # /api/quit needs the session: the page's, from a fresh start address.
        status, data = post(doc["port"], "/api/instance/start", {"browser": False}, {launch.HEADER: doc["secret"]})
        self.assertEqual(status, 200)
        self.quit(proc, data["url"])
        self.assertIsNone(launch.read_instance())
        self.assertFalse(launch.pid_alive(doc["pid"]))

    def test_new_instance(self):
        server = self.start()
        proc, url, start = self.subprocess_config("--no-browser", "--new-instance")
        self.assertNotIn(":%d/" % server.server_port, url)
        self.assertEqual(launch.read_instance()["port"], server.server_port)  # the first one is still the one found
        # Quit through its page (terminating proc would stop only the venv
        # launcher on Windows, not the configurator).
        self.quit(proc, url)
        self.assertEqual(launch.read_instance()["port"], server.server_port)

    def subprocess_config(self, *argv):
        """The configurator started as a process: the process, its address
        (stdout's first line) and its starter's id (launch.START_ENV)."""
        start = "test-%d-%d" % (os.getpid(), id(self))
        env = dict(os.environ, PYTHONPATH=DEPLOY, **{launch.START_ENV: start})
        proc = subprocess.Popen([sys.executable, "-m", "canworks.configurator.server"] + list(argv),
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, env=env)
        self.addCleanup(lambda: proc.poll() is None and proc.kill())
        self.addCleanup(proc.stdout.close)
        line = proc.stdout.readline()
        self.assertIn("http://127.0.0.1:", line)
        return proc, line.split()[-1], start

    def quit(self, proc, url):
        """Quit as the page does: the session token from the start address
        `url`, then /api/quit."""
        jar = http.cookiejar.CookieJar()
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPCookieProcessor(jar))
        opener.open(url, timeout=10).read()
        token = next(c.value for c in jar)
        post(int(url.split(":")[2].split("/")[0]), "/api/quit", {}, {srv.TOKEN_HEADER: token})
        self.assertEqual(proc.wait(10), 0)


class LastPage(Base):
    def test_beacon_stops_it_and_frees_the_adapter(self):
        server = self.start(stop_unused=True)
        ch = "cfg-instance-%d" % os.getpid()
        p = mock.patch.object(core_mod, "LISTEN_S", 0.05)
        p.start()
        self.addCleanup(p.stop)
        self.api(server, "POST", "/api/commission", {})
        self.api(server, "POST", "/api/online/settings", {"adapter": "virtual:" + ch, "adapter_bitrate": 250})
        self.api(server, "POST", "/api/online/status", {})
        self.assertTrue(server.connection.connected)
        self.beat(server, "a")
        self.assertEqual(self.beacon(server, "a")[0], 204)
        self.assertTrue(self.stops_within(server, 5))
        self.assertEqual(server.stopped_why, "its last page was closed")
        self.assertFalse(server.connection.connected)

    def test_reload_keeps_it(self):
        server = self.start(stop_unused=True, closed=1.5)
        self.beat(server, "a")
        self.beacon(server, "a")
        self.beat(server, "b")  # the reloaded page
        self.assertFalse(self.stops_within(server, 2.5))  # past a's end
        self.beacon(server, "b")
        self.assertTrue(self.stops_within(server, 10))

    def test_two_pages_keep_it(self):
        server = self.start(stop_unused=True)
        self.beat(server, "a")
        self.beat(server, "b")
        self.beacon(server, "a")
        self.assertFalse(self.stops_within(server, 0.6))

    def test_no_heartbeat(self):
        server = self.start(stop_unused=True, silent=0.5)
        self.beat(server, "a")
        self.assertTrue(self.stops_within(server, 5))

    def test_beacon_needs_the_cookie(self):
        server = self.start(stop_unused=True)
        self.beat(server, "a")
        self.assertEqual(self.beacon(server, "a", cookie=False)[0], 403)
        self.assertFalse(self.stops_within(server, 0.6))

    def test_keep_running(self):
        server = self.start(stop_unused=False, startup=0.2)
        self.beat(server, "a")
        self.beacon(server, "a")
        self.assertFalse(self.stops_within(server, 0.6))

    def test_startup_grace(self):
        server = self.start(stop_unused=True, startup=0.5)
        self.assertTrue(self.stops_within(server, 5))
        self.assertIn("no page was opened", server.stopped_why)

    def test_second_start_waits_for_its_page(self):
        # The last page closed; a second start's page is due after it, not the
        # close. The times leave seconds for a slow runner; PageEnds checks the
        # same rule with chosen times.
        server = self.start(stop_unused=True, closed=1.5, startup=5)
        self.beat(server, "a")
        self.beacon(server, "a")
        self.instance(server, "/api/instance/start", {"browser": False})
        self.assertFalse(self.stops_within(server, 2.5))  # past a's end
        self.beat(server, "b")
        self.assertFalse(self.stops_within(server, 3.0))  # past the second start's grace
        self.beacon(server, "b")
        self.assertTrue(self.stops_within(server, 10))

    def test_address_printed_when_no_page_came(self):
        out = io.StringIO()
        with mock.patch("sys.stdout", out):
            server = self.start(no_page=0.2)
            url = server.url
            server.asked_browser(url)
            opened = server.url
            server.asked_browser(opened)
            server.take_start_code(opened.split("code=")[1])  # this one the browser opened
            end = time.monotonic() + 10
            while not out.getvalue() and time.monotonic() < end:
                time.sleep(0.05)
            time.sleep(0.5)  # ticks after it: the opened one is not printed
        self.assertEqual(out.getvalue().strip(), launch.NO_BROWSER % url)



class PageEnds(Base):
    """Server.unused() and the watch tick with chosen monotonic times
    (configurator-survive-sleep): when a page ends, why, and sleep."""

    def server(self, since=0.0):
        server = srv.Server()
        self.addCleanup(server.server_close)
        server.stop_unused = True
        server.since = since
        server.last_tick = since
        return server

    def test_every_stop_logs_why(self):
        # Quit, the last page, or stopped from outside (SIGTERM): one line in the log each.
        server = self.server()
        threading.Thread(target=server.serve_forever, daemon=True).start()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            server.stop("it was told to stop (a signal)")
        self.assertEqual(out.getvalue(), "canworks-config stopped: it was told to stop (a signal).\n")

    def test_mac_app_teardown_signals_let_go(self):
        # macOS stops the app's processes when its script ends: the configurator
        # it started lets SIGINT/SIGTERM go by for its first seconds, then stops on them.
        clock = [100.0]
        server = mock.Mock()
        handler, names = srv.outside_stop(server, "shortcut", platform="darwin", now=lambda: clock[0])
        self.assertIn("SIGINT", names)
        handler()
        clock[0] += srv.APP_TEARDOWN_S - 1
        handler()
        server.stop.assert_not_called()
        clock[0] += 2
        handler()
        deadline = time.monotonic() + 5
        while not server.stop.called and time.monotonic() < deadline:
            time.sleep(0.01)
        server.stop.assert_called_once_with("it was told to stop (a signal)")

    def test_terminal_start_stops_on_a_signal_at_once(self):
        for mode, platform in (("terminal", "darwin"), ("shortcut", "win32"), ("shortcut", "linux")):
            server = mock.Mock()
            handler, names = srv.outside_stop(server, mode, platform=platform)
            self.assertNotIn("SIGINT", names)
            handler()
            deadline = time.monotonic() + 5
            while not server.stop.called and time.monotonic() < deadline:
                time.sleep(0.01)
            server.stop.assert_called_once_with("it was told to stop (a signal)")

    def ticks(self, server, start, end, step=1.0):
        """Ticks the watch loop from start to end; the first stop reason and
        its time, or (None, None)."""
        t = start
        while t <= end:
            why = server.tick(t)
            if why:
                return why, t
            t += step
        return None, None

    def test_beacon_stops_after_the_grace(self):
        server = self.server()
        server.heartbeat("a", now=5.0)
        server.page_closed("a", now=20.0)
        self.assertIsNone(server.unused(now=29.0))
        self.assertEqual(server.unused(now=30.0), "its last page was closed")

    def test_saved_page_silent_past_the_limit(self):
        server = self.server()
        server.heartbeat("a", now=5.0)
        self.assertIsNone(server.unused(now=5.0 + srv.PAGE_SILENT_S - 1))
        self.assertEqual(server.unused(now=5.0 + srv.PAGE_SILENT_S),
                         "its last page sent no heartbeat for 60 minutes")

    def test_unsaved_page_never_times_out(self):
        server = self.server()
        server.heartbeat("a", unsaved=True, now=5.0)
        self.assertIsNone(server.unused(now=5.0 + 10 * srv.PAGE_SILENT_S))
        server.page_closed("a", now=10 * srv.PAGE_SILENT_S)
        self.assertEqual(server.unused(now=10 * srv.PAGE_SILENT_S + srv.PAGE_CLOSED_S), "its last page was closed")

    def test_page_saved_again_times_out(self):
        server = self.server()
        server.heartbeat("a", unsaved=True, now=5.0)
        server.heartbeat("a", unsaved=False, now=100.0)
        self.assertIsNone(server.unused(now=100.0 + srv.PAGE_SILENT_S - 1))
        self.assertIn("no heartbeat", server.unused(now=100.0 + srv.PAGE_SILENT_S))

    def test_silent_unsaved_page_keeps_it_when_another_page_closes(self):
        server = self.server()
        server.heartbeat("crashed", unsaved=True, now=5.0)
        server.heartbeat("new", now=5000.0)
        server.page_closed("new", now=5001.0)
        self.assertIsNone(server.unused(now=5100.0))

    def test_reason_of_the_page_that_ended_last(self):
        server = self.server()
        server.heartbeat("a", now=5.0)
        server.heartbeat("b", now=10.0)
        server.page_closed("b", now=20.0)
        self.assertIsNone(server.unused(now=40.0))  # a still answers within the limit
        self.assertIn("no heartbeat", server.unused(now=5.0 + srv.PAGE_SILENT_S))

    def test_sleep_does_not_count(self):
        server = self.server()
        server.heartbeat("a", now=5.0)
        self.assertEqual(self.ticks(server, 1.0, 100.0), (None, None))
        # The computer slept for two hours: the next tick comes 7200 s later.
        self.assertIsNone(server.tick(100.0 + 7200))
        self.assertEqual(self.ticks(server, 7301.0, 7300.0 + srv.PAGE_SILENT_S - 200), (None, None))
        why, at = self.ticks(server, 7300.0 + srv.PAGE_SILENT_S - 200, 7300.0 + srv.PAGE_SILENT_S + 200)
        self.assertIn("no heartbeat", why)
        self.assertAlmostEqual(at, 5.0 + srv.PAGE_SILENT_S + 7200 - 1, delta=1.5)

    def test_short_gaps_count(self):
        server = self.server()
        server.heartbeat("a", now=5.0)
        server.tick(10.0)
        self.assertIsNone(server.tick(10.0 + srv.SLEEP_GAP_S))  # a slow tick, not sleep
        self.assertEqual(server.pages["a"]["seen"], 5.0)

    def test_startup_grace_with_a_gap(self):
        server = self.server()
        self.assertEqual(self.ticks(server, 1.0, 100.0), (None, None))
        self.assertIsNone(server.tick(100.0 + 3600))  # slept an hour before any page came
        why, at = self.ticks(server, 3701.0, 3700.0 + srv.STARTUP_GRACE_S)
        self.assertIn("no page was opened within 10 minutes", why)
        self.assertAlmostEqual(at, srv.STARTUP_GRACE_S + 3600 - 1, delta=1.5)

    def test_closed_page_with_a_gap(self):
        server = self.server()
        server.heartbeat("a", now=5.0)
        server.tick(6.0)
        server.page_closed("a", now=6.5)
        self.assertIsNone(server.tick(6.0 + 600))  # slept in the grace: the grace goes on after waking
        self.assertEqual(self.ticks(server, 607.0, 700.0)[0], "its last page was closed")

    def test_second_start_waits_for_its_page(self):
        closed = self.server()
        closed.heartbeat("a", now=5.0)
        closed.page_closed("a", now=6.0)
        self.assertEqual(closed.unused(now=6.0 + srv.PAGE_CLOSED_S), "its last page was closed")
        # The same with a second start after the close: its page is due
        # STARTUP_GRACE_S after it, not the close.
        server = self.server()
        server.heartbeat("a", now=5.0)
        server.page_closed("a", now=6.0)
        server.second_start(None, browser=False, now=8.0)
        self.assertIsNone(server.unused(now=6.0 + srv.PAGE_CLOSED_S))
        self.assertIsNone(server.unused(now=8.0 + srv.STARTUP_GRACE_S - 1))
        self.assertIn("no page was opened", server.unused(now=8.0 + srv.STARTUP_GRACE_S))
        # Its page came: that page keeps it past the grace, until it closes.
        server = self.server()
        server.heartbeat("a", now=5.0)
        server.page_closed("a", now=6.0)
        server.second_start(None, browser=False, now=8.0)
        server.heartbeat("b", now=20.0)
        self.assertIsNone(server.unused(now=8.0 + srv.STARTUP_GRACE_S))
        server.page_closed("b", now=700.0)
        self.assertIsNone(server.unused(now=700.0 + srv.PAGE_CLOSED_S - 1))
        self.assertEqual(server.unused(now=700.0 + srv.PAGE_CLOSED_S), "its last page was closed")

    def test_second_start_at_the_same_clock_time_as_a_page(self):
        # A coarse monotonic clock (Windows: 15.6 ms steps) gives a page's
        # first heartbeat, its close and a second start one time: that page is
        # still not the second start's.
        server = self.server()
        server.heartbeat("a", now=5.0)
        server.page_closed("a", now=5.0)
        server.second_start(None, browser=False, now=5.0)
        self.assertIsNone(server.unused(now=5.0 + srv.PAGE_CLOSED_S))
        self.assertIn("no page was opened", server.unused(now=5.0 + srv.STARTUP_GRACE_S))
        # A page that came at the second start's time is its page.
        server = self.server()
        server.second_start(None, browser=False, now=5.0)
        server.heartbeat("b", now=5.0)
        self.assertIsNone(server.unused(now=5.0 + srv.STARTUP_GRACE_S))

    def test_second_start_does_not_wait_for_a_silent_unsaved_page(self):
        server = self.server()
        now = time.monotonic()
        server.heartbeat("editing", unsaved=True, now=now - srv.PAGE_ANSWERING_S - 1)
        server.second_start(self.project, browser=False)
        self.assertIsNone(server.open_request)
        self.assertEqual(server.session.folder, self.project)  # opened at once
        self.assertIsNone(server.unused())  # and the silent unsaved page still keeps it

    def test_answering_unsaved_page_is_asked_first(self):
        server = self.server()
        server.heartbeat("editing", unsaved=True)
        server.second_start(self.project, browser=False)
        self.assertEqual(server.open_request["path"], self.project)

    def test_keep_running(self):
        server = self.server()
        server.stop_unused = False
        server.heartbeat("a", now=5.0)
        self.assertIsNone(server.tick(5.0 + 10 * srv.PAGE_SILENT_S))
        server.page_closed("a", now=10 * srv.PAGE_SILENT_S)
        self.assertIsNone(server.tick(20 * srv.PAGE_SILENT_S))


class Cookie(Base):
    def test_two_configurators_in_one_browser(self):
        a, b = self.start(publish=False), self.start(publish=False)
        jar = http.cookiejar.CookieJar()
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPCookieProcessor(jar))
        for s in (a, b):
            opener.open(s.url, timeout=10).read()
        for s in (a, b):  # neither logged the other out
            with opener.open("http://127.0.0.1:%d/" % s.server_port, timeout=10) as r:
                self.assertEqual(r.status, 200)
        self.assertEqual(sorted(c.name for c in jar), sorted("%s_%d" % (srv.COOKIE, s.server_port) for s in (a, b)))


class Background(unittest.TestCase):
    def args(self, *argv):
        return srv.parser().parse_args(list(argv))

    def test_foreground_rules(self):
        desktop = {"DISPLAY": ":0"}
        for argv, env, platform, want in (
                ((), desktop, "linux", False),
                ((), {"WAYLAND_DISPLAY": "wayland-0"}, "linux", False),
                ((), {}, "linux", True),  # no display: the printed address is the way in
                ((), {}, "darwin", False),
                ((), {}, "win32", False),
                ((), dict(desktop, SSH_CONNECTION="10.0.0.1 1 10.0.0.2 22"), "linux", True),
                ((), {"SSH_CONNECTION": "x"}, "darwin", True),
                (("--foreground",), {}, "win32", True),
                (("--no-browser",), desktop, "linux", True),
                (("--keep-running",), {}, "darwin", True)):
            self.assertEqual(launch.foreground(self.args(*argv), env, platform), want, (argv, env, platform))

    def test_hidden_child_option(self):
        self.assertNotIn("child-background", srv.parser().format_help())
        self.assertNotIn("from-shortcut", srv.parser().format_help())
        cmd = launch.child_command(["--port", "0", launch.CHILD], executable="/x/python")
        self.assertEqual(cmd, ["/x/python", "-m", "canworks.configurator.start", "--port", "0", launch.CHILD])

    @POSIX
    def test_child_detached(self):
        d = tmpdir(self)
        log = os.path.join(d, "x.log")
        code = ("import os, sys; print(os.getsid(0) == os.getpid(), repr(sys.stdin.read()), os.getppid() != %d, "
                "flush=True)" % -1)
        with mock.patch.object(launch, "child_command", return_value=[sys.executable, "-c", code]):
            p = launch.spawn([], log)
        self.assertEqual(p.wait(10), 0)
        with open(log) as f:
            self.assertEqual(f.read().split()[:2], ["True", "''"])  # its own session, no terminal input

    def test_log_kept_to_its_size(self):
        d = tmpdir(self)
        path = os.path.join(d, "configurator.log")
        log = launch.Log(path, limit=100)
        log.write("a" * 80)
        log.write("b" * 40)
        log.f.close()
        with open(path + ".1") as f:
            self.assertEqual(f.read(), "a" * 80)
        with open(path) as f:
            self.assertEqual(f.read(), "b" * 40)
        launch.rotate(path, limit=10)
        self.assertFalse(os.path.exists(path))

    def background(self, *argv, **kw):
        d = tmpdir(self)
        env = {"CANWORKS_CONFIG_DIR": os.path.join(d, "cfg"), "PYTHONPATH": DEPLOY}
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.dict(os.environ, env), contextlib.redirect_stderr(err), \
                mock.patch("webbrowser.open") as opened, mock.patch.object(launch, "message_window") as window:
            code = launch.background(list(argv), out=out, **kw)
            inst = launch.read_instance()
        return code, out.getvalue(), err.getvalue(), opened, window, inst, d

    def test_failure_prints_the_reason(self):
        d = tmpdir(self)
        f = os.path.join(d, "file")
        open(f, "w").close()
        code, _, err, opened, _, inst, _ = self.background(f)
        self.assertEqual(code, 2)
        self.assertIn("did not start", err)
        self.assertIn("is not a folder", err)
        opened.assert_not_called()
        self.assertIsNone(inst)

    def test_started_without_a_browser(self):
        code, out, _, opened, window, inst, d = self.background()
        try:
            self.assertEqual(code, 0)
            url = opened.call_args[0][0]
            self.assertIn("canworks configurator: %s" % url, out)  # printed at once, no wait for the page
            window.assert_not_called()
            self.assertTrue(launch.pid_alive(inst["pid"]))
            self.assertNotEqual(inst["pid"], os.getpid())
            with open(os.path.join(d, "cfg", launch.LOG)) as f:
                self.assertIn("canworks configurator started on 127.0.0.1:%d" % inst["port"], f.read())
        finally:
            if inst:
                post(inst["port"], "/api/instance/start", {})  # still answers
                os.kill(inst["pid"], signal.SIGTERM)


class Timing(unittest.TestCase):
    """The start timing line (skip-reinstall-faster-start)."""

    def test_line(self):
        t = launch.StartTiming(100.0)
        t.marks["python"] = 100.14
        t.mark("listening", 100.42)
        t.mark("listening", 101.0)  # the first time counts
        t.mark("page", 101.31)
        self.assertEqual(t.line("shortcut"), "start timing: python 140 ms, listening 420 ms, page 1310 ms (from shortcut)")

    def test_carried_to_the_background_configurator(self):
        t = launch.StartTiming(100.0)
        t.marks["python"] = 100.25
        with mock.patch.dict(os.environ, {launch.T0_ENV: t.env()}):
            child = launch.StartTiming.here(now=100.9)
            self.assertNotIn(launch.T0_ENV, os.environ)  # not passed on further
        self.assertEqual(child.line("terminal"), "start timing: python 250 ms, background 900 ms (from terminal)")

    def test_process_start_known(self):
        started = launch.process_started()
        if started is not None:
            self.assertLess(abs(time.time() - started), 3600)

    def test_terminal_start_logs_its_timing(self):
        code, _, _, opened, _, inst, d = Background.background(self, timing=launch.StartTiming.here())
        try:
            self.assertEqual(code, 0)
            url = opened.call_args[0][0]
            urllib.request.build_opener(urllib.request.HTTPCookieProcessor()).open(url, timeout=10).read()
            log = os.path.join(d, "cfg", launch.LOG)
            deadline = time.monotonic() + 10
            text = ""
            while "start timing" not in text and time.monotonic() < deadline:
                with open(log) as f:
                    text = f.read()
                time.sleep(0.05)
            line = [l for l in text.splitlines() if l.startswith("start timing:")]
            self.assertEqual(len(line), 1, text)
            for step in ("python", "background", "listening", "browser asked", "page"):
                self.assertIn(step + " ", line[0])
            self.assertTrue(line[0].endswith("(from terminal)"), line[0])
        finally:
            if inst:
                os.kill(inst["pid"], signal.SIGTERM)


@POSIX
class FromShortcut(unittest.TestCase):
    """The app shortcut's process is the configurator itself."""

    def test_serves_in_the_shortcut_process(self):
        d = tmpdir(self)
        browser = os.path.join(d, "browser")
        with open(browser, "w") as f:  # a stand-in browser that loads the page
            f.write("#!/bin/sh\n%s -c \"import sys, urllib.request; urllib.request.urlopen(sys.argv[1], timeout=10)\" "
                    "\"$1\" &\n" % sys.executable)
        os.chmod(browser, 0o755)
        env = dict(os.environ, CANWORKS_CONFIG_DIR=os.path.join(d, "cfg"), PYTHONPATH=DEPLOY, BROWSER=browser,
                   DISPLAY=":0")
        p = subprocess.Popen([sys.executable, "-m", "canworks.configurator.start", "--from-shortcut"], env=env,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            path = os.path.join(d, "cfg", launch.INSTANCE)
            log = os.path.join(d, "cfg", launch.LOG)
            deadline = time.monotonic() + 20
            text = ""
            while "start timing" not in text and time.monotonic() < deadline:
                try:
                    with open(log) as f:
                        text = f.read()
                except OSError:
                    pass
                time.sleep(0.05)
            with mock.patch.dict(os.environ, {"CANWORKS_CONFIG_DIR": os.path.join(d, "cfg")}):
                inst = launch.read_instance(path)
            self.assertEqual(inst["pid"], p.pid)  # no second Python
            self.assertIn("from the app shortcut", text)
            self.assertRegex(text, r"start timing: python \d+ ms, listening \d+ ms, browser asked \d+ ms, "
                                   r"page \d+ ms \(from shortcut\)")
            # A second click: a tab of this one, and that process exits.
            q = subprocess.run([sys.executable, "-m", "canworks.configurator.start", "--from-shortcut"], env=env,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=30)
            self.assertEqual(q.returncode, 0, q.stdout)
            self.assertIsNone(p.poll())
        finally:
            p.kill()  # on macOS a shortcut start lets SIGTERM go by for its first seconds (APP_TEARDOWN_S)
            p.wait(10)


class MessageWindow(unittest.TestCase):
    def test_per_desktop(self):
        url = "http://127.0.0.1:1/?code=x"
        calls = []
        run = calls.append
        self.assertEqual(launch.message_window(url, run, "darwin"), "osascript")
        self.assertIn('default answer "%s"' % url, calls[-1][2])
        with mock.patch.object(launch, "_which", side_effect=lambda n: n == "zenity"):
            self.assertEqual(launch.message_window(url, run, "linux"), "zenity")
        self.assertEqual(calls[-1][-1], url)
        with mock.patch.object(launch, "_which", side_effect=lambda n: n == "notify-send"):
            self.assertEqual(launch.message_window(url, run, "linux"), "notify-send")
        with mock.patch.object(launch, "_which", return_value=None):
            self.assertIsNone(launch.message_window(url, run, "linux"))


if __name__ == "__main__":
    unittest.main()
