#include "image_io.h"

#include <cstring>

#include "byte_image.h"

namespace canopen_plugin {

// ---------------------------------------------------------------------------
// TripleBuffer

void TripleBuffer::resize(size_t n) {
  size_ = n;
  for (auto& b : bufs_) b.assign(n ? n : 1, 0);
  back_ = 0;
  front_ = 1;
  middle_.store(2, std::memory_order_relaxed);
}

void TripleBuffer::publish() {
  // Hand the filled buffer over and take the spare one. The new back buffer
  // starts as a copy of the published one, so a producer that only updates
  // some slots keeps the others.
  uint8_t filled = back_;
  uint8_t prev = middle_.exchange(filled | kDirty, std::memory_order_acq_rel);
  back_ = prev & 0x3;
  std::memcpy(bufs_[back_].data(), bufs_[filled].data(), bufs_[filled].size() * sizeof(uint64_t));
}

const uint64_t* TripleBuffer::latest(bool* fresh) {
  bool got = false;
  if (middle_.load(std::memory_order_acquire) & kDirty) {
    uint8_t prev = middle_.exchange(front_, std::memory_order_acq_rel);
    front_ = prev & 0x3;
    got = true;
  }
  if (fresh) *fresh = got;
  return bufs_[front_].data();
}

// ---------------------------------------------------------------------------
// ByteImageHost

namespace {

unsigned location_bytes(IecSize size) {
  switch (size) {
    case IecSize::X:
    case IecSize::B: return 1;
    case IecSize::W: return 2;
    case IecSize::D: return 4;
    case IecSize::L: return 8;
  }
  return 1;
}

}  // namespace

void ByteImageHost::write_input(const IecLocation& loc, uint64_t v) {
  const unsigned n = location_bytes(loc.size);
  if (loc.index >= in.size() || n > in.size() - loc.index) return;
  if (loc.size == IecSize::X) {
    uint8_t mask = static_cast<uint8_t>(1u << loc.bit);
    if (v)
      in[loc.index] |= mask;
    else
      in[loc.index] &= static_cast<uint8_t>(~mask);
    return;
  }
  canworks_bridge::store_value(&in[loc.index], v, n, low_first);
}

uint64_t ByteImageHost::read_output(const IecLocation& loc) const {
  const unsigned n = location_bytes(loc.size);
  if (loc.index >= out.size() || n > out.size() - loc.index) return 0;
  if (loc.size == IecSize::X) return (out[loc.index] >> loc.bit) & 1;
  return canworks_bridge::load_value(&out[loc.index], n, low_first);
}

}  // namespace canopen_plugin
