// layout_check.cpp - the library's copy of the plugin's C interface
// (library/src/common.inc) against the plugin's header
// (plugin/src/canopen/canopen_plc_api.h): sizes and field offsets of every
// structure of versions 1 and 2. A compile-time check; main() only runs.

#include <cstddef>

#include "canopen_plc_api.h"
#include "../../library/src/common.inc"

#define SAME_SIZE(a, b) static_assert(sizeof(a) == sizeof(b), #a " and " #b " differ in size")
#define SAME_FIELD(a, b, f) static_assert(offsetof(a, f) == offsetof(b, f), #a "." #f " moved")

SAME_SIZE(canopen_plc_request, co_sdo::request);
SAME_FIELD(canopen_plc_request, co_sdo::request, timeout_ms);
SAME_FIELD(canopen_plc_request, co_sdo::request, data);
SAME_FIELD(canopen_plc_request, co_sdo::request, length);
SAME_SIZE(canopen_plc_result, co_sdo::result);
SAME_FIELD(canopen_plc_result, co_sdo::result, abort_code);
SAME_FIELD(canopen_plc_result, co_sdo::result, size);
SAME_SIZE(canopen_plc_api_v1, co_sdo::api_v1);
SAME_FIELD(canopen_plc_api_v1, co_sdo::api_v1, poll);
SAME_SIZE(canopen_plc_api_v2, co_sdo::api_v2);
SAME_FIELD(canopen_plc_api_v2, co_sdo::api_v2, start);
SAME_FIELD(canopen_plc_api_v2, co_sdo::api_v2, poll);
SAME_FIELD(canopen_plc_api_v2, co_sdo::api_v2, emcy_begin);
SAME_FIELD(canopen_plc_api_v2, co_sdo::api_v2, emcy_read);
SAME_SIZE(canopen_plc_emcy, co_sdo::emcy);
SAME_FIELD(canopen_plc_emcy, co_sdo::emcy, seq);
SAME_FIELD(canopen_plc_emcy, co_sdo::emcy, error_code);
SAME_FIELD(canopen_plc_emcy, co_sdo::emcy, node);
SAME_FIELD(canopen_plc_emcy, co_sdo::emcy, error_register);
SAME_FIELD(canopen_plc_emcy, co_sdo::emcy, msef);
SAME_SIZE(canopen_plc_emcy_cursor, co_sdo::emcy_cursor);
SAME_FIELD(canopen_plc_emcy_cursor, co_sdo::emcy_cursor, next);
SAME_SIZE(canopen_plc_emcy_info, co_sdo::emcy_info);
SAME_FIELD(canopen_plc_emcy_info, co_sdo::emcy_info, lost);
// Version 2 begins with version 1's fields.
static_assert(offsetof(canopen_plc_api_v2, poll) == offsetof(canopen_plc_api_v1, poll), "v2 is not a superset of v1");
static_assert(sizeof(canopen_plc_emcy) == 24, "an EMCY queue entry is 24 bytes");
static_assert(co_sdo::api_version == 1 && co_sdo::api_version_emcy == CANOPEN_PLC_API_VERSION, "versions");

int main() { return 0; }
