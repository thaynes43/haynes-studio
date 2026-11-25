"""HTTP over a private Unix socket. Only the supervised engine runs inference."""

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
from time import monotonic

from haynes_studio.jsonio import parse_strict
from haynes_studio.store import canonical_json

from .profile import REQUEST_SECONDS, SegmentationError, digest

MAX_REQUEST = 4096
MAX_REPLY = 8192
MAX_DRAIN = 65536
STATUS = {
    "invalid_input": 400, "input_unavailable": 404, "profile_unavailable": 503,
    "timeout": 504, "inference_failed": 500, "invalid_output": 502, "store_failed": 500, "busy": 409,
}


class _Handler(BaseHTTPRequestHandler):
    busy = False

    def setup(self):
        self.request.settimeout(3)
        super().setup()

    def log_message(self, *_):
        pass

    def _reply(self, status: int, document: dict):
        body = canonical_json(document)
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self, size: int) -> bytes:
        deadline = monotonic() + 3
        body = bytearray()
        try:
            while len(body) < size and (remaining := deadline - monotonic()) > 0:
                self.request.settimeout(remaining)
                chunk = self.rfile.read1(min(size - len(body), 8192))
                if not chunk:
                    break
                body.extend(chunk)
        except OSError:
            pass
        finally:
            self.request.settimeout(3)
        return bytes(body)

    def do_GET(self):
        if self.path != "/v1/ready":
            self._reply(404, {"code": "not_found"})
        elif ready := self.server.engine.readiness:
            self._reply(200, ready)
        else:
            self._reply(503, {"code": "profile_unavailable"})

    def do_POST(self):
        lengths = self.headers.get_all("Content-Length", [])
        size = int(lengths[0]) if len(lengths) == 1 and re.fullmatch(r"[0-9]{1,9}", lengths[0]) else 0
        # Even refusals consume a bounded part of the announced body before
        # sending a reply, so the client can finish its ordinary body write.
        body = self._body(min(size, MAX_DRAIN))
        if self.path != "/v1/segment":
            self._reply(404, {"code": "not_found"})
            return
        if self.busy:
            self._reply(409, {"code": "busy"})
            return
        if (not 0 < size <= MAX_REQUEST or len(body) != size or self.headers.get("Transfer-Encoding")
                or self.headers.get_content_type() != "application/json"):
            self._reply(400, {"code": "invalid_input"})
            return
        try:
            payload = parse_strict(body.decode("utf-8"))
            receipt = self.server.engine.run(payload)
        except (ValueError, RecursionError):
            self._reply(400, {"code": "invalid_input"})
        except SegmentationError as error:
            self._reply(STATUS[error.reason], {"code": error.reason})
        else:
            status = STATUS[receipt["reason"]] if receipt["status"] == "failed" else 200
            self._reply(status, {"result": receipt, "result_sha256": digest(canonical_json(receipt))})


class _BusyHandler(_Handler):
    busy = True


class Server(ThreadingMixIn, UnixStreamServer):
    def __init__(self, path: Path, engine):
        self.engine = engine
        self._path = path
        self._bound = False
        self._slots = BoundedSemaphore(4)
        try:
            facts = path.lstat()
        except FileNotFoundError:
            pass
        else:
            if not S_ISSOCK(facts.st_mode) or facts.st_uid != os.getuid():
                raise SegmentationError("inference_failed")
            with socket.socket(socket.AF_UNIX) as probe:
                probe.settimeout(1)
                try:
                    probe.connect(str(path))
                except ConnectionRefusedError:
                    path.unlink()
                else:
                    raise SegmentationError("busy")
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

    def process_request(self, request, address):
        if not self._slots.acquire(blocking=False):
            try:
                _BusyHandler(request, address, self)
            except OSError:
                pass
            finally:
                self.shutdown_request(request)
            return
        try:
            super().process_request(request, address)
        except BaseException:
            self._slots.release()
            raise

    def process_request_thread(self, request, address):
        try:
            super().process_request_thread(request, address)
        finally:
            self._slots.release()

    def handle_error(self, request, address):
        # The caller can disconnect mid-request. Keep request contents private.
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


def local_call(path: Path, method: str, route: str, payload: dict | None = None, *,
               timeout: float = REQUEST_SECONDS + 5) -> tuple[int, dict]:
    connection = _UnixConnection(path, timeout)
    try:
        connection.request(method, route, body=canonical_json(payload) if payload is not None else None,
                           headers={"Content-Type": "application/json"})
        response = connection.getresponse()
        body = response.read(MAX_REPLY + 1)
        if len(body) > MAX_REPLY:
            raise SegmentationError("invalid_output")
        return response.status, parse_strict(body.decode("utf-8"))
    finally:
        connection.close()


@contextmanager
def listening(path, engine):
    with Server(path, engine) as server:
        thread = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.1})
        thread.start()
        try:
            yield
        finally:
            server.shutdown()
            thread.join()
