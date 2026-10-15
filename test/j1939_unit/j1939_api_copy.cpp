// The J1939 blocks' copy of the plugin interface
// (library/src/j1939_common.inc) agrees with the plugin's header
// (plugin/src/j1939/j1939_plc_api.h): same versions, layouts and tables, and
// the copy's api() and api2() find the plugin's tables (specs
// j1939-plc-diagnostics, j1939-plc-blocks).

#include <cstddef>
#include <type_traits>

#include "check.hpp"
#include "j1939_plc_api.h"

#define J1939_DM_TEST_ENTRY canworks_j1939_api_table
#include "j1939_common.inc"

namespace {

using copy_dm = j1939_dm::dm;
using copy_api = j1939_dm::api_v1;

static_assert(j1939_dm::api_version == 1, "trouble code blocks: version 1");
static_assert(j1939_dm::api_version_msgs == CANWORKS_J1939_API_VERSION, "message blocks: the newest version");
static_assert(j1939_dm::max_length == CANWORKS_J1939_MAX_LENGTH, "message length");
static_assert(j1939_dm::rx_any == CANWORKS_J1939_RX_ANY &&
                  j1939_dm::rx_all_destinations == CANWORKS_J1939_RX_ALL_DESTINATIONS,
              "receiver flags");
static_assert(j1939_dm::err_bus == CANWORKS_J1939_ERR_BUS && j1939_dm::err_cancelled == CANWORKS_J1939_ERR_CANCELLED,
              "error IDs");

using copy_msg = j1939_dm::msg;
static_assert(sizeof(copy_msg) == sizeof(canworks_j1939_msg), "msg size");
static_assert(offsetof(copy_msg, pgn) == offsetof(canworks_j1939_msg, pgn), "pgn");
static_assert(offsetof(copy_msg, source) == offsetof(canworks_j1939_msg, source), "source");
static_assert(offsetof(copy_msg, destination) == offsetof(canworks_j1939_msg, destination), "destination");
static_assert(offsetof(copy_msg, priority) == offsetof(canworks_j1939_msg, priority), "priority");
static_assert(offsetof(copy_msg, ack_code) == offsetof(canworks_j1939_msg, ack_code), "ack_code");
static_assert(offsetof(copy_msg, length) == offsetof(canworks_j1939_msg, length), "length");
static_assert(offsetof(copy_msg, time_us) == offsetof(canworks_j1939_msg, time_us), "time_us");
static_assert(offsetof(copy_msg, data) == offsetof(canworks_j1939_msg, data), "data");
using copy_rx = j1939_dm::rx_info;
static_assert(sizeof(copy_rx) == sizeof(canworks_j1939_rx_info), "rx_info size");
static_assert(offsetof(copy_rx, queued) == offsetof(canworks_j1939_rx_info, queued), "queued");
static_assert(offsetof(copy_rx, overflow) == offsetof(canworks_j1939_rx_info, overflow), "overflow");
static_assert(offsetof(copy_rx, bus_down) == offsetof(canworks_j1939_rx_info, bus_down), "bus_down");
static_assert(offsetof(copy_rx, dropped) == offsetof(canworks_j1939_rx_info, dropped), "dropped");
using copy_info = j1939_dm::ecu_info;
static_assert(sizeof(copy_info) == sizeof(canworks_j1939_ecu_info), "ecu_info size");
static_assert(offsetof(copy_info, state) == offsetof(canworks_j1939_ecu_info, state), "state");
static_assert(offsetof(copy_info, address) == offsetof(canworks_j1939_ecu_info, address), "address");
static_assert(offsetof(copy_info, ecu_count) == offsetof(canworks_j1939_ecu_info, ecu_count), "ecu_count");
static_assert(offsetof(copy_info, name) == offsetof(canworks_j1939_ecu_info, name), "name");
using copy_found = j1939_dm::ecu_found;
static_assert(sizeof(copy_found) == sizeof(canworks_j1939_ecu_found), "ecu_found size");
static_assert(offsetof(copy_found, found) == offsetof(canworks_j1939_ecu_found, found), "found");
static_assert(offsetof(copy_found, address) == offsetof(canworks_j1939_ecu_found, address), "found address");
static_assert(offsetof(copy_found, count) == offsetof(canworks_j1939_ecu_found, count), "count");
static_assert(offsetof(copy_found, name) == offsetof(canworks_j1939_ecu_found, name), "found name");
using copy_api2 = j1939_dm::api_v2;
static_assert(sizeof(copy_api2) == sizeof(canworks_j1939_api_v2), "table 2 size");
#define SAME_SLOT(f) static_assert(offsetof(copy_api2, f) == offsetof(canworks_j1939_api_v2, f), #f)
SAME_SLOT(size);
SAME_SLOT(dm_read_start);
SAME_SLOT(cancel);
SAME_SLOT(send_start);
SAME_SLOT(send_poll);
SAME_SLOT(request_start);
SAME_SLOT(request_poll);
SAME_SLOT(msg_cancel);
SAME_SLOT(rx_open);
SAME_SLOT(rx_read);
SAME_SLOT(rx_close);
SAME_SLOT(ecu_info);
SAME_SLOT(find_ecu);
#undef SAME_SLOT
static_assert(sizeof(unsigned long long) == sizeof(uint64_t), "NAME width");
static_assert(j1939_dm::max_codes == CANWORKS_J1939_DM_CODES, "codes per read");
static_assert(j1939_dm::err_not_running == CANWORKS_J1939_ERR_NOT_RUNNING &&
                  j1939_dm::err_input == CANWORKS_J1939_ERR_INPUT,
              "error IDs");

static_assert(sizeof(copy_dm) == sizeof(canworks_j1939_dm), "canworks_j1939_dm size");
static_assert(offsetof(copy_dm, lamps) == offsetof(canworks_j1939_dm, lamps), "lamps");
static_assert(offsetof(copy_dm, flash) == offsetof(canworks_j1939_dm, flash), "flash");
static_assert(offsetof(copy_dm, count) == offsetof(canworks_j1939_dm, count), "count");
static_assert(offsetof(copy_dm, age_ms) == offsetof(canworks_j1939_dm, age_ms), "age_ms");
static_assert(offsetof(copy_dm, dtcs) == offsetof(canworks_j1939_dm, dtcs), "dtcs");
static_assert(sizeof(copy_dm{}.dtcs) == sizeof(canworks_j1939_dm{}.dtcs), "dtcs size");

static_assert(sizeof(copy_api) == sizeof(canworks_j1939_api_v1), "table size");
static_assert(offsetof(copy_api, size) == offsetof(canworks_j1939_api_v1, size), "size");
static_assert(offsetof(copy_api, dm_read_start) == offsetof(canworks_j1939_api_v1, dm_read_start), "dm_read_start");
static_assert(offsetof(copy_api, dm_read_poll) == offsetof(canworks_j1939_api_v1, dm_read_poll), "dm_read_poll");
static_assert(offsetof(copy_api, dm_clear_start) == offsetof(canworks_j1939_api_v1, dm_clear_start), "dm_clear_start");
static_assert(offsetof(copy_api, dm_clear_poll) == offsetof(canworks_j1939_api_v1, dm_clear_poll), "dm_clear_poll");
static_assert(offsetof(copy_api, cancel) == offsetof(canworks_j1939_api_v1, cancel), "cancel");

// The functions' types, with the copy's structs standing for the plugin's.
template <typename A, typename B>
constexpr bool same() {
  return std::is_same<A, B>::value;
}
static_assert(same<decltype(copy_api::dm_read_start), decltype(canworks_j1939_api_v1::dm_read_start)>(), "");
static_assert(same<decltype(copy_api::dm_clear_start), decltype(canworks_j1939_api_v1::dm_clear_start)>(), "");
static_assert(same<decltype(copy_api::dm_clear_poll), decltype(canworks_j1939_api_v1::dm_clear_poll)>(), "");
static_assert(same<decltype(copy_api::cancel), decltype(canworks_j1939_api_v1::cancel)>(), "");
static_assert(same<decltype(copy_api::dm_read_poll), int (*)(unsigned int, copy_dm*, unsigned short*)>() &&
                  same<decltype(canworks_j1939_api_v1::dm_read_poll),
                       int (*)(uint32_t, canworks_j1939_dm*, uint16_t*)>(),
              "");

TEST(j1939_api_copy_finds_the_table) {
  const copy_api* t = j1939_dm::api();
  CHECK(t && static_cast<const void*>(t) == canworks_j1939_api_table(1));
  CHECK(t->size == sizeof(canworks_j1939_api_v1));
  const copy_api2* t2 = j1939_dm::api2();
  CHECK(t2 && static_cast<const void*>(t2) == canworks_j1939_api_table(CANWORKS_J1939_API_VERSION));
  CHECK(t2->size == sizeof(canworks_j1939_api_v2));
  CHECK(j1939_dm::time_ms(0) == 0 && j1939_dm::time_ms(1) == 1 && j1939_dm::time_ms(1500000000LL) == 1500);
}

}  // namespace
