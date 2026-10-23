// byte_image.cpp - see byte_image.h.

#include "byte_image.h"

#include <algorithm>
#include <cstring>

namespace canworks_bridge {

void ByteImage::resize(size_t input_bytes, size_t output_bytes) {
  std::lock_guard<std::mutex> lock(mu_);
  in_.assign((input_bytes + 1) & ~size_t(1), 0);
  out_.assign((output_bytes + 1) & ~size_t(1), 0);
  out_written_.assign(out_.size(), false);
  out_version_.fetch_add(1, std::memory_order_acq_rel);
}

void ByteImage::publish_inputs(const uint8_t* data, size_t n) {
  std::lock_guard<std::mutex> lock(mu_);
  n = std::min(n, in_.size());
  if (n) std::memcpy(in_.data(), data, n);
  std::fill(in_.begin() + static_cast<std::ptrdiff_t>(n), in_.end(), 0);
}

uint64_t ByteImage::take_outputs(uint8_t* dst, uint64_t seen) const {
  uint64_t v = out_version_.load(std::memory_order_acquire);
  if (v == seen) return v;
  std::lock_guard<std::mutex> lock(mu_);
  if (!out_.empty()) std::memcpy(dst, out_.data(), out_.size());
  return out_version_.load(std::memory_order_acquire);
}

void ByteImage::write_outputs(size_t offset, const uint8_t* data, size_t n) {
  std::lock_guard<std::mutex> lock(mu_);
  if (offset >= out_.size()) return;
  n = std::min(n, out_.size() - offset);
  std::memcpy(out_.data() + offset, data, n);
  out_version_.fetch_add(1, std::memory_order_acq_rel);
}

bool ByteImage::client_wrote(size_t offset, size_t n) const {
  std::lock_guard<std::mutex> lock(mu_);
  if (offset + n > out_written_.size()) return false;
  for (size_t i = offset; i < offset + n; ++i)
    if (!out_written_[i]) return false;
  return true;
}

void ByteImage::Access::mark_written(size_t offset, size_t n) {
  for (size_t i = offset; i < offset + n && i < img_.out_written_.size(); ++i) img_.out_written_[i] = true;
}

ByteImage::Access::~Access() {
  if (written_) img_.out_version_.fetch_add(1, std::memory_order_acq_rel);
}

void store_value(uint8_t* p, uint64_t v, unsigned nbytes, bool low_first) {
  for (unsigned i = 0; i < nbytes; ++i) p[i] = static_cast<uint8_t>(v >> (8 * (nbytes - 1 - i)));
  if (!low_first || nbytes < 4) return;
  // Reverse the order of the 16-bit words, keeping each word big-endian.
  for (unsigned a = 0, b = nbytes - 2; a < b; a += 2, b -= 2) {
    std::swap(p[a], p[b]);
    std::swap(p[a + 1], p[b + 1]);
  }
}

uint64_t load_value(const uint8_t* p, unsigned nbytes, bool low_first) {
  uint8_t tmp[8];
  std::memcpy(tmp, p, nbytes);
  if (low_first && nbytes >= 4) {
    for (unsigned a = 0, b = nbytes - 2; a < b; a += 2, b -= 2) {
      std::swap(tmp[a], tmp[b]);
      std::swap(tmp[a + 1], tmp[b + 1]);
    }
  }
  uint64_t v = 0;
  for (unsigned i = 0; i < nbytes; ++i) v = v << 8 | tmp[i];
  return v;
}

void ByteImage::set_link(size_t header_bytes, uint32_t hash) {
  std::lock_guard<std::mutex> lock(mu_);
  link_bytes_ = header_bytes;
  link_hash_ = hash;
}

ByteImage::Link ByteImage::link_state() const {
  if (!link_bytes_) return Link::kNone;
  if (out_.size() < 6) return Link::kStopped;
  if (get_be16(&out_[0]) == 0) return Link::kStopped;
  if (get_be16(&out_[0]) != 1 || link_hash_seen() != link_hash_) return Link::kMismatch;
  return Link::kOk;
}

uint32_t ByteImage::link_hash_seen() const {
  if (out_.size() < 6) return 0;
  return uint32_t(get_be16(&out_[2])) << 16 | get_be16(&out_[4]);
}

ByteImage::Link ByteImage::link_now(uint32_t* hash_seen) const {
  std::lock_guard<std::mutex> lock(mu_);
  if (hash_seen) *hash_seen = link_hash_seen();
  return link_state();
}

}  // namespace canworks_bridge
