"""canworks-config: the command and the app shortcut's entry
(skip-reinstall-faster-start). It parses the arguments, finds a running
configurator or starts one, and imports the configurator itself (server.py,
with everything it pulls in) only in the process that serves pages: a start
that hands over to a running configurator, or that starts one in the
background, stays a small Python start.

Ways in:
- a terminal: starts the configurator in the background (launch.background),
  prints its address, asks the browser to open it and returns;
- the app shortcut (--from-shortcut): has no console already, so with no
  configurator running this process becomes the configurator and opens the
  browser itself, with no second Python;
- --foreground and the cases launch.foreground() names: serves here.
"""

import argparse
import importlib
import sys

from .. import __version__
from . import launch

SHORTCUT = "--from-shortcut"


def parser():
    p = argparse.ArgumentParser(
        prog="canworks-config",
        description="Edit the CANopen config of an OpenPLC editor project (or a standalone config folder) in a "
                    "local web page. It runs in the background and stops when its last browser tab is closed; "
                    "started again, it opens a tab on the running one.")
    p.add_argument("path", nargs="?", help="editor project folder, or standalone config folder, to open directly")
    p.add_argument("--port", type=int, default=0, help="port on 127.0.0.1 (default: a free one)")
    p.add_argument("--no-browser", action="store_true",
                   help="print the URL but do not open a browser (stays in the foreground)")
    p.add_argument("--foreground", action="store_true",
                   help="stay in this terminal, printing its messages here; Ctrl-C stops it")
    p.add_argument("--keep-running", action="store_true",
                   help="keep running when no page is open, until Quit or Ctrl-C (scripts, remote use; "
                        "stays in the foreground)")
    p.add_argument("--new-instance", action="store_true",
                   help="start a separate configurator even when one runs already")
    p.add_argument("--create-shortcut", action="store_true",
                   help="add an app shortcut that starts the configurator without a terminal, and exit")
    p.add_argument("--remove-shortcut", action="store_true", help="remove that shortcut, and exit")
    p.add_argument(launch.CHILD, action="store_true", help=argparse.SUPPRESS)  # the background configurator itself
    p.add_argument(SHORTCUT, action="store_true", help=argparse.SUPPRESS)  # started by the app shortcut
    p.add_argument("--verbose", action="store_true", help="log every request")
    p.add_argument("--version", action="version", version="%(prog)s " + __version__)
    return p


def main(argv=None, serving=None):
    """`serving`: the server module when it is already loaded (run as
    `python -m canworks.configurator.server`, which older shortcuts do)."""
    timing = launch.StartTiming.here()
    argv = sys.argv[1:] if argv is None else list(argv)
    args = parser().parse_args(argv)
    if args.create_shortcut or args.remove_shortcut:
        from . import shortcut
        return shortcut.main(remove=args.remove_shortcut)
    child, from_shortcut = args.child_background, args.from_shortcut
    if child:
        launch.log_to_file()
    elif not args.new_instance:
        # One configurator per user: started again, it opens a page of the running one.
        inst = launch.running()
        out = None if from_shortcut else sys.stdout
        done = launch.hand_over(inst, args.path, browser=not args.no_browser, out=out,
                                from_shortcut=from_shortcut) if inst else None
        if done is not None:
            return done
    if from_shortcut:
        launch.log_to_file()  # no console: this process is the background configurator
    elif not child and not launch.foreground(args):
        return launch.background(argv, new_instance=args.new_instance, timing=timing)
    server = serving or importlib.import_module(".server", __package__)
    mode = "terminal" if child else "shortcut" if from_shortcut else "foreground"
    return server.run(args, mode, timing)


if __name__ == "__main__":
    sys.exit(main())
