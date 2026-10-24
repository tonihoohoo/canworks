// The bridge's Modbus requests in the Trace view (canopen-configurator
// "Modbus requests in the Trace view"; add-modbus-traffic-view;
// docs/modbus-bridge.md "Seeing the Modbus traffic"): the Capture… choice,
// the rows between the CAN frames, their inspector and By request.

const TM = { seqs: new Set(), generation: null, on: true, changesOnly: true, client: "", tableAt: 0, tableSeq: 0 };

// Why Modbus requests cannot be recorded now, or "".
function traceModbusWhy() {
  if (!(S.model && S.model.top && S.model.top.bridge)) return "Modbus requests are recorded by canworks-bridge; this project is not a bridge project.";
  if (S.state && S.state.commission) return "Commissioning records the CAN bus only.";
  if (connAdapter()) return "A USB adapter or an adapter server sees the CAN bus only: connect to the runtime that runs canworks-bridge to record Modbus requests.";
  return "";
}

function traceModbusBody() {
  if (!TM.on || traceModbusWhy()) return undefined;
  return { on: true, changes_only: TM.changesOnly, client: TM.client || undefined };
}

// The Modbus part of Capture….
function traceModbusCapture() {
  const why = traceModbusWhy();
  const on = el("input", { type: "checkbox", checked: TM.on && !why, disabled: !!why, dataset: { trace: "modbus-on" } });
  const only = el("input", { type: "checkbox", checked: TM.changesOnly, disabled: !!why || !TM.on, dataset: { trace: "modbus-changes" } });
  const conns = typeof connectionsOf === "function" && !why ? connectionsOf().filter((c) => typeof c.address === "string" && c.address) : [];
  const client = el("select", { "aria-label": "Modbus client to record", disabled: !!why || !TM.on, dataset: { trace: "modbus-client" } },
    el("option", { value: "" }, "All clients"),
    conns.map((c) => el("option", { value: c.address, selected: TM.client === c.address }, `${c.name || c.address} (${c.address})`)));
  on.onchange = () => { TM.on = on.checked; only.disabled = client.disabled = !on.checked; };
  only.onchange = () => { TM.changesOnly = only.checked; };
  client.onchange = () => { TM.client = client.value; };
  return el("div", { class: "trace-modbus-capture", dataset: { trace: "modbus-capture" } },
    el("label", { class: "check inline" }, on, " Modbus requests (canworks-bridge)"),
    el("label", { class: "check inline", title: "A request whose values and answer equal the previous one of its kind is counted, not recorded" },
      only, " Only changes"),
    client,
    why ? el("p", { class: "hint", dataset: { trace: "modbus-why" } }, why) : null);
}

function traceModbusSeq(seq) { return TM.seqs.has(Number(seq)); }

// The Modbus rows among the rows fetched (and the selected one, while it
// stays in the same trace): their numbers say which inspector a row opens.
function traceModbusRows(r) {
  const keep = r.generation === TM.generation && T.selected != null && TM.seqs.has(T.selected);
  TM.generation = r.generation;
  TM.seqs = new Set(r.rows.filter((x) => x.kind === "modbus").map((x) => x.seq));
  if (keep) TM.seqs.add(T.selected);
}

// A Modbus row of the Chronological list.
function traceModbusRow(x, cls) {
  const m = x.modbus || {};
  const flag = m.exception != null ? "exception" : m.refused ? "refused" : "";
  return el("div", { class: cls + (flag ? " modbus-" + flag : ""), dataset: { seq: x.seq, t: x.t_us, kind: "modbus" }, onclick: () => selectRow(x, true),
    title: (m.hints || []).join("\n") || null },
    el("span", null, timeText(x.t_us)), el("span", null, m.write ? "Wr" : "Rd"),
    el("span", { class: "modbus-tag" }, "Modbus"), el("span", null, m.short || ""),
    el("span", { class: "mono" }, m.range || ""),
    el("span", { title: m.address }, x.name), el("span", { title: x.text }, (m.hints && m.hints.length ? "⚠ " : "") + x.text));
}

function traceUs(us) { return us == null ? "" : `${(us / 1000).toFixed(1)} ms`; }

