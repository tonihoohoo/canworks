# axe-core 4.10.2 (vendored, tests only)

The configurator's browser tests audit every view with
[axe-core](https://github.com/dequelabs/axe-core) 4.10.2 by Deque Systems,
Mozilla Public License 2.0 (see LICENSE). The file is `axe.min.js` from the
npm package `axe-core@4.10.2`, unchanged. It is injected into the test
browser by `tests/test_configurator_layout.py`; it is not part of the
configurator and is not served to users.

To update: `npm pack axe-core@<version>`, copy `axe.min.js` and LICENSE
here and change the version in this file.
