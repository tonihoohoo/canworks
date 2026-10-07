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

# The editor's ST-to-C++ compiler package, the version OpenPLC Editor 4.3.2
# ships: its runtime headers compile the library's SDO function blocks
# (library/openplc_canopen) into sim_tests the way the editor builds them into
# a PLC program (test/plc_sdo/bridge.py writes the editor's glue).
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
file(GLOB SDO_BLOCK_SOURCES ${PROJECT_SOURCE_DIR}/library/openplc_canopen/*.cpp)
set(SDO_BLOCKS_DIR ${CMAKE_CURRENT_BINARY_DIR}/sdo_blocks)
add_custom_command(
  OUTPUT ${SDO_BLOCKS_DIR}/c_blocks_code.cpp ${SDO_BLOCKS_DIR}/c_blocks.h
  COMMAND python3 ${CMAKE_CURRENT_SOURCE_DIR}/plc_sdo/bridge.py ${SDO_BLOCKS_DIR} ${SDO_BLOCK_SOURCES}
  DEPENDS ${SDO_BLOCK_SOURCES} ${CMAKE_CURRENT_SOURCE_DIR}/plc_sdo/bridge.py
  COMMENT "Editor glue for the SDO function blocks")
add_library(sdo_blocks OBJECT ${SDO_BLOCKS_DIR}/c_blocks_code.cpp)
target_include_directories(sdo_blocks PUBLIC ${SDO_BLOCKS_DIR} ${STRUCPP_DIR}/package/src/runtime/include)
# In one process with the master, the blocks call the API table directly.
target_compile_definitions(sdo_blocks PRIVATE CO_SDO_TEST_ENTRY=canopen_plc_api_test)
set_target_properties(sdo_blocks PROPERTIES CXX_STANDARD 17 CXX_EXTENSIONS ON)

add_executable(sim_tests sim/sim_tests.cpp $<TARGET_OBJECTS:sdo_blocks>)
target_include_directories(sim_tests PRIVATE common pingpong sensor ${SDO_BLOCKS_DIR}
                           ${STRUCPP_DIR}/package/src/runtime/include)
set_target_properties(sim_tests PROPERTIES CXX_STANDARD 17 CXX_EXTENSIONS ON)
add_dependencies(sim_tests sdo_blocks)
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
target_compile_definitions(plugin_lifecycle PRIVATE PINGPONG_DIR="${PINGPONG_DIR}")
add_test(NAME plugin_lifecycle
         COMMAND plugin_lifecycle $<TARGET_FILE:canopen_plugin> ${CMAKE_CURRENT_BINARY_DIR})
set_tests_properties(plugin_lifecycle PROPERTIES ENVIRONMENT "${EDSLINT_ENV}")

# Link setup on a real interface (CI: vcan0, as root and as an unprivileged
# user). Not a ctest: it needs an interface the test may change.
add_executable(link_check link/link_check.cpp)
target_link_libraries(link_check PRIVATE canopen_core)

# The simulator engine's unit tests (expressions, sources, file, scenarios).
add_executable(sim_unit_tests sim_unit/sim_unit_tests.cpp sim_unit/sim_drive_tests.cpp sim_unit/sim_file_tests.cpp)
target_include_directories(sim_unit_tests PRIVATE common)
target_compile_definitions(sim_unit_tests PRIVATE FIXTURES_DIR="${FIXTURES_DIR}" PINGPONG_DIR="${PINGPONG_DIR}" RTD_DIR="${RTD_DIR}")
target_link_libraries(sim_unit_tests PRIVATE canopen_core)
add_test(NAME sim_unit_tests COMMAND sim_unit_tests)
set_tests_properties(sim_unit_tests PROPERTIES ENVIRONMENT "${EDSLINT_ENV}")

# The SDO blocks find the loaded plugin by its SONAME (test/plc_sdo).
add_library(sdo_program SHARED plc_sdo/program.cpp ${SDO_BLOCKS_DIR}/c_blocks_code.cpp)
target_include_directories(sdo_program PRIVATE ${SDO_BLOCKS_DIR} ${STRUCPP_DIR}/package/src/runtime/include)
set_target_properties(sdo_program PROPERTIES CXX_STANDARD 17 CXX_EXTENSIONS ON PREFIX "")
add_executable(plc_sdo_lookup_check plc_sdo/lookup_check.cpp)
target_include_directories(plc_sdo_lookup_check PRIVATE common ${OPENPLC_ROOT}/core/src/drivers)
target_link_libraries(plc_sdo_lookup_check PRIVATE ${CMAKE_DL_LIBS})
add_test(NAME plc_sdo_lookup
         COMMAND ${CMAKE_CURRENT_SOURCE_DIR}/plc_sdo/lookup_check.sh $<TARGET_FILE:plc_sdo_lookup_check>
                 $<TARGET_FILE:canopen_plugin> $<TARGET_FILE:sdo_program> ${PINGPONG_DIR}
                 ${CMAKE_CURRENT_BINARY_DIR}/plc_sdo_lookup)
set_tests_properties(plc_sdo_lookup PROPERTIES ENVIRONMENT "${EDSLINT_ENV}" TIMEOUT 120)

# The library sources are what library/generate.py writes.
add_test(NAME plc_sdo_sources_current COMMAND python3 ${PROJECT_SOURCE_DIR}/library/generate.py --check)
# The .stlib the deploy tool carries is what strucpp builds from the sources
# (needs Node.js and npm; skipped without them).
find_program(NPM_PROGRAM npm)
if(NPM_PROGRAM)
  add_test(NAME plc_sdo_stlib_current COMMAND sh ${PROJECT_SOURCE_DIR}/library/build.sh --check)
  set_tests_properties(plc_sdo_stlib_current PROPERTIES
    ENVIRONMENT "STRUCPP_TGZ=${CMAKE_BINARY_DIR}/strucpp-${STRUCPP_VERSION}.tgz")
endif()

# The slave role and the gateway (canopen-slave-device, canopen-gateway): the
# plugin's master against the plugin's slave on virtual buses.
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
