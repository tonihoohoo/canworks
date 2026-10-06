# Tests. Built from the top-level CMakeLists.txt.

set(PINGPONG_DIR ${PROJECT_SOURCE_DIR}/config/pingpong)
set(FIXTURES_DIR ${PROJECT_SOURCE_DIR}/test/fixtures)
set(RTD_DIR ${PROJECT_SOURCE_DIR}/config/rtd-sensor)

add_executable(unit_tests unit/unit_tests.cpp)
target_include_directories(unit_tests PRIVATE common)
target_compile_definitions(unit_tests PRIVATE PINGPONG_DIR="${PINGPONG_DIR}" FIXTURES_DIR="${FIXTURES_DIR}")
target_link_libraries(unit_tests PRIVATE canopen_core)
add_test(NAME unit_tests COMMAND unit_tests)
# The plugin's EDS lint runs this checkout's deploy tool module (stdlib only).
set(EDSLINT_ENV "CANOPEN_EDSLINT=python3" "PYTHONPATH=${PROJECT_SOURCE_DIR}/tools/deploy")
set_tests_properties(unit_tests PROPERTIES ENVIRONMENT "${EDSLINT_ENV}")

add_executable(sim_tests sim/sim_tests.cpp)
target_include_directories(sim_tests PRIVATE common pingpong sensor)
target_compile_definitions(sim_tests PRIVATE PINGPONG_DIR="${PINGPONG_DIR}" RTD_DIR="${RTD_DIR}" FIXTURES_DIR="${FIXTURES_DIR}")
target_link_libraries(sim_tests PRIVATE canopen_core)

# The CiA 402 example's PLC program (config/cia402-drive/drive_demo.st) runs
# in sim_cia402_demo when STruC++, the editor's compiler, is given:
# -DSTRUCPP=$(scripts/fetch-strucpp.sh). Without it that case says it was not
# built, and fails when CANOPEN_REQUIRE_STRUCPP=1 (CI).
set(STRUCPP "" CACHE FILEPATH "strucpp command (scripts/fetch-strucpp.sh), for the CiA 402 simulation test")
set(CIA402_DIR ${PROJECT_SOURCE_DIR}/config/cia402-drive)
target_include_directories(sim_tests PRIVATE drive cia402)
target_compile_definitions(sim_tests PRIVATE CIA402_DIR="${CIA402_DIR}")
if(STRUCPP)
  get_filename_component(STRUCPP_CLI "${STRUCPP}" REALPATH)
  get_filename_component(STRUCPP_PKG "${STRUCPP_CLI}/../../.." ABSOLUTE)  # <pkg>/dist/node/cli.js
  set(STRUCPP_RUNTIME "${STRUCPP_PKG}/src/runtime/include")
  if(NOT EXISTS "${STRUCPP_RUNTIME}/iec_types.hpp")
    message(FATAL_ERROR "STRUCPP=${STRUCPP}: no runtime headers at ${STRUCPP_RUNTIME}")
  endif()
  set(CIA402_GEN ${CMAKE_CURRENT_BINARY_DIR}/cia402)
  add_custom_command(
    OUTPUT ${CIA402_GEN}/drive_demo.cpp ${CIA402_GEN}/drive_demo.hpp
    COMMAND ${CMAKE_COMMAND} -E make_directory ${CIA402_GEN}
    COMMAND ${STRUCPP} ${CIA402_DIR}/drive_demo.st -o ${CIA402_GEN}/drive_demo.cpp
    DEPENDS ${CIA402_DIR}/drive_demo.st
    COMMENT "STruC++: config/cia402-drive/drive_demo.st")
  add_library(cia402_program STATIC cia402/program_host.cpp ${CIA402_GEN}/drive_demo.cpp)
  # The generated code and its runtime headers need C++17 (inline variables).
  set_target_properties(cia402_program PROPERTIES CXX_STANDARD 17)
  target_include_directories(cia402_program PRIVATE ${CIA402_GEN} ${STRUCPP_RUNTIME} cia402)
  target_compile_options(cia402_program PRIVATE -w)
  target_link_libraries(sim_tests PRIVATE cia402_program)
  target_compile_definitions(sim_tests PRIVATE CIA402_PROGRAM=1)
endif()
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

# canopen_check --dump-writes: the configuration download the plugin performs
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

# Loads the real plugin .so with a stand-in PLC scan (test/pingpong/run.sh).
add_executable(canopen_host host/canopen_host.cpp)
target_include_directories(canopen_host PRIVATE common ${OPENPLC_ROOT}/core/src/drivers)
target_link_libraries(canopen_host PRIVATE ${CMAKE_DL_LIBS})

# The entry points as the runtime calls them for a disabled and an enabled plugin.
add_executable(plugin_lifecycle host/plugin_lifecycle.cpp)
target_include_directories(plugin_lifecycle PRIVATE common ${OPENPLC_ROOT}/core/src/drivers)
target_link_libraries(plugin_lifecycle PRIVATE ${CMAKE_DL_LIBS})
add_test(NAME plugin_lifecycle
         COMMAND plugin_lifecycle $<TARGET_FILE:canopen_plugin> ${CMAKE_CURRENT_BINARY_DIR})
set_tests_properties(plugin_lifecycle PROPERTIES ENVIRONMENT "${EDSLINT_ENV}")

# Link setup on a real interface (CI: vcan0, as root and as an unprivileged
# user). Not a ctest: it needs an interface the test may change.
add_executable(link_check link/link_check.cpp)
target_link_libraries(link_check PRIVATE canopen_core)
