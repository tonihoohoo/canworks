# Tasks

## 1. Server

- [x] 1.1 Tests: `open(path, "auto")` of a folder with neither `project.json` nor `canworks.json` answers 404 `no_config`; an existing project and config folder open as before.
- [x] 1.2 `State.recent()` entries carry `target` (from the folder's config, `null` when missing or unreadable) and `opened` (set by `remember()`); tests for a missing, broken and CODESYS config.
- [x] 1.3 State carries `openplc_cli` (found or not).

## 2. New config request

- [x] 2.1 Checked: an empty config fails `contract.check_config` (no nodes), so a new editor project gets no `canworks/` folder until the first save (`editorproject.create(None, …)`).
- [x] 2.2 `POST /api/new {path, editor_project}`: a config folder; with `editor_project` (OpenPLC only) an editor project, opened as a project. The target is set on the draft by the page. Refuses an existing `canworks.json` (offering to open it) and, with `editor_project`, an existing folder. Tests with a fake `openplc-cli` as `test_new_project` uses.

## 3. Start page

- [x] 3.1 `index.html`/`style.css`: purpose line, Open… (primary), New config…, Commission link, Recent rows with tags, first-run cards; remove the four cards, the inline browser and the target switch.
- [x] 3.2 `app.js`: Open… through `chooseFolder` and `openFolder(path, "auto")` with the "Start a new config here?" question; drop the not-a-project / is-a-project dialogs.
- [x] 3.3 New config dialog: target cards, folder field with Choose…, the editor-project tick (OpenPLC only, disabled with the reason when `openplc_cli` is missing), Create and Cancel, keyboard and focus as other dialogs.
- [x] 3.4 Recent rows: one click opens, Remove button, Enter opens, focus stays sensible after Remove.

## 4. Tests and docs

- [x] 4.1 Update the browser tests' start-page helper and `test_configurator_page.py`, `test_configurator_layout.py`, and every test that clicks the old card ids.
- [x] 4.2 New browser tests: Open… of a project and of a config folder from the dialog; a folder with neither offers New config; New config for each target; editor-project tick with a fake `openplc-cli`; Recent tags; first-run cards; 1000/1280/1440 px with no clipped text.
- [x] 4.3 README, `docs/configurator.md`, `docs/pc-adapter.md`, `docs/trace.md`, tour: new start page words and screenshots where they show it (no doc screenshot shows the start page).
- [x] 4.4 Bump the PC tools version (minor).

## 5. CI time

- [ ] 5.1 Compare the PR's CI wall and summed job time with the main baseline and note both in the PR.
