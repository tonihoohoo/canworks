## 1. Before writing

- [ ] 1.1 Check which of #99, #100, #101, #103 and `one-connect-place` are merged; leave out the tour lines of those that are not (proposal, Depends on)
- [ ] 1.2 Walk the tour on the current page with the virtual plant on the local simulator runtime and note any further stale step

## 2. Tour

- [ ] 2.1 Chapter 2: tab names and places (NMT command on Supervision, Gateway entry), Problems badge wording, two-line tree entries, Notes tab
- [ ] 2.2 Chapter 3: Export menu names; slave EDS from `cell` → Bus → **Export EDS**
- [ ] 2.3 Chapter 5: connect through the connect panel with the token prompt; network from the tree; Status tab for timeouts, SDO variables and Emergency history; state icons and diagnosis flag; NMT reset and the Log panel
- [ ] 2.4 Chapters 6, 9, 10: name the node tab of every step (Object dictionary, Parameters, Status), **Watch** for the drive objects
- [ ] 2.5 Chapter 7: Simulation tool tab with its network picker; Status tab's Simulated device panel as the short way
- [ ] 2.6 Chapter 8: **Scan anyway**; device names; LSS steps in the order of the page
- [ ] 2.7 Chapter 11: tool tab and picker, tab names, Decoding panel with `io.dbc`
- [ ] 2.8 Chapter 12: reset node 6 while recording, then Sequences
- [ ] 2.9 Chapter 13 and 15: labels checked against the page (Transmit list, Simulation → Machine)

## 3. Screenshots and test

- [ ] 3.1 Retake `tour-gateway.png` and `tour-mistake.png` (light theme, 1280 px wide, virtual plant)
- [ ] 3.2 `tools/deploy/tests/test_tour_labels.py`: bold labels of `docs/tour.md` against `static/*.js` and `index.html`, with an allow-list; failure names the label and its chapter
- [ ] 3.3 README checked; `openspec validate update-tour-for-new-ui --strict`

## 4. Hardware

None: the tour runs without hardware.
