#!/usr/bin/env python3
"""Reads and edits the OpenPLC bootloader's runtime spec for
scripts/install-bridge.sh --pinned-runtime.

The managed Docker install of OpenPLC Runtime v4 keeps the runtime container's
settings in /var/lib/openplc-bootloader/runtime-spec.json; the bootloader
reads the file when it starts and rejects unknown keys. This changes the
runtime version only and leaves everything else as it was.

    docker_spec.py image SPEC            prints <repository>:<version>
    docker_spec.py version SPEC          prints the runtime version (the image tag)
    docker_spec.py set-version SPEC VER  sets the runtime version, nothing else

Writes go to a temporary file in the same directory and replace the spec
atomically, keeping its mode.
"""

import json
import os
import re
import sys
import tempfile


class SpecError(Exception):
    pass


def load(path):
    try:
        with open(path, encoding="utf-8") as f:
            spec = json.load(f)
    except (OSError, ValueError) as e:
        raise SpecError("cannot read %s: %s" % (path, e))
    if not isinstance(spec, dict):
        raise SpecError("%s is not a JSON object" % path)
    for key in ("repository", "version"):
        if not isinstance(spec.get(key), str) or not spec[key]:
            raise SpecError("%s has no %r; this bootloader version is not supported" % (path, key))
    for key in ("extraBinds", "extraEnv"):
        if key in spec and not (isinstance(spec[key], list) and all(isinstance(v, str) for v in spec[key])):
            raise SpecError("%s: %r is not a list of strings" % (path, key))
    return spec


def image(spec):
    return "%s:%s" % (spec["repository"], spec["version"])


def set_version(spec, version):
    """The runtime version (freeze-openplc-runtime): a release tag only."""
    if not re.match(r"^v\d+\.\d+\.\d+$", version):
        raise SpecError("not an OpenPLC runtime release version: %r" % version)
    spec["version"] = version
    return spec


def save(path, spec):
    directory = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(prefix=".runtime-spec.", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(spec, f, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        try:
            st = os.stat(path)
            os.chmod(tmp, st.st_mode & 0o7777)
            os.chown(tmp, st.st_uid, st.st_gid)
        except OSError:
            pass
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def main(argv):
    if len(argv) < 2:
        sys.stderr.write(__doc__)
        return 2
    cmd, path = argv[0], argv[1]
    try:
        spec = load(path)
        if cmd == "image" and len(argv) == 2:
            print(image(spec))
        elif cmd == "version" and len(argv) == 2:
            print(spec["version"])
        elif cmd == "set-version" and len(argv) == 3:
            changed = set_version(json.loads(json.dumps(spec)), argv[2])
            if changed != spec:
                save(path, changed)
        else:
            sys.stderr.write(__doc__)
            return 2
    except SpecError as e:
        sys.stderr.write("error: %s\n" % e)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
