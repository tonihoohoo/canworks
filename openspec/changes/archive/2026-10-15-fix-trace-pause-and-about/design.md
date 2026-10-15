## Context

`idsFollow()` calls `fxInspectSeq(seq)` for every new frame of the selected identifier (two to four times a second while recording). `fxInspectSeq` fetches the explanation and replaces the inspector's children with a freshly built `fxInspector(...)`, so the `<details class="fx-about">` comes back closed, the explanation box is empty and the scroll position resets. Paused, the rows do not change, `idsFollow` sees the same `seq` and nothing is rebuilt, which is why the bug only shows while live.

The pause button is built once in `renderIds` with the fixed label "Pause view"; `idsPause` only flips `aria-pressed`.

The Chronological list is a sticky box that draws only the rows in view over a tall spacer. It took the first row as `floor(scrollTop / 22)` and drew rows from the box's top edge, so with a list height that is not a whole number of rows the last row was cut; while following, the client asked for `visible + 2` rows ending at the newest frame, then drew all of them from the top, which pushed the two newest rows below the edge.

The Sequences lists redraw the whole table when a row is picked (to move the selected mark and fill the detail below), and a new scroll box starts at the top.

## Decisions

1. **Label "Resume view", not "Resume".** It pairs with "Pause view" and keeps the button width steady. Tooltip: "Stop updating the table; recording continues" / "Show the waiting updates and keep updating". `aria-pressed` is dropped, since the name now changes (WAI-ARIA toggle-button guidance).
2. **Remember the About state per inspector host, for the page session.** A `fxAboutOpen` flag on the host element (`#trace-inspector`) is set from the `toggle` event of the details and applied when building `fxMeaning`. It survives a change of identifier or message kind, so a user learning the protocol can keep it open while clicking through rows. Not saved in trace preferences: it is reading state, not a setting.
3. **Keep the reading position only for the same identifier.** Before replacing the children, `fxInspectSeq` notes the inspector's `scrollTop`, the field or bit shown in the explanation box, and whether focus is inside the inspector (and on which element, by its `data-fx` role and bit index). After building, if the new frame has the same identifier and kind, it restores them; the box re-explains the same field with the new value. A different identifier starts at the top, as today.
4. **No diffing of the inspector DOM.** Rebuilding at four times a second is cheap; carrying three pieces of state is simpler and safer than patching layers in place.

5. **Chronological window: first row plus a pixel shift.** `listWindow()` returns the first row and how far it sits above the top edge (`scrollTop % 22`); at the end of the list the newest row is aligned to the bottom edge instead. `drawRows` skips the rows the server sent before the first one (it keeps a full window near the end) and moves the first drawn row up by the shift. Above the 4,000,000 px scroll cap the position stays proportional with no shift, as today.
6. **Sequences: keep scroll, page position and focus on pick.** `fxPickSequence` notes the list's `scrollTop` and the page's `scrollY`, redraws, restores both and focuses the picked row without scrolling. Changing the filter still redraws from the top.

## Risks / Trade-offs

- A field that does not exist in the new frame (for example a multiplexed page switched) cannot be restored; the box then stays empty, as for a fresh frame.
- Restoring focus during a rebuild must not steal focus from the table: focus is restored only when it was inside the inspector before the rebuild.
