"""The OpenPLC Runtime v4 REST API, as the editor uses it:

  POST /api/login               {"username", "password"} -> {"access_token"}
  POST /api/upload-file         multipart field "file" (the program zip)
                                -> {"UploadFileFail": "" | reason, ...}
  GET  /api/compilation-status  -> {"status": IDLE|UNZIPPING|COMPILING|SUCCESS|FAILED,
                                    "logs": [...], "exit_code"}
  GET  /api/status              -> {"status": "STATUS:RUNNING" | STOPPED | EMPTY | INIT | TRANSITIONING | ERROR}
  GET  /api/start-plc           -> {"status": "START:OK" | START:ERROR_ALREADY_RUNNING |
                                    START:ERROR_SWITCH_STOP | START:ERROR}

The runtime serves HTTPS on port 8443 with a self-signed certificate. The
certificate is checked against a CA file (--ca, e.g. the runtime's own
cert.pem) or a pinned SHA-256 fingerprint (--fingerprint) before anything,
credentials included, is sent; --insecure skips the check.
"""

import hashlib
import http.client
import json
import ssl
import time
import uuid
from urllib.parse import urlsplit

DEFAULT_PORT = 8443


class RuntimeError_(Exception):
    pass


class CertificateError(RuntimeError_):
    pass


def normalize_fingerprint(text):
    return text.replace(":", "").replace(" ", "").lower()


def fingerprint_of(der):
    digest = hashlib.sha256(der).hexdigest().upper()
    return ":".join(digest[i:i + 2] for i in range(0, len(digest), 2))


def parse_target(runtime):
    """'host', 'host:port' or 'https://host:port' -> (host, port)."""
    if "//" not in runtime:
        runtime = "https://" + runtime
    u = urlsplit(runtime)
    if u.scheme != "https":
        raise RuntimeError_("the runtime API is HTTPS only: %s" % runtime)
    if not u.hostname:
        raise RuntimeError_("no host in %s" % runtime)
    return u.hostname, u.port or DEFAULT_PORT


