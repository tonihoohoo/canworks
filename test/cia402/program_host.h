// program_host.h - runs a PLC program compiled by STruC++ (the editor's
// compiler) inside a test, against the fake runtime image: the located
// variables the program declares are copied from the image before each scan
// and back after it, as the OpenPLC runtime binds them.
//
// Built only when CMake is given -DSTRUCPP=<strucpp command>
// (scripts/fetch-strucpp.sh); the programs are config/cia402-drive/drive_demo.st
// (namespace program_host) and drive_cyclic_demo.st (program_host_cyclic).
// The interface uses plain types so the compiler's runtime headers stay in
// program_host.cpp.

#ifndef CIA402_PROGRAM_HOST_H
#define CIA402_PROGRAM_HOST_H

#include <cstdint>

namespace program_host {

struct Image {
  uint8_t (*bool_in)[8];
  uint8_t (*bool_out)[8];
  uint8_t* byte_in;
  uint8_t* byte_out;
  uint16_t* int_in;
  uint16_t* int_out;
  uint32_t* dint_in;
  uint32_t* dint_out;
  int size;  // entries per table
};

// A fresh program instance (variables at their initial values).
void Reset();
// One scan at `now_ns` (the program's TIME()).
void Scan(const Image& image, int64_t now_ns);
// The program's step variable, for the test (-1 when it has none).
int Step();
// Located variables the program declares.
int LocatedCount();

}  // namespace program_host

#endif  // CIA402_PROGRAM_HOST_H
