## Context

The configurator page is plain JavaScript with no build step. `style.css` has one token set for both themes: `--bg`, `--panel`, `--text`, `--muted`, `--line`, `--accent`, `--error`/`--error-bg`, `--warn`/`--warn-bg`, `--ok`, `--hover`, plus the frame inspector's field tints (`--fx-*`). State is drawn in many separate ways:
- `td.state-5`, `td.state-0` and `td.state-4` colour NMT state text;
- `.tag.sim-tag` and `#sim-banner` use the warning colours for "simulated";
- `.ok-text`, `.online-note.warning`, the round trip colours and `tr.changed` each pick a colour;
- `trace.js` and `explain.js` hold a few hex colours of their own.

The four earlier overhaul changes add the places where state now lives: the connection bar and status bar (`ui-shell-and-connection`), the network tree with problem badges (`network-tree-and-node-tabs`), the Nodes table and node Status tab (`commission-workspace`) and the trace workspace's identifier view (`trace-workspace`). This change gives all of them one visual language and tests the result as whole tasks.

The browser tests already run axe-core 4.10.2 (vendored) and a layout fit check at 1000, 1280 and 1440 px in both themes (`Layout.fits()`), and one keyboard walk over the config pages (`test_configurator_e2e_page.py`).

## Goals / Non-Goals

**Goals:**
- A state reads the same everywhere: same colour, same shape, same word.
- A healthy network looks calm, so a fault stands out (ISA-101 "grey is normal").
- Colour is never the only cue.
- Tables of IDs and values can be scanned down a column.
- One vocabulary across labels, tooltips and messages, kept by a test.
- The main jobs are proven to work with the keyboard alone in both themes.

**Non-Goals:**
- New views, moved controls or new features. Placement is settled by the earlier four changes.
- A theme editor, a density setting or user-picked colours.
- The frame inspector's field tints and the trace graph's series colours. They tell fields and series apart (categorical), not states, and keep their own tokens.
- Translation. The word list is English only.
- Icons for actions (toolbar buttons). Buttons keep text labels.

## Decisions

### 1. State tokens: four colours and "off"
New tokens, defined for Light and Dark (and for Auto through the existing media query):

| Token | Meaning | Used for |
|---|---|---|
| `--st-ok` | running as intended | OPERATIONAL, bit rate confirmed, scan match, link up |
| `--st-busy` | waiting or in progress | PRE-OPERATIONAL, initialising, connecting, a running job, booting |
| `--st-warn` | needs a look | STOPPED, a warning problem, slow round trip, error passive, identity differs, simulated-only notes |
| `--st-error` | broken | error problems, missing node, bus-off, connection ended, EMCY pending |
| `--st-off` | no information | unknown, not connected, absent, cleared |

Each has a `-bg` variant for row and banner tints, used only for `warn` and `error`.

- Existing `--ok`, `--warn` and `--error` become aliases of the new tokens while the views move over, then are removed.
- `--accent` stays for focus rings, links, the primary button and the selected tab only, and is never a state.
- "Simulated" stops using the warning colours. It is a mark (decision 2), not a state.

*Why four colours and not one per NMT state:* STOPPED and a warning problem both mean "look here", and with five or six hues amber, orange and yellow sit too close to tell apart in both themes. The icon's shape tells STOPPED from a warning. *Alternative:* the research's five colours (error, warning, stopped, pre-operational, operational). Rejected for that reason, with the same intent kept.

Contrast: every `--st-*` token reaches 4.5:1 against `--panel` and `--bg`, and against its own `-bg` tint, in both themes. Icons, which are non-text graphics, reach at least 3:1. A unit test computes the ratios from `style.css`, so a token edit that breaks them fails without a browser.

### 2. Grey is normal
- Text in tables and lists stays `--text` whatever the state. The state shows as an icon in its own column or before the name, plus the state word.
- Only `warn` and `error` tint a row or banner background.
- OPERATIONAL shows a green icon and neutral text, so a healthy network is grey with small green dots.
- Problem counts on the tree and tabs are a badge with the icon and number, coloured by the worst problem's level.

