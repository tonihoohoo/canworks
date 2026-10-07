// secure_channel.h - TLS and the SCRAM-SHA-256 login of the diagnostics
// channel (canopen-online-diagnostics spec, "Access control"), shared by the
// plugin's DiagServer and the standalone simulator's control channel and
// client.
//
// TLS runs over memory BIOs: the caller moves bytes between its socket and
// the TlsConn, so the non-blocking poll loops stay as they are. The server's
// key and self-signed certificate are made in memory when the listener opens
// and never written anywhere; nothing checks the certificate chain. The login
// authenticates both ends instead: it binds itself to the certificate the
// client received (tls-server-end-point, RFC 5929), so a machine in the middle
// with its own certificate fails on both sides.
//
// SCRAM (RFC 5802/7677 math, JSON framing):
//   SaltedPassword = PBKDF2-HMAC-SHA-256(token, salt, iterations)
//   ClientKey = HMAC(SaltedPassword, "Client Key"), StoredKey = SHA-256(ClientKey)
//   ServerKey = HMAC(SaltedPassword, "Server Key")
//   AuthMessage = "openplc-canopen-diag/2," cnonce "," snonce "," salt "," iterations "," cbind
//     (nonces, salt and cbind in base64; cbind = SHA-256 of the certificate's DER)
//   ClientProof = ClientKey XOR HMAC(StoredKey, AuthMessage)
//   ServerSignature = HMAC(ServerKey, AuthMessage)

#ifndef CANOPEN_SECURE_CHANNEL_H
#define CANOPEN_SECURE_CHANNEL_H

#include <cstddef>
#include <cstdint>
#include <memory>
#include <string>
#include <vector>

typedef struct ssl_ctx_st SSL_CTX;
typedef struct ssl_st SSL;
typedef struct bio_st BIO;

namespace canopen_plugin {

using Bytes = std::vector<uint8_t>;

constexpr const char* kScramMechanism = "SCRAM-SHA-256-PLUS";
constexpr unsigned kScramDefaultIterations = 4096;
constexpr unsigned kScramMinIterations = 4096;
constexpr unsigned kScramMaxIterations = 1000000;
constexpr size_t kScramMinSalt = 16;
constexpr size_t kScramNonceBytes = 18;

std::string b64_encode(const Bytes& data);
bool b64_decode(const std::string& text, Bytes& out);
Bytes random_bytes(size_t n);
Bytes sha256(const Bytes& data);
// Constant time in the length; false when the lengths differ.
bool bytes_equal(const Bytes& a, const Bytes& b);

struct ScramVerifier {
  unsigned iterations = 0;
  Bytes salt, stored_key, server_key;
};

// "SCRAM-SHA-256$<iterations>:<salt>$<StoredKey>:<ServerKey>" (base64).
bool parse_scram_verifier(const std::string& text, ScramVerifier& out, std::string& why);
std::string format_scram_verifier(const ScramVerifier& v);
ScramVerifier make_scram_verifier(const std::string& token, const Bytes& salt, unsigned iterations);

std::string scram_auth_message(const std::string& cnonce_b64, const std::string& snonce_b64,
                               const std::string& salt_b64, unsigned iterations, const Bytes& cbind);
bool scram_check_proof(const ScramVerifier& v, const std::string& auth_message, const Bytes& proof);
Bytes scram_server_signature(const ScramVerifier& v, const std::string& auth_message);
// The client's side: its proof, and the signature the server must send back.
void scram_client(const std::string& token, const Bytes& salt, unsigned iterations, const std::string& auth_message,
                  Bytes& proof, Bytes& server_signature);

// The server's key and self-signed certificate, made in memory.
class TlsIdentity {
 public:
  TlsIdentity() = default;
  ~TlsIdentity();
  TlsIdentity(const TlsIdentity&) = delete;
  TlsIdentity& operator=(const TlsIdentity&) = delete;
  // A new key and certificate. False with `why`.
  bool create(std::string& why);
  bool ready() const { return ctx_ != nullptr; }
  SSL_CTX* ctx() const { return ctx_; }
  // SHA-256 of the certificate's DER: the channel binding.
  const Bytes& cert_hash() const { return cert_hash_; }

 private:
  SSL_CTX* ctx_ = nullptr;
  Bytes cert_hash_;
};

// One TLS connection over memory buffers.
class TlsConn {
 public:
  ~TlsConn();
  static std::unique_ptr<TlsConn> server(const TlsIdentity& id, std::string& why);
  // A client that checks no certificate; start() sends its first flight.
  static std::unique_ptr<TlsConn> client(std::string& why);

  bool start(std::string& why);
  // Bytes from the socket; decrypted data is appended to `plain`. False on a
  // TLS error (with `why`) or when the peer closed the TLS session.
  bool feed(const char* data, size_t n, std::string& plain, std::string& why);
  // Plaintext to send; encrypted into wire() (queued until the handshake is done).
  bool write(const std::string& plain, std::string& why);
  // Bytes to send on the socket; the caller erases what it sent.
  std::string& wire() { return wire_; }
  bool established() const { return established_; }
  // Client: SHA-256 of the DER of the certificate the server sent.
  Bytes peer_cert_hash() const;

 private:
  TlsConn() = default;
  bool pump(std::string& plain, std::string& why);
  void drain();

  SSL* ssl_ = nullptr;
  BIO* in_ = nullptr;   // owned by ssl_
  BIO* out_ = nullptr;  // owned by ssl_
  std::string wire_;
  std::string pending_;  // plaintext written before the handshake finished
  bool established_ = false;
};

// The first byte of a TLS connection (a handshake record).
constexpr unsigned char kTlsHandshakeByte = 0x16;

}  // namespace canopen_plugin

#endif  // CANOPEN_SECURE_CHANNEL_H
