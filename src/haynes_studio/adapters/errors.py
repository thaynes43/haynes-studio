"""Adapter errors. Each carries a stable code, the call's label and a short message.

No error carries a request payload, an environment value, a full command line or a
credential. The only service text an error keeps is ``detail``: the last few hundred
characters of the command's stderr after :func:`safe_detail` has removed URL
passwords and ``token=``-style values. ``tests/support/policy.py`` redacts test
reports as a backstop; this module is the plan.
"""

from __future__ import annotations

import re

REQUEST_INVALID = "adapter.request_invalid"
PIN_MISMATCH = "adapter.pin_mismatch"
COMMAND_FAILED = "adapter.command_failed"
TIMEOUT = "adapter.timeout"
RESPONSE_INVALID = "adapter.response_invalid"
NOT_FOUND = "adapter.not_found"
BUSY = "adapter.busy"

DETAIL_LIMIT = 300
_URL_USERINFO = re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://)[^/\s@]+@")
_KEYED = re.compile(
    r"(?i)\b(token|access_token|password|passwd|secret|api[_-]?key|authorization|bearer|cookie)"
    r"(\"?\s*[:=]\s*\"?|\s+)([^\s\"',;]+)")


def safe_detail(raw: bytes | str | None, limit: int = DETAIL_LIMIT) -> str:
    """Service stderr as short, printable text with credentials removed.

    Redaction runs on the whole text before it is cut to its last ``limit``
    characters, so a cut never exposes part of a value the rules would hide.
    """
    if not raw:
        return ""
    text = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw
    text = _URL_USERINFO.sub(r"\1<redacted>@", text)
    text = _KEYED.sub(lambda m: m.group(1) + m.group(2) + "<redacted>", text)
    text = "".join(ch if ch.isprintable() or ch == "\n" else "?" for ch in text).strip()
    return text[-limit:]


class AdapterError(RuntimeError):
    """A service call that was refused, failed or answered badly.

    ``code`` is one of the module constants; ``label`` names the call (for example
    ``kokoro.synthesize``); ``returncode`` is the command's exit status when it ran.
    """

    def __init__(self, code: str, label: str, message: str, *, detail: str = "",
                 returncode: int | None = None):
        self.code = code
        self.label = label
        self.message = message
        self.detail = detail
        self.returncode = returncode
        text = f"{label}: {code}: {message}"
        if detail:
            text += f" (stderr tail: {detail})"
        super().__init__(text)


class RequestInvalid(AdapterError):
    """A request failed validation before anything ran. The message names the field."""

    def __init__(self, label: str, message: str):
        super().__init__(REQUEST_INVALID, label, message)


class PinMismatch(AdapterError):
    """A graph or in-pod snippet whose SHA-256 is not its pinned value."""

    def __init__(self, name: str, expected: str, actual: str):
        self.name = name
        self.expected = expected
        self.actual = actual
        super().__init__(PIN_MISMATCH, f"pinned.{name}",
                         f"sha256 {actual} is not the pinned {expected}; refusing to send it")


class ImageError(AdapterError):
    """A ComfyUI call that failed. ``prompt_id`` is set when ComfyUI had already
    accepted the prompt: the work may still be running on the shared GPU, so read
    ``/history/<prompt_id>`` instead of submitting it again."""

    def __init__(self, code: str, label: str, message: str, *, prompt_id: str | None = None,
                 detail: str = "", returncode: int | None = None):
        self.prompt_id = prompt_id
        if prompt_id:
            message += f"; ComfyUI accepted prompt {prompt_id}: read its history, do not resubmit"
        super().__init__(code, label, message, detail=detail, returncode=returncode)
