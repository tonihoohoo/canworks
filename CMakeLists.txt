# CANopen master plugin for OpenPLC Runtime v4.
#
# Built against the headers of a stock runtime checkout
# (Autonomy-Logic/openplc-runtime); scripts/install-stock.sh does this on a
# device with -DCANWORKS_BUILD_TESTS=OFF.
#
# Development build:
#   cmake -B build -DOPENPLC_ROOT=/path/to/openplc-runtime && cmake --build build
#   ctest --test-dir build
# This also builds canopen_check, the tests and the ping-pong slave unless
# -DCANWORKS_BUILD_TESTS=OFF.

cmake_minimum_required(VERSION 3.13)
project(canworks C CXX)

set(CMAKE_CXX_STANDARD 14)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_C_STANDARD 11)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)
# Only the plugin entry points (and canopen_plc_api) are exported from the .so.
set(CMAKE_C_VISIBILITY_PRESET hidden)
set(CMAKE_CXX_VISIBILITY_PRESET hidden)
set(CMAKE_VISIBILITY_INLINES_HIDDEN ON)
if(NOT CMAKE_BUILD_TYPE)
    set(CMAKE_BUILD_TYPE RelWithDebInfo)
endif()

if(NOT DEFINED OPENPLC_ROOT OR NOT EXISTS "${OPENPLC_ROOT}/core/src/drivers/plugin_types.h")
    message(FATAL_ERROR "OpenPLC runtime headers not found (OPENPLC_ROOT=${OPENPLC_ROOT}); "
                        "pass -DOPENPLC_ROOT=<runtime checkout>")
endif()
message(STATUS "canworks plugin - OpenPLC root: ${OPENPLC_ROOT}")

option(CANWORKS_BUILD_TESTS "Build canopen_check, the tests and the ping-pong slave" ON)

add_subdirectory(plugin)

if(CANWORKS_BUILD_TESTS)
    enable_testing()
    if(CANWORKS_WITH_CANOPEN)
        add_executable(canopen_check tools/canopen_check.cpp)
        target_link_libraries(canopen_check PRIVATE canopen_core)
    endif()
    add_subdirectory(test)
endif()
