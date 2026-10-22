# Security policy

## Reporting a problem

Report security problems privately through GitHub: on the repository's **Security** tab choose **Report a vulnerability**. Include what is affected (the plugin, the Modbus bridge, the remote link, a PC tool or a container image), the version, and the steps or input that show the problem. Please do not open a public issue for it; if private reporting is not available, open an issue that only asks for a way to send the details.

Reports are answered as soon as possible. A confirmed problem is fixed in a new release, and the release notes say what was fixed once the release is out.

## Supported versions

Fixes go into `main` and the next `deploy-v<version>` release, with its `canworks-bridge` and `canworks-local-runtime` images. Older releases get no fixes: update to the newest release ([docs/install-pc.md](docs/install-pc.md)) and reinstall the plugin or bridge on the runtime host from the same version.

The bridge and the images are built against the OpenPLC runtime release pinned in `docker/local-runtime/runtime-version`. Problems in the runtime itself, in Lely CANopen or in other upstream components go to those projects; tell us too when canworks needs a change for them.
