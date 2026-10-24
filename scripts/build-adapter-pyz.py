#!/usr/bin/env python3
"""The adapter server as one file, canworks-adapter-<version>.pyz
(canopen-remote-adapter "Adapter server file"): canworks-diag, adapter-serve
included, for Python 3.11 or newer with only the standard library.

  build-adapter-pyz.py (--wheel WHEEL | --source tools/deploy) --constraints FILE --out FILE.pyz

The file holds canworks without the parts a device never runs (DROP) and
python-can and pyserial with their dependencies at the constraints'
versions, pure Python only: compiled extensions are removed (wrapt falls
back to its Python code). Fails when the file is larger than MAX_BYTES.
"""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import zipapp
import zipfile

DROP = ("configurator", "library", "nodered_package", "codesys", "builtin_notes")
PACKAGES = ("python-can", "pyserial")
MAX_BYTES = 2 * 1024 * 1024

MAIN = '''import sys

if sys.version_info < (3, 11):
    sys.stderr.write("canworks-adapter: this file needs Python 3.11 or newer (this is Python %d.%d)\\n"
                     % sys.version_info[:2])
    sys.exit(1)

from canworks.diag import main

sys.exit(main())
'''


def _canworks(args, into):
    if args.wheel:
        with zipfile.ZipFile(args.wheel) as z:
            for name in z.namelist():
                if name.startswith("canworks/"):
                    z.extract(name, into)
    else:
        shutil.copytree(os.path.join(args.source, "canworks"), os.path.join(into, "canworks"))
    for name in DROP:
        shutil.rmtree(os.path.join(into, "canworks", name))


def _dependencies(constraints, into):
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "--disable-pip-version-check", "--no-compile",
                    "--only-binary=:all:", "--target", into, "-c", constraints] + list(PACKAGES), check=True)


def _prune(root):
    for top, dirs, files in os.walk(root, topdown=False):
        for d in dirs:
            if d == "__pycache__" or d.endswith(".dist-info") or d == "bin":
                shutil.rmtree(os.path.join(top, d))
        for f in files:
            if f.endswith((".so", ".pyd", ".pyc")):
                os.remove(os.path.join(top, f))


def build(args):
    with tempfile.TemporaryDirectory(prefix="canworks-adapter-pyz-") as tmp:
        root = os.path.join(tmp, "root")
        os.mkdir(root)
        _canworks(args, root)
        _dependencies(args.constraints, root)
        _prune(root)
        with open(os.path.join(root, "__main__.py"), "w", encoding="utf-8") as f:
            f.write(MAIN)
        zipapp.create_archive(root, args.out, interpreter="/usr/bin/env python3", compressed=True)
    size = os.path.getsize(args.out)
    if size > MAX_BYTES:
        os.remove(args.out)
        sys.exit("build-adapter-pyz: the file is %d bytes, more than %d" % (size, MAX_BYTES))
    print("%s: %d bytes" % (args.out, size))


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--wheel", help="the release wheel")
    src.add_argument("--source", help="the package folder (tools/deploy), for tests")
    p.add_argument("--constraints", required=True, help="the locked dependency versions")
    p.add_argument("--out", required=True)
    build(p.parse_args(argv))


if __name__ == "__main__":
    main()
