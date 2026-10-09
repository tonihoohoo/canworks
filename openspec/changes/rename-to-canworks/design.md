## Context

One public repository (`tonihoohoo/openplc-canopen`, Apache-2.0) holds:
- a native runtime plugin
- the PC tools (deploy, configurator, diagnostics client, simulator runtime launcher)
- an editor hook
- a simulator runtime image
- the OpenSpec specs

The name `canworks` was chosen on 2026-10-09. It replaced `opencan-plc` (2026-10-08), which was dropped because the tools also work with no PLC and CODESYS may become a target.

The owner confirmed the project is not in real use anywhere. The only installs are the development bench (one PLC, two PCs) and the CI images. That makes a clean cut cheaper than any compatibility layer.

## Goals / Non-Goals

**Goals:**
- Every project-level name says `canworks`: repo, package, commands, PLC plugin, install path, config file and folder, image, settings and variables.
- One reviewable rename commit, produced by a script that in-flight branches can replay.
- CI keeps the old names from coming back.

**Non-Goals:**
- Aliases, environment fallbacks, settings migration or container takeover.
- Renaming CANopen-specific things (spec capabilities `canopen-*`, CANopen examples, CANopen PLC block names).
- Restarting the config `schema_version` numbering.
- Splitting the repository or the plugin.

## Decisions

### 1. Name mapping

| Old | New |
|---|---|
| repo `tonihoohoo/openplc-canopen` | `tonihoohoo/canworks` |
| distribution `openplc-canopen-deploy`, module `openplc_canopen_deploy` | `canworks` |
| commands `openplc-canopen-{deploy,config,diag,sim-runtime}` (+ `openplc-canopen-runtime`) | `canworks-{deploy,config,diag,sim-runtime}` (the extra alias is dropped) |
| editor hook `openplc-canopen-editor-hook` / `openplc_canopen_hook` | `canworks-editor-hook` / `canworks_hook` |
| plugin `canopen`, `libcanopen_plugin.so`, CMake target `canopen_plugin` | `canworks`, `libcanworks_plugin.so`, `canworks_plugin` |
| `/opt/openplc-canopen` | `/opt/canworks` |
| `conf/canopen.json`, `conf/canopen/` | `conf/canworks.json`, `conf/canworks/` |
| editor project folder `canopen/` with `canopen.json` | `canworks/` with `canworks.json` |
| generated folder `.canopen/` | `.canworks/` |
| device simulator `openplc-canopen-sim` | `canworks-sim` |
| `OPENPLC_CANOPEN_*`, `CANOPEN_FORCE_SIMULATE` | `CANWORKS_*`, `CANWORKS_FORCE_SIMULATE` |
| settings folder `openplc-canopen` | `canworks` |
| schemas `canopen.v{1,2}`, `canopen-sim.v{1,2}` | `canworks.v{1,2}`, `canworks-sim.v{1,2}` |
| image/container `openplc-canopen-sim-runtime` | `canworks-sim-runtime` |
| `openplc_canopen.stlib` | `canworks.stlib` |

The plugin's own source file names (`canopen_plugin.cpp`, `network.cpp` …) are left alone. The J1939 change moves files into `plugin/src/can/` and `plugin/src/canopen/` anyway, and renaming them twice is churn.

### 2. Clean cut, one cleanup

There is no compatibility code. The only concession is in `install-stock.sh`. When it finds a `canopen,` line in `plugins.conf`, `/opt/openplc-canopen`, or runtime-spec entries that bind `/opt/openplc-canopen`, it removes them before installing, and prints one line per item.

This is a few lines, and it keeps the bench PLC from loading two plugins on the same bus. It can be deleted in a later change.

### 3. A script makes the commit

`scripts/rename_to_canworks.py`:
- `git mv` the package, hook, schema and library paths
- applies the text mapping to tracked files, excluding `openspec/changes/archive/**`, `LICENSE` and the CANopen-specific names in the non-goals
- uses explicit patterns, not blind replacement of `canopen`, which would hit CANopen-specific words everywhere
- is idempotent

`--check` lists any old project-level name left outside the exclusions and exits non-zero. CI runs `--check` inside the existing tools job (no new job).

### 4. In-flight branches

The change merges when no other PR is open, or right after the open ones merge. A branch that still exists afterwards:
1. runs the script on itself and commits
2. merges `origin/main`

Only real content conflicts remain. The recipe is posted once in the project.

### 5. Repository rename last

The PR merges first. Then the owner renames the repository in Settings → General, and GitHub redirects the old URLs. The first release after that publishes the new wheel and image names. The new ghcr.io package starts private, so a task sets it public.

## Risks / Trade-offs

- [A pattern renames a CANopen-specific word (for example `canopen-pdo-io` or a CANopen example file)] → explicit pattern list plus the full test suite. Spec validation catches capability path changes.
- [Bench breaks after the merge until it is redeployed] → bench redeploy is a task. Install cleanup handles the PLC side.
- [Very large diff] → the rename commit is pure script output, and compatibility-free hand edits are in a separate small commit.

## Migration Plan

1. Merge the PR (0.42.0).
2. Rename the repository on GitHub.
3. Release publishes `canworks-0.42.0` and the `canworks-sim-runtime` image; set the image public.
4. Bench: reinstall the PC tools, re-run `install-stock.sh` on the PLC, rename the template project's folder, redeploy.

Rollback: revert the merge and the GitHub rename.

## Open Questions

- None.
