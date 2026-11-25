"""Worker-side HTTP client. Its only access to queue records is the internal API."""

from urllib.parse import urlsplit

import httpx

from haynes_studio.build.errors import BuildInterrupted


class WorkerAPIError(BuildInterrupted):
    def __init__(self, code, status=None):
        self.code, self.status = code, status
        super().__init__(code)


def service_url(value):
    parsed = urlsplit(value)
    if (parsed.scheme not in ("http", "https") or not parsed.hostname or
            parsed.username is not None or parsed.password is not None or
            parsed.path not in ("", "/") or parsed.query or parsed.fragment):
        raise ValueError("Expected a service origin with no credentials, path or query")
    return value.rstrip("/")


class WorkerAPI:
    def __init__(self, client):
        self.client = client

    def _post(self, path, data=None):
        try:
            response = self.client.post(f"/internal/v1/work/{path}", json=data)
        except httpx.RequestError as error:
            raise WorkerAPIError("work.transport") from error
        if response.status_code == 204:
            return None
        try:
            body = response.json()
        except ValueError as error:
            raise WorkerAPIError("work.response_invalid", response.status_code) from error
        if not isinstance(body, dict):
            raise WorkerAPIError("work.response_invalid", response.status_code)
        if response.status_code != 200:
            error = body.get("error")
            code = error.get("code") if isinstance(error, dict) else None
            raise WorkerAPIError(code or "work.request_failed", response.status_code)
        return body

    def claim(self, lane="run"):
        body = self._post("claim", None if lane == "run" else {"lane": lane})
        return None if body is None else (ClaimAPI if lane == "run" else MediaClaimAPI)(self, body)


class ClaimAPI:
    def __init__(self, api, body):
        self.api = api
        self.body = body
        self.identity = {"run_id": body["run"]["id"], "fence": body["fence"]}

    def _post(self, path, **fields):
        return self.api._post(path, {**self.identity, **fields})

    def heartbeat(self, progress=None):
        return self._post("heartbeat", progress=progress)

    def resume(self):
        self.body["run"] = self._post("resume")

    def reserve(self, kind, request):
        return self._post("attempts", proposal={**request, "kind": kind})

    def attempt(self, job_id, state, result=None):
        return self._post(f"attempts/{job_id}", state=state, result=result)

    def publish(self):
        self._post("publish")

    def complete(self, evidence):
        return self._post("complete", **evidence)

    def fail(self, *, status, reason, **evidence):
        return self._post("fail", status=status, reason=reason, **evidence)


class MediaClaimAPI(ClaimAPI):
    def __init__(self, api, body):
        self.api, self.body = api, body
        self.identity = {"job_id": body["job"]["id"], "fence": body["fence"]}

    def heartbeat(self, progress=None):
        return self._post("heartbeat")

    def fail(self, *, code, message):
        return self._post("fail", code=code, message=message)
