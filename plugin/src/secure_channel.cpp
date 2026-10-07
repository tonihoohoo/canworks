#include "secure_channel.h"

#include <openssl/bio.h>
#include <openssl/crypto.h>
#include <openssl/err.h>
#include <openssl/evp.h>
#include <openssl/hmac.h>
#include <openssl/rand.h>
#include <openssl/sha.h>
#include <openssl/ssl.h>
#include <openssl/x509.h>

#include <cctype>
#include <cstdlib>
#include <cstring>

namespace canopen_plugin {

namespace {

std::string ssl_error_text() {
  unsigned long e = ERR_get_error();
  ERR_clear_error();
  if (!e) return "TLS error";
  char buf[256];
  ERR_error_string_n(e, buf, sizeof buf);
  return buf;
}

Bytes hmac(const Bytes& key, const std::string& data) {
  unsigned char out[EVP_MAX_MD_SIZE];
  unsigned len = 0;
  HMAC(EVP_sha256(), key.data(), static_cast<int>(key.size()), reinterpret_cast<const unsigned char*>(data.data()),
       data.size(), out, &len);
  return Bytes(out, out + len);
}

Bytes xor_bytes(const Bytes& a, const Bytes& b) {
  Bytes r(a.size());
  for (size_t i = 0; i < a.size() && i < b.size(); ++i) r[i] = a[i] ^ b[i];
  return r;
}

Bytes salted_password(const std::string& token, const Bytes& salt, unsigned iterations) {
  Bytes out(32);
  PKCS5_PBKDF2_HMAC(token.data(), static_cast<int>(token.size()), salt.data(), static_cast<int>(salt.size()),
                    static_cast<int>(iterations), EVP_sha256(), static_cast<int>(out.size()), out.data());
  return out;
}

SSL_CTX* client_ctx() {
  static SSL_CTX* ctx = [] {
    SSL_CTX* c = SSL_CTX_new(TLS_client_method());
    if (c) {
      SSL_CTX_set_min_proto_version(c, TLS1_2_VERSION);
      // The login checks the certificate (channel binding), not the chain.
      SSL_CTX_set_verify(c, SSL_VERIFY_NONE, nullptr);
    }
    return c;
  }();
  return ctx;
}

}  // namespace

std::string b64_encode(const Bytes& data) {
  if (data.empty()) return "";
  std::string out(4 * ((data.size() + 2) / 3), '\0');
  int n = EVP_EncodeBlock(reinterpret_cast<unsigned char*>(&out[0]), data.data(), static_cast<int>(data.size()));
  out.resize(static_cast<size_t>(n));
  return out;
}

bool b64_decode(const std::string& text, Bytes& out) {
  out.clear();
  if (text.empty()) return true;
  if (text.size() % 4) return false;
  for (char c : text)
    if (!(std::isalnum(static_cast<unsigned char>(c)) || c == '+' || c == '/' || c == '=')) return false;
  out.resize(text.size() / 4 * 3);
  int n = EVP_DecodeBlock(out.data(), reinterpret_cast<const unsigned char*>(text.data()), static_cast<int>(text.size()));
  if (n < 0) return false;
  size_t pad = 0;
  if (text[text.size() - 1] == '=') ++pad;
  if (text[text.size() - 2] == '=') ++pad;
  out.resize(static_cast<size_t>(n) - pad);
  return true;
}

Bytes random_bytes(size_t n) {
  Bytes b(n);
  if (n && RAND_bytes(b.data(), static_cast<int>(n)) != 1) std::abort();  // no randomness: never go on
  return b;
}

Bytes sha256(const Bytes& data) {
  Bytes out(SHA256_DIGEST_LENGTH);
  SHA256(data.data(), data.size(), out.data());
  return out;
}

bool bytes_equal(const Bytes& a, const Bytes& b) {
  return a.size() == b.size() && CRYPTO_memcmp(a.data(), b.data(), a.size()) == 0;
}

bool parse_scram_verifier(const std::string& text, ScramVerifier& out, std::string& why) {
  const std::string prefix = "SCRAM-SHA-256$";
  why = "must look like SCRAM-SHA-256$<iterations>:<salt>$<StoredKey>:<ServerKey> "
        "(openplc-canopen-diag hash-token prints it)";
  if (text.compare(0, prefix.size(), prefix) != 0) return false;
  std::string rest = text.substr(prefix.size());
  size_t dollar = rest.find('$');
  if (dollar == std::string::npos) return false;
  std::string params = rest.substr(0, dollar), keys = rest.substr(dollar + 1);
  size_t c1 = params.find(':'), c2 = keys.find(':');
  if (c1 == std::string::npos || c2 == std::string::npos) return false;
  std::string iter = params.substr(0, c1);
  if (iter.empty() || iter.size() > 7 || iter.find_first_not_of("0123456789") != std::string::npos) return false;
  ScramVerifier v;
  v.iterations = static_cast<unsigned>(std::strtoul(iter.c_str(), nullptr, 10));
  if (!b64_decode(params.substr(c1 + 1), v.salt) || !b64_decode(keys.substr(0, c2), v.stored_key) ||
      !b64_decode(keys.substr(c2 + 1), v.server_key))
    return false;
  if (v.stored_key.size() != 32 || v.server_key.size() != 32) return false;
  if (v.iterations < kScramMinIterations || v.iterations > kScramMaxIterations) {
    why = "iterations must be " + std::to_string(kScramMinIterations) + "-" + std::to_string(kScramMaxIterations);
    return false;
  }
  if (v.salt.size() < kScramMinSalt) {
    why = "the salt must be at least " + std::to_string(kScramMinSalt) + " bytes";
    return false;
  }
  why.clear();
  out = v;
  return true;
}

std::string format_scram_verifier(const ScramVerifier& v) {
  return "SCRAM-SHA-256$" + std::to_string(v.iterations) + ":" + b64_encode(v.salt) + "$" + b64_encode(v.stored_key) +
         ":" + b64_encode(v.server_key);
}

ScramVerifier make_scram_verifier(const std::string& token, const Bytes& salt, unsigned iterations) {
  Bytes sp = salted_password(token, salt, iterations);
  ScramVerifier v;
  v.iterations = iterations;
  v.salt = salt;
  v.stored_key = sha256(hmac(sp, "Client Key"));
  v.server_key = hmac(sp, "Server Key");
  return v;
}

std::string scram_auth_message(const std::string& cnonce_b64, const std::string& snonce_b64,
                               const std::string& salt_b64, unsigned iterations, const Bytes& cbind) {
  return "openplc-canopen-diag/2," + cnonce_b64 + "," + snonce_b64 + "," + salt_b64 + "," +
         std::to_string(iterations) + "," + b64_encode(cbind);
}

bool scram_check_proof(const ScramVerifier& v, const std::string& auth_message, const Bytes& proof) {
  if (proof.size() != 32) return false;
  Bytes client_key = xor_bytes(proof, hmac(v.stored_key, auth_message));
  return bytes_equal(sha256(client_key), v.stored_key);
}

Bytes scram_server_signature(const ScramVerifier& v, const std::string& auth_message) {
  return hmac(v.server_key, auth_message);
}

void scram_client(const std::string& token, const Bytes& salt, unsigned iterations, const std::string& auth_message,
                  Bytes& proof, Bytes& server_signature) {
  Bytes sp = salted_password(token, salt, iterations);
  Bytes client_key = hmac(sp, "Client Key");
  proof = xor_bytes(client_key, hmac(sha256(client_key), auth_message));
  server_signature = hmac(hmac(sp, "Server Key"), auth_message);
}

// ---- TLS ----

TlsIdentity::~TlsIdentity() {
  if (ctx_) SSL_CTX_free(ctx_);
}

bool TlsIdentity::create(std::string& why) {
  EVP_PKEY* key = EVP_EC_gen("P-256");
  X509* x = X509_new();
  bool ok = key && x;
  if (ok) {
    X509_set_version(x, 2);
    Bytes serial = random_bytes(8);
    serial[0] &= 0x7F;
    uint64_t s = 0;
    for (uint8_t b : serial) s = (s << 8) | b;
    ASN1_INTEGER_set_uint64(X509_get_serialNumber(x), s);
    X509_gmtime_adj(X509_getm_notBefore(x), -24L * 3600);
    X509_gmtime_adj(X509_getm_notAfter(x), 10L * 365 * 24 * 3600);
    X509_set_pubkey(x, key);
    X509_NAME* name = X509_get_subject_name(x);
    X509_NAME_add_entry_by_txt(name, "CN", MBSTRING_ASC, reinterpret_cast<const unsigned char*>("openplc-canopen-diag"),
                               -1, -1, 0);
    X509_set_issuer_name(x, name);
    ok = X509_sign(x, key, EVP_sha256()) > 0;
  }
  SSL_CTX* ctx = ok ? SSL_CTX_new(TLS_server_method()) : nullptr;
  ok = ok && ctx && SSL_CTX_set_min_proto_version(ctx, TLS1_2_VERSION) == 1 &&
       SSL_CTX_use_certificate(ctx, x) == 1 && SSL_CTX_use_PrivateKey(ctx, key) == 1;
  if (ok) {
    unsigned char* der = nullptr;
    int len = i2d_X509(x, &der);
    ok = len > 0;
    if (ok) cert_hash_ = sha256(Bytes(der, der + len));
    OPENSSL_free(der);
  }
  if (!ok) {
    why = ssl_error_text();
    if (ctx) SSL_CTX_free(ctx);
    ctx = nullptr;
  }
  X509_free(x);
  EVP_PKEY_free(key);
  if (ctx_) SSL_CTX_free(ctx_);
  ctx_ = ctx;
  return ok;
}

TlsConn::~TlsConn() {
  if (ssl_) SSL_free(ssl_);
}

std::unique_ptr<TlsConn> TlsConn::server(const TlsIdentity& id, std::string& why) {
  std::unique_ptr<TlsConn> c(new TlsConn);
  c->ssl_ = id.ctx() ? SSL_new(id.ctx()) : nullptr;
  if (!c->ssl_) {
    why = ssl_error_text();
    return nullptr;
  }
  c->in_ = BIO_new(BIO_s_mem());
  c->out_ = BIO_new(BIO_s_mem());
  SSL_set_bio(c->ssl_, c->in_, c->out_);
  SSL_set_accept_state(c->ssl_);
  return c;
}

std::unique_ptr<TlsConn> TlsConn::client(std::string& why) {
  std::unique_ptr<TlsConn> c(new TlsConn);
  SSL_CTX* ctx = client_ctx();
  c->ssl_ = ctx ? SSL_new(ctx) : nullptr;
  if (!c->ssl_) {
    why = ssl_error_text();
    return nullptr;
  }
  c->in_ = BIO_new(BIO_s_mem());
  c->out_ = BIO_new(BIO_s_mem());
  SSL_set_bio(c->ssl_, c->in_, c->out_);
  SSL_set_connect_state(c->ssl_);
  return c;
}

void TlsConn::drain() {
  char buf[4096];
  int n;
  while ((n = BIO_read(out_, buf, sizeof buf)) > 0) wire_.append(buf, static_cast<size_t>(n));
}

bool TlsConn::pump(std::string& plain, std::string& why) {
  if (!established_) {
    int r = SSL_do_handshake(ssl_);
    if (r != 1) {
      int e = SSL_get_error(ssl_, r);
      drain();
      if (e == SSL_ERROR_WANT_READ || e == SSL_ERROR_WANT_WRITE) return true;
      why = e == SSL_ERROR_SSL ? ssl_error_text() : "TLS handshake failed";
      return false;
    }
    established_ = true;
    if (!pending_.empty()) {
      std::string p;
      p.swap(pending_);
      if (!write(p, why)) return false;
    }
  }
  char buf[4096];
  for (;;) {
    int n = SSL_read(ssl_, buf, sizeof buf);
    if (n > 0) {
      plain.append(buf, static_cast<size_t>(n));
      continue;
    }
    int e = SSL_get_error(ssl_, n);
    drain();
    if (e == SSL_ERROR_WANT_READ || e == SSL_ERROR_WANT_WRITE) return true;
    why = e == SSL_ERROR_ZERO_RETURN ? "connection closed" : e == SSL_ERROR_SSL ? ssl_error_text() : "TLS error";
    return false;
  }
}

bool TlsConn::start(std::string& why) {
  std::string none;
  return pump(none, why);
}

bool TlsConn::feed(const char* data, size_t n, std::string& plain, std::string& why) {
  if (n && BIO_write(in_, data, static_cast<int>(n)) != static_cast<int>(n)) {
    why = "TLS buffer error";
    return false;
  }
  return pump(plain, why);
}

bool TlsConn::write(const std::string& plain, std::string& why) {
  if (plain.empty()) return true;
  if (!established_) {
    pending_ += plain;
    return true;
  }
  int n = SSL_write(ssl_, plain.data(), static_cast<int>(plain.size()));
  drain();
  if (n != static_cast<int>(plain.size())) {
    why = ssl_error_text();
    return false;
  }
  return true;
}

Bytes TlsConn::peer_cert_hash() const {
  X509* x = SSL_get1_peer_certificate(ssl_);
  if (!x) return {};
  unsigned char* der = nullptr;
  int len = i2d_X509(x, &der);
  Bytes h = len > 0 ? sha256(Bytes(der, der + len)) : Bytes();
  OPENSSL_free(der);
  X509_free(x);
  return h;
}

}  // namespace canopen_plugin
