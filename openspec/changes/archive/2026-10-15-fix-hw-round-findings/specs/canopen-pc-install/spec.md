## MODIFIED Requirements

### Requirement: Adapter libraries in the package
The tools package SHALL depend on python-can and pyserial, and every dependency SHALL install with uv from wheels or pure Python sources on Windows, macOS (Intel and Apple silicon) and Linux (x86_64 and ARM64) without a compiler. The PC tools CI job SHALL run the local backend's virtual-bus tests on each of its runners.

On Windows the package SHALL also bring everything a gs_usb adapter needs: python-can's gs_usb driver with pyusb, and a libusb DLL (the `libusb` package), which the tools SHALL find without the user putting it on the PATH. `canworks-diag adapters` SHALL then list a plugged-in gs_usb adapter, and `gs_usb:0` SHALL open, with nothing else installed.

#### Scenario: Fresh install on each runner
- **WHEN** the PC tools job installs the wheel with uv on its four runners
- **THEN** the install needs no compiler and the local backend's virtual-bus tests pass on each

#### Scenario: gs_usb adapter on Windows
- **WHEN** the wheel is installed with uv on a Windows PC with a gs_usb (candleLight) adapter plugged in and nothing else installed
- **THEN** `canworks-diag adapters` lists `gs_usb:0` and `canworks-diag --adapter gs_usb:0 --bitrate 500 scan` runs
