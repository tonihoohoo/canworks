## ADDED Requirements

### Requirement: Export for CODESYS
The header's Export menu SHALL offer "CODESYS", which runs the `codesys-export` export on the config as shown on the page, saved or not, with every master network, and offers the folder as a browser download `<config folder name>_codesys.zip`. When the config has errors or a DCF fails validation, it SHALL download nothing and show the messages in the Problems panel, as the DCF export does. It SHALL NOT write any file in the project or config folder.

#### Scenario: Download
- **WHEN** the config is valid and the user picks Export > CODESYS
- **THEN** the browser downloads `<folder>_codesys.zip` holding the network folders with their DCFs, `canworks-codesys.json`, `import_canworks.py` and `README.txt`

#### Scenario: Config with errors
- **WHEN** the config has errors and the user picks Export > CODESYS
- **THEN** nothing is downloaded and the Problems panel lists the errors
