// fake_host.hpp - a stand-in for the host's byte image (image_io.h), for
// tests that drive the scan hooks (ProcessImage::copy_to_plc/copy_from_plc
// and the protocol runtimes).
//
// The image is byte-addressed as a bridge config's locations are: %ID100 is
// input bytes 100-103, %IX10.0 bit 0 of input byte 10. The views read and
// write it by location, most significant byte first:
//   img.dint_in[100]      %ID100     img.bool_out[20][1]   %QX20.1
// so a test reads `img.int_in[40]` where its config has %IW40.

#ifndef FAKE_HOST_HPP
#define FAKE_HOST_HPP

#include <algorithm>
#include <cstdint>
#include <vector>

#include "byte_image.h"
#include "image_io.h"

namespace fake_host {

constexpr int kSize = 8192;

// The value of `N` bytes at byte `i` of an area.
template <typename T, unsigned N>
class Ref {
 public:
  Ref(std::vector<uint8_t>& a, unsigned i) : a_(a), i_(i) {}
  operator T() const { return static_cast<T>(canworks_bridge::load_value(&a_[i_], N, false)); }
  Ref& operator=(T v) {
    canworks_bridge::store_value(&a_[i_], static_cast<uint64_t>(v), N, false);
    return *this;
  }
  Ref& operator=(const Ref& o) { return *this = static_cast<T>(o); }

 private:
  std::vector<uint8_t>& a_;
  unsigned i_;
};

template <typename T, unsigned N>
class Area {
 public:
  explicit Area(std::vector<uint8_t>& a) : a_(a) {}
  Ref<T, N> operator[](unsigned i) const { return Ref<T, N>(a_, i); }

 private:
  std::vector<uint8_t>& a_;
};

// Bit `b` of byte `i`: 0 or 1.
class BitRef {
 public:
  BitRef(std::vector<uint8_t>& a, unsigned i, unsigned b) : a_(a), i_(i), b_(b) {}
  operator uint8_t() const { return (a_[i_] >> b_) & 1; }
  BitRef& operator=(unsigned v) {
    if (v)
      a_[i_] = static_cast<uint8_t>(a_[i_] | (1u << b_));
    else
      a_[i_] = static_cast<uint8_t>(a_[i_] & ~(1u << b_));
    return *this;
  }
  BitRef& operator=(const BitRef& o) { return *this = static_cast<uint8_t>(o); }

 private:
  std::vector<uint8_t>& a_;
  unsigned i_, b_;
};

class BitRow {
 public:
  BitRow(std::vector<uint8_t>& a, unsigned i) : a_(a), i_(i) {}
  BitRef operator[](unsigned b) const { return BitRef(a_, i_, b); }

 private:
  std::vector<uint8_t>& a_;
  unsigned i_;
};

class BitArea {
 public:
  explicit BitArea(std::vector<uint8_t>& a) : a_(a) {}
  BitRow operator[](unsigned i) const { return BitRow(a_, i); }

 private:
  std::vector<uint8_t>& a_;
};

// The image behind the located variables. Every location "exists" here, as
// if the program used all of them.
struct Image : canopen_plugin::ByteImageHost {
  Image() { reset(); }
  Image(const Image&) = delete;
  Image& operator=(const Image&) = delete;

  void reset() {
    in.assign(kSize, 0);
    out.assign(kSize, 0);
    locks = unlocks = journal_writes = 0;
  }
  void write_input(const canopen_plugin::IecLocation& loc, uint64_t v) override {
    ++journal_writes;
    ByteImageHost::write_input(loc, v);
  }
  void lock() override { ++locks; }
  void unlock() override { ++unlocks; }

  BitArea bool_in{in}, bool_out{out};
  Area<uint8_t, 1> byte_in{in}, byte_out{out};
  Area<uint16_t, 2> int_in{in}, int_out{out};
  Area<uint32_t, 4> dint_in{in}, dint_out{out};
  Area<uint64_t, 8> lint_in{in}, lint_out{out};

  int locks = 0, unlocks = 0, journal_writes = 0;
};

// What the scan hooks get: the image a test attached.
struct Runtime : canopen_plugin::ImageHost {
  Image* img = nullptr;
  void write_input(const canopen_plugin::IecLocation& loc, uint64_t v) override { img->write_input(loc, v); }
  uint64_t read_output(const canopen_plugin::IecLocation& loc) const override { return img->read_output(loc); }
  void lock() override { img->lock(); }
  void unlock() override { img->unlock(); }
};

// Clears `img` and points `rt` at it.
inline void attach(Image& img, Runtime& rt) {
  img.reset();
  rt.img = &img;
}

}  // namespace fake_host

#endif  // FAKE_HOST_HPP
