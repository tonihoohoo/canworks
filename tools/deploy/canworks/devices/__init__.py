"""The configurator's Devices workspace (device-install): the devices of a
project, SSH to them, the read-only probe, what to install, and install jobs
that run on the device by themselves.

No password is ever stored: devices.json keeps hosts, users and host keys
only, and the SSH and sudo passwords live in the one request that uses them.
"""
