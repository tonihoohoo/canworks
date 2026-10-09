// byte_image.h - the bridge's process image: an input and an output byte
// array, most significant byte first, shared between the bus side and the
// Modbus server.
//
// Every Modbus request runs under one Access, so a read sees one input
// snapshot and a write publishes one output snapshot. The bus side publishes
// a whole input snapshot at once and takes the newest output snapshot, so a
// value spanning several registers never mixes two snapshots. The lock is
// held only for a copy of the image; nothing blocks on the bus.

#ifndef CANWORKS_BRIDGE_BYTE_IMAGE_H
#define CANWORKS_BRIDGE_BYTE_IMAGE_H

#include <atomic>
#include <cstddef>
#include <cstdint>
#include <mutex>
#include <vector>

namespace canworks_bridge {

class ByteImage {
 public:
  // Sizes are rounded up to an even number of bytes (whole registers).
  void resize(size_t input_bytes, size_t output_bytes);
  size_t input_size() const { return in_.size(); }
  size_t output_size() const { return out_.size(); }

  // Bus side: replace the input image with `n` bytes (the rest reads 0).
  void publish_inputs(const uint8_t* data, size_t n);
  // Bus side: copy the output image into `dst` (output_size() bytes) when it
  // changed since `seen`; returns the current output version.
  uint64_t take_outputs(uint8_t* dst, uint64_t seen) const;
  uint64_t output_version() const { return out_version_.load(std::memory_order_acquire); }
  // Bus side: overwrite output bytes (the "zero" action of outputs off).
  void write_outputs(size_t offset, const uint8_t* data, size_t n);

  // One request's view of both images, under the image lock.
  class Access {
   public:
    explicit Access(ByteImage& img) : img_(img), lock_(img.mu_) {}
    ~Access();
    const std::vector<uint8_t>& in() const { return img_.in_; }
    const std::vector<uint8_t>& out() const { return img_.out_; }
    // Writable output bytes; publishes a new output version when the Access ends.
    std::vector<uint8_t>& out_for_write() {
      written_ = true;
      return img_.out_;
    }

   private:
    ByteImage& img_;
    std::lock_guard<std::mutex> lock_;
    bool written_ = false;
  };

 private:
  mutable std::mutex mu_;
  std::vector<uint8_t> in_;
  std::vector<uint8_t> out_;
  std::atomic<uint64_t> out_version_{0};
};

// Big-endian helpers for the image and the bridge blocks.
inline uint16_t get_be16(const uint8_t* p) { return static_cast<uint16_t>(p[0] << 8 | p[1]); }
inline uint32_t get_be32(const uint8_t* p) {
  return uint32_t(p[0]) << 24 | uint32_t(p[1]) << 16 | uint32_t(p[2]) << 8 | p[3];
}
inline void put_be16(uint8_t* p, uint16_t v) {
  p[0] = static_cast<uint8_t>(v >> 8);
  p[1] = static_cast<uint8_t>(v);
}
inline void put_be32(uint8_t* p, uint32_t v) {
  put_be16(p, static_cast<uint16_t>(v >> 16));
  put_be16(p + 2, static_cast<uint16_t>(v));
}

// Stores a value of `nbytes` (1, 2, 4 or 8) at `p`, most significant byte
// first. With `low_first` the 16-bit words of a 4- or 8-byte value are stored
// lowest word first, for clients that expect that word order.
void store_value(uint8_t* p, uint64_t v, unsigned nbytes, bool low_first);
uint64_t load_value(const uint8_t* p, unsigned nbytes, bool low_first);

}  // namespace canworks_bridge

#endif
