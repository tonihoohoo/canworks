## Context

Today the configurator has one real message bar (`#banner`, `banner()` in `app.js`), sticky under the header, with an info look (grey) and an error look (red tint and icon). Every other message is built by hand in its view: `.online-conn`, `.online-note`, `.field-msg`, `.field-msg.warning`, `.fx-note`, `.fx-error`, `.machine-notice`, `.machine-nodata`, `.job-status`, `.j1939-dm-result`, `.ok-text`, `lockedNote()` and plain `p.muted`. Each picks its own colours, role and position. The inventory (2026-10-16) found these placements at the bottom: the Parameters job status, the Error history and NMT locked notes, the J1939 DM result, the restore/configure preview's "no changes" line, the connect panel's error, and the Machine view's "no data". The Commission Nodes view has its connection line after the toolbar while the other views have it at the top.

Screenshots of today: [page bars](images/before-page-bars.png), [Frame lab note](images/before-frame-lab-note.png).

The state colours and icons (`--st-ok/warn/error/busy`, `Icons.stateIcon`) already exist and are the base for this change.

## Goals / Non-Goals

**Goals:**
- One component and one look per kind, used for every message bigger than a field.
- One rule for where a message goes, simple enough to explain in one sentence: at the top of what it is about.
- Same announce behaviour for screen readers everywhere.

**Non-Goals:**
- Changing message wording (the word list in `docs/wording.md` still applies).
- Field-level hints and field errors (owned by each view; grey hint vs amber leftover setting is decided in `eds-gated-node-settings`).
- The exported HTML documentation, the Problems panel layout and the status bar.
- Toasts or a message history.

## Decisions

**1. Four kinds, one look each.** `info`, `done`, `warning`, `error`. Each bar has a 3 px left accent bar in the state colour, a light tint, the state icon and the text, then optional actions (buttons or links such as Undo, Unlock…, Remove, Details) and an optional close.
- info: neutral `--hover` tint, accent `--muted`, new "i" icon added to `icons.js` and the legend.
- done: neutral tint, accent `--st-ok`, the operational circle icon.
- warning: `--st-warn-bg`, accent `--st-warn`, triangle.
- error: `--st-error-bg`, accent `--st-error`, cross.
Alternative considered: a tint per kind including green for done. Rejected: the page is grey while all is well (docs/configurator.md "Colours and icons"), so success stays neutral and only the accent and icon show it.

**2. One helper.** `notice(kind, content, {actions, close, timed})` returns the element; `banner(text, isError)` becomes `banner(kind, text, opts)` on top of it (old two-argument calls map to info/error during the change, then go). Views put a notice in a slot with `noticeSlot(sectionEl)`, which is the first child after the section's heading. One slot holds several notices, most severe first; a notice with the same key replaces the old one.

**3. Placement: at the top of what it is about.**
- Page: the message bar under the header (unchanged place), for results of the user's actions that are not tied to one section, and for errors of a request.
- View or section: the slot under the view's or section's heading, before its first control. Locked notes, read-only reasons, "needs a connection", stale data, connection lines of a view, job results of a section (Read all, Back up, Compare, Restore, DM read), section warnings.
- Dialog: the slot at the top of the dialog body, under its question or title. A request started from a dialog reports there while the dialog is open, never in the page bar behind it.
- Field: hints, a field's error, a table row's error and an inline read value stay next to their field and are not bars.
Alternative considered: everything in the page bar. Rejected: with several sections busy (Parameters and NMT on one node), a section result in the page bar loses which section it was about, and it is far from the eye on a long page.

**4. Order under the header.** Connection bar (part of the header), then the simulation banner, then the message bar. The simulation banner and the message bar are sticky together with the header, so both stay in view while the page scrolls (today the simulation banner scrolls away).

**5. Simulation banner is a warning.** Its text tells the user not to upload the configuration to a machine; it is a warning by content. The dashed outline for simulated nodes stays for the nodes themselves.

**6. Connection bar tints.** Error tint for an ended or lost connection, bus-off, another master, and a round trip above 300 ms; warning tint for error passive and a round trip above 100 ms. Today all of these are red. Another master stays an error because two masters on one bus is a fault.

**7. Close and timing.** Unchanged for the page bar: info and done close by themselves after about 6 s, warnings and errors stay until closed, replaced or the view changes. Section and dialog notices describe a state and have no close; they go when the state changes or the section is drawn again. A section job result (done or error) stays until the next run of that job.

**8. Roles.** Error: `role="alert"`. Warning, info, done: `role="status"`. A notice that is drawn with its view (not a change) gets no live role, so opening a page does not read all its notes.

**9. Test.** A Playwright walk opens every view, tool tab, node tab and dialog of the virtual-plant and pingpong configs in Light and Dark, in Configure and Commission, and asserts:
- no element with a retired class (`online-note`, `fx-note`, `fx-error` as a section message, `machine-notice`, `machine-nodata`, `job-status` as a result line (it keeps only the progress), `j1939-dm-result`, `field-msg warning` outside a field);
- every `.notice` is the first child after its section's heading or in the dialog's top slot;
- each kind's computed background and accent colour equals the kind's tokens.

## Risks / Trade-offs

- [Many files touched at once] → one helper and a mechanical move per view; the placement test catches what was missed.
- [Overlap with in-flight UI changes in the same files] → apply after `eds-gated-node-settings` and `row-highlight-and-list-resize` merge; no shared requirement text.
- [Sticky simulation banner takes vertical space] → it is already one line (two at phone width); the message bar is hidden when empty.
