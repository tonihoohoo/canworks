"""Test helpers: a sample editor build output and a stub runtime API."""

import json
import os
import shutil
import ssl
import subprocess
import sys
import tempfile
import threading
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
PINGPONG = os.path.join(REPO, "config", "pingpong")


def editor_bundle(root, conf=None):
    """A runtime v4 bundle as the editor's "Build only" writes it."""
    os.makedirs(os.path.join(root, "strucpp_runtime", "include"))
    files = {
        "generated.hpp": "// generated\n",
        "generated.cpp": "#include \"generated.hpp\"\n",
        "generated_debug.cpp": "// debug\n",
        "debug-map.json": "{}\n",
        "program.st": "PROGRAM main\nEND_PROGRAM\n",
        "defines.h": "#define PROGRAM_MD5 \"x\"\n",
        "strucpp_runtime/include/iec_std_lib.hpp": "// lib\n",
    }
    for name, text in (conf or {}).items():
        files["conf/" + name] = text if isinstance(text, str) else json.dumps(text, indent=2)
    for name, text in files.items():
        path = os.path.join(root, *name.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
    return root


def pingpong_config(dir_, **changes):
    """The ping-pong example config with its EDS, copied to dir_."""
    with open(os.path.join(PINGPONG, "canopen_config.json"), encoding="utf-8") as f:
        cfg = json.load(f)
    cfg.update(changes)
    shutil.copy(os.path.join(PINGPONG, "cpp-slave.eds"), dir_)
    path = os.path.join(dir_, "canopen_config.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
    return path


def zip_contents(path):
    with zipfile.ZipFile(path) as z:
        return {n: z.read(n) for n in z.namelist()}


def make_cert(dir_):
    """A self-signed certificate for localhost/127.0.0.1, or None without openssl."""
    cert, key = os.path.join(dir_, "cert.pem"), os.path.join(dir_, "key.pem")
    try:
        subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-sha256", "-nodes", "-keyout", key,
                        "-out", cert, "-days", "2", "-subj", "/CN=localhost",
                        "-addext", "subjectAltName=DNS:localhost,IP:127.0.0.1"],
                       check=True, capture_output=True)
    except (OSError, subprocess.CalledProcessError):
        return None
    return cert, key


class StubRuntime:
    """The runtime's login, upload-file, compilation-status, status and start-plc endpoints."""

    def __init__(self, cert, key, password="secret", build_ok=True, canopen_line=True, editor_hook=False,
                 hook_error=None, start_answer="START:OK"):
        self.password = password
        self.start_answer = start_answer
        self.plc = "STOPPED"  # an upload leaves the PLC stopped
        self.editor_hook = editor_hook
        self.hook_error = hook_error
        self.build_ok = build_ok
        self.canopen_line = canopen_line
        self.requests = []
        self.users = ["openplc"]  # /api/create-user only works while this is empty
        self.uploaded = None
        self.polls = 0
        stub = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def reply(self, status, doc):
                body = json.dumps(doc).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def authorized(self):
                return self.headers.get("Authorization") == "Bearer token-1"

            def do_POST(self):
                body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
                stub.requests.append(("POST", self.path))
                if self.path == "/api/login":
                    doc = json.loads(body)
                    if doc.get("password") != stub.password:
                        return self.reply(401, "Wrong username or password")
                    return self.reply(200, {"access_token": "token-1"})
                if self.path == "/api/create-user":
                    if stub.users:
                        return self.reply(401, {"msg": "User already created"})
                    doc = json.loads(body)
                    stub.users.append(doc["username"])
                    stub.password = doc["password"]
                    return self.reply(201, {"msg": "User created", "id": 1})
                if self.path == "/api/upload-file":
                    if not self.authorized():
                        return self.reply(401, {"msg": "Missing Authorization Header"})
                    boundary = self.headers["Content-Type"].split("boundary=")[1].encode()
                    part = body.split(b"--" + boundary)[1]
                    stub.uploaded = part.split(b"\r\n\r\n", 1)[1].rsplit(b"\r\n", 1)[0]
                    return self.reply(200, {"UploadFileFail": "", "CompilationStatus": "COMPILING"})
                self.reply(404, {})

            def do_GET(self):
                stub.requests.append(("GET", self.path))
                if self.path == "/api/version":
                    return self.reply(200, {"version": "v4.2.4"})
                if self.path == "/api/get-users-info" and not self.authorized():
                    return self.reply(200 if stub.users else 404, {"msg": "Users found" if stub.users else
                                                                    "No users found"})
                if self.path == "/api/status" and self.authorized():
                    state = stub.plc
                    if state == "TRANSITIONING":
                        stub.plc = "RUNNING"
                    return self.reply(200, {"status": "STATUS:%s\n" % state})
                if self.path == "/api/start-plc" and self.authorized():
                    if stub.start_answer == "START:OK":
                        stub.plc = "TRANSITIONING"
                    return self.reply(200, {"status": stub.start_answer + "\n"})
                if self.path == "/api/compilation-status" and self.authorized():
                    stub.polls += 1
                    logs = []
                    if stub.editor_hook:
                        logs.append("[INFO] CANopen: the upload carries conf/canworks.json; the project snapshot "
                                    "is not used\n")
                    logs.append("[INFO] Found 2 config files in core/generated/conf: ['canworks', 'ethercat']\n")
                    if stub.canopen_line:
                        logs.append("[DEBUG] Final state - canopen: enabled=True, "
                                    "config_path='/opt/canworks/lib/canworks.json'\n")
                    logs.append("[DEBUG] Final state - ethercat: enabled=True, config_path='x'\n")
                    if stub.hook_error:
                        logs.append("[ERROR] CANopen: %s\n" % stub.hook_error)
                    if stub.polls < 2:
                        return self.reply(200, {"status": "COMPILING", "logs": logs, "exit_code": None})
                    logs.append("[INFO] Build finished successfully\n" if stub.build_ok
                                else "[ERROR] generated.cpp:1: error: boom\n")
                    return self.reply(200, {"status": "SUCCESS" if stub.build_ok else "FAILED", "logs": logs,
                                            "exit_code": 0 if stub.build_ok else 1})
                self.reply(404, {})

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(cert, key)
        self.server.socket = ctx.wrap_socket(self.server.socket, server_side=True)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *a):
        self.server.shutdown()
        self.server.server_close()


