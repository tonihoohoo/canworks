## Context

GitHub renders README images through `<img>`, which cannot load web fonts and does not follow GitHub's theme setting from inside an SVG's own `prefers-color-scheme` query (it follows the operating system instead). A `<picture>` element with a `prefers-color-scheme: dark` source is what GitHub documents for theme-aware README images, and it follows the GitHub theme.

## Goals / Non-Goals

**Goals:** a logo that is readable in both GitHub themes, small files, reproducible from a script, no third-party marks.

**Non-Goals:** a favicon in the configurator, the repository's social preview image, release page or docs site branding, a style guide. These can use the files later.

## Decisions

- **Two files, not one with a media query.** One SVG with an internal `@media (prefers-color-scheme: dark)` would follow the operating system, not GitHub's theme, so a reader with a light OS and GitHub in dark would get dark text on a dark page.
- **Text as outlines.** Fonts are not embedded; `scripts/make_logo.py` converts the glyphs with fontTools. The script is a development tool only (fontTools is not a runtime dependency of any package) and documents the font it needs.
- **Markup.** The README's first line becomes:

  ```html
  <h1><picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/images/logo-dark.svg">
    <img alt="canworks" src="docs/images/logo-light.svg" height="72">
  </picture></h1>
  ```

  Kept inside `<h1>` so the page still has its title heading, and left aligned like the rest of the README. The height is fixed so the logo does not fill a wide screen.
- **Colours.** Ink `#1a2233` / `#e6edf3`, blue `#1f5fbf` / `#6ea0f0` (configurator accent), amber `#e0782a` / `#f2a25c`. Blue and ink meet 4.5:1 against GitHub's `#ffffff` and `#0d1117`; amber is only used for strokes next to blue, never for text.

## Risks / Trade-offs

- [The dark variant shows in a light place, e.g. a dark logo pasted into a light slide] → each file has a theme in its name; the square icon's tile (option B) carries its own background.
- [Option C's nut hole is filled with GitHub's background colour, not cut out] → on another background it shows as a disc; if C is picked the hole becomes a real cut-out (even-odd path) before apply.

## Open Questions

- Which option (A, B, C or D), and any change to it (colours, weight, "can" highlighted or not)?
