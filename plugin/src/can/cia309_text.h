// cia309_text.h - one Lely CiA 309-3 text layer (canopen-cia309-gateway
// "Lely's text layer").
//
// Cia309Text owns one co_gw_txt_t from <lely/co/gw_txt.h> (CiA 309-3 version
// 2.1): a line goes in and comes out as the co_gw_req Lely parsed from it; a
// confirmation (co_gw_con_*) or indication (co_gw_ind_*) goes in and comes
// out as the text line Lely formats. Pure text: no CAN access and no
// locking (one object per session, used by one thread).

#ifndef CANWORKS_CIA309_TEXT_H
#define CANWORKS_CIA309_TEXT_H

#include <cstddef>
#include <cstdint>
#include <functional>
#include <string>

struct co_gw_req;
struct co_gw_srv;
struct __co_gw_txt;

namespace canopen_plugin {

class Cia309Text {
 public:
  // `on_request`: each request Lely parses from a line (valid during the
  // call only). `on_text`: each line Lely formats, without the line end.
  Cia309Text(std::function<void(const co_gw_req&)> on_request, std::function<void(const std::string&)> on_text);
  ~Cia309Text();
  Cia309Text(const Cia309Text&) = delete;
  Cia309Text& operator=(const Cia309Text&) = delete;

  bool ok() const { return gw_ != nullptr; }

  // Parses one line (without its line end); a valid request reaches
  // on_request before this returns. False: Lely could not parse it (CiA
  // 309-3 error 101); `seq` is the sequence number the line starts with, or
  // 0. A blank line or a comment is valid and requests nothing.
  bool line(const std::string& text, uint32_t& seq);

  // Formats a confirmation or an indication through on_text.
  bool format(const co_gw_srv& srv);
  // A confirmation of service `srv` without data: "[seq] OK", or with an
  // internal error code "[seq] ERROR: 102 (...)", or with an SDO abort code.
  bool confirm(uint32_t seq, int srv, int iec, uint32_t ac = 0);

  // Requests parsed and not confirmed yet (co_gw_txt_pending).
  size_t pending() const;

  // Whether `n` bytes at `p` are a value of CANopen data type `type` (an SDO
  // upload answer of the requested type; Lely formats only those).
  static bool value_fits(uint16_t type, const uint8_t* p, size_t n);

 private:
  static int recv_cb(const char* txt, void* data);
  static int send_cb(const co_gw_req* req, void* data);

  __co_gw_txt* gw_ = nullptr;
  std::function<void(const co_gw_req&)> on_request_;
  std::function<void(const std::string&)> on_text_;
};

}  // namespace canopen_plugin

#endif  // CANWORKS_CIA309_TEXT_H
