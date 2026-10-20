# Proposal

## Why

The configurator's app shortcut (added with configurator-quit-and-background) shows only the bus from the README logo, with no letters, so it does not read as canworks, and its 16 and 24 px sizes are a blur of lines. The browser tab, where the configurator actually runs, still has an older blue square icon that matches neither the logo nor the shortcut. The shortcut, the Start menu, the Dock and the browser tab should all look like the logo readers see on GitHub.

## What Changes

- One app icon drawn from the logo: the blue word "can" over the two-wire bus with its terminators and two nodes, on a rounded square (option C of the 2026-10-20 explore, `images/options.png`). Letters are the logo's own outlined glyphs, so no font is needed.
- At 32 px and smaller, a simpler form of the same icon: the blue "c" over the two wires, which stays readable where "can" would not.
- `scripts/make_icons.py` draws both forms and writes every icon file: the shortcut icons (`logo.ico` with 16, 24 and 32 px from the small form and 48 to 256 px from the large one, `logo.icns`, `logo-256.png`), the configurator's `favicon.svg` and a 180 px `apple-touch-icon.png`.
- The favicon becomes the small form with light and dark colours chosen by the operating system theme inside the SVG; it replaces the old blue square.
- PC tools patch version bump. No README text change (the README already shows the logo and names the shortcut).

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `toolkit-names`: new requirement App icon next to Project logo, covering the shortcut icons and the configurator's browser tab icon.

## Impact

- `scripts/make_icons.py` (rewritten drawing, new outputs), `tools/deploy/canworks/configurator/icons/*` (regenerated), `tools/deploy/canworks/configurator/static/favicon.svg` (replaced), `static/apple-touch-icon.png` (new), `static/index.html` (one `<link>` line).
- No change to how shortcuts are made (`shortcut.py`), to the server or to any runtime part. Installed shortcuts pick up the new icon when the PC tools are updated and the shortcut is created again (the installer does that).
