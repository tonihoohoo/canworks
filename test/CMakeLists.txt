# Tests. Built from the top-level CMakeLists.txt.

set(PINGPONG_DIR ${PROJECT_SOURCE_DIR}/config/pingpong)
set(FIXTURES_DIR ${PROJECT_SOURCE_DIR}/test/fixtures)
set(RTD_DIR ${PROJECT_SOURCE_DIR}/config/rtd-sensor)

# The J1939 engine on a fake socket (no kernel J1939 module needed).
if(CANWORKS_WITH_J1939)
  add_executable(j1939_unit_tests j1939_unit/j1939_unit_tests.cpp)
  target_include_directories(j1939_unit_tests PRIVATE common)
  target_compile_definitions(j1939_unit_tests PRIVATE FIXTURES_DIR="${FIXTURES_DIR}")
  target_link_libraries(j1939_unit_tests PRIVATE canopen_core)
  add_test(NAME j1939_unit_tests COMMAND j1939_unit_tests)
  # The kernel socket's long send numbering on vcan0 (needs can-j1939; run by
  # the vcan CI job, test/j1939/long_ids.cpp).
  add_executable(j1939_long_ids j1939/long_ids.cpp)
  target_link_libraries(j1939_long_ids PRIVATE canopen_core)
endif()

# Raw CAN (can-raw-messages): the frame port and its call table, the raw
# config and engine, and the I/O thread on a simulated bus.
add_executable(can_raw_tests can_raw/raw_tests.cpp)
target_include_directories(can_raw_tests PRIVATE common)
target_compile_definitions(can_raw_tests PRIVATE FIXTURES_DIR="${FIXTURES_DIR}")
target_link_libraries(can_raw_tests PRIVATE canopen_core)
add_test(NAME can_raw_tests COMMAND can_raw_tests)

# The frame port from four threads at once. Built from
# plc_frames.cpp alone so that -DCANWORKS_TSAN=ON (the weekly workflow)
# instruments the port: cmake --build <dir> --target can_frames_stress.
option(CANWORKS_TSAN "Build can_frames_stress with ThreadSanitizer" OFF)
find_package(Threads REQUIRED)
add_executable(can_frames_stress can_raw/frames_stress.cpp ${PROJECT_SOURCE_DIR}/plugin/src/can/raw/plc_frames.cpp)
target_include_directories(can_frames_stress PRIVATE common ${PROJECT_SOURCE_DIR}/plugin/src)
target_link_libraries(can_frames_stress PRIVATE Threads::Threads)
if(CANWORKS_TSAN)
  # TSan does not model fences; the port only fences over atomic data.
  target_compile_options(can_frames_stress PRIVATE -fsanitize=thread -g -O1 $<$<CXX_COMPILER_ID:GNU>:-Wno-tsan>)
  target_link_options(can_frames_stress PRIVATE -fsanitize=thread)
endif()
add_test(NAME can_frames_stress COMMAND can_frames_stress)

# Everything below is CANopen (CANWORKS_WITH_CANOPEN).
if(NOT CANWORKS_WITH_CANOPEN)
  return()
endif()

add_executable(unit_tests unit/unit_tests.cpp)
target_include_directories(unit_tests PRIVATE common)
target_compile_definitions(unit_tests PRIVATE PINGPONG_DIR="${PINGPONG_DIR}" FIXTURES_DIR="${FIXTURES_DIR}")
target_link_libraries(unit_tests PRIVATE canopen_core)
add_test(NAME unit_tests COMMAND unit_tests)
# The CiA 309-3 gateway's text layer, dispatcher and server (canopen-cia309-gateway).
if(CANWORKS_CIA309)
  add_executable(cia309_tests unit/cia309_tests.cpp)
  target_include_directories(cia309_tests PRIVATE common)
  target_link_libraries(cia309_tests PRIVATE canopen_core)
  add_test(NAME cia309_tests COMMAND cia309_tests)
  set_tests_properties(cia309_tests PROPERTIES TIMEOUT 120)
