## ADDED Requirements

### Requirement: Skip an up-to-date install
Before installing, the one-line PC installers SHALL read the installed version of the tools from uv. When it equals the version they would install and neither `--force` (`-Force`) nor `--wheel` (`-Wheel`) is given, they SHALL say that this version is already installed and how to install it again, change nothing, and exit 0. Otherwise, including when the installed version cannot be read, they SHALL install as before. `--force` SHALL install even the same version again and recreate the shortcut.

#### Scenario: Line run again
- **WHEN** a user with 0.92.0 installed runs the one-line installer while 0.92.0 is the newest release
- **THEN** it prints that canworks 0.92.0 is already installed and that `--force` installs it again, exits 0 within seconds, and the tools' environment is unchanged

#### Scenario: Newer release
- **WHEN** a user with 0.92.0 installed runs the line after 0.93.0 was released
- **THEN** 0.93.0 is installed as before

#### Scenario: Force
- **WHEN** a user runs the installer with `-Force` and the newest version is already installed
- **THEN** it installs that version again and recreates the shortcut
