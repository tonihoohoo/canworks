## ADDED Requirements

### Requirement: Export network documentation
The page header SHALL have an "Export documentation" action. It SHALL run the `canopen-network-docs` export on the config as currently shown on the page, saved or not, for all networks, and offer the result as a browser download named `<config folder name>.html`. In project mode the export SHALL use the project's located variables for PLC variable names and the project's task interval as the PLC cycle. When the config has errors, the configurator SHALL download nothing and SHALL show the messages in the Problems pane; warnings from the export SHALL be shown there after the download. The action SHALL NOT write any file in the project or config folder.

#### Scenario: Export
- **WHEN** the config is valid and the user clicks "Export documentation"
- **THEN** the browser downloads the HTML document and no file under the project changes

#### Scenario: Unsaved change is documented
- **WHEN** the user adds node 7 without saving and exports
- **THEN** the downloaded document has a section for node 7

#### Scenario: Config with errors
- **WHEN** the config has a duplicate node ID
- **THEN** nothing is downloaded and the Problems pane shows the error
