// State icons and disabled-control reasons (visual-refresh).
// Each state has its own shape as well as its colour, so colour is never the only cue.
// The sprite is added to the page once; stateIcon() returns an <svg> that uses it.
(function () {
  "use strict";
  const NS = "http://www.w3.org/2000/svg";

  // state key -> [symbol, CSS class, word, when it shows]. The legend is drawn from this table.
  const STATES = {
    operational: ["st-i-circle", "st-operational", "Operational", "The node runs and exchanges PDOs."],
    preop: ["st-i-half", "st-preop", "Pre-operational", "The node answers SDOs but sends no PDOs yet."],
    busy: ["st-i-ring", "st-busy", "In progress", "Connecting, booting or a job is running."],
    stopped: ["st-i-square", "st-stopped", "Stopped", "The node was stopped and only answers NMT and heartbeat."],
    warning: ["st-i-triangle", "st-warning", "Warning", "Something needs a look, but nothing is broken."],
    error: ["st-i-cross", "st-error", "Error", "Missing, bus-off, an ended connection or an error problem."],
    unknown: ["st-i-hollow", "st-unknown", "Unknown", "No information: not connected, not heard or absent."],
  };
  // Aliases used by the views: NMT state codes and words.
  const ALIAS = {
    ok: "operational", "5": "operational", OPERATIONAL: "operational",
    "127": "preop", PRE_OPERATIONAL: "preop", "PRE-OPERATIONAL": "preop", "pre-operational": "preop",
    // The plugin reports 0 for "no contact" (not heard within the heartbeat time).
    "0": "error", "no contact": "error", BOOTUP: "busy", INITIALISING: "busy", connecting: "busy", running: "busy",
    "4": "stopped", STOPPED: "stopped",
    warn: "warning", missing: "error", "bus-off": "error", ended: "error",
    absent: "unknown", off: "unknown", "": "unknown",
  };

  const SPRITE = `
<symbol id="st-i-circle" viewBox="0 0 16 16"><circle cx="8" cy="8" r="6" fill="currentColor"/></symbol>
<symbol id="st-i-half" viewBox="0 0 16 16"><circle cx="8" cy="8" r="5.5" fill="none" stroke="currentColor" stroke-width="1.5"/><path d="M8 2.5a5.5 5.5 0 0 1 0 11z" fill="currentColor"/></symbol>
<symbol id="st-i-ring" viewBox="0 0 16 16"><path d="M8 2.5a5.5 5.5 0 1 1-5.2 3.7" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></symbol>
<symbol id="st-i-square" viewBox="0 0 16 16"><rect x="2.5" y="2.5" width="11" height="11" rx="1" fill="currentColor"/></symbol>
<symbol id="st-i-triangle" viewBox="0 0 16 16"><path d="M8 1.5 15 14H1z" fill="currentColor"/><path d="M8 6v4" stroke="var(--panel, #fff)" stroke-width="1.6" stroke-linecap="round"/><circle cx="8" cy="12" r="0.9" fill="var(--panel, #fff)"/></symbol>
<symbol id="st-i-cross" viewBox="0 0 16 16"><circle cx="8" cy="8" r="6.5" fill="currentColor"/><path d="m5.5 5.5 5 5m0-5-5 5" stroke="var(--panel, #fff)" stroke-width="1.7" stroke-linecap="round"/></symbol>
<symbol id="st-i-hollow" viewBox="0 0 16 16"><circle cx="8" cy="8" r="5.5" fill="none" stroke="currentColor" stroke-width="1.5"/></symbol>
<symbol id="st-i-sim" viewBox="0 0 16 16"><circle cx="8" cy="8" r="7.6" fill="none" stroke="currentColor" stroke-width="0.9" stroke-dasharray="2 1.6"/></symbol>
<symbol id="st-i-flag" viewBox="0 0 10 12"><path d="M1.5 1v10" stroke="currentColor" stroke-width="1.4"/><path d="M2 1.5h6.5L7 4l1.5 2.5H2z" fill="currentColor"/></symbol>`;

  function ensureSprite() {
    if (document.getElementById("st-sprite")) return;
    const svg = document.createElementNS(NS, "svg");
    svg.id = "st-sprite";
    svg.setAttribute("aria-hidden", "true");
    svg.setAttribute("width", "0");
    svg.setAttribute("height", "0");
    svg.style.position = "absolute";
    svg.innerHTML = SPRITE;
    (document.body || document.documentElement).prepend(svg);
  }

  function key(state) {
    const s = state == null ? "" : String(state);
    return STATES[s] ? s : (ALIAS[s] || ALIAS[s.toUpperCase()] || "unknown");
  }

  function word(state) { return STATES[key(state)][2]; }

  function use(svg, id) {
    const u = document.createElementNS(NS, "use");
    u.setAttribute("href", "#" + id);
    svg.appendChild(u);
  }

  // stateIcon(state, {label, simulated, flag, spinning}) -> <svg>.
  // label: true (default) gives the icon its state word as accessible name and tooltip;
  // false hides it from assistive technology (the word is shown next to it).
  function stateIcon(state, opts = {}) {
    ensureSprite();
    const k = key(state);
    const [sym, cls, w] = STATES[k];
    const svg = document.createElementNS(NS, "svg");
    svg.setAttribute("class", `st ${cls}` + (opts.simulated ? " simulated" : "") + (opts.spinning && k === "busy" ? " spinning" : ""));
    svg.setAttribute("viewBox", "0 0 16 16");
    svg.setAttribute("focusable", "false");
    svg.dataset.state = k;
    use(svg, sym);
    const sim = document.createElementNS(NS, "g");
    sim.setAttribute("class", "st-sim");
    use(sim, "st-i-sim");
    svg.appendChild(sim);
    const name = typeof opts.label === "string" ? opts.label : w + (opts.simulated ? ", simulated" : "");
    if (opts.label === false) {
      svg.setAttribute("aria-hidden", "true");
    } else {
      svg.setAttribute("role", "img");
      svg.setAttribute("aria-label", name);
      const t = document.createElementNS(NS, "title");
      t.textContent = name;
      svg.prepend(t);
    }
    if (!opts.flag) return svg;
    const wrap = document.createElement("span");
    wrap.className = "st-with-label";
    wrap.append(svg, diagnosisFlag(opts.flag === "cleared"));
    return wrap;
  }

  // A pending (red) or cleared (grey) diagnosis flag.
  function diagnosisFlag(cleared) {
    ensureSprite();
    const svg = document.createElementNS(NS, "svg");
    svg.setAttribute("class", "st-flag" + (cleared ? " cleared" : ""));
    svg.setAttribute("viewBox", "0 0 10 12");
    svg.setAttribute("role", "img");
    const name = cleared ? "Diagnosis cleared" : "Diagnosis pending";
    svg.setAttribute("aria-label", name);
    const t = document.createElementNS(NS, "title");
    t.textContent = name;
    svg.appendChild(t);
    use(svg, "st-i-flag");
    return svg;
  }

  // Icon followed by its word; the icon is hidden from assistive technology.
  function stateLabel(state, opts = {}) {
    const span = document.createElement("span");
    span.className = "st-with-label";
    const text = opts.text || word(state);
    span.append(stateIcon(state, { ...opts, label: false, flag: null }), document.createTextNode(text));
    if (opts.flag) span.append(diagnosisFlag(opts.flag === "cleared"));
    return span;
  }

  // The legend under the settings menu: every state, the flag and the simulated mark.
  function legend() {
    const dl = document.createElement("dl");
    dl.className = "legend-list";
    const row = (icon, name, text) => {
      const dt = document.createElement("dt");
      dt.append(icon, document.createTextNode(name));
      const dd = document.createElement("dd");
      dd.style.margin = "0";
      dd.textContent = text;
      dl.append(dt, dd);
    };
    for (const k of Object.keys(STATES)) row(stateIcon(k, { label: false }), STATES[k][2], STATES[k][3]);
    const flag = diagnosisFlag(false);
    flag.setAttribute("aria-hidden", "true");
    row(flag, "Diagnosis", "An EMCY or error is pending; grey once it is cleared.");
    row(stateIcon("operational", { label: false, simulated: true }), "Simulated", "A dashed ring: the node is simulated.");
    return dl;
  }

  // Disabled controls say why: the reason is the tooltip and the accessible description.
  function disable(el, reason) {
    if (!el) return el;
    el.disabled = true;
    el.setAttribute("aria-disabled", "true");
    if (reason) {
      if (!el.dataset.titleBefore && el.title && el.title !== reason) el.dataset.titleBefore = el.title;
      el.title = reason;
      el.setAttribute("aria-description", reason);
      el.dataset.disabledReason = reason;
    }
    return el;
  }

  function enable(el) {
    if (!el) return el;
    el.disabled = false;
    el.removeAttribute("aria-disabled");
    if (el.dataset.disabledReason) {
      el.title = el.dataset.titleBefore || "";
      el.removeAttribute("aria-description");
      delete el.dataset.disabledReason;
      delete el.dataset.titleBefore;
    }
    return el;
  }

  // setDisabled(el, reasonOrFalse): disables with the reason when truthy, enables otherwise.
  function setDisabled(el, reason) { return reason ? disable(el, reason) : enable(el); }

  window.Icons = { STATES, key, word, stateIcon, stateLabel, diagnosisFlag, legend, disable, enable, setDisabled };
})();
