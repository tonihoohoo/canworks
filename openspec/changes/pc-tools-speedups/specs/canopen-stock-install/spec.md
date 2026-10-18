## ADDED Requirements

### Requirement: One-line install and update on the device

The repository SHALL provide `scripts/install-runtime.sh`, and `docs/install-stock.md` and the README SHALL give, first among the install routes, the one line that runs it straight from the repository on GitHub as root (`curl -LsSf <url> | sudo bash`, options after `-s --`). It SHALL download the source of the newest `deploy-v` release (or of `--version <version>`), found from the `releases/latest` redirect without the GitHub API, and run that release's `scripts/install-stock.sh` with every other option given, without a git checkout on the device. Running the same line again SHALL install the newer release over the existing one as `install-stock.sh` re-runs do; `--uninstall` and the other `install-stock.sh` options SHALL pass through unchanged. It SHALL never install code from `main`. Without root it SHALL exit non-zero and say how to run it. It SHALL remove its downloaded source afterwards. The documentation SHALL keep the git checkout route and show the script pinned to a release.

CI SHALL run `shellcheck` on the script and test its release lookup and option pass-through without network access.

#### Scenario: Install on a fresh device
- **WHEN** an operator pastes the documented line on a Raspberry Pi with a stock OpenPLC Runtime v4 and no canworks checkout
- **THEN** the newest release's `install-stock.sh` runs, the plugin is installed as in Requirement: Install on a stock runtime, and no source folder of the release is left behind

#### Scenario: Update
- **WHEN** the line is run again on a device that has the plugin of an older release
- **THEN** the newest release is built and installed, `canworks-sim --version` prints its version and `plugins.conf` still has exactly one `canworks` line

#### Scenario: Options pass through
- **WHEN** the operator runs the line with `-s -- --with-link`
- **THEN** `install-stock.sh` of the release runs with `--with-link`

#### Scenario: Not root
- **WHEN** the line is run without `sudo`
- **THEN** the script exits non-zero before downloading anything and shows the line with `sudo`
