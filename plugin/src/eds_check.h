// eds_check.h - checks the JSON PDO entries against each node's EDS file.

#ifndef CANOPEN_EDS_CHECK_H
#define CANOPEN_EDS_CHECK_H

#include <string>
#include <vector>

#include "config.h"

namespace canopen_plugin {

// For every node: the EDS file must exist and parse (CiA 306), each PDO number
// must exist on the slave, every PDO entry must name an object the EDS
// defines as PDO-mappable, with the configured DataType and an AccessType that
// allows the direction, every startup SDO must name a writable object of the
// configured DataType, and every SDO variable must name an object of its
// DataType that allows its direction (readable or writable). Each PDO
// communication parameter set in the JSON must name a sub-index the EDS
// defines, writable unless the EDS value already matches. The deploy tool runs the same checks with the same
// messages (tools/deploy, test/fixtures/eds).
// It also settles what the EDS decides for the config: each PDO's mapping
// mode (PdoConfig::device_mapping; a device-mapped PDO's entries must be in
// the EDS default mapping) and each node's read-only PDO communication
// sub-indices and kept PDOs (NodeConfig::ro_pdo_comm, kept_tpdos/rpdos),
// adding notes and warnings to the config.
// Returns false and appends one message per problem.
bool check_eds_files(Config& cfg, std::vector<std::string>& errors);

// The value the node's EDS gives an unsigned sub-object (ParameterValue, else
// DefaultValue, $NODEID resolved). False if the EDS or the sub-object is
// missing or not UNSIGNED8/16/32.
bool eds_sub_value(const NodeConfig& n, uint16_t index, uint8_t subindex, uint64_t& value);

// The vendor ID and product code the node's EDS gives in [DeviceInfo]
// (VendorNumber, ProductNumber; 0 when not given). False if the EDS cannot be
// read.
bool eds_identity(const NodeConfig& n, uint32_t& vendor_id, uint32_t& product_code);

// The DataType (a CiA 301 type code) the node's EDS gives a sub-object. False
// if the EDS or the sub-object is missing.
bool eds_sub_type(const NodeConfig& n, uint16_t index, uint8_t subindex, uint16_t& type);

// Bytes a value of a basic CiA 301 data type takes on the bus (BOOLEAN takes
// one), or 0 for other types (strings, domains...).
unsigned co_type_bytes(uint16_t type);

}  // namespace canopen_plugin

#endif  // CANOPEN_EDS_CHECK_H
