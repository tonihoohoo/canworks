"""Only what the target uses, on every page (spec canopen-configurator "Only
what the target uses is shown", "Show fields the target does not use"): the
Modbus bridge example opened as each of the three targets, with settings the
target does not use left in, and every page and node tab walked. No field
the target does not use is shown, no text speaks of another target, and no
node tab is blank; with Show fields the target does not use on, they are
all back. Needs Playwright, like test_configurator_page.py."""

import json
import os
import re
import shutil

from canworks.configurator import server as srv

from .helpers import REPO, node_tab, tree_node
from .test_configurator_online_page import OnlineBase
from .test_configurator_page import load

EXAMPLE = os.path.join(REPO, "examples", "modbus-bridge")

# Words of another target, per target. The Project target field's help and
# the list of settings the target does not use are left out of the check.
FOREIGN = {
    "openplc": re.compile(r"Modbus|CODESYS"),
    "bridge": re.compile(r"the plugin|\bPlugin\b|the Pi\b|PLC scan|PLC location|PLC is stopped|OpenPLC"),
    "codesys": re.compile(r"\bplugin\b|the Pi\b|PLC location|PLC scan|%[IQ][XBWDL]?\d|[Ss]can watchdog|OpenPLC"),
}

# The page's visible fields that the target does not use, and its visible
# text outside the target field and the bar.
SWEEP = """() => {
  const vis = (e) => !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length) && !e.closest('[hidden]');
  const fields = [...document.querySelectorAll('#view input[data-path], #view select[data-path], #view textarea[data-path]')]
    .filter(vis).map((x) => x.dataset.path);
  const view = document.querySelector('#view').cloneNode(true);
  for (const x of view.querySelectorAll('[data-project-target], [data-unused-bar], [hidden], option, select')) x.remove();
  return { unused: fields.filter((p) => unusedWhy(p) !== null), fields: fields.length, text: view.innerText };
}"""


class TargetView(OnlineBase):
    def setUp(self):
        super().setUp()
        for name in ("rtd8.eds", "dio16.eds"):
            shutil.copy(os.path.join(EXAMPLE, name), os.path.join(self.project, "canworks"))

    def use(self, target):
        cfg = load(os.path.join(EXAMPLE, "canworks.json"))
        if target != "bridge":
            del cfg["bridge"]
            cfg = srv.Session().pack_openplc(cfg)["config"]
        net = cfg["networks"][0]
        net["master"]["scan_watchdog_ms"] = 500
        net["master"]["on_plc_stop"] = "keep"
        if target == "codesys":
            cfg["codesys"] = {}
            # A node with the EDS's own supervision (Method "EDS default").
            for k in ("heartbeat_ms", "heartbeat_timeout_ms", "guard_time_ms", "life_time_factor"):
                net["nodes"][1].pop(k, None)
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)

    def pages(self):
        """(name, open) for every page of the tree and every node tab."""
        pg = self.page
        out = [("bus", lambda: pg.evaluate("() => showView('bus')"))]
        for v in ("access", "gateway", "raw", "links", "bridge", "codesys", "declarations"):
            if pg.locator('#tree [data-view="%s"]' % v).count():
                out.append((v, lambda v=v: pg.evaluate("v => showView(v)", v)))
        for i, tabs in enumerate(pg.evaluate("() => S.config.nodes.map((_, i) => nodeTabs(i).map((t) => t[0]))")):
            for t in tabs:
                out.append(("node %d %s" % (i, t), lambda i=i, t=t: (tree_node(pg, i), node_tab(pg, t))))
        return out

    def sweep(self, target):
        pg = self.page
        found, wrong = {}, []
        for name, show in self.pages():
            show()
            pg.wait_for_timeout(50)
            r = pg.evaluate(SWEEP)
            found[name] = r
            if r["unused"]:
                wrong.append("%s: shows %s" % (name, ", ".join(r["unused"])))
            for m in FOREIGN[target].finditer(r["text"]):
                wrong.append("%s: %r in ...%s..." % (name, m.group(0), r["text"][max(0, m.start() - 60):m.end() + 60]))
            if name.startswith("node ") and not pg.inner_text("#node-panel").strip():
                wrong.append("%s is blank" % name)
        self.assertEqual(wrong, [], target + ":\n" + "\n".join(wrong))
        return found

    def check(self, target):
        pg = self.page
        self.use(target)
        self.open()
        pg.wait_for_function("() => document.body.dataset.checking === '0'")
        self.assertEqual(pg.evaluate("() => projectTarget()"), target)
        hidden = self.sweep(target)
        # Every field is back with Show fields the target does not use.
        pg.evaluate("() => setShowAll(true)")
        more = 0
        for name, show in self.pages():
            show()
            r = pg.evaluate(SWEEP)
            more += r["fields"] - hidden.get(name, {"fields": 0})["fields"]
        if target != "openplc":
            self.assertGreater(more, 0)
        pg.evaluate("() => setShowAll(false)")
        pg.wait_for_function("async () => (await (await fetch('/api/ui')).json()).show_all_fields === 'off'")

    def test_openplc(self):
        self.check("openplc")

    def test_bridge(self):
        self.check("bridge")

    def test_codesys(self):
        self.check("codesys")
        # The EDS-default node keeps its Supervision tab's Method choice.
        pg = self.page
        tree_node(self.page, 1, "supervision")
        self.assertTrue(pg.is_visible('#node-panel select[data-supervision]'))

    def test_messages_without_a_windows_path(self):
        # Readable problem messages: a config path with a drive letter goes too.
        pg = self.page
        self.use("openplc")
        self.open()
        for lead in ("C:\\Users\\me\\cell\\canworks\\canworks.json: ", "/home/me/cell/canworks/canworks.json: ",
                     "C:\\Claude workspace\\cell\\canworks.json: "):
            m = lead + "networks[0].nodes[0].tx_pdos[0].entries[1].iec_location: 'iec_location' is not used by CODESYS: why"
            self.assertEqual(pg.evaluate("m => readable(m)", m), "'iec_location' is not used by CODESYS: why")
            self.assertNotIn("canworks.json", pg.evaluate("m => humanise(m)", m))
