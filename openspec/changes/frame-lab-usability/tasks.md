# Tasks

## 1. Fixes in the explanation display

- [ ] 1.1 Caption the low identifier bits of NMT, SYNC and TIME as part of the identifier instead of "Node ID null" (design D7), and verify with a page test that `080#` and `000#0105` show no "null" and no node caption
- [ ] 1.2 Draw the arbitration Bus row from the winner's bits after the deciding bit (D6), and verify with a page test that `185#` against `183#` shows bus 1, 1 at ID1 and ID0

## 2. Close and reopen the Trace inspector

- [ ] 2.1 Give the inspector a title bar with ✕ (keeping `data-trace=inspector-toggle`), remove the separate "Hide inspector" bar, and add the **Inspector ›** rail (`data-trace=inspector-rail`) when closed (D1). Verify the open or closed state survives a reload through `inspector` in the trace prefs
- [ ] 2.2 Make Esc inside the inspector close it and focus the selected row, make click or Enter on a row reopen it, and keep arrow-key moves from reopening it. Verify with page tests for the three scenarios of "Close and reopen the inspector"
- [ ] 2.3 Update the existing trace page tests that used "Hide inspector", and verify `test_configurator_trace_page.py` and `test_configurator_frames_page.py` pass

## 3. Narrow windows

- [ ] 3.1 Below 1280 px, give the list and the inspector a shared box of the window's height with two rows that scroll on their own, resizable by the existing handle, and scroll the box to the top on the first selection (D2). Verify with a 1000×800 page test that the fifth Chronological row and the inspector's meaning are both in the window
- [ ] 3.2 Keep the stacked layout under 640 px with the inspector scrolled into view on select, and verify the phone-width layout check in `test_configurator_layout.py` still passes

## 4. Folding layers and compact grid

- [ ] 4.1 Turn Identifier, Data bits and On the wire into folding sections with a one-line summary in each heading, and keep the folded keys as `fx_fold` in the trace prefs, checked in `transmit.py` `check_prefs` (D3). Verify with a unit test for `check_prefs`, and a page test that folding in Trace carries over to the Frame lab and a reload
- [ ] 4.2 Shrink bit cells to 18 px high, with one header row of bit numbers and each CANopen bit number in the cell's label and tooltip (D4). Scope the target-size exception to `.fx-bit` in `Layout.fits()`, and verify that an 8-byte SDO frame's grid is at most 260 px tall at 1440 px
- [ ] 4.3 Group runs of 2 or more whole bytes of one field into one row that opens to its bits, keeping arrow-key and pointer highlighting (D4). Verify with a page test on `085#0010010000000000`: bytes 3-7 show as one Manufacturer data row, and opening it reaches bit 63 by keyboard
- [ ] 4.4 Update docs/frame-inspector.md (four layers, folding, grouped bytes) and the inspector part of docs/configurator.md, and verify the doc links check passes

## 5. Frame lab layout

- [ ] 5.1 Rebuild the Frame lab as the frame box (frame, Explain, bit rate) with **Examples | Build | Arbitration** tabs and a result column. Make the column sticky at 1280 px and wider, and order the narrow layout frame box, result, tabs (D5). Verify with page tests at 1440×900 (EMCY example result beside the examples) and 1000×800 (SDO build result in the window)
- [ ] 5.2 Render the arbitration demo into the result column, and verify the "Arbitration result in the result column" scenario
- [ ] 5.3 Add **Clear** to the result header and Esc in the frame box, both keeping the tab, builder values and bit rate, and verify with the "Clear" scenario test
- [ ] 5.4 Bring each new result into view (Explain, example, Build, Run both, Explain in Frame lab), focusing the result heading for Explain in Frame lab. Verify with a 1000×800 test from a trace SYNC frame
- [ ] 5.5 Update the existing Frame lab tests (`test_configurator_explain_page.py`, the e2e keyboard walk, the examples and localbus page tests) for the tabs, and verify they pass
- [ ] 5.6 Update the Frame lab section of docs/frame-inspector.md and docs/configurator.md, the Frame lab line in docs/tour.md, and README's Trace line. Retake docs/images/frame-lab.png and docs/images/frame-inspector.png

## 6. Simulation banner

- [ ] 6.1 Show the simulation banner as one line, "Simulated: <network (nodes …)>, … Do not upload as it is.", with **Details** holding the full text (D8). Verify with a page test on examples/virtual-plant at 1440 px (one line, Details text) and at 400 px (at most two lines)
- [ ] 6.2 Update docs/configurator.md's description of the banner, and the tests that read the banner's text, and verify they pass

## 7. Integration

- [ ] 7.1 Run the full configurator browser suite and `openspec validate frame-lab-usability --strict`. Bump the tools version and add release notes, and verify CI is green on the PR
