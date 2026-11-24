"""In-memory Wan product service. Only test-time clip bytes cross the transport."""

import hashlib
import json
from datetime import UTC, datetime, timedelta

import httpx

from haynes_studio.adapters.wan import graph_sha256
from haynes_studio.queue.wan import EXPECTED_PROFILES, PROFILES, RESTART_ERROR, expected_graph

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
        self.foreign_engine_queue = False
        self.foreign = False
        self.busy = False
        self.quota = False
        self.lose_reply = False
        self.disappear = False
        self.restart_failures = 0
        self.poll_misses = 0
        self.corrupt = None

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
            return httpx.Response(200, json={"ready": True, "api_version": "1.0.0",
                                            "active_video_job": None, "active_foley_job": None})
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
            assert not file_route and job_id not in self.jobs
            if self.busy:
                return httpx.Response(409, json={"code": "worker_busy"})
            if self.disappear:
                raise httpx.ReadTimeout("lost before acknowledgement")
            body = json.loads(request.content)
            assert body["image_sha256"] in self.inputs
            if kind == "s2v":
                assert body["audio_sha256"] in self.inputs
            digest = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
            graph = graph_sha256(expected_graph({"job_id": job_id, "kind": kind, "request": body}))
            status = {"api_version": "1.0.0", "type": kind, "id": job_id,
                      "request_sha256": digest, "profile": body["profile"], "graph_sha256": graph}
            if self.restart_failures:
                self.restart_failures -= 1
                status.update(state="failed", error=RESTART_ERROR)
            elif self.foreign_engine_queue:
                status.update(state="failed", error="RuntimeError: ComfyUI already has a job; refusing a competing request")
            else:
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
