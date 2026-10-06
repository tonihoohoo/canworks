// program_host.cpp - see program_host.h.

#include "program_host.h"

#include <cstring>
#include <memory>

#include "drive_demo.hpp"

namespace program_host {

namespace {
std::unique_ptr<strucpp::Program_MAIN>& program() {
  static std::unique_ptr<strucpp::Program_MAIN> p;
  return p;
}

// Bytes behind a located variable of this size, and the table element it uses.
void* slot(const Image& img, const strucpp::LocatedVar& v, bool input, size_t& bytes) {
  using strucpp::LocatedSize;
  int i = v.byte_index;
  if (i >= img.size) return nullptr;
  switch (v.size) {
    case LocatedSize::Bit: bytes = 1; return input ? &img.bool_in[i][v.bit_index] : &img.bool_out[i][v.bit_index];
    case LocatedSize::Byte: bytes = 1; return input ? &img.byte_in[i] : &img.byte_out[i];
    case LocatedSize::Word: bytes = 2; return input ? &img.int_in[i] : &img.int_out[i];
    case LocatedSize::DWord: bytes = 4; return input ? &img.dint_in[i] : &img.dint_out[i];
    default: return nullptr;
  }
}
}  // namespace

void Reset() {
  program().reset();  // the new instance points locatedVars at itself
  program().reset(new strucpp::Program_MAIN());
}

void Scan(const Image& img, int64_t now_ns) {
  if (!program()) Reset();
  strucpp::__CURRENT_TIME_NS = now_ns;
  for (uint32_t k = 0; k < strucpp::locatedVarsCount; ++k) {
    const strucpp::LocatedVar& v = strucpp::locatedVars[k];
    size_t bytes = 0;
    void* at = v.area == strucpp::LocatedArea::Input ? slot(img, v, true, bytes) : nullptr;
    if (at && v.pointer) std::memcpy(v.pointer, at, bytes);
  }
  program()->run();
  for (uint32_t k = 0; k < strucpp::locatedVarsCount; ++k) {
    const strucpp::LocatedVar& v = strucpp::locatedVars[k];
    size_t bytes = 0;
    void* at = v.area == strucpp::LocatedArea::Output ? slot(img, v, false, bytes) : nullptr;
    if (at && v.pointer) std::memcpy(at, v.pointer, bytes);
  }
}

int Step() { return program() ? static_cast<int>(program()->STEP.get()) : -1; }

int LocatedCount() { return static_cast<int>(strucpp::locatedVarsCount); }

}  // namespace program_host