class Client:
    def __init__(self, runtime, ca=None, fingerprint=None, insecure=False, timeout=30.0):
        self.host, self.port = parse_target(runtime)
        self.fingerprint = normalize_fingerprint(fingerprint) if fingerprint else None
        self.timeout = timeout
        if ca:
            self.context = ssl.create_default_context(cafile=ca)
        elif fingerprint or insecure:
            # The fingerprint is compared by hand right after the handshake.
            self.context = ssl._create_unverified_context()
        else:
            self.context = ssl.create_default_context()
        self.token = None

    def _connect(self):
        conn = http.client.HTTPSConnection(self.host, self.port, context=self.context, timeout=self.timeout)
        try:
            conn.connect()
        except ssl.SSLCertVerificationError as e:
            seen = self._peek_fingerprint()
            raise CertificateError(
                "the runtime's certificate is not trusted (%s). Check it on the device and pass it with --ca "
                "<cert.pem>, or pin it with --fingerprint%s" % (e.verify_message or e,
                                                               " " + seen if seen else " <SHA-256>"))
        except (OSError, ssl.SSLError) as e:
            raise RuntimeError_("cannot connect to %s:%d: %s" % (self.host, self.port, e))
        if self.fingerprint:
            seen = fingerprint_of(conn.sock.getpeercert(binary_form=True))
            if normalize_fingerprint(seen) != self.fingerprint:
                conn.close()
                raise CertificateError("the runtime's certificate fingerprint %s does not match --fingerprint"
                                       % seen)
        return conn

    def _peek_fingerprint(self):
        """The fingerprint the server presents, for the error message only."""
        try:
            pem = ssl.get_server_certificate((self.host, self.port), timeout=self.timeout)
            return fingerprint_of(ssl.PEM_cert_to_DER_cert(pem))
        except (OSError, ssl.SSLError, ValueError):
            return None

    def _request(self, method, path, body=None, headers=None):
        conn = self._connect()
        try:
            h = dict(headers or {})
            if self.token:
                h["Authorization"] = "Bearer " + self.token
            conn.request(method, path, body=body, headers=h)
            resp = conn.getresponse()
            data = resp.read()
        except (OSError, http.client.HTTPException) as e:
            raise RuntimeError_("%s %s failed: %s" % (method, path, e))
        finally:
            conn.close()
        try:
            doc = json.loads(data.decode("utf-8")) if data else None
        except ValueError:
            doc = data.decode("utf-8", "replace")
        return resp.status, doc

    def login(self, user, password):
        status, doc = self._request("POST", "/api/login", json.dumps({"username": user, "password": password}),
                                    {"Content-Type": "application/json"})
        if status != 200 or not isinstance(doc, dict) or not doc.get("access_token"):
            reason = doc.get("msg") if isinstance(doc, dict) else doc
            raise RuntimeError_("login as %s failed (HTTP %d): %s" % (user, status, reason or "no token"))
        self.token = doc["access_token"]

    def upload(self, zip_bytes, filename="program.zip"):
        boundary = uuid.uuid4().hex
        body = (("--%s\r\nContent-Disposition: form-data; name=\"file\"; filename=\"%s\"\r\n"
                 "Content-Type: application/zip\r\n\r\n" % (boundary, filename)).encode()
                + zip_bytes + ("\r\n--%s--\r\n" % boundary).encode())
        status, doc = self._request("POST", "/api/upload-file", body,
                                    {"Content-Type": "multipart/form-data; boundary=" + boundary})
        if status != 200 or not isinstance(doc, dict):
            raise RuntimeError_("upload failed (HTTP %d): %s" % (status, doc))
        if doc.get("UploadFileFail"):
            raise RuntimeError_("the runtime rejected the upload: %s" % doc["UploadFileFail"])
        return doc

    def compilation_status(self):
        status, doc = self._request("GET", "/api/compilation-status")
        if status != 200 or not isinstance(doc, dict):
            raise RuntimeError_("compilation-status failed (HTTP %d): %s" % (status, doc))
        return doc

    def wait_for_build(self, on_log, timeout=900.0, interval=1.0, sleep=time.sleep):
        """Polls compilation-status until SUCCESS or FAILED, passing each new
        log line to on_log. Returns (succeeded, all log lines)."""
        printed = 0
        deadline = time.monotonic() + timeout
        while True:
            doc = self.compilation_status()
            logs = doc.get("logs") or []
            for line in logs[printed:]:
                on_log(line)
            printed = max(printed, len(logs))
            if doc.get("status") in ("SUCCESS", "FAILED"):
                return doc["status"] == "SUCCESS", logs
            if time.monotonic() > deadline:
                raise RuntimeError_("the runtime is still %s after %d s" % (doc.get("status"), timeout))
            sleep(interval)

    def _plc(self, command):
        status, doc = self._request("GET", "/api/" + command)
        if status != 200 or not isinstance(doc, dict):
            raise RuntimeError_("%s failed (HTTP %d): %s" % (command, status, doc))
        return str(doc.get("status") or "").strip().upper()

    def plc_status(self):
        """RUNNING, STOPPED, EMPTY, INIT, TRANSITIONING, ERROR or what else the runtime says."""
        return self._plc("status").split(":", 1)[-1]

    def start_plc(self, timeout=30.0, interval=0.5, sleep=time.sleep):
        """Starts the PLC program and waits until the runtime reports it
        running. An upload leaves the PLC stopped. Returns True when this call
        started it, False when it was already running."""
        deadline = time.monotonic() + timeout
        sent = False
        while True:
            state = self.plc_status()
            if state == "RUNNING":
                return sent
            if state not in ("INIT", "TRANSITIONING") and not sent:
                answer = self._plc("start-plc")
                if "ALREADY_RUNNING" in answer:
                    return False
                if "SWITCH_STOP" in answer:
                    raise RuntimeError_("the PLC was not started: the device's run/stop switch is at STOP")
                if answer != "START:OK":
                    raise RuntimeError_("the PLC was not started: the runtime answered %s (status %s)"
                                        % (answer or "nothing", state))
                sent = True
            elif sent and state in ("ERROR", "EMPTY"):
                raise RuntimeError_("the PLC did not start: the runtime reports %s" % state)
            if time.monotonic() > deadline:
                raise RuntimeError_("the PLC is still %s %d s after the start" % (state, timeout))
            sleep(interval)


def canopen_state(logs):
    """From the build log's "Final state - <plugin>: enabled=..." lines:
    True/False for the canworks plugin, or None if the log does not say."""
    seen_any = False
    for line in logs:
        if "Final state - " not in line:
            continue
        seen_any = True
        rest = line.split("Final state - ", 1)[1]
        if rest.startswith("canopen:"):
            return "enabled=True" in rest
    return False if seen_any else None


def canopen_errors(logs):
    """The build log's "[ERROR] CANopen: ..." lines: the editor hook turned the
    canworks plugin off after the runtime enabled it (Docker: built for another
    runtime version)."""
    return [line.strip() for line in logs if "[ERROR] CANopen:" in line]
