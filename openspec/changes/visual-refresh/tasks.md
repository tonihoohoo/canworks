## 1. Tokens and icons

- [ ] 1.1 `style.css`: state tokens `--st-ok`, `--st-busy`, `--st-warn`, `--st-error`, `--st-off` (with `-bg` for warn and error) for Light, Dark and Auto; spacing tokens `--sp-1`…`--sp-5`; `--mono`; keep `--ok`, `--warn`, `--error` as aliases for now
- [ ] 1.2 Contrast unit test: parse the tokens from `style.css` and check 4.5:1 text and 3:1 icon ratios against `--bg`, `--panel` and the `-bg` tints in both themes
- [ ] 1.3 Icon sprite in `index.html` and `icons.js` (`stateIcon(state, {label, simulated, flag})`); accessible name or `aria-hidden` by use; forced-colours and reduced-motion rules
- [ ] 1.4 `disable(el, reason)` / `enable(el)` helper

## 2. States on every view

- [ ] 2.1 Network tree and its problem badges; Nodes table; node tab headers
- [ ] 2.2 Connection bar and status bar (connect states, check result, bus state, round trip, other master, jobs)
- [ ] 2.3 Problems panel, message bar, field messages; simulation marks move from warning colours to the dashed outline
- [ ] 2.4 Node Status tab, EMCY history and diagnosis flag; scan comparison; LSS panel
- [ ] 2.5 Trace (both views), Frame lab status lines, Simulation, Machine view notices; move the hex state colours in `trace.js` and `explain.js` to tokens
- [ ] 2.6 Remove the `--ok`, `--warn`, `--error` aliases and `td.state-*`; add a test that fails on a raw state colour outside the tokens
- [ ] 2.7 Colours and icons legend in the settings menu, drawn from `icons.js`

## 3. Density

- [ ] 3.1 `table.data` style (row heights, padding, sticky headers, right-aligned tabular numbers) and `.mono`; `fmt` helpers write hex as `0x` upper case and add `.mono`
- [ ] 3.2 Move every data table listed in the spec to `table.data`; replace ad hoc margins with the spacing tokens
- [ ] 3.3 Layout fit at 1000, 1280 and 1440 px in both themes stays green; 24 px targets kept

## 4. Wording

- [ ] 4.1 `docs/wording.md` (terms and style) and `tests/data/wording.json`; `test_configurator_wording.py` over `static/*.js`, `index.html` and the server's user-facing messages
- [ ] 4.2 Wording pass over Configure views (labels, tooltips, empty states, messages), updating the page tests that assert on old texts
- [ ] 4.3 Wording pass over Commission, Trace, Frame lab, Simulation and the connect panel, with their tests
- [ ] 4.4 Wording pass over server messages in `configurator/server.py` and `online.py`, with their tests
- [ ] 4.5 Every disabled control gets a reason through `disable()`; layout test check for disabled controls without one

## 5. Task tests

- [ ] 5.1 `KeyboardOnly` page wrapper (fails on click, hover, mouse, tap) with per-step axe, visible-focus and clipping checks and step screenshots on failure
- [ ] 5.2 `test_configurator_tasks_page.py`: connect, scan, add to config, map a PDO, record a trace; each in Light and Dark
- [ ] 5.3 Forced-colours run of the tree and the Nodes table in the layout test
- [ ] 5.4 Check CI time: the task tests run only under the `ui` path filter, in the configurator-page shard, within about 60 s; rebalance shards if the shard's time grows

## 6. Docs and release

- [ ] 6.1 `docs/configurator.md`: Colours and icons section with the legend and screenshots in both themes; text updated to the word list; `docs/tour.md`
- [ ] 6.2 `README.md` (screenshots and wording)
- [ ] 6.3 PC tools minor version bump and changelog line
