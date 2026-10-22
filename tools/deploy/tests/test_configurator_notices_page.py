"""Message bars in a real browser (consistent-message-bars): every bar has
one look per kind, sits at the top of what it is about (under the view's,
section's or dialog's heading, before the first control), and no view
keeps a retired message style. Walks the ping-pong project online and the
virtual-plant example in Light and Dark. Needs Playwright, like
test_configurator_page.py."""

import os
import shutil

from canworks import diag

from .fake_diag import TOKEN, FakePlugin
from .helpers import REPO, node_tab, tree_entry, tree_node, tree_view, header_action
from .test_configurator_layout import open_tree, pick_theme
from .test_configurator_online_page import OnlineBase

# Bars outside a slot or a page bar: everything before them in their box is
# a heading, a view-head row, another bar or a slot. Retired styles are gone,
# and section text is no longer a red or amber field message.
PLACEMENT = r"""() => {
  const out = [];
  const shown = (e) => e.getClientRects().length > 0;
  const name = (e) => (e.tagName.toLowerCase() + (e.id ? "#" + e.id : "") + (e.className && typeof e.className === "string" ? "." + e.className.trim().split(/\s+/).join(".") : "")
    + " " + (e.textContent || "").trim().slice(0, 50));
  for (const e of document.querySelectorAll(".online-note, .online-conn, .fx-note, .machine-notice, .machine-nodata, .j1939-dm-result, .ws-note"))
    out.push("retired " + name(e));
  for (const e of document.querySelectorAll(".field-msg")) {
    if (!shown(e) || !e.textContent.trim() || e.dataset.for !== undefined) continue;
    if (e.closest("label, td, th, li, .check-field, .field-block, .toolbar, .row, .grid, .od-value, .notice")) continue;
    out.push("section message as field text: " + name(e));
  }
  const head = (s) => !shown(s) || /^(H[1-6]|LEGEND|SUMMARY)$/.test(s.tagName) || s.matches(".view-head, .notice, .notice-slot, #modal-text");
  for (const n of document.querySelectorAll(".notice")) {
    if (!shown(n) || n.closest("#page-bars, #conn-bar, .notice-text, .machine-bars")) continue;
    const box = n.parentElement.matches(".notice-slot") ? n.parentElement : n;
    for (let s = box.previousElementSibling; s; s = s.previousElementSibling) {
      if (!head(s)) { out.push("not at the top: " + name(n) + " after " + name(s)); break; }
    }
  }
  return out;
}"""

# Each kind's accent and tint are its state tokens.
KINDS = r"""() => {
  const probe = document.createElement("div");
  document.body.append(probe);
  const token = (v, prop) => { probe.style.setProperty(prop, `var(${v})`); const c = getComputedStyle(probe).getPropertyValue(prop); probe.style.removeProperty(prop); return c; };
  const out = {};
  for (const kind of ["info", "done", "warning", "error"]) {
    const n = notice(kind, "x");
    probe.append(n);
    const st = getComputedStyle(n);
    out[kind] = { accent: st.borderLeftColor, background: st.backgroundColor, role: n.getAttribute("role"), icon: !!n.querySelector("svg") };
    n.remove();
  }
  out.tokens = { muted: token("--muted", "color"), ok: token("--st-ok", "color"), warn: token("--st-warn", "color"), error: token("--st-error", "color"),
    hover: token("--hover", "background-color"), warnBg: token("--st-warn-bg", "background-color"), errorBg: token("--st-error-bg", "background-color") };
  probe.remove();
  return out;
}"""


