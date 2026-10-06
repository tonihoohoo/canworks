// fake_runtime.hpp - a stand-in for the OpenPLC runtime's I/O image and
// journal, for tests that drive ProcessImage::copy_to_plc/copy_from_plc.

#ifndef FAKE_RUNTIME_HPP
#define FAKE_RUNTIME_HPP

#include <cstring>

extern "C" {
#include "plugin_types.h"
}

namespace fake_runtime {

constexpr int kSize = 1024;

// Storage behind the located variables. Every location "exists" here, as if
// the PLC program declared all of them.
struct Image {
  IEC_BOOL bool_in[kSize][8], bool_out[kSize][8];
  IEC_BYTE byte_in[kSize], byte_out[kSize];
  IEC_UINT int_in[kSize], int_out[kSize];
  IEC_UDINT dint_in[kSize], dint_out[kSize];
  IEC_ULINT lint_in[kSize], lint_out[kSize];

  IEC_BOOL* p_bool_in[kSize][8];
  IEC_BOOL* p_bool_out[kSize][8];
  IEC_BYTE* p_byte_in[kSize];
  IEC_BYTE* p_byte_out[kSize];
  IEC_UINT* p_int_in[kSize];
  IEC_UINT* p_int_out[kSize];
  IEC_UDINT* p_dint_in[kSize];
  IEC_UDINT* p_dint_out[kSize];
  IEC_ULINT* p_lint_in[kSize];
  IEC_ULINT* p_lint_out[kSize];

  int locks = 0, unlocks = 0, journal_writes = 0;
};

inline Image*& current() {
  static Image* img = nullptr;
  return img;
}

inline int j_bool(int type, int index, int bit, int value) {
  Image* m = current();
  ++m->journal_writes;
  if (type == 0) m->bool_in[index][bit] = value ? 1 : 0;
  return 0;
}
inline int j_byte(int type, int index, int value) {
  ++current()->journal_writes;
  if (type == 3) current()->byte_in[index] = (IEC_BYTE)value;
  return 0;
}
inline int j_int(int type, int index, int value) {
  ++current()->journal_writes;
  if (type == 5) current()->int_in[index] = (IEC_UINT)value;
  return 0;
}
inline int j_dint(int type, int index, unsigned value) {
  ++current()->journal_writes;
  if (type == 8) current()->dint_in[index] = value;
  return 0;
}
inline int j_lint(int type, int index, unsigned long long value) {
  ++current()->journal_writes;
  if (type == 11) current()->lint_in[index] = value;
  return 0;
}
inline void lock() { ++current()->locks; }
inline void unlock() { ++current()->unlocks; }

// Fills `rt` so that it points at `img`.
inline void attach(Image& img, plugin_runtime_args_t& rt) {
  std::memset(&img, 0, sizeof(img));
  std::memset(&rt, 0, sizeof(rt));
  for (int i = 0; i < kSize; ++i) {
    for (int b = 0; b < 8; ++b) {
      img.p_bool_in[i][b] = &img.bool_in[i][b];
      img.p_bool_out[i][b] = &img.bool_out[i][b];
    }
    img.p_byte_in[i] = &img.byte_in[i];
    img.p_byte_out[i] = &img.byte_out[i];
    img.p_int_in[i] = &img.int_in[i];
    img.p_int_out[i] = &img.int_out[i];
    img.p_dint_in[i] = &img.dint_in[i];
    img.p_dint_out[i] = &img.dint_out[i];
    img.p_lint_in[i] = &img.lint_in[i];
    img.p_lint_out[i] = &img.lint_out[i];
  }
  rt.bool_input = img.p_bool_in;
  rt.bool_output = img.p_bool_out;
  rt.byte_input = img.p_byte_in;
  rt.byte_output = img.p_byte_out;
  rt.int_input = img.p_int_in;
  rt.int_output = img.p_int_out;
  rt.dint_input = img.p_dint_in;
  rt.dint_output = img.p_dint_out;
  rt.lint_input = img.p_lint_in;
  rt.lint_output = img.p_lint_out;
  rt.image_lock = lock;
  rt.image_unlock = unlock;
  rt.journal_write_bool = j_bool;
  rt.journal_write_byte = j_byte;
  rt.journal_write_int = j_int;
  rt.journal_write_dint = j_dint;
  rt.journal_write_lint = j_lint;
  rt.buffer_size = kSize;
  current() = &img;
}

}  // namespace fake_runtime

#endif  // FAKE_RUNTIME_HPP