endif()
# The engine's EDS lint runs this checkout's deploy tool module (stdlib only).
set(EDSLINT_ENV "CANWORKS_EDSLINT=python3" "PYTHONPATH=${PROJECT_SOURCE_DIR}/tools/deploy")
set_tests_properties(unit_tests PROPERTIES ENVIRONMENT "${EDSLINT_ENV}")

# The editor's ST-to-C++ compiler package, the version OpenPLC Editor 4.3.2
# ships: its runtime headers compile the library's ST helpers for their tests.
set(STRUCPP_VERSION 0.7.0)
set(STRUCPP_SHA256 8d78ae92d931b87c06145520222d1491206f424c147ec66ea84653cb8b0e1be5)
set(STRUCPP_DIR ${CMAKE_BINARY_DIR}/strucpp-${STRUCPP_VERSION})
if(NOT EXISTS ${STRUCPP_DIR}/package/src/runtime/include/iec_std_lib.hpp)
  file(DOWNLOAD https://github.com/Autonomy-Logic/STruCpp/releases/download/v${STRUCPP_VERSION}/strucpp-${STRUCPP_VERSION}.tgz
       ${CMAKE_BINARY_DIR}/strucpp-${STRUCPP_VERSION}.tgz EXPECTED_HASH SHA256=${STRUCPP_SHA256})
  file(MAKE_DIRECTORY ${STRUCPP_DIR})
  execute_process(COMMAND tar xzf ${CMAKE_BINARY_DIR}/strucpp-${STRUCPP_VERSION}.tgz -C ${STRUCPP_DIR}
                  RESULT_VARIABLE strucpp_untar)
  if(NOT strucpp_untar EQUAL 0)
    message(FATAL_ERROR "cannot unpack strucpp ${STRUCPP_VERSION}")
  endif()
endif()
# The ST helpers of the packaged library (CAN_*, J1939_*) against the
# shared vectors.
add_test(NAME can_st_helpers COMMAND python3 ${CMAKE_CURRENT_SOURCE_DIR}/library/st_helpers.py
         ${STRUCPP_DIR}/package/src/runtime/include ${CMAKE_CURRENT_BINARY_DIR}/st_helpers)
add_test(NAME j1939_st_dtc COMMAND python3 ${CMAKE_CURRENT_SOURCE_DIR}/library/st_dtc.py
         ${STRUCPP_DIR}/package/src/runtime/include ${CMAKE_CURRENT_BINARY_DIR}/st_dtc)
add_test(NAME j1939_st_functions COMMAND python3 ${CMAKE_CURRENT_SOURCE_DIR}/library/st_j1939.py
         ${STRUCPP_DIR}/package/src/runtime/include ${CMAKE_CURRENT_BINARY_DIR}/st_j1939)

add_executable(sim_tests sim/sim_tests.cpp)
target_include_directories(sim_tests PRIVATE common pingpong sensor)
target_compile_definitions(sim_tests PRIVATE PINGPONG_DIR="${PINGPONG_DIR}" RTD_DIR="${RTD_DIR}" FIXTURES_DIR="${FIXTURES_DIR}")
target_link_libraries(sim_tests PRIVATE canopen_core)

# One ctest test per TEST() case, so `ctest -j` overlaps their real-time waits.
file(STRINGS sim/sim_tests.cpp SIM_CASES REGEX "^TEST\\([a-z0-9_]+\\)")
if(NOT SIM_CASES)
  message(FATAL_ERROR "no TEST() cases found in test/sim/sim_tests.cpp")
endif()
set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS sim/sim_tests.cpp)
foreach(line IN LISTS SIM_CASES)
  string(REGEX REPLACE "^TEST\\(([a-z0-9_]+)\\).*" "\\1" name "${line}")
  add_test(NAME sim_tests.${name} COMMAND sim_tests --exact ${name})
  set_tests_properties(sim_tests.${name} PROPERTIES TIMEOUT 180 ENVIRONMENT "${EDSLINT_ENV}")
endforeach()

# canopen_check --dump-writes: the configuration download the engine performs
# (the deploy tool's DCF export is checked against this list).
add_test(NAME dump_writes_pingpong
         COMMAND ${PROJECT_SOURCE_DIR}/test/dump/run.sh $<TARGET_FILE:canopen_check>
                 ${PROJECT_SOURCE_DIR}/config/pingpong ${PROJECT_SOURCE_DIR}/test/dump/pingpong.expected
                 ${CMAKE_CURRENT_BINARY_DIR}/dump_pingpong)
