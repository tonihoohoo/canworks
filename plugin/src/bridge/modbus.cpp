// modbus.cpp - see modbus.h.

#include "modbus.h"

namespace canworks_bridge {

namespace {

constexpr unsigned kMaxReadRegisters = 125;
constexpr unsigned kMaxWriteRegisters = 123;
constexpr unsigned kMaxReadWriteWriteRegisters = 121;  // function 23's write part
constexpr unsigned kMaxReadBits = 2000;
constexpr unsigned kMaxWriteBits = 1968;

bool is_write(uint8_t f) {
  return f == kWriteSingleCoil || f == kWriteSingleRegister || f == kWriteMultipleCoils ||
         f == kWriteMultipleRegisters || f == kReadWriteMultipleRegisters;
}

void read_bits(const std::vector<uint8_t>& img, unsigned addr, unsigned count, std::vector<uint8_t>& resp) {
  unsigned nbytes = (count + 7) / 8;
  resp.push_back(static_cast<uint8_t>(nbytes));
  size_t at = resp.size();
  resp.resize(at + nbytes, 0);
  for (unsigned i = 0; i < count; ++i) {
    unsigned bit = addr + i;
    if (img[bit / 8] >> (bit % 8) & 1) resp[at + i / 8] |= static_cast<uint8_t>(1u << (i % 8));
  }
}

void read_registers(const std::vector<uint8_t>& img, unsigned addr, unsigned count, std::vector<uint8_t>& resp) {
  resp.push_back(static_cast<uint8_t>(count * 2));
  resp.insert(resp.end(), img.begin() + addr * 2, img.begin() + (addr + count) * 2);
}

void write_bit(std::vector<uint8_t>& img, unsigned bit, bool on) {
  uint8_t mask = static_cast<uint8_t>(1u << (bit % 8));
  if (on)
    img[bit / 8] |= mask;
  else
    img[bit / 8] &= static_cast<uint8_t>(~mask);
}

}  // namespace

void exception_pdu(uint8_t function, uint8_t code, std::vector<uint8_t>& resp) {
  resp.assign({static_cast<uint8_t>(function | 0x80), code});
}

bool handle_pdu(ByteImage& image, const uint8_t* pdu, size_t n, bool may_write, std::vector<uint8_t>& resp) {
  resp.clear();
  if (n < 1) return false;
  uint8_t f = pdu[0];
  auto fail = [&](uint8_t code) {
    exception_pdu(f, code, resp);
    return false;
  };
  auto u16 = [&](size_t at) { return get_be16(pdu + at); };

  switch (f) {
    case kReadCoils:
    case kReadDiscreteInputs:
    case kReadHoldingRegisters:
    case kReadInputRegisters:
    case kWriteSingleCoil:
    case kWriteSingleRegister:
    case kDiagnostics:
    case kWriteMultipleCoils:
    case kWriteMultipleRegisters:
    case kReadWriteMultipleRegisters:
      break;
    default:
      return fail(kIllegalFunction);
  }
  if (is_write(f) && !may_write) return fail(kIllegalFunction);

  ByteImage::Access a(image);
  const unsigned in_regs = static_cast<unsigned>(a.in().size() / 2);
  const unsigned out_regs = static_cast<unsigned>(a.out().size() / 2);

  switch (f) {
    case kReadCoils:
    case kReadDiscreteInputs: {
      if (n != 5) return fail(kIllegalDataValue);
      unsigned addr = u16(1), count = u16(3);
      if (count < 1 || count > kMaxReadBits) return fail(kIllegalDataValue);
      const std::vector<uint8_t>& img = f == kReadCoils ? a.out() : a.in();
      if (addr + count > img.size() * 8) return fail(kIllegalDataAddress);
      resp.push_back(f);
      read_bits(img, addr, count, resp);
      return false;
    }
    case kReadHoldingRegisters:
    case kReadInputRegisters: {
      if (n != 5) return fail(kIllegalDataValue);
      unsigned addr = u16(1), count = u16(3);
      if (count < 1 || count > kMaxReadRegisters) return fail(kIllegalDataValue);
      bool holding = f == kReadHoldingRegisters;
      if (addr + count > (holding ? out_regs : in_regs)) return fail(kIllegalDataAddress);
      resp.push_back(f);
      read_registers(holding ? a.out() : a.in(), addr, count, resp);
      return false;
    }
    case kWriteSingleCoil: {
      if (n != 5) return fail(kIllegalDataValue);
      unsigned addr = u16(1), value = u16(3);
      if (value != 0xFF00 && value != 0x0000) return fail(kIllegalDataValue);
      if (addr >= a.out().size() * 8) return fail(kIllegalDataAddress);
      write_bit(a.out_for_write(), addr, value == 0xFF00);
      resp.assign(pdu, pdu + n);
      return true;
    }
    case kWriteSingleRegister: {
      if (n != 5) return fail(kIllegalDataValue);
      unsigned addr = u16(1);
      if (addr >= out_regs) return fail(kIllegalDataAddress);
      std::vector<uint8_t>& out = a.out_for_write();
      out[addr * 2] = pdu[3];
      out[addr * 2 + 1] = pdu[4];
      resp.assign(pdu, pdu + n);
      return true;
    }
    case kDiagnostics: {
      // Only sub-function 0, return query data (loopback).
      if (n < 3) return fail(kIllegalDataValue);
      if (u16(1) != 0) return fail(kIllegalFunction);
      resp.assign(pdu, pdu + n);
      return false;
    }
    case kWriteMultipleCoils: {
      if (n < 6) return fail(kIllegalDataValue);
      unsigned addr = u16(1), count = u16(3), bytes = pdu[5];
      if (count < 1 || count > kMaxWriteBits || bytes != (count + 7) / 8 || n != 6 + bytes)
        return fail(kIllegalDataValue);
      if (addr + count > a.out().size() * 8) return fail(kIllegalDataAddress);
      std::vector<uint8_t>& out = a.out_for_write();
      for (unsigned i = 0; i < count; ++i) write_bit(out, addr + i, pdu[6 + i / 8] >> (i % 8) & 1);
      resp.assign(pdu, pdu + 5);
      return true;
    }
    case kWriteMultipleRegisters: {
      if (n < 6) return fail(kIllegalDataValue);
      unsigned addr = u16(1), count = u16(3), bytes = pdu[5];
      if (count < 1 || count > kMaxWriteRegisters || bytes != count * 2 || n != 6 + bytes)
        return fail(kIllegalDataValue);
      if (addr + count > out_regs) return fail(kIllegalDataAddress);
      std::vector<uint8_t>& out = a.out_for_write();
      std::copy(pdu + 6, pdu + 6 + bytes, out.begin() + addr * 2);
      resp.assign(pdu, pdu + 5);
      return true;
    }
    case kReadWriteMultipleRegisters: {
      if (n < 10) return fail(kIllegalDataValue);
      unsigned raddr = u16(1), rcount = u16(3), waddr = u16(5), wcount = u16(7), bytes = pdu[9];
      if (rcount < 1 || rcount > kMaxReadRegisters || wcount < 1 || wcount > kMaxReadWriteWriteRegisters ||
          bytes != wcount * 2 || n != 10 + bytes)
        return fail(kIllegalDataValue);
      if (raddr + rcount > out_regs || waddr + wcount > out_regs) return fail(kIllegalDataAddress);
      // The write comes first; the read returns the image after it.
      std::vector<uint8_t>& out = a.out_for_write();
      std::copy(pdu + 10, pdu + 10 + bytes, out.begin() + waddr * 2);
      resp.push_back(f);
      read_registers(out, raddr, rcount, resp);
      return true;
    }
  }
  return fail(kIllegalFunction);
}

}  // namespace canworks_bridge
