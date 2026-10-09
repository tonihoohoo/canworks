// eds_lint.h - dcfgen's EDS lint and the prepared EDS copy, run through the
// deploy tool's Python module canworks.edslint (the same code
// the configurator and the deploy tool's checks run on the PC).
//
// For each node the module reads the EDS, makes the prepared copy (UTF-8,
// "$NODEID+<n>", REAL values in hex, OCTET_STRING/DOMAIN values Lely cannot
// read cleared) when a correction applies, runs dcfgen's lint and read step on
// it and judges the findings under master.eds_lint: only findings in the
// communication objects 0x1000-0x1FFF that are not only about limits stop the
// load by default. The plugin logs its verdict in the module's words.

#ifndef CANOPEN_EDS_LINT_H
#define CANOPEN_EDS_LINT_H

#include <string>
#include <vector>

#include "config.h"

namespace canopen_plugin {

// Runs the lint for every node whose EDS file exists (check_eds_files reports
// a missing one). A node whose EDS needed corrections gets the prepared copy
// <work_dir>/eds/node_<id>.eds as its eds_path, which the EDS checks and dcfgen
// then read. Corrections are added to cfg.notes, accepted findings to
// cfg.warnings (one per EDS). Returns false and appends one message per node
// the lint stops, or one if the module cannot run. `python` is the interpreter
// that has the module (default_edslint_python()).
bool run_eds_lint(Config& cfg, const std::string& python, const std::string& work_dir,
                  std::vector<std::string>& errors);

// $CANWORKS_EDSLINT, else the installer's venv python
// (<prefix>/venv/bin/python, where install-stock.sh installs the deploy tool),
// else python3 from PATH.
std::string default_edslint_python();

}  // namespace canopen_plugin

#endif  // CANOPEN_EDS_LINT_H
