// modbus.h - Modbus application protocol (PDU) handling on the bridge's byte
// image, by the fixed register rule:
//   input byte n   -> input register n/2 (even n the high byte)
//   %IXn.b         -> discrete input n*8+b
//   output byte n  -> holding register n/2, %QXn.b -> coil n*8+b
// Holding registers and coils read back the output image.

#ifndef CANWORKS_BRIDGE_MODBUS_H
#define CANWORKS_BRIDGE_MODBUS_H

#include <cstddef>
#include <cstdint>
#include <vector>

#include "byte_image.h"

namespace canworks_bridge {

enum ModbusException : uint8_t {
  kIllegalFunction = 0x01,
  kIllegalDataAddress = 0x02,
  kIllegalDataValue = 0x03,
  kGatewayTargetFailed = 0x0B,
};

enum ModbusFunction : uint8_t {
  kReadCoils = 1,
  kReadDiscreteInputs = 2,
  kReadHoldingRegisters = 3,
  kReadInputRegisters = 4,
  kWriteSingleCoil = 5,
  kWriteSingleRegister = 6,
  kDiagnostics = 8,
  kWriteMultipleCoils = 15,
  kWriteMultipleRegisters = 16,
  kReadWriteMultipleRegisters = 23,
};

// Handles one request PDU (function code and data) under one image Access and
// puts the response PDU in `resp`. A write from a client that may not write
// gets exception 0x01 and changes nothing. Returns true for an accepted write
// request (functions 5, 6, 15, 16, 23), which feeds the output watchdog even
// when the values did not change.
bool handle_pdu(ByteImage& image, const uint8_t* pdu, size_t n, bool may_write, std::vector<uint8_t>& resp);

// The exception response for `function`.
void exception_pdu(uint8_t function, uint8_t code, std::vector<uint8_t>& resp);

}  // namespace canworks_bridge

#endif
