"""Adapter errors. Each carries a stable code, the call's label and a short message.

No error carries a request payload, an environment value, a full command line or a
credential. The only service text an error keeps is ``detail``: the last few hundred
characters of the command's stderr after :func:`redact` has removed credentials, and
``redacted_stderr``: the same redacted text uncut, for a caller to search (ComfyUI's
``PROMPT_ID`` line), never part of the message. ``tests/support/policy.py`` redacts
test reports as a backstop; this module is the plan.
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
JOB_FAILED = "adapter.job_failed"  # story 842: a Wan job ended in a state other than succeeded
COMPETING_WORK = "adapter.competing_work"  # story 842: foreign engine work seen during a job

DETAIL_LIMIT = 300
REDACTED = "<redacted>"

# Every pattern stays linear on long input. Each repeat is bounded, or scans forward
# once to its delimiter (a closing quote, the end of the line, an END line or the end of
# the text) with nothing after it that can fail, so no position is rescanned. None nests
# an unbounded repeat.
#
# A PEM block, from its -----BEGIN line through its -----END line, or to the end of the
# text when the END line is missing.
_PEM = re.compile(r"-----BEGIN[\s\S]*?(?:-----END[^\n]*|\Z)")
# URL userinfo, in either of two forms: no whitespace, through the last "@" before a
# space (it over-redacts a path that contains "@", which is harmless); or "user:password"
# with spaces in the password, stopping at "/", "?", "#" or a newline, so a plain
# "host:8080/path" is never taken for a password.
_URL_USERINFO = re.compile(
    r"(?i)\b([a-z][a-z0-9+.-]{0,31}://)(?:\S{0,1024}@|[^\s/?#@:]{0,256}:[^/?#@\n]{0,1024}@)")
_AWS_KEY_ID = re.compile(r"(?:AKIA|ASIA)[A-Z0-9]{16}")
_AUTH_SCHEME = re.compile(r"(?i)\b(bearer|basic|token)(\s{1,16})[^\s\"',;}]+")
# A key that contains one of these words (GH_TOKEN, client_secret, DB_PASSWORD), then
# "=" or ":" (after an optional closing quote: JSON, Python reprs, headers), then the
# value: a quoted value through its closing quote, spaces included (to the end of the
# line if the quote never closes); an unquoted value to the end of the line. The match
# starts at the word ("GH_" stays as it is), so no start position rescans a long prefix.
_KEYED = re.compile(
    r"(?i)((?:token|password|passwd|secret|api[_-]?key|authorization|cookie|credential)"
    r"[\w-]{0,128})(['\"]?[ \t]{0,16}[:=][ \t]{0,16})"
    r"(?:(\")(?:\\.|[^\"\\\n])*(\"?)|(')(?:\\.|[^'\\\n])*('?)|[^\n]+)")


def _keyed(match: re.Match) -> str:
    key, sep, dq, dq_end, sq, sq_end = match.groups()
    return key + sep + (dq or sq or "") + REDACTED + (dq_end or sq_end or "")


def redact(raw: bytes | str | None) -> str:
    """Service stderr as printable text with credentials removed, uncut."""
    if not raw:
        return ""
    text = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw
    text = _PEM.sub(REDACTED, text)
    text = _URL_USERINFO.sub(r"\1" + REDACTED + "@", text)
    text = _AWS_KEY_ID.sub(REDACTED, text)
    text = _AUTH_SCHEME.sub(lambda m: m.group(1) + m.group(2) + REDACTED, text)
    text = _KEYED.sub(_keyed, text)
    return "".join(ch if ch.isprintable() or ch == "\n" else "?" for ch in text).strip()


def safe_detail(raw: bytes | str | None, limit: int = DETAIL_LIMIT) -> str:
    """Service stderr as short, printable text with credentials removed.

    Redaction runs on the whole text before it is cut to its last ``limit``
    characters, so a cut never exposes part of a value the rules would hide.
    """
    return redact(raw)[-limit:]


class AdapterError(RuntimeError):
    """A service call that was refused, failed or answered badly.

    ``code`` is one of the module constants; ``label`` names the call (for example
    ``kokoro.synthesize``); ``returncode`` is the command's exit status when it ran.
    ``detail`` is the redacted stderr tail shown in the message; ``redacted_stderr`` is
    the whole redacted stderr, kept for a caller to search and never shown.
    """

    def __init__(self, code: str, label: str, message: str, *, detail: str = "",
                 returncode: int | None = None, redacted_stderr: str = ""):
        self.code = code
        self.label = label
        self.message = message
        self.detail = detail
        self.returncode = returncode
        self.redacted_stderr = redacted_stderr
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
                 detail: str = "", returncode: int | None = None, redacted_stderr: str = ""):
        self.prompt_id = prompt_id
        if prompt_id:
            message += f"; ComfyUI accepted prompt {prompt_id}: read its history, do not resubmit"
        super().__init__(code, label, message, detail=detail, returncode=returncode,
                         redacted_stderr=redacted_stderr)


class WanError(AdapterError):
    """A Wan clip call that was refused or failed (story 842).

    ``job_id`` is the Wan job's ID once the client has made one (it names the ledger at
    ``/videos/<job_id>``); ``in_flight`` is True when the job may still be running, so
    the process refuses to submit again until it has been read. ``clip`` is set only for
    ``adapter.competing_work``: the job succeeded and its clip was fetched and checked,
    but foreign engine work was seen during it, so the output is kept and no further job
    is submitted until :meth:`WanClipClient.clear_halt` is called."""

    def __init__(self, code: str, label: str, message: str, *, job_id: str | None = None,
                 in_flight: bool = False, clip=None, detail: str = "",
                 returncode: int | None = None, redacted_stderr: str = ""):
        self.job_id = job_id
        self.in_flight = in_flight
        self.clip = clip
        if job_id and in_flight:
            message += f"; Wan job {job_id} may still be running: read /videos/{job_id}, do not resubmit"
        super().__init__(code, label, message, detail=detail, returncode=returncode,
                         redacted_stderr=redacted_stderr)