set_tests_properties(dump_writes_pingpong PROPERTIES ENVIRONMENT "${EDSLINT_ENV}")

# The tutorial ping-pong slave on a SocketCAN interface (test/pingpong/run.sh).
add_executable(pingpong_slave pingpong/slave.cpp)
target_include_directories(pingpong_slave PRIVATE pingpong)
target_link_libraries(pingpong_slave PRIVATE canopen_core)

# The ping-pong slave as an LSS device without a node ID (test/lss/run.sh).
add_executable(lss_slave lss/lss_slave.cpp)
target_include_directories(lss_slave PRIVATE pingpong)
target_link_libraries(lss_slave PRIVATE canopen_core)

# A simulated measuring device driven by a vendor EDS (test/sensor/run.sh).
add_executable(sensor_slave sensor/slave.cpp)
target_include_directories(sensor_slave PRIVATE sensor)
target_link_libraries(sensor_slave PRIVATE canopen_core)

# A stand-in PLC that runs canworks-bridge with a config and reads and writes
# it over Modbus TCP as OpenPLC's Modbus master would (test/pingpong/run.sh).
add_executable(canopen_host host/canopen_host.cpp)
target_include_directories(canopen_host PRIVATE common)
target_link_libraries(canopen_host PRIVATE canopen_core canworks_bridge_proto)

# Link setup on a real interface (CI: vcan0, as root and as an unprivileged
# user). Not a ctest: it needs an interface the test may change.
add_executable(link_check link/link_check.cpp)
target_link_libraries(link_check PRIVATE canopen_core)

# The simulator engine's unit tests (expressions, sources, file, scenarios)
# and its control channel.
add_executable(sim_unit_tests sim_unit/sim_unit_tests.cpp sim_unit/sim_file_tests.cpp
               sim_unit/sim_raw_tests.cpp
               sim_unit/sim_control_tests.cpp ${PROJECT_SOURCE_DIR}/tools/sim/control.cpp)
target_include_directories(sim_unit_tests PRIVATE common ${PROJECT_SOURCE_DIR}/tools/sim)
target_compile_definitions(sim_unit_tests PRIVATE FIXTURES_DIR="${FIXTURES_DIR}" PINGPONG_DIR="${PINGPONG_DIR}" RTD_DIR="${RTD_DIR}")
target_link_libraries(sim_unit_tests PRIVATE canopen_core)
add_test(NAME sim_unit_tests COMMAND sim_unit_tests)
set_tests_properties(sim_unit_tests PROPERTIES ENVIRONMENT "${EDSLINT_ENV}")


# The .stlib the deploy tool carries is what strucpp builds from the sources
# (needs Node.js and npm; skipped without them).
find_program(NPM_PROGRAM npm)
if(NPM_PROGRAM)
  add_test(NAME library_stlib_current COMMAND sh ${PROJECT_SOURCE_DIR}/library/build.sh --check)
  set_tests_properties(library_stlib_current PROPERTIES
    ENVIRONMENT "STRUCPP_TGZ=${CMAKE_BINARY_DIR}/strucpp-${STRUCPP_VERSION}.tgz")
endif()

# The slave role and the gateway (canopen-slave-device, canopen-gateway): the
# engine's master against its slave on virtual buses.
add_executable(slave_tests slave/slave_tests.cpp)
target_include_directories(slave_tests PRIVATE common pingpong)
target_compile_definitions(slave_tests PRIVATE PINGPONG_DIR="${PINGPONG_DIR}"
                           CONFIG_DIR="${PROJECT_SOURCE_DIR}/config")
target_link_libraries(slave_tests PRIVATE canopen_core)
file(STRINGS slave/slave_tests.cpp SLAVE_CASES REGEX "^TEST\\([a-z0-9_]+\\)")
set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS slave/slave_tests.cpp)
foreach(line IN LISTS SLAVE_CASES)
  string(REGEX REPLACE "^TEST\\(([a-z0-9_]+)\\).*" "\\1" name "${line}")
  add_test(NAME slave_tests.${name} COMMAND slave_tests --exact ${name})
  set_tests_properties(slave_tests.${name} PROPERTIES TIMEOUT 180 ENVIRONMENT "${EDSLINT_ENV}")
