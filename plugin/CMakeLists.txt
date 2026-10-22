# The canworks engine, canworks-bridge and canworks-canopen-sim. Built from
# the top-level CMakeLists.txt.
#
# Lely CANopen is found with pkg-config (distro packages), falling back to
# /opt/canworks/lely (override with -DLELY_PREFIX=).

# The protocols built in (canopen-networks "Protocols built into canworks").
option(CANWORKS_WITH_CANOPEN "Build CANopen into canworks (needs Lely CANopen and dcfgen)" ON)
option(CANWORKS_WITH_J1939 "Build J1939 into canworks (Linux kernel J1939 sockets)" ON)
if(NOT CANWORKS_WITH_CANOPEN AND NOT CANWORKS_WITH_J1939)
  message(FATAL_ERROR "build at least one protocol: CANWORKS_WITH_CANOPEN or CANWORKS_WITH_J1939")
endif()

set(LELY_PREFIX "/opt/canworks/lely" CACHE PATH "Lely CANopen install prefix (fallback)")
# Where scripts/build-lely.sh put Lely and the dcfgen venv (<prefix>/venv).
set(CANWORKS_PREFIX "/opt/canworks" CACHE PATH "Install prefix of Lely and dcfgen")
if(CANWORKS_WITH_CANOPEN)
  find_package(PkgConfig REQUIRED)
  set(ENV{PKG_CONFIG_PATH} "${LELY_PREFIX}/lib/pkgconfig:$ENV{PKG_CONFIG_PATH}")
  pkg_check_modules(LELY REQUIRED liblely-coapp liblely-co liblely-io2 liblely-ev liblely-util liblely-libc)
  message(STATUS "canworks - CANopen with Lely CANopen ${LELY_liblely-coapp_VERSION} in ${LELY_LIBRARY_DIRS}")
endif()
if(CANWORKS_WITH_J1939)
  message(STATUS "canworks - J1939 on the kernel's CAN_J1939 sockets")
endif()
# The CiA 309-3 gateway (canopen-cia309-gateway) uses Lely's text layer
# (lely/co/gw_txt.h), which a Lely build configured without its gateway
# lacks: canworks is then built without the gateway, and a config with
# `cia309` is refused naming the missing part.
option(CANWORKS_WITH_CIA309 "Build the CiA 309-3 gateway into canworks (needs Lely's co_gw_txt)" ON)
set(CANWORKS_CIA309 OFF)
if(CANWORKS_WITH_CANOPEN AND CANWORKS_WITH_CIA309)
  include(CheckSymbolExists)
  set(CMAKE_REQUIRED_INCLUDES ${LELY_INCLUDE_DIRS})
  set(CMAKE_REQUIRED_LIBRARIES ${LELY_LINK_LIBRARIES})
  check_symbol_exists(co_gw_txt_create "lely/co/gw_txt.h" CANWORKS_HAVE_CO_GW_TXT)
  unset(CMAKE_REQUIRED_INCLUDES)
  unset(CMAKE_REQUIRED_LIBRARIES)
  if(CANWORKS_HAVE_CO_GW_TXT)
    set(CANWORKS_CIA309 ON)
    message(STATUS "canworks - CiA 309-3 gateway on Lely's co_gw_txt")
  else()
    message(STATUS "canworks - no CiA 309-3 gateway: this Lely CANopen has no co_gw_txt")
  endif()
endif()
# The tests build the gateway's own test only with it.
set(CANWORKS_CIA309 ${CANWORKS_CIA309} PARENT_SCOPE)
# TLS and the SCRAM login of the diagnostics channel (secure_channel.cpp).
find_package(OpenSSL 3 REQUIRED COMPONENTS SSL Crypto)

