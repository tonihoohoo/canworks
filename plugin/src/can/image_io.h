// image_io.h - moving values between a protocol's bus thread and the host's
// I/O image: a lock-free triple buffer for snapshots, and the writes into
// %I* and reads of %Q* the scan hooks make through the host.

#ifndef CANWORKS_IMAGE_IO_H
#define CANWORKS_IMAGE_IO_H

#include <atomic>
#include <cstdint>
#include <vector>

#include "iec_location.h"

namespace canopen_plugin {

// Single-producer/single-consumer triple buffer of fixed-size uint64 arrays.
class TripleBuffer {
 public:
  void resize(size_t n);
  size_t size() const { return size_; }

  // Producer: the buffer to fill, then publish().
  uint64_t* back() { return bufs_[back_].data(); }
  void publish();

  // Consumer: returns the newest published snapshot (or the previous one if
  // nothing new was published). Never blocks.
  const uint64_t* latest(bool* fresh = nullptr);

 private:
  static constexpr uint8_t kDirty = 0x4;
  std::vector<uint64_t> bufs_[3];
  size_t size_ = 0;
  uint8_t back_ = 0;
  uint8_t front_ = 1;
  std::atomic<uint8_t> middle_{2};
};

// The host's I/O image as the scan hooks see it: the bridge's byte image
// (bridge/bridge_host.cpp) or a test's. cycle_start writes the inputs,
// cycle_end reads the outputs between lock() and unlock(). Locations are
// byte-addressed: %IW2 is input bytes 2 and 3.
class ImageHost {
 public:
  virtual ~ImageHost() = default;
  virtual void write_input(const IecLocation& loc, uint64_t v) = 0;
  virtual uint64_t read_output(const IecLocation& loc) const = 0;
  virtual void lock() {}
  virtual void unlock() {}
};

inline void image_write_input(ImageHost& host, const IecLocation& loc, uint64_t v) { host.write_input(loc, v); }
inline uint64_t image_read_output(ImageHost& host, const IecLocation& loc) { return host.read_output(loc); }

// An ImageHost over two byte areas: the bridge's (modbus-bridge "Byte-
// addressed locations") and the tests'. Values are most significant byte
// first; with `low_first` the 16-bit words of 4- and 8-byte values come
// lowest word first. A location past an area is ignored (writes) or reads
// 0; the config check keeps them inside.
class ByteImageHost : public ImageHost {
 public:
  bool low_first = false;
  std::vector<uint8_t> in, out;

  void write_input(const IecLocation& loc, uint64_t v) override;
  uint64_t read_output(const IecLocation& loc) const override;
};

}  // namespace canopen_plugin

#endif  // CANWORKS_IMAGE_IO_H
