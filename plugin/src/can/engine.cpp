// engine.cpp - see engine.h.

#include "engine.h"

#include "diag.h"
#include "log.h"
#include "raw/raw_runtime.h"
#if CANWORKS_WITH_CANOPEN
#include "canopen_runtime.h"
#endif
#if CANWORKS_WITH_J1939
#include "j1939_runtime.h"
#endif

namespace canopen_plugin {

namespace {

std::string prefix_of(const Config& cfg) { return cfg.log_prefix.empty() ? "" : cfg.log_prefix + ": "; }

}  // namespace

Engine::Engine() = default;

Engine::~Engine() {
  stop();
  server_.reset();
  nets_.clear();  // before the gateway link they use
  raws_.clear();
}

bool Engine::load(const std::string& path, const ImageLimits& limits, ConfigSet& set,
                  std::vector<std::string>* problems) {
  log_info("protocols built in: %s", built_in_protocols().c_str());
  std::vector<std::string> errors;
  bool loaded = load_config_set(path, limits, set, errors);
  for (const auto& w : set.warnings) log_warn("%s", w.c_str());
  for (const auto& m : set.notes) log_info("%s", m.c_str());
  for (auto& cfg : set.networks) {
    ScopedLogPrefix prefix(prefix_of(cfg));
    for (const auto& w : cfg.warnings) log_warn("%s", w.c_str());
    for (const auto& m : cfg.notes) log_info("%s", m.c_str());
  }
  // Every network is checked before any interface opens: an error in any of
  // them leaves every network inactive (canopen-networks spec).
  bool checked = loaded;
#if CANWORKS_WITH_CANOPEN
  if (checked) checked = canopen_check(set, errors);
#endif
  if (!checked) {
    for (const auto& e : errors) log_error("%s", e.c_str());
    log_error("configuration rejected (%zu problem%s); canworks inactive, CAN interface not opened",
              errors.size(), errors.size() == 1 ? "" : "s");
    if (problems) *problems = errors;
    return false;
  }
  return true;
}

bool Engine::check(const std::string& path, const ImageLimits& limits, std::vector<std::string>* problems) {
  ConfigSet set;
  return load(path, limits, set, problems);
}

bool Engine::prepare(const std::string& path, const ImageLimits& limits, uint64_t base_tick_ns, const char* version) {
  if (!load(path, limits, set_, nullptr)) return false;
  // The Modbus bridge has no PLC scan (its cycle_end runs on writes) and its
  // own watchdog: no scan watchdog there.
  if (limits.bridge_host)
    for (auto& cfg : set_.networks) cfg.master.scan_watchdog_ms = 0;
  std::vector<std::string> errors;
  for (auto& cfg : set_.networks) {
    if (cfg.is_plain()) {
      canworks_raw::log_plain_loaded(set_, cfg);
      continue;
    }
#if CANWORKS_WITH_J1939
    if (cfg.is_j1939()) {
      j1939_log_loaded(set_, cfg);
      continue;
    }
#endif
#if CANWORKS_WITH_CANOPEN
    canopen_log_loaded(set_, cfg, base_tick_ns);
#endif
  }

  // The raw paths first: a simulated CANopen network's bus thread serves
  // the bridge its raw path registers.
  for (auto& cfg : set_.networks) {
    ScopedLogPrefix prefix(prefix_of(cfg));
    std::unique_ptr<canworks_raw::RawRuntime> raw(new canworks_raw::RawRuntime(cfg));
    if (!raw->make(set_, errors)) {
      for (const auto& e : errors) log_error("%s", e.c_str());
      log_error("raw CAN of this network rejected; canworks inactive, CAN interface not opened");
      return false;
    }
    raws_.push_back(std::move(raw));
  }
  nets_.resize(set_.networks.size());
  for (size_t i = 0; i < set_.networks.size(); ++i)
    if (set_.networks[i].is_plain()) nets_[i] = canworks_raw::make_plain_runtime(raws_[i].get(), version);
#if CANWORKS_WITH_CANOPEN
  if (!canopen_create(set_, base_tick_ns, version, canopen_, nets_)) return false;
#endif
#if CANWORKS_WITH_J1939
  j1939_create(set_, version, nets_);
#endif
  for (auto& n : nets_)
    if (!n) {  // the parser refuses protocols not built in; never here
      log_error("a network has no runtime; canworks inactive");
      return false;
    }
  if (set_.networks[0].master.has_diagnostics) {
    std::vector<DiagHub*> hubs;
    for (size_t i = 0; i < nets_.size(); ++i) {
      DiagHub* h = nets_[i]->hub();
      hubs.push_back(h);
      canworks_raw::RawRuntime* raw = raws_[i].get();
      if (h && !set_.networks[i].is_plain()) h->set_raw_status([raw] { return raw->status(); });
      if (h) h->set_host_status(diag_host_.status_part);
    }
    server_.reset(new DiagServer(hubs));
    server_->set_host(diag_host_);
    for (size_t i = 0; i < nets_.size(); ++i) {
      if (auto src = nets_[i]->trace_source()) server_->set_trace_source(std::move(src), i);
      if (auto inj = nets_[i]->frame_injector()) server_->set_frame_injector(inj, i);
    }
  }
  return true;
}

void Engine::start() {
  for (auto& n : nets_) n->start();
  for (auto& r : raws_) r->start();
  if (server_) server_->start();
#if CANWORKS_WITH_CANOPEN
  canopen_open_plc_requests(set_);
#endif
#if CANWORKS_WITH_J1939
  j1939_open_plc_jobs(set_);
#endif
  started_ = true;
}

void Engine::stop() {
  if (!started_) return;
  started_ = false;
#if CANWORKS_WITH_CANOPEN
  canopen_close_plc_requests();
#endif
#if CANWORKS_WITH_J1939
  j1939_close_plc_jobs();
#endif
  if (server_) server_->stop();
  for (auto& r : raws_) r->stop();
  for (auto& n : nets_) n->stop();
}

void Engine::cycle_start(const plugin_runtime_args_t& rt) {
  for (auto& n : nets_) n->cycle_start(rt);
  for (auto& r : raws_) r->cycle_start(rt);
}

void Engine::cycle_end(const plugin_runtime_args_t& rt) {
  for (auto& n : nets_) n->cycle_end(rt);
  for (auto& r : raws_) r->cycle_end(rt);
}

}  // namespace canopen_plugin
