## ADDED Requirements

### Requirement: Check now shows its result
Settings → **Check now** SHALL keep its menu open and show "Checking…" and then the result there and in the update banner. It SHALL be disabled with the reason while the update check is turned off.

#### Scenario: Check from the menu
- **WHEN** the user presses Check now
- **THEN** the menu stays open and shows the result

### Requirement: Re-check waits for a running check
The re-check before an update SHALL wait for a check already running and use its result, never the version kept from before.

#### Scenario: Update at page open
- **WHEN** the user presses Update now while the start-time check still runs
- **THEN** the update goes to the version that check finds
