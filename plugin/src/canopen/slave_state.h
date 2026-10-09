// slave_state.h - what a slave network keeps across PLC restarts and
// uploads (canopen-slave-device "Stored parameters", "LSS slave"): the
// dictionary ranges the master saved with 0x1010 and a node ID an LSS master
// stored. One JSON file per network in the state directory, outside the
// uploaded project, written only on an explicit save or LSS store.

#ifndef CANOPEN_SLAVE_STATE_H
#define CANOPEN_SLAVE_STATE_H

#include <cstdint>
#include <map>
#include <string>
#include <vector>

namespace canopen_plugin {

struct SlaveStore {
  // Saved ranges: 'C' communication (0x1000-0x1FFF), 'M' manufacturer
  // (0x2000-0x5FFF), 'A' application (0x6000-0x9FFF), as concise DCFs.
  std::map<char, std::vector<uint8_t>> saved;
  uint8_t lss_id = 0;  // 0: none stored
};

// $CANWORKS_STATE_DIR, else <install prefix>/state.
std::string default_slave_state_dir();

// <dir>/<network>.json ("slave" for an unnamed network).
std::string slave_state_path(const std::string& dir, const std::string& network);

// Reads the file into `out`. A missing file is an empty store (true, no
// note). A file written for another EDS (SHA-256 `eds_sha256`) or one that
// cannot be read leaves `out` empty and says why in `note`.
bool load_slave_state(const std::string& path, const std::string& eds_sha256, SlaveStore& out, std::string& note);

// Writes the file (through a temporary file and a rename). False with `why`
// on failure.
bool save_slave_state(const std::string& path, const std::string& eds_sha256, unsigned node_id,
                      const SlaveStore& store, std::string& why);

}  // namespace canopen_plugin

#endif  // CANOPEN_SLAVE_STATE_H
