import os

# No update check against GitHub from configurators the tests start
# (pc-tools-self-update); test_update.py checks against a local server.
os.environ.setdefault("CANWORKS_NO_UPDATE_CHECK", "1")
