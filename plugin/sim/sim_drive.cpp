#include "sim_drive.h"

#include <algorithm>
#include <cmath>

#include "cJSON.h"

namespace canopen_sim {

namespace {

constexpr double kOff32 = 4294967295.0;  // 0xFFFFFFFF: window off
constexpr double kStopped = 1.0;         // counts/s: the axis counts as stopped

// The model's objects: (index, subindex, written by the model).
struct ModelObject {
  uint16_t index;
  uint8_t sub;
  bool core;    // reported when missing
  bool output;  // written by the model
};

const ModelObject kObjects[] = {
    {0x603F, 0, false, true},  // error code
    {0x6040, 0, true, false},  // controlword
    {0x6041, 0, true, true},   // statusword
    {0x605A, 0, false, false}, // quick stop option code
    {0x6060, 0, true, false},  // modes of operation
    {0x6061, 0, true, true},   // modes of operation display
    {0x6062, 0, false, true},  // position demand value
    {0x6063, 0, false, true},  // position actual internal value
    {0x6064, 0, true, true},   // position actual value
    {0x6065, 0, true, false},  // following error window
    {0x6066, 0, true, false},  // following error time out
    {0x6067, 0, false, false}, // position window
    {0x606B, 0, false, true},  // velocity demand value
    {0x606C, 0, true, true},   // velocity actual value
    {0x606D, 0, false, false}, // velocity window
    {0x606F, 0, false, false}, // velocity threshold
    {0x607A, 0, true, false},  // target position
    {0x607C, 0, true, false},  // home offset
    {0x607D, 1, true, false},  // software position limit min
    {0x607D, 2, true, false},  // software position limit max
    {0x6081, 0, true, false},  // profile velocity
    {0x6083, 0, true, false},  // profile acceleration
    {0x6084, 0, true, false},  // profile deceleration
    {0x6085, 0, false, false}, // quick stop deceleration
    {0x6098, 0, true, false},  // homing method
    {0x6099, 1, true, false},  // speed during search for switch
    {0x6099, 2, true, false},  // speed during search for zero
    {0x609A, 0, false, false}, // homing acceleration
    {0x60F4, 0, false, true},  // following error actual value
    {0x6071, 0, false, false}, // target torque
    {0x6077, 0, false, true},  // torque actual value
    {0x60C2, 1, false, false}, // interpolation time period value
    {0x60C2, 2, false, false}, // interpolation time index
    {0x60FF, 0, true, false},  // target velocity
    {0x6502, 0, false, false}, // supported drive modes
};

double sgn(double v) { return v > 0 ? 1 : v < 0 ? -1 : 0; }

double clampd(double v, double lo, double hi) { return std::max(lo, std::min(hi, v)); }

}  // namespace

bool parse_drive_settings(const cJSON* json, DriveSettings& out, std::string& err) {
  DriveSettings s;
  if (!json) {
    out = s;
    return true;
  }
  if (!cJSON_IsObject(json)) {
    err = "drive: must be an object";
    return false;
  }
  for (const cJSON* c = json->child; c; c = c->next) {
    std::string key = c->string ? c->string : "";
    double* dst = nullptr;
    bool positive = true;
    if (key == "sync_watchdog") {
      if (!cJSON_IsBool(c)) {
        err = "drive: \"sync_watchdog\" must be true or false";
        return false;
      }
      s.sync_watchdog = cJSON_IsTrue(c);
      continue;
    }
    if (key == "max_velocity") dst = &s.max_velocity;
    else if (key == "max_acceleration") dst = &s.max_acceleration;
    else if (key == "lag_ms") dst = &s.lag_ms, positive = false;
    else if (key == "start_position") dst = &s.start_position, positive = false;
    else if (key == "torque_accel") dst = &s.torque_accel;
    else {
      err = "drive: unknown key \"" + key + "\"";
      return false;
    }
    if (!cJSON_IsNumber(c)) {
      err = "drive: \"" + key + "\" must be a number";
      return false;
    }
    double v = c->valuedouble;
    if (positive && !(v > 0)) {
      err = "drive: \"" + key + "\" must be greater than 0";
      return false;
    }
    if (key == "lag_ms" && v < 0) {
      err = "drive: \"lag_ms\" must not be negative";
      return false;
    }
    *dst = v;
  }
  out = s;
  return true;
}

DriveModel::DriveModel(DriveIo& io, const DriveSettings& s) : io_(io), s_(s) {}

double DriveModel::rd(uint16_t index, uint8_t sub, double def) const {
  return io_.has(index, sub) ? io_.read(index, sub) : def;
}

void DriveModel::wr(uint16_t index, uint8_t sub, double value) {
  if (io_.has(index, sub)) io_.write(index, sub, value);
}

std::vector<std::pair<uint16_t, uint8_t>> DriveModel::outputs() const {
  std::vector<std::pair<uint16_t, uint8_t>> out;
  for (const auto& o : kObjects)
    if (o.output && io_.has(o.index, o.sub)) out.emplace_back(o.index, o.sub);
  return out;
}

std::vector<std::pair<uint16_t, uint8_t>> DriveModel::missing() const {
  std::vector<std::pair<uint16_t, uint8_t>> out;
  for (const auto& o : kObjects)
    if (o.core && !io_.has(o.index, o.sub)) out.emplace_back(o.index, o.sub);
  return out;
}

bool DriveModel::mode_supported(int mode) const {
  if (mode != 1 && mode != 3 && mode != 6 && mode != 8 && mode != 9 && mode != 10) return false;
  if (!io_.has(0x6502, 0)) return true;
  uint32_t mask = static_cast<uint32_t>(io_.read(0x6502, 0));
  return (mask >> (mode - 1)) & 1u;
}

bool DriveModel::velocity_follower() const { return mode_ == 3 || mode_ == 9 || mode_ == 10; }

double DriveModel::interpolation_period() const {
  if (!io_.has(0x60C2, 1) || !io_.has(0x60C2, 2)) return 0.01;
  double v = io_.read(0x60C2, 1);
  int e = static_cast<int>(static_cast<int8_t>(static_cast<int>(io_.read(0x60C2, 2))));
  double t = v * std::pow(10.0, e);
  return t > 0 ? t : 0.01;
}

bool DriveModel::limits_on(double& lo, double& hi) const {
  lo = rd(0x607D, 1, 0);
  hi = rd(0x607D, 2, 0);
  return lo != 0 || hi != 0;
}

double DriveModel::accel(uint16_t index) const {
  double a = rd(index, 0, 0);
  if (!(a > 0) || a > s_.max_acceleration) a = s_.max_acceleration;
  return a;
}

double DriveModel::profile_velocity() const {
  double v = std::fabs(rd(0x6081, 0, 0));
  if (!(v > 0) || v > s_.max_velocity) v = s_.max_velocity;
  return v;
}

double DriveModel::quick_stop_decel() const { return accel(0x6085); }

void DriveModel::reset_motion() {
  pd_ = pa_;
  vd_ = 0;
  pp_target_ = pa_;
  pp_moving_ = pp_pending_ = ack_ = false;
  v_target_ = 0;
  sw_limit_ = fe_ = false;
  fe_time_ = 0;
  if (hm_ == Homing::Search || hm_ == Homing::Back) hm_ = Homing::Idle;
}

void DriveModel::power_on() {
  state_ = State::NotReadyToSwitchOn;
  pa_ = s_.start_position;
  va_ = 0;
  cw_prev_ = 0;
  sync_seen_ = false;
  cs_pos_ = cs_vel_ = cs_torque_ = 0;
  cs_armed_ = false;
  since_sync_ = 0;
  hm_ = Homing::Idle;
  hm_dir_ = 0;
  reset_motion();
  int m = static_cast<int>(static_cast<int8_t>(static_cast<int>(rd(0x6060, 0, 0))));
  mode_ = mode_supported(m) ? m : 0;
  wr(0x603F, 0, 0);
  // Self-test done: "not ready to switch on" -> "switch on disabled".
  state_ = State::SwitchOnDisabled;
  sw_ = compose_statusword(0);
  write_outputs();
}

void DriveModel::sync() {
  sync_seen_ = true;
  double pos = rd(0x607A, 0, pd_);
  bool following = state_ == State::OperationEnabled && cyclic_mode();
  if (following && cs_armed_ && mode_ == 8 &&
      std::fabs(pos - cs_pos_) > s_.max_velocity * interpolation_period() * (1 + 1e-6) + 0.5)
    ++oversized_steps_;
  cs_pos_ = pos;
  cs_vel_ = rd(0x60FF, 0, 0);
  cs_torque_ = rd(0x6071, 0, 0);
  if (following) cs_armed_ = true;
  since_sync_ = 0;
  sync_new_ = true;
}

void DriveModel::enter_enabled() {
  state_ = State::OperationEnabled;
  reset_motion();
  vd_ = 0;
  cs_pos_ = pa_;
  cs_armed_ = false;
}

// 0x8611 following error, 0x8700 SYNC lost (error register: generic,
// communication).
void DriveModel::enter_fault(uint16_t code) {
  state_ = State::FaultReactionActive;
  pp_moving_ = pp_pending_ = ack_ = false;
  cs_armed_ = false;
  if (hm_ == Homing::Search || hm_ == Homing::Back) hm_ = Homing::Idle;
  wr(0x603F, 0, code);
  io_.emcy(code, code == 0x8700 ? 0x11 : 0x01);
}

void DriveModel::update_state(uint16_t cw, bool edge7) {
  if (state_ == State::Fault) {
    if (edge7) {
      state_ = State::SwitchOnDisabled;
      fe_ = false;
      fe_time_ = 0;
      wr(0x603F, 0, 0);
      io_.emcy_reset();
    }
    return;
  }
  if (state_ == State::FaultReactionActive || state_ == State::NotReadyToSwitchOn) return;
  if (cw & 0x80) return;  // fault reset bit outside fault: no command
  bool disable_voltage = !(cw & 0x02);
  bool quick_stop = (cw & 0x06) == 0x02;
  bool shutdown = (cw & 0x07) == 0x06;
  bool switch_on = (cw & 0x0F) == 0x07;
  bool enable = (cw & 0x0F) == 0x0F;
  switch (state_) {
    case State::SwitchOnDisabled:
      if (shutdown) state_ = State::ReadyToSwitchOn;
      break;
    case State::ReadyToSwitchOn:
      if (disable_voltage || quick_stop) state_ = State::SwitchOnDisabled;
      else if (switch_on) state_ = State::SwitchedOn;
      else if (enable) enter_enabled();  // transitions 3 and 4 at once
      break;
    case State::SwitchedOn:
      if (disable_voltage || quick_stop) state_ = State::SwitchOnDisabled;
      else if (shutdown) state_ = State::ReadyToSwitchOn;
      else if (enable) enter_enabled();
      break;
    case State::OperationEnabled:
      if (disable_voltage) state_ = State::SwitchOnDisabled;
      else if (quick_stop) {
        state_ = State::QuickStopActive;
        pp_moving_ = pp_pending_ = ack_ = false;
        if (hm_ == Homing::Search || hm_ == Homing::Back) hm_ = Homing::Idle;
      } else if (shutdown) state_ = State::ReadyToSwitchOn;
      else if (switch_on) state_ = State::SwitchedOn;
      break;
    case State::QuickStopActive: {
      int option = static_cast<int>(rd(0x605A, 0, 2));
      bool stay = option >= 5 && option <= 8;
      bool stopped = vd_ == 0 && std::fabs(va_) < kStopped;
      if (disable_voltage) state_ = State::SwitchOnDisabled;
      else if (stay && stopped && enable) enter_enabled();
      else if (!stay && stopped) state_ = State::SwitchOnDisabled;
      break;
    }
    default:
      break;
  }
}

void DriveModel::update_mode() {
  int m = static_cast<int>(static_cast<int8_t>(static_cast<int>(rd(0x6060, 0, mode_))));
  if (m == mode_ || !mode_supported(m)) return;
  bool was_velocity = velocity_follower();
  mode_ = m;
  pd_ = pa_;
  if (was_velocity != velocity_follower()) vd_ = va_;
  pp_target_ = pa_;
  pp_moving_ = pp_pending_ = ack_ = false;
  sw_limit_ = fe_ = false;
  fe_time_ = 0;
  cs_pos_ = pa_;
  cs_armed_ = false;
  if (hm_ == Homing::Search || hm_ == Homing::Back) hm_ = Homing::Idle;
}

void DriveModel::step(double dt) {
  if (!(dt > 0) || state_ == State::NotReadyToSwitchOn) return;
  uint16_t cw = static_cast<uint16_t>(static_cast<uint32_t>(rd(0x6040, 0, 0)));
  bool edge4 = (cw & 0x10) && !(cw_prev_ & 0x10);
  bool fall4 = !(cw & 0x10) && (cw_prev_ & 0x10);
  bool edge7 = (cw & 0x80) && !(cw_prev_ & 0x80);
  update_state(cw, edge7);
  update_mode();
  if (state_ != State::OperationEnabled) cs_armed_ = false;
  // The SYNC came somewhere within the last tick: counting from the tick
  // after it never faults early and at most one tick late.
  if (sync_new_) sync_new_ = false;
  else if (cs_armed_) since_sync_ += dt;
  if (cs_armed_ && s_.sync_watchdog && since_sync_ >= 3 * interpolation_period() - 1e-9) enter_fault(0x8700);

  if (state_ == State::OperationEnabled) {
    run_mode(cw, edge4, fall4, dt);
  } else if (state_ == State::QuickStopActive || state_ == State::FaultReactionActive) {
    stop_ramp(quick_stop_decel(), dt);
  }
  follow(dt);
  if (state_ == State::OperationEnabled) check_following_error(dt);
  if (state_ == State::FaultReactionActive && vd_ == 0 && std::fabs(va_) < kStopped) state_ = State::Fault;

  cw_prev_ = cw;
  sw_ = compose_statusword(cw);
  write_outputs();
}

void DriveModel::run_mode(uint16_t cw, bool edge4, bool fall4, double dt) {
  switch (mode_) {
    case 1: run_pp(cw, edge4, dt); break;
    case 3: run_pv(cw, dt); break;
    case 6: run_homing(cw, edge4, fall4, dt); break;
    case 8: run_csp(dt); break;
    case 9: run_csv(); break;
    case 10: run_cst(dt); break;
    default: stop_ramp(quick_stop_decel(), dt); break;
  }
}

void DriveModel::take_setpoint(double target) {
  double lo, hi;
  sw_limit_ = false;
  if (limits_on(lo, hi)) {
    double t = clampd(target, lo, hi);
    sw_limit_ = t != target;
    target = t;
  }
  pp_target_ = target;
  pp_moving_ = true;
}

void DriveModel::run_pp(uint16_t cw, bool edge4, double dt) {
  if (edge4) {
    double t = rd(0x607A, 0, pp_target_);
    if (cw & 0x40) t += pp_target_;  // relative to the preceding target
    if ((cw & 0x20) || !pp_moving_) {
      take_setpoint(t);
      pp_pending_ = false;
    } else {
      pp_pending_ = true;
      pp_pending_target_ = t;
    }
    ack_ = true;
  }
  if (!(cw & 0x10)) ack_ = false;
  double a = accel(0x6083), d = accel(0x6084);
  if (cw & 0x100) {  // halt
    stop_ramp(d, dt);
  } else if (pp_moving_) {
    if (move_to(pp_target_, profile_velocity(), a, d, dt)) {
      pp_moving_ = false;
      if (pp_pending_) {
        pp_pending_ = false;
        take_setpoint(pp_pending_target_);
      }
    }
  } else {
    stop_ramp(d, dt);
  }
  hold_at_limit_switches();
}

// One step of an online trapezoid of the demand towards `target`; true when there.
bool DriveModel::move_to(double target, double v, double a, double d, double dt) {
  double e = target - pd_;
  if (std::fabs(e) < 1e-9 && std::fabs(vd_) < 1e-9) {
    pd_ = target;
    vd_ = 0;
    return true;
  }
  double dir = e > 0 ? 1 : -1;
  double vt = dir * std::min(v, std::sqrt(2 * d * std::fabs(e)));
  ramp_velocity(vt, a, d, dt);
  double np = pd_ + vd_ * dt;
  if ((target - np) * dir <= 0 && vd_ * dir >= 0) {
    pd_ = target;
    vd_ = 0;
    return true;
  }
  pd_ = np;
  return false;
}

// Moves the demand velocity towards `target`: `a` when speeding up, `d` when slowing down.
void DriveModel::ramp_velocity(double target, double a, double d, double dt) {
  bool speeding_up = std::fabs(target) > std::fabs(vd_) && target * vd_ >= 0;
  double r = (speeding_up ? a : d) * dt;
  if (vd_ < target) vd_ = std::min(target, vd_ + r);
  else vd_ = std::max(target, vd_ - r);
}

void DriveModel::stop_ramp(double decel, double dt) {
  ramp_velocity(0, decel, decel, dt);
  if (velocity_follower()) pd_ = pa_;
  else pd_ += vd_ * dt;
}

// Limits a velocity so that the axis stops at the software limits.
double DriveModel::limit_velocity(double v, double decel) {
  double lo, hi;
  if (!limits_on(lo, hi)) return v;
  if (v > 0) {
    double room = hi - pa_;
    double vmax = room > 0 ? std::sqrt(2 * decel * room) : 0;
    if (v > vmax) {
      v = vmax;
      sw_limit_ = true;
    }
  } else if (v < 0) {
    double room = pa_ - lo;
    double vmax = room > 0 ? std::sqrt(2 * decel * room) : 0;
    if (-v > vmax) {
      v = -vmax;
      sw_limit_ = true;
    }
  }
  return v;
}

// Position modes: the demand does not run past an active limit switch.
void DriveModel::hold_at_limit_switches() {
  if (inputs.positive_limit && pd_ > pa_) {
    pd_ = pa_;
    vd_ = std::min(vd_, 0.0);
  }
  if (inputs.negative_limit && pd_ < pa_) {
    pd_ = pa_;
    vd_ = std::max(vd_, 0.0);
  }
}

void DriveModel::run_pv(uint16_t cw, double dt) {
  double a = accel(0x6083), d = accel(0x6084);
  v_target_ = clampd(rd(0x60FF, 0, 0), -s_.max_velocity, s_.max_velocity);
  double vt = (cw & 0x100) ? 0 : v_target_;
  sw_limit_ = false;
  vt = limit_velocity(vt, d);
  ramp_velocity(vt, a, d, dt);
  pd_ = pa_;
}

void DriveModel::run_csp(double dt) {
  double t = sync_seen_ ? cs_pos_ : rd(0x607A, 0, pd_);
  double lo, hi;
  sw_limit_ = false;
  if (limits_on(lo, hi)) {
    double c = clampd(t, lo, hi);
    sw_limit_ = c != t;
    t = c;
  }
  vd_ = clampd((t - pd_) / dt, -s_.max_velocity, s_.max_velocity);
  pd_ = t;
  hold_at_limit_switches();
}

void DriveModel::run_csv() {
  double v = sync_seen_ ? cs_vel_ : rd(0x60FF, 0, 0);
  v_target_ = clampd(v, -s_.max_velocity, s_.max_velocity);
  sw_limit_ = false;
  vd_ = limit_velocity(v_target_, s_.max_acceleration);
  pd_ = pa_;
}

// Cyclic synchronous torque: the torque set-point (per mille) accelerates
// the axis by torque_accel per per mille, up to the maximum velocity.
void DriveModel::run_cst(double dt) {
  double t = sync_seen_ ? cs_torque_ : rd(0x6071, 0, 0);
  sw_limit_ = false;
  double v = clampd(vd_ + t * s_.torque_accel * dt, -s_.max_velocity, s_.max_velocity);
  vd_ = limit_velocity(v, s_.max_acceleration);
  v_target_ = vd_;
  pd_ = pa_;
}

void DriveModel::home_here() {
  double offset = rd(0x607C, 0, 0);
  pa_ = pd_ = pp_target_ = cs_pos_ = offset;
  va_ = vd_ = 0;
  hm_ = Homing::Done;
}

void DriveModel::run_homing(uint16_t cw, bool edge4, bool fall4, double dt) {
  double a = accel(0x609A);
  bool halt = (cw & 0x100) != 0;
  if (edge4 && !halt) {
    int method = static_cast<int>(static_cast<int8_t>(static_cast<int>(rd(0x6098, 0, 0))));
    double s1 = rd(0x6099, 1, s_.max_velocity * 0.1);
    double s2 = rd(0x6099, 2, s_.max_velocity * 0.01);
    sw_limit_ = false;
    if (method == 33 || method == 34 || method == 35 || method == 37) {
      home_here();
    } else if ((method == 17 || method == 18) && s1 > 0 && s2 > 0) {
      hm_ = Homing::Search;
      hm_dir_ = method == 17 ? -1 : 1;
    } else {
      hm_ = Homing::Error;
    }
  } else if ((fall4 || halt) && (hm_ == Homing::Search || hm_ == Homing::Back)) {
    hm_ = Homing::Idle;  // interrupted
  }

  if (hm_ == Homing::Search || hm_ == Homing::Back) {
    double s1 = std::min(std::fabs(rd(0x6099, 1, s_.max_velocity * 0.1)), s_.max_velocity);
    double s2 = std::min(std::fabs(rd(0x6099, 2, s_.max_velocity * 0.01)), s_.max_velocity);
    bool on_switch = hm_dir_ < 0 ? inputs.negative_limit : inputs.positive_limit;
    if (hm_ == Homing::Search) {
      if (on_switch) {
        hm_ = Homing::Back;
        pd_ = pa_;
        vd_ = 0;
      } else {
        ramp_velocity(hm_dir_ * s1, a, a, dt);
        pd_ += vd_ * dt;
      }
    }
    if (hm_ == Homing::Back) {
      if (!on_switch) {
        home_here();
      } else {
        ramp_velocity(-hm_dir_ * s2, a, a, dt);
        pd_ += vd_ * dt;
      }
    }
  } else {
    stop_ramp(a, dt);
  }
}

void DriveModel::follow(double dt) {
  double amax = s_.max_acceleration, vmax = s_.max_velocity;
  double tau = s_.lag_ms / 1000.0;
  double k = tau > 0 ? 1 - std::exp(-dt / tau) : 1;
  bool powered = state_ == State::OperationEnabled || state_ == State::QuickStopActive ||
                 state_ == State::FaultReactionActive;
  double v;
  if (!powered) {
    // No torque: the axis coasts to a stop.
    v = sgn(va_) * std::max(0.0, std::fabs(va_) - amax * dt);
  } else if (velocity_follower()) {
    v = va_ + (vd_ - va_) * k;
  } else {
    double e = pd_ - pa_;
    v = e * k / dt;
    // Do not close in faster than the axis can stop.
    double lim = std::sqrt(2 * amax * std::fabs(e));
    if ((v - vd_) * sgn(e) > lim) v = vd_ + sgn(e) * lim;
  }
  v = clampd(v, va_ - amax * dt, va_ + amax * dt);
  v = clampd(v, -vmax, vmax);
  double lo, hi;
  if (powered && velocity_follower() && limits_on(lo, hi)) {
    // The lag must not carry the axis past a software limit.
    if (v > 0 && pa_ + v * dt > hi) v = std::max(0.0, (hi - pa_) / dt);
    if (v < 0 && pa_ + v * dt < lo) v = std::min(0.0, (lo - pa_) / dt);
  }
  if (inputs.positive_limit && v > 0) v = 0;
  if (inputs.negative_limit && v < 0) v = 0;
  if (inputs.blocked) v = 0;
  pa_ += v * dt;
  va_ = v;
  if (!powered || velocity_follower()) {
    pd_ = pa_;
    if (!powered) vd_ = 0;
  } else if (std::fabs(pd_ - pa_) < 1e-3 && vd_ == 0 && std::fabs(va_) < amax * dt && !inputs.blocked) {
    pa_ = pd_;
    va_ = 0;
  }
}

void DriveModel::check_following_error(double dt) {
  fe_ = false;
  if (mode_ != 1 && mode_ != 8) {
    fe_time_ = 0;
    return;
  }
  double window = rd(0x6065, 0, kOff32);
  if (window >= kOff32 || window < 0) {
    fe_time_ = 0;
    return;
  }
  fe_ = std::fabs(pd_ - pa_) > window;
  if (!fe_) {
    fe_time_ = 0;
    return;
  }
  fe_time_ += dt;
  double time_ms = rd(0x6066, 0, 0);
  if (fe_time_ * 1000.0 + 1e-9 >= time_ms) enter_fault();
}

uint16_t DriveModel::compose_statusword(uint16_t cw) const {
  uint16_t sw = 0;
  switch (state_) {
    case State::NotReadyToSwitchOn: return 0;
    case State::SwitchOnDisabled: sw = 0x0040; break;
    case State::ReadyToSwitchOn: sw = 0x0021; break;
    case State::SwitchedOn: sw = 0x0023; break;
    case State::OperationEnabled: sw = 0x0027; break;
    case State::QuickStopActive: sw = 0x0007; break;
    case State::FaultReactionActive: sw = 0x000F; break;
    case State::Fault: sw = 0x0008; break;
  }
  sw |= 0x0010;  // voltage enabled
  sw |= 0x0200;  // remote
  if (sw_limit_) sw |= 0x0080;  // warning
  if (sw_limit_ || inputs.positive_limit || inputs.negative_limit) sw |= 0x0800;  // internal limit active
  bool stopped = vd_ == 0 && std::fabs(va_) < kStopped;
  bool halt = (cw & 0x100) != 0;
  if (state_ == State::QuickStopActive && stopped) sw |= 0x0400;
  if (state_ == State::Fault && fe_ && (mode_ == 1 || mode_ == 8)) sw |= 0x2000;
  if (state_ != State::OperationEnabled) return sw;
  switch (mode_) {
    case 1: {
      double win = rd(0x6067, 0, 0);
      bool reached;
      if (halt) reached = stopped;
      else if (win >= kOff32) reached = !pp_moving_ && !pp_pending_;
      else reached = !pp_moving_ && !pp_pending_ && std::fabs(pp_target_ - pa_) <= std::max(win, 0.5);
      if (reached) sw |= 0x0400;
      if (ack_ || pp_pending_) sw |= 0x1000;
      if (fe_) sw |= 0x2000;
      break;
    }
    case 3: {
      double vwin = rd(0x606D, 0, 10);
      double vthr = rd(0x606F, 0, 10);
      bool reached = halt ? stopped : (std::fabs(va_ - v_target_) <= vwin && !sw_limit_);
      if (reached) sw |= 0x0400;
      if (std::fabs(va_) <= vthr) sw |= 0x1000;  // speed = 0
      break;
    }
    case 6: {
      bool running = hm_ == Homing::Search || hm_ == Homing::Back;
      if (!running && stopped) sw |= 0x0400;
      if (hm_ == Homing::Done) sw |= 0x1000;
      if (hm_ == Homing::Error) sw |= 0x2000;
      break;
    }
    case 8:
      sw |= 0x1000;  // following the command value
      if (fe_) sw |= 0x2000;
      break;
    case 9:
    case 10:
      sw |= 0x1000;
      break;
    default:
      break;
  }
  return sw;
}

void DriveModel::write_outputs() {
  wr(0x6041, 0, sw_);
  wr(0x6061, 0, mode_);
  wr(0x6062, 0, std::round(pd_));
  wr(0x6063, 0, std::round(pa_));
  wr(0x6064, 0, std::round(pa_));
  wr(0x606B, 0, std::round(vd_));
  wr(0x606C, 0, std::round(va_));
  wr(0x60F4, 0, std::round(pd_ - pa_));
  bool torque = state_ == State::OperationEnabled && mode_ == 10;
  wr(0x6077, 0, torque ? std::round(sync_seen_ ? cs_torque_ : rd(0x6071, 0, 0)) : 0);
}

}  // namespace canopen_sim
