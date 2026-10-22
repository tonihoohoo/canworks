## Context

The runtime version reaches a device or a test in five places today:

| Place | Today |
|---|---|
| CI build, browser and bridge jobs, local simulator image | `docker/local-runtime/runtime-version` = v4.2.4 |
| Integration job (`test/docker/run.sh`) | `openplc-runtime:latest` |
| Devices page **Install OpenPLC Runtime and canworks** | `curl -fsSL https://runtime.getedge.me \| bash`: newest runtime, recorded as a fixed tag in the bootloader spec |
| Bootloader image | always `latest` |
| Later changes on the device | only the OpenPLC Editor's update button (bootloader updater), up or down |

Checked on 2026-10-22 from a Windows PC: `runtime.getedge.me` serves upstream's `scripts/install-docker.sh` byte for byte. It takes `--runtime-version` and `--bootloader-version`. Without a version it pulls `latest` and writes the version baked into that image into the spec. Re-running it rewrites the spec from its own arguments, so the extra bind and environment entries canworks added would be lost. The bench device's spec says `v4.3.1`, and its bootloader container runs `latest`. Upstream's bootloader is versioned on its own (`bootloader/VERSION`, `bootloader-v1.1.0` from v4.2.4 to development) and published as `ghcr.io/autonomy-logic/openplc-runtime-bootloader:bootloader-v1.1.0`.

## Goals / Non-Goals

**Goals:** one version file decides the runtime everywhere; nothing canworks runs can move a device off it; a device that was moved gets back with one action.

**Non-Goals:** native runtimes, blocking the Editor's update button, supporting v4.3.2.

## Decisions

1. **The pin lives in `docker/local-runtime/runtime-version`, as today.** Every consumer already reads it, and `test_locked_versions.py` already ties `TESTED_RUNTIME` to it. The bootloader pin goes next to it (`bootloader-version`), and the same test reads both. Alternative: a new top-level `RUNTIME` file. Rejected because it moves a dozen readers for no gain.

2. **The release carries the pin, and the install reads it from the release.** `install-runtime.sh` is fetched on its own, so it cannot know the pin until it has the release tarball. It downloads the tarball first (today it comes after the OpenPLC install), reads both files and runs `curl -fsSL "$OPENPLC_INSTALLER" | bash -s -- --runtime-version "$RT" --bootloader-version "$BL"`. A failed download now stops before anything changes. `CANWORKS_RUNTIME_VERSION` overrides the pin for testing a new runtime by hand; the job never sets it.

3. **The switch is done by editing the spec, not by upstream's installer.** Re-running upstream's installer drops the canworks spec entries (it writes the spec from its own arguments). `install-stock.sh` already edits the spec atomically through `spec_tool`. A `version` subcommand sets the version and leaves every other key. Then the existing Docker-mode path runs: `docker pull` of `<repository>:<version>` (fails with "the device cannot download runtime vX" and changes nothing), build in that image, recreate the container. The install stamp includes the image id, so the skip-same-version rule rebuilds as it should.

4. **The Devices page always passes the pin on managed Docker.** Install, update and rebuild jobs get `--runtime-version <pin>`, so the page cannot leave a device on a version canworks was not tested with. When the device runs another version, the main action is **Switch runtime to vP**. It replaces **Rebuild for runtime vN**, which would build for an untested runtime. Building for another version stays possible by hand (`install-stock.sh` without the option), and the docs say so.

5. **The bootloader is pinned only at install.** It changes only through its own self-update, started from the Editor, and canworks has no spec field for it. Re-pinning an existing device's bootloader would mean recreating it, so a running bootloader is left alone. The probe reports its image tag, and the hardware check confirms that the bench's `latest` is the pinned version.

6. **The note covers older versions too.** "canworks runs on runtime v4.3.1; this device runs vN" for any known version other than the pin. An older runtime is just as untested.

## Risks / Trade-offs

- First full CI run on v4.3.1 → tests may fail on upstream behaviour changes (outputs zeroed on stop, boot-time plugin `init()`). Mitigation: fixed in this change; the bench has run v4.3.1 since 2026-10-13 without plugin issues.
- A user who updates the runtime on purpose and then presses **Switch runtime** goes back, losing the program until the next upload. Mitigation: the confirmation says so, and the main action is visible only when the version differs.
- Pinned bootloader `bootloader-v1.1.0` could be removed from the registry upstream. Mitigation: the install fails before changing anything; the runtime watch issue is the place to move the pins.

## Migration Plan

Existing devices: nothing happens until their next canworks install, update or rebuild from the Devices page, which also puts the runtime on the pin (no-op on the bench, already v4.3.1). Rollback: revert the change; the pin file returns to v4.2.4.
