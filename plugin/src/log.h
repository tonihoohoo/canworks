// log.h - logging for the CANopen plugin.
//
// All messages are prefixed with "[CANOPEN]" and routed to a sink. In the
// runtime the sink is the runtime logger from plugin_runtime_args_t; in unit
// tests it is a capture buffer. Never call these from cycle_start/cycle_end.

#ifndef CANOPEN_LOG_H
#define CANOPEN_LOG_H

namespace canopen_plugin {

enum class LogLevel { Debug, Info, Warn, Error };

using LogSink = void (*)(LogLevel level, const char* msg);

// Installs the sink. Passing nullptr restores the default (stderr).
void set_log_sink(LogSink sink);

// Routes Lely's diagnostic messages (diag()/diag_at()) to the sink.
void route_lely_diagnostics();

void log_debug(const char* fmt, ...) __attribute__((format(printf, 1, 2)));
void log_info(const char* fmt, ...) __attribute__((format(printf, 1, 2)));
void log_warn(const char* fmt, ...) __attribute__((format(printf, 1, 2)));
void log_error(const char* fmt, ...) __attribute__((format(printf, 1, 2)));

}  // namespace canopen_plugin

#endif  // CANOPEN_LOG_H
