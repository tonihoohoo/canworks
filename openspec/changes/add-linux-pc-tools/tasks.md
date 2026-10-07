# Tasks

## 1. Docs

- [ ] 1.1 `docs/install-pc.md`: Linux in step 1 (`curl -LsSf https://astral.sh/uv/install.sh | sh`, or the distribution's package), `~/.local/bin` as the Linux bin folder, `~/.config/openplc-canopen` as the Linux settings folder, the editor AppImage and `openplc-cli install-cli` on Linux, `--no-browser` for machines without a browser, and a short "CAN adapters" note (the tools reach the bus only through the runtime; an adapter on the PC is used by a runtime on that PC, see install-stock.md).
- [ ] 1.2 `docs/install-pc.md` pip section: PEP 668 note (Debian 12+/Ubuntu 23.04+ refuse a plain pip install; use uv, pipx or a venv). Fix the release section's sentence on when the PC tools job runs (version bumps on `main`, release tags, by hand).
- [ ] 1.3 "Windows, macOS and Linux" in `docs/configurator.md`, `docs/deploy.md`, `tools/deploy/README.md`; README section "PC tools on Windows, macOS and Linux" with the same local commands (they already work in bash on Linux).

## 2. CI

- [ ] 2.1 `pc-tools.yml`: add `ubuntu-24.04` and `ubuntu-24.04-arm` to the matrix, rename the workflow to "PC tools (Windows, macOS, Linux)" and update its header comment. Verify: the existing steps run unchanged on Linux (bash default shell, `uv tool dir --bin` on PATH) and the page/parity tests skip there with their reason, as on Windows and macOS.
- [ ] 2.2 `release-deploy.yml`: the `workflow_run` list names the renamed workflow. Verify: `test/pc-tools` tests that read the workflow names (if any) still pass, and a release still waits for the PC tools run.
- [ ] 2.3 Run the PC tools workflow by hand on this branch. Verify: all four jobs green; record the Linux job times in the PR.

## 3. Hardware / desktop

- [ ] 3.1 On a Linux desktop (x86_64 or a Raspberry Pi with a desktop): install uv and the release wheel as documented, start the configurator (browser opens), install the editor AppImage, run `openplc-cli install-cli`, then New editor project and Build only from the deploy tool. Verify: the commands are found and the build produces a program.
