## ADDED Requirements

### Requirement: Machine view messages
The view's messages (switched to Low for a slow frame rate, no data for more than 1 s, no WebGL, machine file problems) SHALL be the configurator's message bars at the top of the stage: no data as an error, Low and no WebGL as information, file problems as warnings or errors. None SHALL sit at the bottom of the stage.

#### Scenario: No data
- **WHEN** the simulator stops answering for 2 s
- **THEN** an error bar "No data" is shown at the top of the stage, the pose is held, and the bar goes when data comes back

#### Scenario: Switched to Low
- **WHEN** the view switches itself to Low
- **THEN** an information bar at the top of the stage says so
