## 1. Tokens and icons

- [x] 1.1 `style.css`: state tokens `--st-ok`, `--st-busy`, `--st-warn`, `--st-error`, `--st-off` (with `-bg` for warn and error) for Light, Dark and Auto; spacing tokens `--sp-1`…`--sp-5`; `--mono`; keep `--ok`, `--warn`, `--error` as aliases for now
- [x] 1.2 Contrast unit test: parse the tokens from `style.css` and check 4.5:1 text and 3:1 icon ratios against `--bg`, `--panel` and the `-bg` tints in both themes
- [x] 1.3 Icon sprite in `index.html` and `icons.js` (`stateIcon(state, {label, simulated, flag})`); accessible name or `aria-hidden` by use; forced-colours and reduced-motion rules
- [x] 1.4 `disable(el, reason)` / `enable(el)` helper

## 2. States on every view

- [x] 2.1 Network tree and its problem badges; Nodes table; node tab headers
- [x] 2.2 Connection bar and status bar (connect states, check result, bus state, round trip, other master, jobs)
- [x] 2.3 Problems panel, message bar, field messages; simulation marks move from warning colours to the dashed outline
- [x] 2.4 Node Status tab, EMCY history and diagnosis flag; scan comparison; LSS panel
- [x] 2.5 Trace (both views), Frame lab status lines, Simulation, Machine view notices; move the hex state colours in `trace.js` and `explain.js` to tokens
- [x] 2.6 Remove the `--ok`, `--warn`, `--error` aliases and `td.state-*`; add a test that fails on a raw state colour outside the tokens
- [x] 2.7 Colours and icons legend in the settings menu, drawn from `icons.js`

## 3. Density

- [x] 3.1 `table.data` style (row heights, padding, sticky headers, right-aligned tabular numbers) and `.mono`; `fmt` helpers write hex as `0x` upper case and add `.mono`
- [x] 3.2 Every data table gets the compact rows and the sticky header from the base `th`/`td` rules and its scroll box (`.objects`, `.table-scroll`, `.fx-list`), so no table needs a class; new rules use the spacing tokens
- [x] 3.3 Layout fit at 1000, 1280 and 1440 px in both themes stays green; 24 px targets kept

## 4. Wording

- [x] 4.1 `docs/wording.md` (terms and style) and `tests/data/wording.json`; `test_configurator_wording.py` over `static/*.js`, `index.html` and the server's user-facing messages
- [x] 4.2 Wording pass over Configure views (labels, tooltips, empty states, messages), updating the page tests that assert on old texts
- [x] 4.3 Wording pass over Commission, Trace, Frame lab, Simulation and the connect panel, with their tests
- [x] 4.4 Wording pass over server messages in `configurator/server.py` and `online.py`, with their tests
- [x] 4.5 Every disabled control gets a reason through `disable()`; layout test check for disabled controls without one

## 5. Task tests

- [x] 5.1 `KeyboardOnly` page wrapper (fails on click, hover, mouse, tap) with per-step axe, visible-focus and clipping checks and step screenshots on failure
- [x] 5.2 `test_configurator_tasks_page.py`: connect, scan, add to config, map a PDO, record a trace; each in Light and Dark
- [x] 5.3 Forced-colours run of the tree and the Nodes table in the layout test
- [x] 5.4 Check CI time: the task tests run only under the `ui` path filter, in the configurator-page shard, within about 60 s; rebalance shards if the shard's time grows

## 6. Docs and release

- [x] 6.1 `docs/configurator.md`: Colours and icons section with the legend as a table (the page's own legend under Settings replaces screenshots); text updated to the word list; `docs/tour.md`
- [x] 6.2 `README.md` (screenshots and wording)
- [x] 6.3 PC tools minor version bump (0.61.0; the version in `pyproject.toml`, `canworks/__init__.py` and the doc golden files is the record, there is no changelog file)
