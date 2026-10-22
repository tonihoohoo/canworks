## ADDED Requirements

### Requirement: One runtime pin
Every CI job, test script and image build that uses the upstream OpenPLC runtime SHALL take its version from `docker/local-runtime/runtime-version`, and the upstream bootloader's from `docker/local-runtime/bootloader-version`. A test SHALL fail when a workflow, script or Dockerfile names either image by a literal tag other than the pin (such as `latest`), or runs upstream's installer without the pinned versions. Test code is exempt; test shell scripts are not.

#### Scenario: Integration job
- **WHEN** the integration job runs while upstream's `latest` is newer than the pin
- **THEN** it builds and runs canworks in the pinned runtime image

#### Scenario: Literal tag added
- **WHEN** a change adds `ghcr.io/autonomy-logic/openplc-runtime:latest` to a workflow
- **THEN** the pin test fails and names the file and line