### 3. State icons
One inline SVG sprite in `index.html` (`<symbol>`s at 16 px with a 1.5 px stroke, drawn with `currentColor`), and `icons.js` with `stateIcon(state, {label})`, which returns `<svg class="st st-<state>">`.

| State | Shape | Token |
|---|---|---|
| Operational | filled circle | ok |
| Pre-operational | half-filled circle | busy |
| Initialising, connecting, job running | ring with a gap (static; turns only without `prefers-reduced-motion`) | busy |
| Stopped | filled square | warn |
| Warning | triangle with "!" | warn |
| Error, missing, bus-off, ended | circle with a cross | error |
| Unknown, absent, not connected | hollow circle | off |
| Diagnosis flag | small flag after the icon, red while an EMCY or problem is pending, grey once cleared (CODESYS pattern) | error / off |
| Simulated | dashed outline around the state icon | (no colour of its own) |

Rules:
- When the state word is shown next to the icon, the icon is `aria-hidden="true"`.
- When the icon stands alone (tree, compact columns), it has `role="img"` and an `aria-label` with the state word ("Operational", "Pre-operational, simulated"), plus a `title` tooltip.
- In `forced-colors: active`, icons switch to `CanvasText` and keep their shapes; the triangle and cross keep their inner marks.

*Why the half circle, not the triangle, for pre-operational:* the research suggested a triangle (as CODESYS does), but the page also needs a warning shape, and a triangle means "warning" almost everywhere else. One meaning per shape wins.

### 4. Density and numbers
- Spacing scale tokens `--sp-1` to `--sp-5` (4, 8, 12, 16, 24 px) replace ad hoc margins and padding in `style.css`.
- Data tables (class `table.data`) have 28 px rows (32 px where a row holds a button or field), 4 px vertical padding, header cells in `--muted`, and `position: sticky` header rows inside their scroll box.
- Number columns are right-aligned with `font-variant-numeric: tabular-nums`.
- `--mono` (the system monospace stack) is used for COB-IDs and CAN IDs, `index:sub`, data bytes, hex values and PLC locations, through a `.mono` class that `fmt` helpers add. Hex is written `0x` with upper-case digits (`0x6150:1`, `0x181`); node IDs are decimal.
- Forms keep 24 px controls, as the 24 px target rule requires. Form density does not change.

Tables in scope: the Nodes table, PDO entries, startup SDO writes, SDO variables, object dictionary, watch list, trace (both views), transmit list, PDO links, gateway routes, bridge register map, CAN messages and signals, J1939 signals, scan result, EMCY history.

### 5. Word list and its test
`docs/wording.md` holds:
- **Terms:** preferred term, words it replaces, notes. Examples: bit rate (not bitrate, baud, baudrate); node ID (not Node-ID, node id, NodeID); COB-ID; EDS; runtime; USB adapter; Allow changes; Read all; Commission; Configure.
- **Style:** sentence case for labels, headings and buttons. Buttons start with a verb. "…" for buttons that open a dialog or need more input. Units after a space ("500 kbit/s", "100 ms", "1.5 s"). No "please", no "Error:" or "Warning:" prefixes (the icon says it), no exclamation marks. Messages say what happened, then what to do, in one or two sentences. Empty states say what the area is for and give the action that fills it.

A machine-readable `tests/data/wording.json` (preferred term plus ruled-out patterns, with an allow list for EDS texts and quoted standards) drives `test_configurator_wording.py`. It reads the string literals in `static/*.js`, the text of `index.html` and the user-facing message strings in `configurator/*.py` (those passed to the error helpers), and fails naming the file, line and preferred term. EDS and DBC content shown on the page is data and is not checked.

Existing page tests that assert on old texts are updated in the same task as the text.

