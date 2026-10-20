## 1. Icon drawing

- [ ] 1.1 Rewrite `scripts/make_icons.py` to build the large ("can" over the bus) and small ("c" over two wires) forms as SVG from the glyph outlines in `docs/images/logo-light.svg`, in the logo's light and dark colours
- [ ] 1.2 Write `logo.ico` (16/24/32 small, 48/64/128/256 large), `logo.icns` and `logo-256.png` under `tools/deploy/canworks/configurator/icons/`
- [ ] 1.3 Write `static/favicon.svg` (small form, dark colours under `prefers-color-scheme: dark`) and `static/apple-touch-icon.png` (180 px, large form); link the touch icon from `static/index.html`

## 2. Checks

- [ ] 2.1 Test: favicon.svg is the generated one (has the dark-mode rule, no old blue square), `.ico` holds the seven sizes, `apple-touch-icon.png` is 180 px and is served by the configurator
- [ ] 2.2 Look at the icons at 16, 24, 32, 48 and 256 px in light and dark; screenshot of a browser tab in both OS themes in the PR
- [ ] 2.3 PC tools patch version bump; run the banned-words check on the new files

## 3. Desktop check (after release)

- [ ] 3.1 Windows: update the PC tools with the one-line installer; the desktop and Start menu shortcuts show the new icon
- [ ] 3.2 macOS: the app in `~/Applications` shows the new icon in Finder and the Dock
