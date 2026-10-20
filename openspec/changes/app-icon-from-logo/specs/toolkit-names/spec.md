## ADDED Requirements

### Requirement: App icon
The configurator's app shortcut and its browser tab SHALL use an icon drawn from the project logo: at 48 px and larger the logo's word "can" in the logo's blue over the logo's two-wire bus with terminators and nodes, on a rounded square; at 32 px and smaller the logo's "c" over the two wires. The letters SHALL be the logo's outlined glyphs and the colours the logo's own. The Windows `.ico` SHALL hold both forms at their sizes, and the browser tab icon SHALL be an SVG that uses the logo's dark colours when the operating system is in dark mode. Every icon file SHALL be written by one script in the repository from the same drawing, and SHALL contain no third-party logo or trademark.

#### Scenario: Shortcut matches the logo
- **WHEN** a user installs the PC tools and looks at the canworks configurator shortcut on the desktop, in the Start menu, in `~/Applications` or among the Linux applications
- **THEN** its icon shows the blue "can" over the bus, as in the README logo

#### Scenario: Small sizes
- **WHEN** Windows shows the shortcut at 16 or 24 px (Start menu list, taskbar jump list)
- **THEN** the icon is the "c" over two wires with no blurred detail

#### Scenario: Browser tab
- **WHEN** the configurator page is open in a browser
- **THEN** its tab shows the small form of the app icon, not the earlier blue square

#### Scenario: Dark mode tab
- **WHEN** the operating system is in dark mode
- **THEN** the tab icon uses the logo's dark colours on a dark tile

#### Scenario: Logo colour changed
- **WHEN** a developer changes a colour in the icon script and runs it
- **THEN** the shortcut icons, the favicon and the touch icon are all rewritten with the new colour