// The inspector of a Modbus row: the request and answer, the values by
// name, the skipped count, the hints and each changed value's delay with a
// link that selects its CAN frame.
async function traceModbusInspect(seq, box) {
  const my = (box._fxSeq = (box._fxSeq || 0) + 1);
  let m;
  try { m = await api("POST", "/api/trace/modbus/record", { seq }); } catch (e) {
    if (box._fxSeq === my) fxFill(box, el("p", { class: "muted" }, e.message));
    return;
  }
  if (box._fxSeq !== my || !box.isConnected) return;
  const kv = (k, v) => v === "" || v == null ? null : el("tr", null, el("th", null, k), el("td", null, v));
  const delays = (m.delays || []).map((d) => el("li", { dataset: { modbusDelay: d.location } },
    `${d.name}: ${d.text}`,
    d.frame != null ? el("button", { type: "button", class: "link", dataset: { trace: "modbus-to-frame" },
      onclick: () => traceSelectFrame(d.frame) }, "Select the frame") : null));
  const root = el("div", { class: "modbus-insp", dataset: { trace: "modbus-inspector" } },
    el("h3", null, `Modbus ${m.write ? "write" : "read"} from ${m.client}`),
    el("p", { class: "muted" }, secText(m.time_us)),
    m.undecoded ? noteBar("warning", m.undecoded, { trace: "modbus-undecoded" }) : null,
    ...(m.hints || []).map((h) => noteBar("warning", h, { trace: "modbus-hint" })),
    el("table", { class: "compare" }, el("tbody", null,
      kv("Client", m.client !== m.address ? `${m.client} (${m.address}:${m.port})` : `${m.address}:${m.port}`),
      kv("Function", `${m.function} (${m.function_name})`),
      kv("Range", m.range ? `${m.short} ${m.range}` : ""),
      kv("Unit", String(m.unit)), kv("Transaction", String(m.transaction)),
      kv("Result", m.result),
      kv("Skipped before it", m.skipped ? `${m.skipped} unchanged request${m.skipped === 1 ? "" : "s"}` : ""),
      kv("Request PDU", el("span", { class: "mono" }, m.request)),
      kv("Answer PDU", el("span", { class: "mono" }, m.answer)))),
    m.values && m.values.length ? el("div", null, el("h4", null, "Values"),
      el("table", { class: "compare", dataset: { trace: "modbus-values" } },
        el("thead", null, el("tr", null, thCells(["Name", "Location", "Type", "Value"]))),
        el("tbody", null, m.values.map((v) => el("tr", null, el("td", null, v.name), el("td", { class: "mono" }, v.location),
          el("td", null, v.type), el("td", null, v.text)))))) : null,
    delays.length ? el("div", null, el("h4", null, m.write ? "Delay to the bus" : "Delay from the bus"),
      el("ul", { class: "modbus-delays" }, delays)) : null);
  fxFill(box, root);
}

// Selects CAN frame `seq` (absolute) in the Chronological list.
async function traceSelectFrame(seq) {
  let m;
  try { m = await api("POST", "/api/trace/explain", { seq }); } catch (e) { banner(e.message, true); return; }
  if (T.filter.source === "modbus") { T.filter.source = "any"; updateFilterCount(); }
  jumpToFrame(m.t_us, null);
}

// By request: one row per client, function and range.
function traceModbusTableBox() {
  return el("div", { class: "trace-modbus-table", id: "trace-modbus-table", dataset: { trace: "by-request" } });
}

async function traceModbusRefresh(force) {
  const box = $("#trace-modbus-table");
  if (!box) return;
  if (!(T.st && T.st.modbus)) { box.replaceChildren(); return; }
  const now = Date.now();
  if (!force && now - TM.tableAt < 1000) return;
  TM.tableAt = now;
  const my = ++TM.tableSeq;
  let r;
  try { r = await api("POST", "/api/trace/modbus", {}); } catch (e) { box.replaceChildren(el("p", { class: "muted" }, e.message)); return; }
  if (my !== TM.tableSeq || !box.isConnected) return;
  const ms = (v) => v == null ? "" : v.toFixed(1);
  box.replaceChildren(
    el("h3", null, "By request"),
    el("p", { class: "muted" }, `${r.records.toLocaleString()} Modbus records` +
      (r.skipped ? `, ${r.skipped.toLocaleString()} unchanged requests counted, not recorded` : "") + "."),
    r.note ? noteBar("warning", r.note, { trace: "modbus-note" }) : null,
    el("div", { class: "objects" }, el("table", { class: "modbus-requests" },
      el("thead", null, el("tr", null, thCells(["Client", "Function", "Range", "Requests", "Cycle avg ms", "Delay min / avg / max ms",
        "Last values", "Last exception"]))),
      el("tbody", null, r.requests.map((q) => el("tr", { class: q.hints && q.hints.length ? "warn" : "",
        title: (q.hints || []).join("\n") || null, dataset: { modbusRequest: `${q.address} ${q.function} ${q.range}` } },
        el("td", { title: q.address }, q.client), el("td", null, `${q.function} ${q.function_name}`),
        el("td", { class: "mono" }, q.short ? `${q.short} ${q.range}` : q.range), el("td", null, q.count.toLocaleString()),
        el("td", null, ms(q.cycle_avg_ms)),
        el("td", null, q.delay_avg_ms == null ? "" : `${ms(q.delay_min_ms)} / ${ms(q.delay_avg_ms)} / ${ms(q.delay_max_ms)}`),
        el("td", null, (q.values || []).map((v) => `${v.name} = ${v.text}`).join(", ")),
        el("td", null, q.last_exception || "")))))));
}