def tmpdir(test):
    d = tempfile.mkdtemp(prefix="deploy-test-")
    test.addCleanup(shutil.rmtree, d, True)
    return d


def python_program(path, source):
    """A program at path that runs the Python source with this interpreter.

    POSIX: an executable script with a shebang. Windows cannot run those, so it
    gets <path>.py and a <path>.cmd that starts it; returns the path to run."""
    if os.name == "nt":
        with open(path + ".py", "w", encoding="utf-8") as f:
            f.write(source)
        with open(path + ".cmd", "w", encoding="utf-8") as f:
            f.write('@"%s" "%s" %%*\r\n' % (sys.executable, path + ".py"))
        return path + ".cmd"
    with open(path, "w", encoding="utf-8") as f:
        f.write("#!%s\n" % sys.executable + source)
    os.chmod(path, 0o755)
    return path


def fake_editor_cli(dir_, fail=False):
    """A stand-in `openplc-cli` whose `create` writes what OpenPLC Editor 4.3.2
    writes for a new Structured Text project, and logs its arguments to
    <dir_>/cli-args.json."""
    return python_program(os.path.join(dir_, "openplc-cli"), """import json, os, sys
args = sys.argv[1:]
with open(%(log)r, "w") as f:
    json.dump(args, f)
if %(fail)r:
    print("create failed on purpose")
    sys.exit(4)
assert args[0] == "create", args
name = args[1]
flags = dict(a[2:].split("=", 1) for a in args[2:] if "=" in a)
root = os.path.join(flags["path"], name)
if os.path.exists(root):
    sys.exit(2)
for d in ("devices", "pous/functions", "pous/function-blocks", "pous/programs", "datatypes"):
    os.makedirs(os.path.join(root, d))
project = {"meta": {"name": name, "type": "plc-project"},
           "data": {"pous": [], "dataTypes": [], "libraries": [], "configuration": {"resource": {
               "tasks": [{"name": "task0", "triggering": "Cyclic", "interval": flags.get("time", "T#20ms"),
                          "priority": 1}],
               "instances": [{"name": "instance0", "program": "main", "task": "task0"}],
               "globalVariables": []}}}}
with open(os.path.join(root, "project.json"), "w") as f:
    json.dump(project, f, indent=2)
with open(os.path.join(root, "devices", "configuration.json"), "w") as f:
    json.dump({"deviceBoard": "OpenPLC Simulator", "communicationPort": "", "selectedPlatformOptions": {}}, f,
              indent=2)
with open(os.path.join(root, "devices", "pin-mapping.json"), "w") as f:
    json.dump({}, f, indent=2)
with open(os.path.join(root, "pous", "programs", "main.st"), "w") as f:
    f.write("PROGRAM main\\n  VAR\\n  END_VAR\\n\\n\\n\\nEND_PROGRAM")
print('Created "%%s" at %%s' %% (name, root))
""" % {"log": os.path.join(dir_, "cli-args.json"), "fail": fail})
