"""In-memory Wan product service. Only test-time clip bytes cross the transport."""

import hashlib
import json
from datetime import UTC, datetime, timedelta

import httpx

from haynes_studio.adapters.wan import graph_sha256
from haynes_studio.queue.wan import (
    EXPECTED_PROFILES, FOREIGN_ENGINE_QUEUE, PROFILES, RESTART_ERROR, expected_graph,
)

STORY = "https://work.haynesnetwork.com/work_packages/410"


class Clock:
    def __init__(self):
        self.now = datetime(2026, 11, 24, 21, 20, tzinfo=UTC)

    def db_time(self, _conn):
        return self.now

    def monotonic(self):
        return self.now.timestamp()

    def advance(self, seconds):
        self.now += timedelta(seconds=seconds)


class FakeWan:
    def __init__(self, clip=b"decoded separately in transport tests"):
        self.clip = clip
        self.jobs = {}
        self.inputs = {}
        self.events = []
        self.outage = False
        self.held = False
        self.ready = True
        self.active_video_job = None
        self.active_foley_job = None
        self.foreign_engine_queue = False
        self.foreign = False
        self.busy = False
        self.gpu_refusal = None
        self.submit_error = None
        self.connect_error = None
        self.quota = False
        self.lose_reply = False
        self.disappear = False
        self.restart_failures = 0
        self.poll_misses = 0
        self.corrupt = None
        self.corrupt_graph = None
        self.put_bodies = []
        self.submissions = []
        self.before_put = None
        self.before_get = None

    def client(self):
        return httpx.Client(transport=httpx.MockTransport(self.request),
                            base_url="http://wan.example.invalid")

    def request(self, request):
        method, path = request.method, request.url.path
        self.events.append((method, path))
        if self.outage:
            raise httpx.ConnectError("unavailable")
        if path == "/v1/ready":
            if self.held:
                return httpx.Response(503, json={"code": "worker_held"})
            return httpx.Response(200, json={"ready": self.ready, "api_version": "1.0.0",
                                            "active_video_job": self.active_video_job,
                                            "active_foley_job": self.active_foley_job})
        if path == "/v1/profiles":
            return httpx.Response(200, json={"api_version": "1.0.0", "profiles": {
                kind: {"profile": name, **EXPECTED_PROFILES[kind]} for kind, name in PROFILES.items()
            }})
        if path.startswith("/v1/inputs/"):
            assert method == "PUT"
            digest, suffix = path.rsplit("/", 1)[1].split(".")
            assert suffix in ("png", "wav")
            assert int(request.headers["content-length"]) == len(request.content)
            assert hashlib.sha256(request.content).hexdigest() == digest
            if self.quota:
                return httpx.Response(507, json={"code": "input_storage_full"})
            self.inputs[digest] = request.content
            return httpx.Response(201, json={"bytes": len(request.content), "sha256": digest})
        _, v1, jobs, kind, job_id, *file_route = path.split("/")
        assert (v1, jobs) == ("v1", "jobs")
        if method == "PUT":
            assert not file_route
            self.put_bodies.append((job_id, request.content))
            if self.before_put is not None:
                callback, self.before_put = self.before_put, None
                callback()
            if self.connect_error is not None:
                error, self.connect_error = self.connect_error, None
                raise error("connection failed before send")
            body = json.loads(request.content)
            digest = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
            if job_id in self.jobs:
                status = self.jobs[job_id]
                if status["request_sha256"] != digest or status["type"] != kind:
                    return httpx.Response(409, json={"code": "id_conflict"})
                return httpx.Response(200, json=status)
            if self.submit_error is not None:
                status_code, code = self.submit_error
                return httpx.Response(status_code, json={"code": code})
            if self.busy:
                return httpx.Response(409, json={"code": "worker_busy"})
            if self.disappear:
                raise httpx.ReadTimeout("lost before acknowledgement")
            assert body["image_sha256"] in self.inputs
            if kind == "s2v":
                assert body["audio_sha256"] in self.inputs
            graph = graph_sha256(expected_graph({"job_id": job_id, "kind": kind, "request": body}))
            status = {"api_version": "1.0.0", "type": kind, "id": job_id,
                      "request_sha256": digest, "profile": body["profile"],
                      "graph_sha256": self.corrupt_graph or graph}
            if self.restart_failures:
                self.restart_failures -= 1
                status.update(state="failed", error=RESTART_ERROR)
            elif self.foreign_engine_queue:
                status.update(state="failed", error=FOREIGN_ENGINE_QUEUE)
            elif self.gpu_refusal is not None:
                status.update(state="failed", error=self.gpu_refusal)
            else:
                self.submissions.append(job_id)
                status.update(state="succeeded", result={
                    "file_url": path + "/file", "media_type": "video/mp4", "bytes": len(self.clip),
                    "sha256": hashlib.sha256(self.clip).hexdigest(),
                })
            if self.foreign:
                status["unexpected_work_seen"] = ["foreign-engine-id"]
            self.jobs[job_id] = status
            if self.lose_reply:
                self.lose_reply = False
                raise httpx.ReadTimeout("lost after committing the job")
            return httpx.Response(202, json=status)
        assert method == "GET"
        if not file_route and self.before_get is not None:
            self.before_get(job_id)
        if not file_route and self.poll_misses:
            self.poll_misses -= 1
            raise httpx.ReadTimeout("slow poll")
        if job_id not in self.jobs:
            return httpx.Response(404, json={"code": "job_not_found"})
        if file_route:
            assert file_route == ["file"]
            content = self.clip if self.corrupt is None else self.corrupt
            return httpx.Response(200, content=content, headers={"Content-Type": "video/mp4"})
        return httpx.Response(200, json=self.jobs[job_id])

    def puts(self):
        return [path for method, path in self.events if method == "PUT" and "/jobs/" in path]
