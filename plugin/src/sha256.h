// sha256.h - SHA-256 (FIPS 180-4), for the diagnostics token check and the
// configuration fingerprint. Small and self-contained so the plugin needs no
// crypto library.

#ifndef CANOPEN_SHA256_H
#define CANOPEN_SHA256_H

#include <array>
#include <cstddef>
#include <cstdint>
#include <string>

namespace canopen_plugin {

std::array<uint8_t, 32> sha256(const void* data, size_t len);
// Lower-case hexadecimal digest.
std::string sha256_hex(const std::string& data);
// Compares two equal-length strings without an early exit.
bool equal_constant_time(const std::string& a, const std::string& b);

}  // namespace canopen_plugin

#endif  // CANOPEN_SHA256_H
