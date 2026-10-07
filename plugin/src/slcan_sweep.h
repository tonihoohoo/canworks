// slcan_sweep.h - bit rate detection on an slcan adapter over its serial
// device (canopen-online-diagnostics spec, "Bit rate detection").
//
// The kernel's slcan driver opens a listen-only channel with 'L', and some
// slcan firmware takes 'L' and then receives nothing. So for a sweep the
// slcan backend gives up the kernel driver and talks to the adapter itself:
// per rate "C", "S<n>", then silent mode ("m1", then "O": receive without
// acknowledging or sending) unless the firmware refuses "m1" with a BEL
// (some firmware answers no command at all), else "L". Closing
// sets the mode back with "m0", so the kernel driver's "O" opens a normal
// channel again when CANopen restarts.

#ifndef CANOPEN_SLCAN_SWEEP_H
#define CANOPEN_SLCAN_SWEEP_H

#include <string>

#include "bitrate_sweep.h"
#include "can_adapter.h"

namespace canopen_plugin {

// The link operations and the listener of run_bitrate_sweep on an slcan
// serial device opened raw (fd). The device stays the caller's.
class SlcanSweepPort : public LinkOps, public SweepListener {
 public:
  explicit SlcanSweepPort(int fd) : fd_(fd) {}
  ~SlcanSweepPort() override;  // closes the channel and sets the mode back

  int get(const std::string& name, LinkInfo& out) override;
  // Down: "C" (and "m0" after silent mode). Up: opens the channel only when
  // listen-only is set; a normal channel is the kernel driver's to open.
  int set_up(const std::string& name, bool up) override;
  // "S0".."S8" for 10, 20, 50, 100, 125, 250, 500, 800 and 1000 kbit/s;
  // -EINVAL for other rates.
  int set_bitrate(const std::string& name, unsigned bitrate, long restart_ms) override;
  int rename(const std::string&, const std::string&) override { return 0; }
  int set_txqlen(const std::string&, unsigned) override { return 0; }
  int set_listen_only(const std::string& name, bool on) override;

  int listen(const std::string& interface, unsigned ms, SweepRate& out, const std::function<bool()>& stop) override;

  // Whether a listen-only open used silent mode ("m1") rather than "L".
  bool used_silent() const { return used_silent_; }

 private:
  int send(const std::string& cmd);  // cmd + CR
  bool ask(const std::string& cmd);  // false: the firmware refused it with BEL
  void count(const std::string& line, SweepRate& out);

  int fd_;
  bool listen_only_ = false;
  bool silent_ = false;  // the firmware is in silent mode now
  bool used_silent_ = false;
  unsigned unanswered_ = 0;  // commands sent whose answer is not read yet
  std::string pending_;  // received bytes up to the next CR
};

}  // namespace canopen_plugin

#endif  // CANOPEN_SLCAN_SWEEP_H