endforeach()

# The master and its own slave on one simulated bus (adapter.simulate and the
# same interface on both networks), through canworks-bridge.
add_test(NAME slave_simulated_bus COMMAND bash ${CMAKE_CURRENT_SOURCE_DIR}/slave/simulated.sh ${CMAKE_BINARY_DIR} 6)
set_tests_properties(slave_simulated_bus PROPERTIES TIMEOUT 120 ENVIRONMENT "${EDSLINT_ENV}")

# The Modbus bridge's server, register rule and own registers, with a Modbus
# TCP client over loopback (modbus-bridge).
add_executable(bridge_tests bridge/bridge_tests.cpp)
target_include_directories(bridge_tests PRIVATE common)
target_link_libraries(bridge_tests PRIVATE canworks_bridge_proto)
add_test(NAME bridge_tests COMMAND bridge_tests)
set_tests_properties(bridge_tests PROPERTIES TIMEOUT 60)

# canworks-bridge end to end: the example on its simulated bus with a Modbus
# TCP client (modbus-bridge).
add_executable(bridge_host_tests bridge/bridge_host_tests.cpp ${PROJECT_SOURCE_DIR}/plugin/src/bridge/bridge_host.cpp)
target_include_directories(bridge_host_tests PRIVATE common)
target_compile_definitions(bridge_host_tests PRIVATE EXAMPLE_DIR="${PROJECT_SOURCE_DIR}/examples/modbus-bridge"
                           OPENPLC_EXAMPLE_DIR="${PROJECT_SOURCE_DIR}/examples/openplc-modbus"
                           FIXTURES_DIR="${FIXTURES_DIR}")
target_link_libraries(bridge_host_tests PRIVATE canopen_core canworks_bridge_proto)
add_test(NAME bridge_host_tests COMMAND bridge_host_tests)
set_tests_properties(bridge_host_tests PROPERTIES TIMEOUT 120 ENVIRONMENT "${EDSLINT_ENV}")
# Its config upload over the diagnostics channel (put_config).
add_test(NAME bridge_upload COMMAND python3 ${CMAKE_CURRENT_SOURCE_DIR}/bridge/upload_test.py
         $<TARGET_FILE:canworks-bridge> ${PROJECT_SOURCE_DIR}/examples/modbus-bridge)
set_tests_properties(bridge_upload PROPERTIES TIMEOUT 120 ENVIRONMENT "${EDSLINT_ENV}")
# The CiA 309-3 gateway end to end: canworks-bridge on a simulated bus with
# the deploy tool's client (test/cia309/run.sh).
if(CANWORKS_CIA309)
  add_test(NAME cia309_gateway COMMAND bash ${CMAKE_CURRENT_SOURCE_DIR}/cia309/run.sh --build-dir ${CMAKE_BINARY_DIR})
  set_tests_properties(cia309_gateway PROPERTIES TIMEOUT 240 ENVIRONMENT "${EDSLINT_ENV}")
endif()
# scripts/install-bridge.sh with a stub systemctl.
add_test(NAME bridge_install COMMAND bash ${CMAKE_CURRENT_SOURCE_DIR}/bridge/install_test.sh $<TARGET_FILE:canworks-bridge>)
# scripts/install-link.sh with stub systemctl and pip (the remote link).
add_test(NAME link_install COMMAND bash ${CMAKE_CURRENT_SOURCE_DIR}/link/install_test.sh)

# The longest tests start first under `ctest -j` (seconds on a CI runner), so
# none of them is left running alone at the end.
foreach(pair IN ITEMS unit_tests:37 sim_tests.sim_simulated_power_cycles:24
                      sim_tests.sim_lss_diag_commissioning:15 bridge_host_tests:11)
  string(REPLACE ":" ";" pair "${pair}")
  list(GET pair 0 name)
  list(GET pair 1 cost)
  if(TEST ${name})
    set_tests_properties(${name} PROPERTIES COST ${cost})
  endif()
endforeach()
