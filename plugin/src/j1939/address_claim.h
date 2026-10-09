// address_claim.h - the J1939-81 address claim of the PLC's ECU (design
// Decision 2), as plain logic driven by the bus thread: what was seen on the
// bus goes in, the claims to send come out through Actions. It follows the
// procedure of can-utils' jacd, written anew.
//
// At start it asks every ECU for its claim (Request for Address Claimed from
// the null address) and listens 250 ms, then claims the configured address
// unless an ECU with a lower NAME holds it. A claim stands after 250 ms
// without a contending claim from a lower NAME. Against a lower NAME an
// arbitrary-address-capable ECU moves to the next free address of its range;
// otherwise, or with the range used up, it sends Cannot Claim and stays
// silent. A contending claim from a higher NAME is answered with our claim.

#ifndef CANWORKS_J1939_ADDRESS_CLAIM_H
#define CANWORKS_J1939_ADDRESS_CLAIM_H

#include <chrono>
#include <cstdint>
#include <map>

#include "j1939_config.h"

namespace canopen_plugin {

class AddressClaimer {
 public:
  using clock = std::chrono::steady_clock;
  static constexpr std::chrono::milliseconds kClaimWait{250};

  class Actions {
   public:
    virtual ~Actions() = default;
    // Address Claimed with our NAME from `address`; 254 is Cannot Claim.
    virtual void send_claim(uint8_t address) = 0;
    // Request for Address Claimed to global, from the null address.
    virtual void send_claim_request() = 0;
  };

  AddressClaimer(const J1939Ecu& ecu, Actions& actions);

  // The bus is usable: start over (the table of claims seen is cleared).
  void start(clock::time_point now);
  // The bus is gone: state "no bus", no address.
  void bus_lost();
  // An Address Claimed (or Cannot Claim, from 254) from another ECU.
  void on_claim(uint8_t source, uint64_t name, clock::time_point now);
  // A Request for Address Claimed to global or to our address.
  void on_claim_request();
  // Runs what is due; call at least every few milliseconds.
  void tick(clock::time_point now);

  J1939ClaimState state() const { return state_; }
  // The address held (claimed), else 254.
  uint8_t address() const { return state_ == J1939ClaimState::Claimed ? address_ : kJ1939NullAddress; }
  // The address being claimed or held, 254 when none.
  uint8_t claiming_address() const { return (collecting_ || !has_address_) ? kJ1939NullAddress : address_; }
  uint64_t name() const { return name_; }
  // Other ECUs' claims seen since start(): address -> NAME.
  const std::map<uint8_t, uint64_t>& claims() const { return claims_; }

 private:
  // The next address to claim after losing `from`, or -1.
  int next_free(int from) const;
  void claim(uint8_t address, clock::time_point now);
  void cannot_claim();

  const J1939Ecu& ecu_;
  Actions& actions_;
  uint64_t name_;
  J1939ClaimState state_ = J1939ClaimState::NoBus;
  bool collecting_ = false;
  bool has_address_ = false;
  uint8_t address_ = kJ1939NullAddress;
  clock::time_point deadline_{};
  std::map<uint8_t, uint64_t> claims_;
};

const char* j1939_claim_state_name(J1939ClaimState s);

}  // namespace canopen_plugin

#endif  // CANWORKS_J1939_ADDRESS_CLAIM_H
