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
  double torque_accel = 10000;       // counts/s² per per mille of target torque (CST)
  bool sync_watchdog = true;         // cyclic modes: fault when SYNC stops
};

// Parses the simulation file's "drive" object; unknown keys are errors
// ("drive: unknown key \"x\""). nullptr gives the defaults.
bool parse_drive_settings(const cJSON* json, DriveSettings& out, std::string& err);

// Inputs of the model, set as the `drive_input` fault and by a machine model
// (the engine ORs the two).
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
  // Whether any SYNC came (else CSP/CSV/CST follow their target every tick).
  bool has_sync_seen() const { return sync_seen_; }
  // CSP set-points that moved more than the maximum velocity allows in one
  // interpolation period (0x60C2).
  uint64_t oversized_steps() const { return oversized_steps_; }
  // The interpolation time period in seconds: 0x60C2, or 10 ms without it.
  double interpolation_period() const;

  DriveInputs inputs;
  // A machine's load on the axis, per mille of rated torque: shown in the
  // actual torque (0x6077) while operation is enabled, and taken off the
  // target torque in cyclic synchronous torque mode.
  double load_permille = 0;

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
  double demand_velocity() const { return vd_; }

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
  void enter_fault(uint16_t code = 0x8611);
  void update_state(uint16_t cw, bool edge7);
  void update_mode();
  void run_mode(uint16_t cw, bool edge4, bool fall4, double dt);
  void run_pp(uint16_t cw, bool edge4, double dt);
  void run_pv(uint16_t cw, double dt);
  void run_homing(uint16_t cw, bool edge4, bool fall4, double dt);
  void run_csp(double dt);
  void run_csv();
  void run_cst(double dt);
  bool cyclic_mode() const { return mode_ >= 8 && mode_ <= 10; }
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
  double cs_pos_ = 0, cs_vel_ = 0, cs_torque_ = 0;
  bool cs_armed_ = false;     // a SYNC came in this cyclic mode with operation enabled
  double since_sync_ = 0;     // seconds since that SYNC, counted from the tick after it
  bool sync_new_ = false;     // a SYNC came since the last tick
  uint64_t oversized_steps_ = 0;
  // Homing.
  Homing hm_ = Homing::Idle;
  double hm_dir_ = 0;
  bool hm_home_ = false;  // methods 19-22: the home switch, else a limit switch
};

}  // namespace canopen_sim

#endif  // CANOPEN_SIM_DRIVE_H
