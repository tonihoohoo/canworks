## Context

Today `scripts/make_icons.py` draws only the bus on a 64-unit grid with Pillow and writes `logo.ico`, `logo.icns` and `logo-256.png` under `tools/deploy/canworks/configurator/icons/`; `shortcut.py` copies them into the shortcut on each platform. `static/favicon.svg` is a separate, older hand-written icon. The README logo comes from `scripts/make_logo.py`, which outlines Inter Display Bold glyphs with fontTools into `docs/images/logo-light.svg` and `logo-dark.svg`. The explore notes and the three options are in `/mnt/project-files/research/app-icon-2026-10-20/` (project folder) and `images/options.png` here; Toni picked option C.

## Goals / Non-Goals

**Goals:** shortcut and tab icon recognisably the README logo; readable at 16 px; one script for every icon file; dark tab icon in dark mode.

**Non-Goals:** opening the configurator in its own app window (Edge/Chrome `--app`) so the taskbar shows the icon instead of the browser's; a web app manifest; the repository's social preview image; dark shortcut icons (Windows and macOS app icons are normally one light design).

## Decisions

- **Draw in SVG, rasterise for the platforms.** The icon is written once as SVG (64-unit grid, two forms, two themes). The glyph outlines are read from `docs/images/logo-light.svg` (the "c" and "can" subpaths of its first path), so `make_icons.py` needs no font and stays in step with the logo. Raster files are rendered from that SVG with `resvg-py` (prebuilt wheels with the resvg renderer, no system library; checked to install and import here, 0.5.0), then sized and packed into `.ico`/`.icns` with Pillow. Both are development-only dependencies, like Pillow and fontTools today, and the script's docstring names them. Alternative considered: keep Pillow drawing and flatten the glyph curves to polygons ourselves; more code for the same result.
- **Two forms by size.** 48 px and up: "can" (14 units tall) over the bus at 40/46 units with terminators and two nodes. 32 px and down: "c" (31 units tall) over two 5-unit wires, no terminators or nodes. The `.ico` gets 16, 24, 32 from the small form and 48, 64, 128, 256 from the large one; `.icns` and `logo-256.png` use the large form. The favicon is the small form, since browsers draw it at 16 to 32 px.
- **Favicon theme.** One `favicon.svg` with a `<style>` holding `@media (prefers-color-scheme: dark)` that swaps tile and stroke colours. Browsers apply this from the OS theme, not from the configurator's own Light/Dark/Auto choice; that is the accepted limit (a page script could swap the link, but it is not worth the code).
- **Touch icon.** `apple-touch-icon.png` at 180 px from the large form, linked from `index.html`, for Safari's Add to Dock and phone home screens.
- **Committed files.** As today, generated files are committed so building the package needs nothing; `make_icons.py` is run by hand after a logo change. A test checks the committed favicon and icon sizes so a missing or stale file is caught.

## Risks / Trade-offs

- [Windows caches shortcut icons] → the installer recreates the shortcut on update; a stale cached icon may stay until Explorer refreshes. Noted in the task check, no code for it.
- [Two forms look different at the switch-over size] → both share colours, the "c" shape and the wires; checked side by side at 32 and 48 px.
- [SVG renderer differences] → output is checked visually once and committed; the renderer only runs on a developer machine.

## Open Questions

None.
