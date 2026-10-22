## 1. Shared EDS list

- [ ] 1.1 Move the Add node dialog's device-description list into a shared function in `app.js`: groups, product names, use counts, EDS library fill, **Browse…** import with the replace or keep-both question (EDS lint passed in), and resolving a library pick through `/api/online/use_eds`
- [ ] 1.2 Add node dialog uses it, with no visible change
- [ ] 1.3 Enter or double-click on a list entry presses the dialog's main button; focus starts in the list, or on Browse… when it is empty

## 2. Slave device page

- [ ] 2.1 EDS field: product name and file name as text (or the None yet line), **Choose EDS…** and **Export EDS**; remove the dropdown and the "Use an EDS file…" input
- [ ] 2.2 "Choose the slave's EDS" dialog: Built here, In this project, EDS library; current EDS selected; Use / Cancel; Browse… with the slave's EDS lint; focus back to Choose EDS… on close

## 3. Checks and docs

- [ ] 3.1 Page tests: slave picks from In this project, Built here and the EDS library; Browse… with a name clash (keep both); Cancel keeps the EDS; empty state; Add node tests pass; Enter and double-click in both dialogs
- [ ] 3.2 docs/configurator.md (slave device); PC tools minor version bump; release notes line
