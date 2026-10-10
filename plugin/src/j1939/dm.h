// dm.h - J1939-73 diagnostic messages (j1939-diagnostics spec): the codec of
// DM1/DM2 (active and previously active trouble codes), DM13 and DM22, the
// store of every ECU's latest DM1, the network's own trouble code table and
// the DM13 suspension. Plain logic driven by the bus thread
// (j1939_network.cpp); the byte fixtures in test/fixtures/j1939-dm pin the
// codec to the PC tools' canworks/j1939/dm.py.
//
// A trouble code (DTC) on the wire is four bytes: the SPN's low 16 bits, then
// its top 3 bits above the 5-bit FMI, then the conversion method bit (CM)
// above the 7-bit occurrence count. The PLC gets one UDINT instead (design
// Decision 2): SPN + FMI * 2^19 + OC * 2^24 + CM * 2^31.

#ifndef CANWORKS_J1939_DM_H
#define CANWORKS_J1939_DM_H

#include <chrono>
#include <cstddef>
#include <cstdint>
#include <map>
#include <vector>

#include "j1939_config.h"

namespace canopen_plugin {

constexpr uint32_t kPgnDm1 = 0xFECA;   // 65226 active codes
constexpr uint32_t kPgnDm2 = 0xFECB;   // 65227 previously active codes
constexpr uint32_t kPgnDm3 = 0xFECC;   // 65228 clear previously active codes (a Request)
constexpr uint32_t kPgnDm11 = 0xFED3;  // 65235 clear active codes (a Request)
constexpr uint32_t kPgnDm13 = 0xDF00;  // 57088 stop/start broadcast
constexpr uint32_t kPgnDm22 = 0xC300;  // 49920 clear one code
constexpr unsigned kDmStoredCodes = 64;  // per source; more are counted
constexpr unsigned kOwnMaxOc = 126;
constexpr std::chrono::milliseconds kDm1Period{1000};
constexpr std::chrono::milliseconds kDm13Resume{6000};

struct J1939Dtc {
  uint32_t spn = 0;
  uint8_t fmi = 0;
  uint8_t oc = 0;
  bool cm = false;

  bool operator==(const J1939Dtc& o) const { return spn == o.spn && fmi == o.fmi && oc == o.oc && cm == o.cm; }
};

// The PLC's UDINT and back.
uint32_t dtc_value(const J1939Dtc& d);
J1939Dtc dtc_from_value(uint32_t v);
J1939Dtc dtc_from_bytes(const uint8_t* b);
void dtc_to_bytes(const J1939Dtc& d, uint8_t* b);

// A parsed DM1 or DM2.
struct DmList {
  uint8_t lamps = 0;
  uint8_t flash = 0xFF;
  std::vector<J1939Dtc> dtcs;  // the first `keep` codes, the all-zero "no code" left out
  size_t count = 0;            // codes in the message (beyond `keep` too)
};

// DM1/DM2 payload -> list; false when shorter than 6 bytes. Keeps at most
// `keep` codes in `out.dtcs` and counts them all.
bool dm_parse(const uint8_t* data, size_t len, DmList& out, size_t keep = SIZE_MAX);
// DM1/DM2 payload: at least 8 bytes; with no code one all-zero code and two
// 0xFF bytes.
std::vector<uint8_t> dm_build(uint8_t lamps, uint8_t flash, const std::vector<J1939Dtc>& dtcs);

// What a DM13 tells the current data link.
enum class Dm13Command : uint8_t { None, Stop, Start };
struct Dm13 {
  Dm13Command command = Dm13Command::None;
  bool hold = false;  // the hold signal (byte 4, bits 8-5) is not "not available"
};
Dm13 dm13_decode(const uint8_t* data, size_t len);

// The negative acknowledgement of a DM22 command (control 0x01 or 0x11), reason
// "general", or empty for any other DM22 (an acknowledgement, a short one).
std::vector<uint8_t> dm22_nack(const uint8_t* data, size_t len);

// The flash byte of active codes given as (kJ1939Lamp* bits, flash: -1 none,
// 0 slow, 1 fast): no flash (11) for each lamp unless an active code lights
// it with a flash; fast beats slow.
uint8_t dm_flash_byte(const std::vector<std::pair<uint8_t, int>>& codes);

// ---------------------------------------------------------------------------
// Every ECU's latest DM1 (design Decision 3).

class DmStore {
 public:
  using clock = std::chrono::steady_clock;
  struct Source {
    uint8_t lamps = 0;
    uint8_t flash = 0xFF;
    size_t count = 0;
    std::vector<J1939Dtc> dtcs;  // the first kDmStoredCodes
    clock::time_point last{};
    uint64_t dm1_count = 0;
    uint64_t old_format = 0;  // codes with CM set received
    bool logged = false;
  };

  // A DM1 from `source`; nullptr when it is too short. Logs the first code
  // in the older SPN format of each source.
  const Source* on_dm1(uint8_t source, const uint8_t* data, size_t len, clock::time_point now);
  const Source* find(uint8_t source) const;
  const std::map<uint8_t, Source>& sources() const { return sources_; }
  void clear() { sources_.clear(); }

 private:
  std::map<uint8_t, Source> sources_;
};

// ---------------------------------------------------------------------------
// The network's own trouble codes (design Decision 4).

class OwnDtcs {
 public:
  explicit OwnDtcs(const J1939Diagnostics& d);

  // The active bits of the last finished scan (one per own code) and the
  // lamps_location byte; true when the active set or a lamp changed.
  bool update(const std::vector<uint8_t>& active, uint8_t lamps_output);
  // DM3 (`all` false): the previously active list; DM11 (`all`): that and
  // every occurrence count, codes still active stay with OC 1. True when
  // the DM1 changed.
  bool clear(bool all);

  // The current DM1 and DM2 contents.
  uint8_t lamps() const { return lamps_; }
  uint8_t flash() const { return flash_; }
  std::vector<J1939Dtc> active() const;
  std::vector<J1939Dtc> previous() const;
  std::vector<uint8_t> dm1() const { return dm_build(lamps_, flash_, active()); }
  std::vector<uint8_t> dm2() const { return dm_build(lamps_, flash_, previous()); }

  // Per own code (config order).
  bool is_active(size_t k) const { return active_[k] != 0; }
  uint8_t oc(size_t k) const { return oc_[k]; }
  // Own code indexes in the previously active list, in the order they went.
  const std::vector<size_t>& previous_list() const { return prev_; }

 private:
  void recompute();

  const J1939Diagnostics& d_;
  std::vector<uint8_t> active_;
  std::vector<uint8_t> oc_;
  std::vector<size_t> prev_;
  uint8_t lamps_output_ = 0;
  uint8_t lamps_ = 0;
  uint8_t flash_ = 0xFF;
};

// ---------------------------------------------------------------------------
// DM13 (design Decision 6): broadcasts stop on "stop" for the current data
// link and resume on "start", or 6 s after the last stop or hold.

class Dm13State {
 public:
  using clock = std::chrono::steady_clock;
  void on_dm13(const Dm13& m, clock::time_point now);
  // Resumes when the 6 s have passed; whether broadcasts are suspended.
  bool suspended(clock::time_point now);
  bool suspended() const { return suspended_; }
  void reset() { suspended_ = false; }

 private:
  bool suspended_ = false;
  clock::time_point last_{};
};

}  // namespace canopen_plugin

#endif  // CANWORKS_J1939_DM_H
