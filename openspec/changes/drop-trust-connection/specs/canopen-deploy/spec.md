## MODIFIED Requirements

### Requirement: Upload wording only for uploads
A failed command that never uploads (an export, `--check`, `--check-only`) SHALL NOT end with "nothing was uploaded".

#### Scenario: Refused truST export
- **WHEN** `canworks-deploy --export-plcopen DIR --for trust` is refused as an unknown choice, or `--for generic` for a config without the PLC link
- **THEN** the output has the reason and no "nothing was uploaded" line
