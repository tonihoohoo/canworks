#include "address_claim.h"

#include "log.h"

namespace canopen_plugin {

constexpr std::chrono::milliseconds AddressClaimer::kClaimWait;  // C++14: odr-used
constexpr unsigned AddressClaimer::kCannotClaimDelayMaxMs;

const char* j1939_claim_state_name(J1939ClaimState s) {
  switch (s) {
    case J1939ClaimState::Claiming: return "claiming";
    case J1939ClaimState::Claimed: return "claimed";
    case J1939ClaimState::CannotClaim: return "cannot claim";
    case J1939ClaimState::NoBus: return "no bus";
  }
  return "?";
}

AddressClaimer::AddressClaimer(const J1939Ecu& ecu, Actions& actions)
    : ecu_(ecu), actions_(actions), name_(ecu.name.value()), random_(name_) {}

std::chrono::milliseconds AddressClaimer::cannot_claim_delay() {
  // splitmix64
  uint64_t z = (random_ += 0x9E3779B97F4A7C15ULL);
  z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9ULL;
  z = (z ^ (z >> 27)) * 0x94D049BB133111EBULL;
  z ^= z >> 31;
  return std::chrono::milliseconds(z % (kCannotClaimDelayMaxMs + 1));
}

void AddressClaimer::start(clock::time_point now) {
  claims_.clear();
  cannot_claim_due_ = false;
  state_ = J1939ClaimState::Claiming;
  collecting_ = true;
  has_address_ = false;
  address_ = kJ1939NullAddress;
  deadline_ = now + kClaimWait;
  actions_.send_claim_request();
}

void AddressClaimer::bus_lost() {
  cannot_claim_due_ = false;
  state_ = J1939ClaimState::NoBus;
  collecting_ = false;
  has_address_ = false;
  address_ = kJ1939NullAddress;
}

int AddressClaimer::next_free(int from) const {
  if (!ecu_.has_range || !ecu_.name.arbitrary_address_capable) return -1;
  const int lo = static_cast<int>(ecu_.range_low), hi = static_cast<int>(ecu_.range_high);
  const int n = hi - lo + 1;
  // Start after `from` when it lies in the range, else at the range's start.
  int first = (from >= lo && from <= hi) ? from + 1 : lo;
  for (int k = 0; k < n; ++k) {
    int a = lo + ((first - lo + k) % n + n) % n;
    if (a == from) continue;
    if (!claims_.count(static_cast<uint8_t>(a))) return a;
  }
  return -1;
}

void AddressClaimer::claim(uint8_t address, clock::time_point now) {
  address_ = address;
  has_address_ = true;
  state_ = J1939ClaimState::Claiming;
  deadline_ = now + kClaimWait;
  actions_.send_claim(address);
}

void AddressClaimer::cannot_claim() {
  if (state_ != J1939ClaimState::CannotClaim)
    log_error("J1939: cannot claim an address (NAME 0x%016llX): every address it may use is held by an ECU with a "
              "lower NAME; the network sends nothing",
              static_cast<unsigned long long>(name_));
  state_ = J1939ClaimState::CannotClaim;
  has_address_ = false;
  address_ = kJ1939NullAddress;
  actions_.send_claim(kJ1939NullAddress);
}

void AddressClaimer::on_claim(uint8_t source, uint64_t name, clock::time_point now) {
  if (source > kJ1939MaxAddress) return;  // Cannot Claim holds no address
  if (name == name_) return;              // our own claim
  claims_[source] = name;
  if (state_ == J1939ClaimState::NoBus || state_ == J1939ClaimState::CannotClaim || collecting_) return;
  if (!has_address_ || source != address_) return;
  if (name > name_) {
    // We win: defend the address.
    actions_.send_claim(address_);
    return;
  }
  int next = next_free(address_);
  if (next < 0) {
    cannot_claim();
    return;
  }
  log_warn("J1939: address %u lost to an ECU with a lower NAME (0x%016llX); claiming %d", address_,
           static_cast<unsigned long long>(name), next);
  claim(static_cast<uint8_t>(next), now);
}

void AddressClaimer::on_claim_request(clock::time_point now) {
  if (state_ == J1939ClaimState::CannotClaim) {
    // One answer per wait; requests meanwhile are answered by it.
    if (!cannot_claim_due_) {
      cannot_claim_due_ = true;
      cannot_claim_at_ = now + cannot_claim_delay();
    }
  } else if (has_address_ && !collecting_) {
    actions_.send_claim(address_);
  }
}

void AddressClaimer::tick(clock::time_point now) {
  if (cannot_claim_due_ && now >= cannot_claim_at_) {
    cannot_claim_due_ = false;
    if (state_ == J1939ClaimState::CannotClaim) actions_.send_claim(kJ1939NullAddress);
  }
  if (state_ != J1939ClaimState::Claiming || now < deadline_) return;
  if (collecting_) {
    collecting_ = false;
    uint8_t want = static_cast<uint8_t>(ecu_.address);
    auto held = claims_.find(want);
    if (held == claims_.end() || held->second > name_) {
      claim(want, now);
      return;
    }
    int next = next_free(want);
    if (next < 0) {
      cannot_claim();
      return;
    }
    log_warn("J1939: address %u is held by an ECU with a lower NAME (0x%016llX); claiming %d", want,
             static_cast<unsigned long long>(held->second), next);
    claim(static_cast<uint8_t>(next), now);
    return;
  }
  state_ = J1939ClaimState::Claimed;
  log_info("J1939: address %u claimed (NAME 0x%016llX)", address_, static_cast<unsigned long long>(name_));
}

}  // namespace canopen_plugin
