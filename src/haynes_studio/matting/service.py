"""A small HTTP/1.0 service and a probe, both restricted to a Unix socket."""

from __future__ import annotations

import http.client
import os
import re
import socket
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from socketserver import ThreadingMixIn, UnixStreamServer
from stat import S_ISSOCK
from threading import BoundedSemaphore, Thread

from haynes_studio.jsonio import parse_strict
from haynes_studio.store import canonical_json

from .profile import (
    BUSY, COMMAND_FAILED, NOT_FOUND, PIN_MISMATCH, REQUEST_INVALID, RESPONSE_INVALID,
    TIMEOUT, MatteError,
)

MAX_REQUEST = 4096
MAX_REPLY = 8192
STATUS = {
    BUSY: 409, COMMAND_FAILED: 500, NOT_FOUND: 503, PIN_MISMATCH: 409,
    REQUEST_INVALID: 400, RESPONSE_INVALID: 502, TIMEOUT: 504,
}


class _Handler(BaseHTTPRequestHandler):
    def setup(self):
        self.request.settimeout(3)
        super().setup()

    def log_message(self, *_):
        pass

    def address_string(self):
        return "local"

    def _reply(self, status: int, document: dict):
        body = canonical_json(document)
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path != "/v1/ready":
            self._reply(404, {"code": NOT_FOUND})
        elif ready := self.server.engine.readiness:
            self._reply(200, ready)
        else:
            self._reply(503, {"code": NOT_FOUND})

    def do_POST(self):
        if self.path != "/v1/matte":
            self._reply(404, {"code": NOT_FOUND})
            return
        lengths = self.headers.get_all("Content-Length", [])
        if (len(lengths) != 1 or not re.fullmatch(r"[0-9]{1,4}", lengths[0])
                or not 0 < int(lengths[0]) <= MAX_REQUEST or self.headers.get("Transfer-Encoding")
                or self.headers.get_content_type() != "application/json"):
            self._reply(400, {"code": REQUEST_INVALID})
            return
        try:
            body = self.rfile.read(int(lengths[0]))
            if len(body) != int(lengths[0]):
                raise ValueError
            value = parse_strict(body.decode("utf-8"))
        except (ValueError, RecursionError, TimeoutError):
            self._reply(400, {"code": REQUEST_INVALID})
            return
        try:
            receipt = self.server.engine.run(value)
        except MatteError as error:
            self._reply(STATUS[error.code], {"code": error.code})
        else:
            self._reply(200, receipt)


class MatteServer(ThreadingMixIn, UnixStreamServer):
    """Bound the number of local handlers, including partially sent requests."""

    def __init__(self, path: Path, engine):
        self.engine = engine
        self._slots = BoundedSemaphore(4)
        self._path = path
        self._bound = False
        try:
            facts = path.lstat()
        except FileNotFoundError:
            pass
        else:
            if not S_ISSOCK(facts.st_mode) or facts.st_uid != os.getuid():
                raise MatteError(COMMAND_FAILED)
            # A previous container may leave its socket in the shared volume.
            # Probe it before unlinking so we cannot displace a live listener.
            with socket.socket(socket.AF_UNIX) as probe:
                probe.settimeout(1)
                try:
                    probe.connect(str(path))
                except ConnectionRefusedError:
                    path.unlink()
                else:
                    raise MatteError(BUSY)
        # Restrict the initial socket mode as well as the final mode (0660).
        old_umask = os.umask(0o117)
        try:
            super().__init__(str(path), _Handler)
            self._bound = True
        finally:
            os.umask(old_umask)
        try:
            path.chmod(0o660)
        except OSError:
            self.server_close()
            raise

    def process_request(self, request, client_address):
        if not self._slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._slots.release()

    def handle_error(self, request, client_address):
        # A caller may disconnect during work. No request data or filesystem
        # locations are emitted by the service.
        pass

    def server_close(self):
        super().server_close()
        if self._bound:
            self._path.unlink(missing_ok=True)
            self._bound = False


class _UnixConnection(http.client.HTTPConnection):
    def __init__(self, path: Path, timeout: float):
        super().__init__("localhost", timeout=timeout)
        self._path = path

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX)
        self.sock.settimeout(self.timeout)
        self.sock.connect(str(self._path))


def local_call(path: Path, method: str, route: str, payload: dict | None = None,
               *, timeout: float = 35) -> tuple[int, dict]:
    connection = _UnixConnection(path, timeout)
    try:
        connection.request(method, route, body=canonical_json(payload) if payload is not None else None,
                           headers={"Content-Type": "application/json"})
        response = connection.getresponse()
        body = response.read(MAX_REPLY + 1)
        if len(body) > MAX_REPLY:
            raise MatteError(RESPONSE_INVALID)
        return response.status, parse_strict(body.decode("utf-8"))
    finally:
        connection.close()


@contextmanager
def listening(path: Path, engine):
    with MatteServer(path, engine) as server:
        thread = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.1})
        thread.start()
        try:
            yield
        finally:
            server.shutdown()
            thread.join()
