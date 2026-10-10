// The trouble code blocks' copy of the plugin interface
// (library/src/j1939_common.inc) agrees with the plugin's header
// (plugin/src/j1939/j1939_plc_api.h): same version, layout and table, and
// the copy's api() finds the plugin's table (spec j1939-plc-diagnostics).

#include <cstddef>
#include <type_traits>

#include "check.hpp"
#include "j1939_plc_api.h"

#define J1939_DM_TEST_ENTRY canworks_j1939_api_table
#include "j1939_common.inc"

namespace {

using copy_dm = j1939_dm::dm;
using copy_api = j1939_dm::api_v1;

static_assert(j1939_dm::api_version == CANWORKS_J1939_API_VERSION, "API version");
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
  CHECK(t && static_cast<const void*>(t) == canworks_j1939_api_table(CANWORKS_J1939_API_VERSION));
  CHECK(t->size == sizeof(canworks_j1939_api_v1));
  CHECK(j1939_dm::time_ms(0) == 0 && j1939_dm::time_ms(1) == 1 && j1939_dm::time_ms(1500000000LL) == 1500);
}

}  // namespace
