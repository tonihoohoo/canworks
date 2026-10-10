// mux.h - DBC-style multiplexed signals (spec can-multiplexed-signals),
// shared by raw CAN messages and J1939: the `multiplexer` and `mux` fields of
// a signal, their checks, which signals a frame carries (its page), the page
// list of a send entry and which signals can share a frame. The PC tools have
// the same rules in tools/deploy/canworks/raw/mux.py, checked against
// the multiplexing cases of test/fixtures/config/cases-raw.json and
// cases-j1939.json.

#ifndef CANWORKS_MUX_H
#define CANWORKS_MUX_H

#include <cstdint>
#include <string>
#include <vector>

struct cJSON;

namespace canworks_can {

// One value (lo == hi) or an inclusive range of switch values.
struct MuxRange {
  uint64_t lo = 0, hi = 0;
};

// The multiplexing fields of one signal as written.
struct MuxSpec {
  bool is_switch = false;           // "multiplexer": true
  bool has_mux = false;             // "mux" present
  std::string on;                   // "mux.on"; empty: the message's only switch
  std::vector<MuxRange> values;     // "mux.values", as written
  bool bad = false;                 // the fields had errors (already reported)
};

// Reads `multiplexer` and `mux` of the signal object `sig` at `path` (for
// example "networks[0].raw.rx[0].signals[2]"). Shape errors go to `errors`;
// the value-range and switch-name checks need the whole message and are made
// by MuxLayout::build.
void parse_mux_fields(const cJSON* sig, const std::string& path, MuxSpec& out, std::vector<std::string>& errors);

// A signal of a message, as far as multiplexing needs it.
struct MuxSignalDef {
  std::string name;
  std::string path;  // "networks[0].raw.rx[0].signals[2]"
  unsigned start_bit = 0;
  unsigned length = 1;
  bool big_endian = false;
  bool is_signed = false;
  MuxSpec mux;
};

// The page modes of a send entry with switches.
enum class MuxPages { Program, All, Rotate };
// Parses a `pages` value ("program", "all", "rotate"). False when unknown.
bool parse_mux_pages(const std::string& text, MuxPages& out);
const char* mux_pages_name(MuxPages p);

// At most this many pages for `all` and `rotate`.
constexpr unsigned kMuxMaxPages = 64;

// The multiplexing of one message, built once at start. Everything a frame
// needs at run time is in flat tables; evaluate() and activity() do not
// allocate.
class MuxLayout {
 public:
  // Checks the signals' multiplexing and builds the tables. Errors and
  // warnings are "<path>: <message>". False when there were errors (the
  // layout is then not multiplexed).
  bool build(const std::vector<MuxSignalDef>& sigs, std::vector<std::string>& errors,
             std::vector<std::string>& warnings);

  bool multiplexed() const { return has_switch_; }
  size_t size() const { return parent_.size(); }
  bool is_switch(size_t i) const { return is_switch_[i] != 0; }
  // The switch signal index a signal depends on, or -1.
  int parent(size_t i) const { return parent_[i]; }
  bool always(size_t i) const { return parent_[i] < 0; }

  // True when both signals can be in one frame (overlap checks).
  bool can_share(size_t a, size_t b) const;

  // Which signals a received frame of `bytes` data bytes carries. `active`
  // has size() entries.
  struct Eval {
    bool short_frame = false;  // a switch the frame needs reaches past `bytes`
    bool unknown = false;      // an active switch selects none of its signals
    unsigned need = 0;         // bytes the frame's active signals need
  };
  Eval evaluate(const uint8_t* data, unsigned bytes, uint8_t* active) const;

  // Which signals a frame carries when its switches have `values` (indexed
  // by signal; only switch entries are read). True when an active switch
  // selects none of its signals.
  bool activity(const uint64_t* values, uint8_t* active) const;

  // The number of pages of `all` and `rotate` (saturates at 2^40).
  uint64_t page_count() const;

  // The pages in order: the value of every switch (indexed by signal, 0 for
  // others and for inactive switches) and the active signals. Only call when
  // page_count() <= kMuxMaxPages.
  struct Page {
    std::vector<uint64_t> values;
    std::vector<uint8_t> active;
  };
  std::vector<Page> pages() const;

 private:
  bool in_values(size_t i, uint64_t v) const;
  // The merged values of the direct dependents of switch `s`.
  std::vector<MuxRange> candidates(size_t s) const;
  uint64_t count_switch(size_t s) const;
  void enumerate(std::vector<size_t> pending, std::vector<uint64_t>& values, std::vector<Page>& out) const;

  bool has_switch_ = false;
  std::vector<int> parent_;
  std::vector<uint8_t> is_switch_;
  std::vector<std::vector<MuxRange>> ranges_;  // merged, sorted
  std::vector<size_t> order_;                  // parents before dependents
  std::vector<unsigned> start_, length_;
  std::vector<uint8_t> big_;
  mutable std::vector<uint64_t> scratch_;      // switch values during evaluate()
};

// Merges ranges into sorted, non-overlapping, non-adjacent ones.
std::vector<MuxRange> mux_merge(std::vector<MuxRange> r);

}  // namespace canworks_can

#endif  // CANWORKS_MUX_H
