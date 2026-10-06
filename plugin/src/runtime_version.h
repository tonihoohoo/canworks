// The runtime version guard for the managed Docker install.
//
// scripts/install-stock.sh builds the plugin inside the runtime image and
// records that image's RUNTIME_VERSION in <prefix>/lib/runtime-version. The
// bootloader can later move the device to another runtime version under the
// plugin; the plugin interface is not versioned, so the plugin refuses to
// start until it is rebuilt. Native installs have no RUNTIME_VERSION in the
// environment and are not checked here.
#pragma once

#include <string>

namespace canopen_plugin {

// Empty when the plugin may start; otherwise the error to log. `running` is
// the RUNTIME_VERSION environment variable (nullptr when unset).
std::string runtime_version_problem(const std::string& stamp_path, const char* running);

}  // namespace canopen_plugin
