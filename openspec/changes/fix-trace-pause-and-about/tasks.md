## 1. Pause button

- [ ] 1.1 `trace_ids.js`: `idsPause` sets the label "Pause view" / "Resume view" and the matching tooltip; build the button through the same helper in `renderIds` so a re-render while paused shows "Resume view"; drop `aria-pressed`
- [ ] 1.2 Browser test: press Pause view while recording, the button reads Resume view and updates wait; press it, it reads Pause view and the waiting updates appear

## 2. Inspector state across live updates

- [ ] 2.1 `explain.js`: keep the About open state on the inspector host (from the details `toggle` event) and apply it in `fxMeaning`
- [ ] 2.2 `fxInspectSeq`: before replacing the inspector, note scroll position, the explained field or bit and focus inside the inspector; after building a frame of the same identifier and kind, restore them
- [ ] 2.3 Browser test: select a live heartbeat row, open About this kind of message, wait for several new frames; the section stays open, the explained field stays, focus stays on the summary; select another row, the section is still open
- [ ] 2.4 Check the Chronological view while following the newest frame behaves the same

## 3. Release

- [ ] 3.1 Tools version 0.61.0 -> 0.61.1; README only if it describes the pause button (check)
- [ ] 3.2 Light and dark, phone width: button label fits without the toolbar jumping
