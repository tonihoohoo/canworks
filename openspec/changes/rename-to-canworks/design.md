## Context

The project is one public repository (`tonihoohoo/openplc-canopen`, Apache-2.0) with a native runtime plugin, PC tools (deploy, configurator, diagnostics client, simulator runtime launcher), a simulator runtime image and OpenSpec specs. The names show up in four kinds of places:

1. **Developer-facing:** the repo URL, the Python package and module paths, workflow files and docs.
2. **PC-user-facing:** command names, the wheel, the settings folder, environment variables, the container image and container name.
3. **On-device contracts:** the plugin name in `plugins.conf`, `libcanopen_plugin.so`, `/opt/openplc-canopen`, `conf/canopen.json`, the editor project's `canopen/` folder, the editor hook module the runtime spec starts, and diag port 7531.
4. **History:** archived OpenSpec changes, release tags, and the private repo.

The name `canworks` was chosen on 2026-10-09, after `opencan-plc` (2026-10-08) was dropped because the tools also work with no PLC and CODESYS may become a target. There is one user today, so a hard cut would be possible. Aliases are cheap, though, and existing scripts and venvs use the old command names.

## Goals / Non-Goals

**Goals:**
- One rename commit, produced by a script, so the diff is reviewable as "script output" and other branches can replay it.
- Old commands, environment variables, settings and the local simulator container keep working after an upgrade, with a visible hint.
- No change on any installed PLC.

**Non-Goals:**
- Renaming on-device contracts (kind 3 above).
- Renaming spec capabilities `canopen-*` (they really are CANopen).
- Splitting the repository or the plugin.
- Removing the aliases. A later change can do that.

## Decisions

### 1. Name mapping (single table, used by the script and the spec)

| Old | New |
|---|---|
| repo `tonihoohoo/openplc-canopen` | `tonihoohoo/canworks` |
| distribution `openplc-canopen-deploy` | `canworks` |
| module `openplc_canopen_deploy` | `canworks` |
| wheel `openplc_canopen_deploy-<v>-…whl` | `canworks-<v>-…whl` |
| `openplc-canopen-deploy` | `canworks-deploy` |
| `openplc-canopen-config` | `canworks-config` |
| `openplc-canopen-diag` | `canworks-diag` |
| `openplc-canopen-sim-runtime` | `canworks-sim-runtime` |
| image `ghcr.io/<owner>/openplc-canopen-sim-runtime` | `ghcr.io/<owner>/canworks-sim-runtime` |
| container `openplc-canopen-sim-runtime` | `canworks-sim-runtime` |
| settings folder `openplc-canopen` | `canworks` |
| `OPENPLC_CANOPEN_<X>` (PC tools) | `CANWORKS_<X>` |
| editor hook distribution `openplc-canopen-editor-hook` | `canworks-editor-hook` (its module stays) |

Commands are `canworks-<tool>`; one name for repo, distribution, module, image and settings folder keeps it simple. `OPENPLC_CANOPEN_SIM_*` variables that only the plugin's C++ build or the simulator read on the device stay unchanged, because they are on-device.

### 2. Aliases are thin entry points

Each old command is a console-script entry point to a small wrapper. The wrapper prints `"<old> is now <new>"` to stderr once and calls the same `main`. This is the pattern already used for `openplc-canopen-runtime` (canopen-local-runtime, "Earlier command name"). Exit status and stdout are identical, so scripts that parse output keep working.

### 3. Settings: copy, don't move

`config_dir()` returns the new folder. When the new folder does not exist and the old one does, it copies the old tree (tokens, saved runtimes, local-runtime.json, recent files) and logs one line. Moving would break an older tools version still installed in another venv (the bench has one on the PLC and one on the engineering PC).

### 4. Simulator container takeover reuses the 0.30 logic

`localruntime.py` already takes over `openplc-canopen-runtime` → `openplc-canopen-sim-runtime`. That becomes a list of earlier names, newest first. The data volume keeps its old name (saved in `local-runtime.json`), so credentials and the certificate fingerprint survive.

### 5. A script makes the commit

`scripts/rename_to_canworks.py` performs these steps:
- `git mv tools/deploy/openplc_canopen_deploy tools/deploy/canworks`
- applies the text mapping to tracked files, excluding `openspec/changes/archive/**`, `LICENSE`, and the on-device names, using an explicit allow-list of patterns rather than a blind replace
- adds the alias entry points and the fallbacks, which are hand-written code in a second commit, not script output

It is idempotent: running it twice changes nothing. `--check` exits non-zero if anything is left to rename. CI runs `--check` in the existing tools job, so a branch that missed the rename fails fast.

### 6. In-flight branches

The change merges when no other PR is open, or right after the open ones merge. A branch that still exists afterwards does this:
1. `python3 scripts/rename_to_canworks.py` on the branch (from the renamed `main`), then commit.
2. `git merge origin/main`. What is left to resolve are real content conflicts, not names.

The PR's tasks include posting this recipe once in the project, so other threads pick it up.

### 7. The GitHub repository rename is the last step, done by the owner

The PR merges first, while `main` still lives at the old URL (the new links resolve after step 2). Then the owner renames the repository in Settings → General. Until then GitHub would not redirect, so the PR body says the docs links resolve only after the rename. The first release from the renamed repo publishes the new image name. The workflow's `${{ github.repository_owner }}` is unchanged.

## Risks / Trade-offs

- [The pip upgrade path breaks because the distribution name changes, so `pip install -U openplc-canopen-deploy` stays on 0.40.0] → README and the 0.41.0 release notes give `pip uninstall openplc-canopen-deploy && pip install canworks-….whl` and the uv equivalents. Old 0.40.0 installs keep working against new runtimes, because the protocol is unchanged.
- [A blind text replace hits on-device names, so `/opt/openplc-canopen` would break installs] → the script uses explicit patterns, plus a test that `install-stock.sh` still installs to `/opt/openplc-canopen` and the plugin still registers as `canopen`.
- [ghcr.io package visibility: a new package name starts private] → task to set `canworks-sim-runtime` public after the first push. The local-runtime CI job checks an anonymous pull.
- [Rename churn on open PRs] → merge timing in Decision 6.

## Migration Plan

1. Merge this PR (version 0.41.0).
2. The owner renames the repository on GitHub.
3. The release workflow publishes `deploy-v0.41.0` with the new wheel and image. Set the image package public.
4. Run a HW check on the engineering PC: upgrade the tools, check that the old commands print the hint, the settings carry over, and the local sim runtime is taken over.

Rollback: revert the merge commit. GitHub repo rename can be undone in Settings. The old image tags are untouched.

## Open Questions

- None blocking. The aliases stay until a later change removes them.
