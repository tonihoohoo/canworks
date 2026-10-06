# The plugin library. Built from the top-level CMakeLists.txt, which sets
# OPENPLC_ROOT.
#
# Lely CANopen is found with pkg-config (distro packages), falling back to
# /opt/openplc-canopen/lely (override with -DLELY_PREFIX=).

set(LELY_PREFIX "/opt/openplc-canopen/lely" CACHE PATH "Lely CANopen install prefix (fallback)")
# Where scripts/build-lely.sh put Lely and the dcfgen venv (<prefix>/venv).
set(CANOPEN_PREFIX "/opt/openplc-canopen" CACHE PATH "Install prefix of Lely and dcfgen")
find_package(PkgConfig REQUIRED)
set(ENV{PKG_CONFIG_PATH} "${LELY_PREFIX}/lib/pkgconfig:$ENV{PKG_CONFIG_PATH}")
pkg_check_modules(LELY REQUIRED liblely-coapp liblely-co liblely-io2 liblely-ev liblely-util liblely-libc)
message(STATUS "CANopen plugin - Lely CANopen ${LELY_liblely-coapp_VERSION} in ${LELY_LIBRARY_DIRS}")

set(NATIVE_DIR ${OPENPLC_ROOT}/core/src/drivers/plugins/native)

# Everything except the entry points, so the tests can link it too.
add_library(canopen_core STATIC
    src/log.cpp
    src/iec_location.cpp
    src/config.cpp
    src/eds_check.cpp
    src/eds_lint.cpp
    src/dcf_gen.cpp
    src/process_image.cpp
    src/network.cpp
    src/network_diag.cpp
    src/network_lss.cpp
    src/diag.cpp
    src/trace_capture.cpp
    src/sha256.cpp
    src/can_adapter.cpp
    src/bus.cpp
    src/bus_monitor.cpp
    src/runtime_version.cpp
    sim/sim_expr.cpp
    sim/sim_od.cpp
    sim/sim_source.cpp
    sim/sim_device.cpp
    ${NATIVE_DIR}/cjson/cJSON.c
)
target_include_directories(canopen_core PUBLIC
    ${CMAKE_CURRENT_SOURCE_DIR}/src
    ${CMAKE_CURRENT_SOURCE_DIR}/sim
    ${NATIVE_DIR}/cjson
    ${OPENPLC_ROOT}/core/src/drivers
    ${OPENPLC_ROOT}/core/src/lib
    ${LELY_INCLUDE_DIRS}
)
target_compile_options(canopen_core PRIVATE -Wall -Wextra -Wno-unused-parameter)
target_compile_definitions(canopen_core PRIVATE CANOPEN_PREFIX="${CANOPEN_PREFIX}")
target_link_directories(canopen_core PUBLIC ${LELY_LIBRARY_DIRS})
target_link_libraries(canopen_core PUBLIC ${LELY_LIBRARIES} pthread)

# The plugin version the diagnostics channel reports.
execute_process(COMMAND git describe --always --tags --dirty
                WORKING_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR}
                OUTPUT_VARIABLE CANOPEN_PLUGIN_VERSION OUTPUT_STRIP_TRAILING_WHITESPACE ERROR_QUIET)
if(NOT CANOPEN_PLUGIN_VERSION)
  set(CANOPEN_PLUGIN_VERSION "unknown")
endif()

add_library(canopen_plugin SHARED src/canopen_plugin.cpp)
target_compile_definitions(canopen_plugin PRIVATE CANOPEN_PLUGIN_VERSION="${CANOPEN_PLUGIN_VERSION}"
                           CANOPEN_PREFIX="${CANOPEN_PREFIX}")
target_link_libraries(canopen_plugin PRIVATE canopen_core)
# Keep cJSON and the core symbols private to the plugin.
target_link_options(canopen_plugin PRIVATE -Wl,--exclude-libs,ALL)
target_compile_options(canopen_plugin PRIVATE -Wall -Wextra -Wno-unused-parameter)
set_target_properties(canopen_plugin PROPERTIES
    PREFIX "lib"
    OUTPUT_NAME "canopen_plugin"
    SUFFIX ".so"
    LIBRARY_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR}/plugins
    # Find the Lely shared libraries at runtime without ld.so.conf changes.
    BUILD_RPATH "${LELY_LIBRARY_DIRS}"
    INSTALL_RPATH "${LELY_LIBRARY_DIRS}"
    # Export only the plugin entry points.
    CXX_VISIBILITY_PRESET hidden
)