# The protocol-neutral core: the config model, diagnostics channel, adapters,
# traces and the image copies.
set(CANWORKS_CORE_SOURCES
    src/can/log.cpp
    src/can/iec_location.cpp
    src/can/image_io.cpp
    src/can/signals.cpp
    src/can/mux.cpp
    src/can/config.cpp
    src/j1939/j1939_config.cpp
    src/can/diag.cpp
    src/can/trace_capture.cpp
    src/can/frame_tx.cpp
    src/can/iface_lock.cpp
    src/can/engine.cpp
    src/can/sha256.cpp
    src/can/secure_channel.cpp
    src/can/can_adapter.cpp
    src/can/raw/config.cpp
    src/can/raw/engine.cpp
    src/can/raw/plc_frames.cpp
    src/can/raw/raw_io.cpp
    src/can/raw/raw_link.cpp
    src/can/raw/raw_devices.cpp
    src/can/raw/raw_runtime.cpp
    # Value sources and plain CAN devices of the simulation file: the raw path
    # plays plain CAN devices on any simulated network, without Lely.
    src/canopen/sim/sim_expr.cpp
    src/canopen/sim/sim_source.cpp
    src/canopen/sim/sim_raw.cpp
    third_party/cjson/cJSON.c
)
set(CANWORKS_CANOPEN_SOURCES
    src/canopen/canopen_runtime.cpp
    src/canopen/eds_check.cpp
    src/canopen/eds_lint.cpp
    src/canopen/dcf_gen.cpp
    src/canopen/process_image.cpp
    src/canopen/network.cpp
    src/canopen/network_diag.cpp
    src/canopen/network_lss.cpp
    src/canopen/network_plc.cpp
    src/canopen/plc_api.cpp
    src/canopen/plc_emcy.cpp
    src/canopen/host_requests.cpp
    src/canopen/bus.cpp
    src/canopen/bus_monitor.cpp
    src/canopen/slave_state.cpp
    src/canopen/slave_device.cpp
    src/canopen/plc_slave.cpp
    src/canopen/slave_bus.cpp
    src/canopen/gateway.cpp
    src/canopen/sim_config.cpp
    src/canopen/sim_trace.cpp
    src/canopen/raw_bridge_server.cpp
    src/canopen/sim/sim_od.cpp
    src/canopen/sim/sim_device.cpp
    src/canopen/sim/sim_file.cpp
    src/canopen/sim/sim_engine.cpp
    src/canopen/sim/sim_host.cpp
)
set(CANWORKS_J1939_SOURCES
    src/j1939/j1939_signal.cpp
    src/j1939/dm.cpp
    src/j1939/j1939_plc_api.cpp
    src/j1939/j1939_plc_msgs.cpp
    src/j1939/address_claim.cpp
    src/j1939/j1939_socket.cpp
    src/j1939/j1939_network.cpp
    src/j1939/j1939_runtime.cpp
)
set(CANWORKS_CIA309_SOURCES
    src/can/cia309_text.cpp
    src/can/cia309_server.cpp
    src/canopen/cia309_dispatch.cpp
)
set(CANWORKS_SOURCES ${CANWORKS_CORE_SOURCES})
if(CANWORKS_WITH_CANOPEN)
  list(APPEND CANWORKS_SOURCES ${CANWORKS_CANOPEN_SOURCES})
endif()
if(CANWORKS_CIA309)
  list(APPEND CANWORKS_SOURCES ${CANWORKS_CIA309_SOURCES})
endif()
if(CANWORKS_WITH_J1939)
  list(APPEND CANWORKS_SOURCES ${CANWORKS_J1939_SOURCES})
endif()

# The Modbus TCP bridge's server, byte image and own registers
# (canworks-bridge). No Lely here, so it builds and tests without it.
add_library(canworks_bridge_proto STATIC
    src/bridge/byte_image.cpp
    src/bridge/modbus.cpp
    src/bridge/modbus_server.cpp
    src/bridge/address_list.cpp
    src/bridge/bridge_blocks.cpp
)
target_include_directories(canworks_bridge_proto PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/src/bridge)
target_compile_options(canworks_bridge_proto PRIVATE -Wall -Wextra -Wno-unused-parameter)
target_link_libraries(canworks_bridge_proto PUBLIC pthread)

