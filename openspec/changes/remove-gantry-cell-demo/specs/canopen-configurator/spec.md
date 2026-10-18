## MODIFIED Requirements

### Requirement: Moving a config keeps its files
"Move into project…" and "New editor project…" SHALL take along every file of the standalone config: `canworks.json`, the EDS files, `simulation.json` and the slave EDS description, and the replace question SHALL name the project's `canworks/` folder.

#### Scenario: Simulation file moves
- **WHEN** a standalone config with a `simulation.json` is moved into an editor project
- **THEN** the project's `canworks/simulation.json` has the same content and the Simulation view shows it as saved

### Requirement: One look for messages
Every message about a page, view, section or dialog SHALL be a message bar of one of four kinds: information, done, warning or error. Each kind SHALL have one tint, one left accent bar in its state colour and one state icon, the same on every page, tool tab and dialog, in light and dark theme. Information and done SHALL use the neutral tint; warning the warning tint; error the error tint.

#### Scenario: Same warning everywhere
- **WHEN** the user sees a warning in the message bar, in a node's Parameters tab and in the Simulation view
- **THEN** the three have the same tint, accent bar and warning icon

#### Scenario: Dark theme
- **WHEN** the theme is Dark
- **THEN** each kind uses the dark values of its tokens and its text keeps the normal text colour
