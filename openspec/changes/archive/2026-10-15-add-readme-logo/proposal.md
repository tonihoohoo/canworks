## Why

The README opens with a plain `# canworks` heading. The project now has a public repository, release pages, a configurator with its own visual style and docs that other people read first; it has no mark that people recognise in a list of repositories, a browser tab or a slide. A logo at the top of the README is the cheapest place to start.

## What Changes

- **A logo for the README.** Option A of the four candidates below (Toni's pick, 2026-10-15) replaces the `# canworks` heading at the top of `README.md`, as a `<picture>` element with a light and a dark SVG, so it follows the reader's GitHub theme. The alt text is "canworks", so screen readers and text-only views still get the name.
- **Outlined text, no fonts needed.** The wordmark is converted to outlines, so the SVG looks the same on GitHub, in a release page or in a PDF, with no web font. A small generator script (`scripts/make_logo.py`) rebuilds the files from the font (Inter Display Bold, SIL Open Font Licence), so a colour or spacing change is one edit, not hand-editing paths.
- **Colours from the configurator.** The blue is the configurator's accent (`#1f5fbf` light, `#6ea0f0` dark); the second colour is a warm amber used only for the CAN_L wire. Both variants are checked against GitHub's light and dark backgrounds.
- **No third-party marks.** The design uses no CiA, OpenPLC, CAN in Automation or vendor logo, no trademarked shape, and only generic CAN ideas (two-wire bus, differential signal, frame fields).

### Candidates

All four were drawn in a light and a dark variant and compared side by side in the proposal; only A is kept.

- **A, Bus.** "can" in blue and "works" in ink, sitting on a two-wire bus (CAN_H blue, CAN_L amber) with a terminator at each end and three nodes tapping it. Says "CAN network" at a glance; no separate icon.
- **B, Signal.** A rounded tile with the differential CAN signal: CAN_H rises and CAN_L falls on dominant bits, which draws the familiar eye shape. Bold "canworks" next to it. The tile works on its own as an icon.
- **C, Nut.** A hex nut (the "works") threaded onto the two bus wires (the "CAN"), with "can" bold and "works" light. The most "tool" and least "electronics" of the four; the nut works on its own as an icon.
- **D, Frame.** The name laid out as a CAN frame in a trace view: start bit, "can" in the identifier field, "works" in the data field, CRC and ACK bits, a bit clock above. Ties to the trace and frame inspector tools; wide, and needs the mono font.

Chosen: **A**. (B was the proposal's recommendation, for its stand-alone icon; A has no separate icon.)

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `toolkit-names`: adds the project logo next to the project and package names.

## Impact

- `README.md` (top heading), `docs/images/logo-light.svg`, `docs/images/logo-dark.svg`, `scripts/make_logo.py`.
- No code, config, CI or package change. The banned-words guard covers the new files like any other.
