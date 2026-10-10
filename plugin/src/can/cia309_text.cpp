// cia309_text.cpp - see cia309_text.h.

// Lely's C type names (co_gw_txt_t, ...): in C++ only its .hpp wrappers define
// them otherwise.
#ifndef LELY_NO_CXX
#define LELY_NO_CXX 1
#endif

#include "cia309_text.h"

#include <cctype>
#include <cstdlib>

#include <lely/co/gw_txt.h>
#include <lely/co/val.h>

namespace canopen_plugin {

Cia309Text::Cia309Text(std::function<void(const co_gw_req&)> on_request,
                       std::function<void(const std::string&)> on_text)
    : on_request_(std::move(on_request)), on_text_(std::move(on_text)) {
  gw_ = co_gw_txt_create();
  if (!gw_) return;
  co_gw_txt_set_recv_func(gw_, &Cia309Text::recv_cb, this);
  co_gw_txt_set_send_func(gw_, &Cia309Text::send_cb, this);
}

Cia309Text::~Cia309Text() {
  if (gw_) co_gw_txt_destroy(gw_);
}

int Cia309Text::recv_cb(const char* txt, void* data) {
  auto* self = static_cast<Cia309Text*>(data);
  if (self->on_text_) self->on_text_(txt);
  return 0;
}

int Cia309Text::send_cb(const co_gw_req* req, void* data) {
  auto* self = static_cast<Cia309Text*>(data);
  if (self->on_request_) self->on_request_(*req);
  return 0;
}

bool Cia309Text::line(const std::string& text, uint32_t& seq) {
  seq = 0;
  // The sequence number, for the answer to a line Lely cannot parse (Lely
  // reports the error without one).
  size_t i = 0;
  while (i < text.size() && std::isspace(static_cast<unsigned char>(text[i]))) ++i;
  if (i < text.size() && text[i] == '[') ++i;
  while (i < text.size() && (text[i] == ' ' || text[i] == '\t')) ++i;
  if (i < text.size() && std::isdigit(static_cast<unsigned char>(text[i])))
    seq = static_cast<uint32_t>(std::strtoul(text.c_str() + i, nullptr, 0));
  if (!gw_) return false;
  co_gw_txt_iec(gw_);  // clears an earlier error
  // No file location: Lely's parser then logs nothing about a client's
  // syntax errors.
  co_gw_txt_send(gw_, text.data(), text.data() + text.size(), nullptr);
  return co_gw_txt_iec(gw_) != CO_GW_IEC_SYNTAX;
}

bool Cia309Text::format(const co_gw_srv& srv) { return gw_ && co_gw_txt_recv(gw_, &srv) == 0; }

bool Cia309Text::confirm(uint32_t seq, int srv, int iec, uint32_t ac) {
  co_gw_con con{};
  con.size = sizeof con;
  // Without an error Lely prints "OK" only for services without data.
  con.srv = iec || ac ? srv : CO_GW_SRV_NMT_START;
  con.data = reinterpret_cast<void*>(static_cast<uintptr_t>(seq));
  con.iec = iec;
  con.ac = ac;
  bool ok = format(*reinterpret_cast<const co_gw_srv*>(&con));
  if (gw_) co_gw_txt_iec(gw_);  // Lely keeps the last error code; the session does not use it
  return ok;
}

size_t Cia309Text::pending() const { return gw_ ? co_gw_txt_pending(gw_) : 0; }

bool Cia309Text::value_fits(uint16_t type, const uint8_t* p, size_t n) {
  co_val val;
  co_val_init(type, &val);
  size_t got = co_val_read(type, &val, p, p + n);
  co_val_fini(type, &val);
  return got == n;
}

}  // namespace canopen_plugin