# The engine, which the hosts and the tests link.
add_library(canopen_core STATIC ${CANWORKS_SOURCES})
target_include_directories(canopen_core PUBLIC
    ${CMAKE_CURRENT_SOURCE_DIR}/src
    ${CMAKE_CURRENT_SOURCE_DIR}/src/can
    ${CMAKE_CURRENT_SOURCE_DIR}/src/canopen
    ${CMAKE_CURRENT_SOURCE_DIR}/src/canopen/sim
    ${CMAKE_CURRENT_SOURCE_DIR}/src/j1939
    ${CMAKE_CURRENT_SOURCE_DIR}/third_party/cjson
    ${LELY_INCLUDE_DIRS}
)
target_compile_options(canopen_core PRIVATE -Wall -Wextra -Wno-unused-parameter)
target_compile_definitions(canopen_core PRIVATE CANWORKS_PREFIX="${CANWORKS_PREFIX}")
target_compile_definitions(canopen_core PUBLIC CANWORKS_WITH_CANOPEN=$<BOOL:${CANWORKS_WITH_CANOPEN}>
                           CANWORKS_WITH_J1939=$<BOOL:${CANWORKS_WITH_J1939}>
                           CANWORKS_WITH_CIA309=$<BOOL:${CANWORKS_CIA309}>)
target_link_directories(canopen_core PUBLIC ${LELY_LIBRARY_DIRS})
target_link_libraries(canopen_core PUBLIC canworks_bridge_proto ${LELY_LIBRARIES} OpenSSL::SSL OpenSSL::Crypto pthread)

# The version the diagnostics channel reports: $CANWORKS_PLUGIN_VERSION
# when set and not empty (images and release installs, built without .git),
# else git.
if(NOT "$ENV{CANWORKS_PLUGIN_VERSION}" STREQUAL "")
  set(CANWORKS_PLUGIN_VERSION "$ENV{CANWORKS_PLUGIN_VERSION}")
else()
execute_process(COMMAND git describe --always --tags --dirty
                WORKING_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR}
                OUTPUT_VARIABLE CANWORKS_PLUGIN_VERSION OUTPUT_STRIP_TRAILING_WHITESPACE ERROR_QUIET)
endif()
if(NOT CANWORKS_PLUGIN_VERSION)
  set(CANWORKS_PLUGIN_VERSION "unknown")
endif()

if(CANWORKS_WITH_CANOPEN)
# canworks-canopen-sim, the CANopen simulator (docs/simulator.md): the
# simulator engine of canopen_core on a SocketCAN interface. It reports the
# engine's version.
add_executable(canworks-canopen-sim
    ${PROJECT_SOURCE_DIR}/tools/sim/main.cpp
    ${PROJECT_SOURCE_DIR}/tools/sim/sim_run.cpp
    ${PROJECT_SOURCE_DIR}/tools/sim/sim_commands.cpp
    ${PROJECT_SOURCE_DIR}/tools/sim/control.cpp
)
target_compile_definitions(canworks-canopen-sim PRIVATE CANWORKS_PLUGIN_VERSION="${CANWORKS_PLUGIN_VERSION}")
target_compile_options(canworks-canopen-sim PRIVATE -Wall -Wextra -Wno-unused-parameter)
target_link_libraries(canworks-canopen-sim PRIVATE canopen_core)
set_target_properties(canworks-canopen-sim PROPERTIES
    RUNTIME_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR}/bin
    BUILD_RPATH "${LELY_LIBRARY_DIRS}"
    INSTALL_RPATH "${LELY_LIBRARY_DIRS}"
)
endif()

# canworks-bridge, the Modbus TCP bridge (docs/modbus-bridge.md): the
# engine with a byte image served to Modbus clients.
add_executable(canworks-bridge
    src/bridge/bridge_host.cpp
    src/bridge/bridge_main.cpp
)
target_compile_definitions(canworks-bridge PRIVATE CANWORKS_PLUGIN_VERSION="${CANWORKS_PLUGIN_VERSION}")
target_compile_options(canworks-bridge PRIVATE -Wall -Wextra -Wno-unused-parameter)
target_link_libraries(canworks-bridge PRIVATE canopen_core canworks_bridge_proto)
set_target_properties(canworks-bridge PROPERTIES
    RUNTIME_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR}/bin
    BUILD_RPATH "${LELY_LIBRARY_DIRS}"
    INSTALL_RPATH "${LELY_LIBRARY_DIRS}"
)
