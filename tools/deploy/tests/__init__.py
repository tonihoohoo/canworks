import os

# No update check against GitHub from configurators the tests start
# (pc-tools-self-update); test_update.py checks against a local server.
os.environ.setdefault("CANWORKS_NO_UPDATE_CHECK", "1")

# Saving an OpenPLC project installs the canworks library into OpenPLC
# Editor when it is missing: into a throwaway folder here, never the user's.
if "OPENPLC_EDITOR_USER_DATA" not in os.environ:
    import atexit
    import shutil
    import tempfile

    _editor_user_data = tempfile.mkdtemp(prefix="canworks-editor-")
    os.environ["OPENPLC_EDITOR_USER_DATA"] = _editor_user_data
    atexit.register(shutil.rmtree, _editor_user_data, True)