class MessageBars(OnlineBase):
    def placed(self, where):
        self.page.wait_for_timeout(150)
        self.assertEqual(self.page.evaluate(PLACEMENT), [], where)

    def kinds(self, where):
        k = self.page.evaluate(KINDS)
        t = k["tokens"]
        self.assertEqual([k[x]["accent"] for x in ("info", "done", "warning", "error")], [t["muted"], t["ok"], t["warn"], t["error"]], where)
        self.assertEqual([k[x]["background"] for x in ("info", "done", "warning", "error")], [t["hover"], t["hover"], t["warnBg"], t["errorBg"]], where)
        self.assertEqual([k[x]["role"] for x in ("info", "done", "warning", "error")], ["status", "status", "status", "alert"], where)
        self.assertTrue(all(k[x]["icon"] for x in ("info", "done", "warning", "error")), where)

    def test_pingpong_online(self):
        pg = self.page
        pg.set_viewport_size({"width": 1280, "height": 800})
        with FakePlugin(allow_changes=True) as fp:
            self.online(fp, allow=True)
            pg.wait_for_selector("text=changes allowed")
            for theme in ("light", "dark"):
                if theme == "dark":  # a fresh page: the node list as at the start
                    header_action(pg, "#btn-close")
                    pg.wait_for_selector("#start:not([hidden])")
                    self.open()
                    pg.click('button[data-view="online"]')
                pick_theme(pg, theme)
                self.kinds(theme)
                pg.wait_for_selector("text=changes allowed")
                self.placed("nodes, %s" % theme)
                pg.wait_for_selector('tr[data-online-node="2"], button[data-online="write"]')
                if not pg.locator('button[data-online="write"]').count():  # the node page stays open
                    pg.click('tr[data-online-node="2"]')
                pg.wait_for_selector('button[data-online="write"]')
                for tab in pg.eval_on_selector_all("[data-online-tab]", "bs => bs.map((b) => b.dataset.onlineTab)"):
                    pg.click('[data-online-tab="%s"]' % tab)
                    self.placed("node 2, %s, %s" % (tab, theme))
                for view in ("trace", "framelab", "simulation"):
                    pg.click('button[data-view="%s"]' % view)
                    self.placed("%s, %s" % (view, theme))
                pg.click('#ws [data-ws="configure"]')
                open_tree(pg)
                for view in ("bus", "access"):
                    tree_view(pg, view)
                    self.placed("%s, %s" % (view, theme))
                tree_node(pg, 0)
                for tab in pg.eval_on_selector_all(".node-tabs [data-node-tab]", "bs => bs.map((b) => b.dataset.nodeTab)"):
                    node_tab(pg, tab)
                    self.placed("node 0, %s, %s" % (tab, theme))
            # The check finds a bar under a control.
            pg.evaluate("() => document.querySelector('#view fieldset, #view .grid, #view').append(notice('info', 'late'))")
            self.assertIn("not at the top", " ".join(pg.evaluate(PLACEMENT)))

    def test_connect_error_in_the_dialog(self):
        pg = self.page
        self.write_config({"token_verifier": diag.token_verifier(TOKEN)})
        self.open()
        pg.click('#ws [data-ws="commission"]')
        pg.click('#conn-bar [data-conn="connect"]')
        pg.wait_for_selector('#conn-dialog[open] [data-online="connect"]')
        pg.fill('#conn-dialog input[data-online="host"]', "")
        pg.click('#conn-dialog [data-online="connect"]')
        bar = '#conn-dialog [data-online="connect-msg"]'
        pg.wait_for_selector(bar + ":has-text('Enter the runtime')")
        self.assertEqual(pg.get_attribute(bar, "role"), "alert")
        self.assertEqual(pg.get_attribute(bar, "data-notice"), "error")
        self.placed("connect dialog")

    def test_virtual_plant(self):
        pg = self.page
        pg.set_viewport_size({"width": 1280, "height": 800})
        folder = os.path.join(self.dir, "virtual-plant")
        shutil.copytree(os.path.join(REPO, "examples", "virtual-plant"), folder)
        pg.goto(self.server.url)
        pg.click("#start-open")
        pg.fill("[data-folder=path]", folder)
        pg.click("[data-folder=dialog] [data-value=use]")
        pg.wait_for_selector("#editor:not([hidden])")
        pg.wait_for_function("() => document.body.dataset.checking === '0'")
        for theme in ("dark", "light"):
            pick_theme(pg, theme)
            nets = pg.eval_on_selector_all("#tree li.net", "es => es.map((e) => e.dataset.key)")
            for k in nets:
                open_tree(pg)
                tree_entry(pg, k)
                for view in pg.eval_on_selector_all("#tree .open-net [data-view]", "es => es.map((e) => e.dataset.view)"):
                    tree_view(pg, view)
                    self.placed("network %s, %s, %s" % (k, view, theme))
                for i in pg.eval_on_selector_all("#tree .open-net [data-node]", "es => es.map((e) => Number(e.dataset.node))"):
                    tree_node(pg, i)
                    self.placed("network %s, node %d, %s" % (k, i, theme))
            for view in ("gateway", "bridge"):
                if pg.locator('#tree > [data-view="%s"]' % view).count():
                    tree_view(pg, view)
                    self.placed("%s, %s" % (view, theme))
            pg.click('#ws [data-ws="commission"]')
            pg.click('button[data-view="online"]')
            self.placed("commission nodes, %s" % theme)
            pg.click('button[data-view="simulation"]')
            pg.wait_for_selector("#sim-body")
            self.placed("simulation, %s" % theme)
            pg.click('#ws [data-ws="configure"]')
