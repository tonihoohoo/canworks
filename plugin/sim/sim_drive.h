// sim_drive.h - the CiA 402 drive model (docs/simulator.md, "CiA 402 drive model").
//
// The model works on the device's object dictionary through a DriveIo: each
// step() reads the controlword, the mode of operation and the targets,
// advances the state machine and the axis, and writes the statusword and the
// actual values. It only touches objects the device has. Positions are in
// counts, velocities in counts/s, accelerations in counts/s².

#ifndef CANOPEN_SIM_DRIVE_H
#define CANOPEN_SIM_DRIVE_H

#include <cstdint>
#include <string>
#include <utility>
#include <vector>

typedef struct cJSON cJSON;

namespace canopen_sim {

struct DriveSettings {
  double max_velocity = 100000;      // counts/s
  double max_acceleration = 1000000; // counts/s²
  double lag_ms = 5;                 // first-order lag of the actual values
  double start_position = 0;         // actual position at power on
};

// Parses the simulation file's "drive" object; unknown keys are errors
// ("drive: unknown key \"x\""). nullptr gives the defaults.
bool parse_drive_settings(const cJSON* json, DriveSettings& out, std::string& err);

// Inputs of the model, set as the `drive_input` fault.
struct DriveInputs {
  bool blocked = false, positive_limit = false, negative_limit = false, home_switch = false;
};

// The device's object dictionary, as the engine gives it.
class DriveIo {
 public:
  virtual ~DriveIo() = default;
  virtual bool has(uint16_t index, uint8_t subindex) const = 0;
  virtual double read(uint16_t index, uint8_t subindex) const = 0;
  // Writes the model's output; the engine skips objects a higher-precedence writer owns.
  virtual void write(uint16_t index, uint8_t subindex, double value) = 0;
  virtual void emcy(uint16_t code, uint8_t error_register) = 0;  // sends an EMCY
  virtual void emcy_reset() = 0;                                  // error reset EMCY (on fault reset)
};

class DriveModel {
 public:
  enum class State {
    NotReadyToSwitchOn,
    SwitchOnDisabled,
    ReadyToSwitchOn,
    SwitchedOn,
    OperationEnabled,
    QuickStopActive,
    FaultReactionActive,
    Fault
  };

  DriveModel(DriveIo& io, const DriveSettings& s);

  // "Switch on disabled" after "not ready", actual position = start_position,
  // everything else reset; writes the outputs.
  void power_on();
  // One tick of `dt` seconds: reads controlword, mode and targets, advances,
  // writes statusword and actual values.
  void step(double dt);
  // A SYNC came: the cyclic synchronous modes take their target now.
  void sync();
  // Whether any SYNC came (else CSP/CSV follow their target every tick).
  bool has_sync_seen() const { return sync_seen_; }

  DriveInputs inputs;

  // Objects the model writes (statusword 0x6041, 0x6061, 0x6064, 0x606C, ...)
  // that the device has, for the engine's precedence and status.
  std::vector<std::pair<uint16_t, uint8_t>> outputs() const;
  // Objects of the model the device does not have (left out; the engine
  // reports them once).
  std::vector<std::pair<uint16_t, uint8_t>> missing() const;

  State state() const { return state_; }
  int mode() const { return mode_; }
  uint16_t statusword() const { return sw_; }
  double actual_position() const { return pa_; }
  double actual_velocity() const { return va_; }
  double demand_position() const { return pd_; }

  const DriveSettings& settings() const { return s_; }

 private:
  enum class Homing { Idle, Search, Back, Done, Error };

  double rd(uint16_t index, uint8_t sub, double def) const;
  void wr(uint16_t index, uint8_t sub, double value);
  bool mode_supported(int mode) const;
  bool velocity_follower() const;
  bool limits_on(double& lo, double& hi) const;
  double accel(uint16_t index) const;
  double profile_velocity() const;
  double quick_stop_decel() const;

  void reset_motion();
  void enter_enabled();
  void enter_fault();
  void update_state(uint16_t cw, bool edge7);
  void update_mode();
  void run_mode(uint16_t cw, bool edge4, bool fall4, double dt);
  void run_pp(uint16_t cw, bool edge4, double dt);
  void run_pv(uint16_t cw, double dt);
  void run_homing(uint16_t cw, bool edge4, bool fall4, double dt);
  void run_csp(double dt);
  void run_csv();
  void take_setpoint(double target);
  bool move_to(double target, double v, double a, double d, double dt);
  void ramp_velocity(double target, double a, double d, double dt);
  void stop_ramp(double decel, double dt);
  double limit_velocity(double v, double decel);
  void hold_at_limit_switches();
  void follow(double dt);
  void check_following_error(double dt);
  void home_here();
  uint16_t compose_statusword(uint16_t cw) const;
  void write_outputs();

  DriveIo& io_;
  DriveSettings s_;
  State state_ = State::NotReadyToSwitchOn;
  int mode_ = 0;
  uint16_t cw_prev_ = 0;
  uint16_t sw_ = 0;
  // Actual and demand position/velocity.
  double pa_ = 0, va_ = 0, pd_ = 0, vd_ = 0;
  // Profile position.
  double pp_target_ = 0, pp_pending_target_ = 0;
  bool pp_moving_ = false, pp_pending_ = false, ack_ = false;
  // Profile velocity / CSV target.
  double v_target_ = 0;
  // Limits and following error.
  bool sw_limit_ = false, fe_ = false;
  double fe_time_ = 0;
  // Cyclic synchronous.
  bool sync_seen_ = false;
  double cs_pos_ = 0, cs_vel_ = 0;
  // Homing.
  Homing hm_ = Homing::Idle;
  double hm_dir_ = 0;
};

}  // namespace canopen_sim

#endif  // CANOPEN_SIM_DRIVE_H