### 6. Disabled controls say why
- A helper `disable(el, reason)` sets `disabled`, `title` and an `aria-describedby` hint, and `enable(el)` clears them. Every place that disables a control uses it.
- Busy states ("Saving…") count as their own reason.
- `Layout.fits()` gains a check: every disabled `button`, `input`, `select` or `[role=tab]` in the view has a non-empty `title` or an accessible description. The failure names the view and the control.

### 7. Legend
The settings menu (added by `ui-shell-and-connection`) gets **Colours and icons**, a small non-modal popover that lists every state icon with its word and one line on when it shows. It is rendered from the same `icons.js` table, so it cannot drift from the icons. `docs/configurator.md` shows the same table, with screenshots in both themes.

### 8. Task tests, keyboard only
New `tests/test_configurator_tasks_page.py`:

| Task | Steps |
|---|---|
| Connect | Commission a device → connect panel → virtual adapter → 500 kbit/s → Connect; the bar shows the confirmed rate |
| Scan | start a scan from the Nodes table; the found simulated nodes appear with state icons; cancel a second scan from the status bar |
| Add to config | with the virtual example open in Commission on the local simulator runtime, scan compares; add the found node that is not in the config; it appears in the Configure tree |
| Map a PDO | Configure → node → PDOs tab → Add entry… → pick an object → location suggested → Save; Save reads "Saved" |
| Record a trace | Trace tab → Start → frames arrive in By identifier → Stop → Save recording |

How they run:
- A `KeyboardOnly` page wrapper exposes `press`, `type` and `expect_focus`, and raises if the test calls `click`, `hover`, `mouse` or `tap`, so a pointer step cannot slip in.
- Each task runs in Light and in Dark (pytest parameter).
- After each step: axe-core (critical and serious fail), a visible-focus check (the focused element has an outline of at least 2 px in a colour reaching 3:1 against its neighbours), and no clipped text in the view.
- On failure, a screenshot per step is saved under the test output folder for CI to upload.
- One extra test opens the tree and the Nodes table with `forced_colors="active"` and checks that every state icon has a non-zero painted area and its accessible name.

The tasks use the existing fakes: the virtual adapter, the fake plugin runtime and the local simulator runtime, which keeps them hardware-free.

**CI time:** these run in the existing configurator-page shard and only when files under the configurator or its tests change (the existing `ui` path filter). One server and one browser context per task, with the theme switched through the settings route between runs, keep the ten runs to a target of about 60 s in total. The word-list and contrast tests are plain unit tests (no browser).

### 9. Order of work
Tokens and icons first, then each view moves to them one by one (aliases keep the rest working), then density, then the wording pass, then the tests that lock it in. The task tests need the earlier four changes merged, so this change is applied last.

## Risks / Trade-offs

- **[Parallel changes add new colours or texts while this one is open]** → The word-list test and the "no raw state colour" check (a test that fails on `--ok`, `--warn`, `--error` or a hex colour in a state class once the aliases are removed) catch late additions. This change is applied after the other four have merged.
- **[Many page tests assert on texts that change]** → Each wording task updates the tests it breaks, and the word list stays small (terms that actually vary today), not a full style guide.
- **[Denser tables cramp fields in rows]** → Rows with a field or button stay 32 px, and the 24 px target check stays in force.
- **[Grey-is-normal hides a healthy-but-wrong state]** → Every state still has its icon and word. Only the text colour is neutral.
- **[Keyboard-only tests are slow or flaky]** → They wait on page state (focus, live region text), never on fixed delays, reuse one server per task, and run only on UI changes.
- **[MODIFIED "Accessibility check in the browser tests" clashes with another change]** → None of the other four overhaul changes modify it, as proposed. If one does by apply time, the delta is merged by hand before archiving.

## Migration Plan

UI only, with nothing stored to migrate:
- `ui.json`, `online.json` and the config files are unchanged.
- Rollback is the previous tools version.

## Open Questions

None. The defaults picked here can change in review:
- four state colours plus "off", rather than one per NMT state;
- the half circle for pre-operational;
- no density setting;
- the legend in the settings menu.
