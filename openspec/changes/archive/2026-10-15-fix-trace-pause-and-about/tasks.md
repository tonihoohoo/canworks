## 1. Pause button

- [x] 1.1 `trace_ids.js`: `idsPause` sets the label "Pause view" / "Resume view" and the matching tooltip; build the button through the same helper in `renderIds` so a re-render while paused shows "Resume view"; drop `aria-pressed`
- [x] 1.2 Browser test: press Pause view while recording, the button reads Resume view and updates wait; press it, it reads Pause view and the waiting updates appear

## 2. Inspector state across live updates

- [x] 2.1 `explain.js`: keep the About open state on the inspector host (from the details `toggle` event) and apply it in `fxMeaning`
- [x] 2.2 `fxInspectSeq`: before replacing the inspector, note scroll position, the explained field or bit and focus inside the inspector; after building a frame of the same identifier and kind, restore them
- [x] 2.3 Browser test: select a live heartbeat row, open About this kind of message, wait for several new frames; the section stays open, the explained field stays, focus stays on the summary; select another row, the section is still open
- [x] 2.4 Check the Chronological view while following the newest frame behaves the same

## 3. Chronological list end

- [x] 3.1 `trace.js`: `listWindow()` (first row and pixel shift, newest row aligned to the bottom at the end); `refreshRows` asks one row more and no longer overrides the server's offset; `drawRows` starts at the first row in view and shifts it
- [x] 3.2 Browser test: list 301 px high, follow a recording of 61 frames, the newest frame is the last row drawn and ends at the bottom edge

## 4. Sequences pick

- [x] 4.1 `explain.js`: `fxPickSequence` keeps the list scroll, the page position and focus on the picked row, for SDO conversations and boot stories
- [x] 4.2 Browser test: 60 conversations, scroll to the end, click and Enter pick rows, the list stays where it was

## 5. Release

- [x] 5.1 Tools version 0.61.0 -> 0.61.1; README only if it describes the pause button (check)
- [x] 5.2 Light and dark, phone width: button label fits without the toolbar jumping
