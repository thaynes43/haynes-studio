"""Read-only reads of single files on the Wan volume (PVC ``ai/wan-video``), story 846.

The ledger reader of story 425 (:mod:`~haynes_studio.adapters.wan_ledger`) fetches a
file only when a delivery ledger lists it. Two kinds of private input of The Winter
Menu are on the same volume but in no delivery ledger, and :class:`VolumeReader` reads
them, in the same style (a call is a :class:`~haynes_studio.adapters.runner.Command`
handed to the runner; the code that runs in the pod is a pinned snippet):

- :meth:`VolumeReader.fetch_job_output`: the output of one Wan job, by its job ID (the E0
  doll loops, the set loop and the speech-to-video clips), through its own ledger
  ``/workspace/jobs/<job_id>.json`` (``wan_job_output_read.py``, 180 s, 64 MiB).
- :meth:`VolumeReader.fetch_upload`: one E0 upload, by its SHA-256, from
  ``/workspace/input/studio-e0/<first 16 hex digits>.png`` or ``.wav`` (the doll-on-green
  start images and the keyframes; ``wan_upload_read.py``, 60 s, 20 000 000 bytes, the
  upload snippet's own limit).

Paths are built in the pod from validated values only (a 32-digit job ID, a 64-digit
hash, an extension from a fixed set, and a job ledger's ``output`` that must be plain
relative names); nothing a caller passes is used as a path. Every folder below
``/workspace`` and the file are opened without following a link, after an ``lstat``;
the file must be a regular file with one link, within the limit, and is read from the
descriptor it was checked on, hashed in the pod and again here. There is no write,
rename, link, ``chmod``, truncate or delete anywhere in either snippet or here (a test
holds both snippets to an allowlist of calls and ``open`` flags).

A file the pod refuses is a named :class:`~haynes_studio.adapters.errors.AdapterError`
(``adapter.source_*``, :data:`~haynes_studio.adapters.errors.SOURCE_REFUSALS`), never
bytes. Anything else (a ``kubectl`` failure, a denial, a timeout, an unreadable
folder) is ``adapter.command_failed`` or ``adapter.timeout``, as for every client.

:func:`ledger_fetch_refusal` reads an error of the existing
:meth:`~haynes_studio.adapters.wan_ledger.LedgerReader.fetch_asset` the same way, by
the fixed messages of its pinned snippet, without changing that client.

    reader = VolumeReader(runner)
    clip = reader.fetch_job_output("8b5a72ca7bf140b19a46e2850b857d8a", clip_sha256)
    image = reader.fetch_upload(image_sha256, ".png")
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any

from haynes_studio.adapters import pinned
from haynes_studio.adapters.errors import (
    COMMAND_FAILED,
    DETAIL_LIMIT,
    RESPONSE_INVALID,
    SOURCE_CHANGED,
    SOURCE_HARD_LINK,
    SOURCE_HASH_MISMATCH,
    SOURCE_LINK,
    SOURCE_MISSING,
    SOURCE_NOT_REGULAR,
    SOURCE_OUTSIDE,
    SOURCE_RECORD_INVALID,
    SOURCE_TOO_LARGE,
    AdapterError,
    RequestInvalid,
    redact,
)
from haynes_studio.adapters.runner import WAN_API, Command, Completed, ExecTarget, Runner, failure

UPLOAD_SNIPPET = "wan_upload_read.py"
OUTPUT_SNIPPET = "wan_job_output_read.py"
UPLOAD_TIMEOUT_S = 60  # proposal: twice poc/wan.py's 30 s upload
OUTPUT_TIMEOUT_S = 180  # poc/deliver.py's per-file copy timeout, as wan_ledger.fetch_asset
MAX_UPLOAD_BYTES = 20_000_000  # wan_upload.py's assertion: no upload is larger
MAX_OUTPUT_BYTES = 64 * 1024 * 1024  # as wan_ledger.MAX_ASSET_BYTES; E0 clips are under 4 MB
UPLOAD_SUFFIXES = (".png", ".wav")  # poc/wan.py and poc/s2v.py upload names
UPLOAD_FOLDER = "/workspace/input/studio-e0/"
REFUSED_EXIT = 3
JOB_ID = re.compile(r"[0-9a-f]{32}")
SHA256 = re.compile(r"[0-9a-f]{64}")
_REFUSED = re.compile(r"REFUSED ([a-z_]+)")

# The reasons the two snippets print, and the error each becomes.
REASONS = {
    "missing": (SOURCE_MISSING, "no such file (or folder, or job ledger)"),
    "link": (SOURCE_LINK, "the file or a folder on its path is a symbolic link"),
    "not_regular": (SOURCE_NOT_REGULAR, "the file or a folder on its path is not a regular file "
                                         "or folder"),
    "hard_link": (SOURCE_HARD_LINK, "the file has more than one link"),
    "too_large": (SOURCE_TOO_LARGE, "the file is over the read's size limit"),
    "outside": (SOURCE_OUTSIDE, "the ledger's output path is not plain names below "
                                "/workspace/output"),
    "hash_mismatch": (SOURCE_HASH_MISMATCH, "the file's bytes do not hash to the expected sha256"),
    "size_mismatch": (SOURCE_HASH_MISMATCH, "the file is not the size its ledger records"),
    "record": (SOURCE_RECORD_INVALID, "the job ledger is not a succeeded job of that ID with an "
                                      "output"),
    "changed": (SOURCE_CHANGED, "the file or a folder changed between its checks and its read"),
}

# What the pinned wan_ledger_fetch.py (story 425) prints when it refuses, and the error
# each means. A test holds every message to that snippet's text.
LEDGER_FETCH_MESSAGES = {
    "no asset with that sha256 in the ledger": SOURCE_MISSING,
    "asset bytes do not match the ledger sha256": SOURCE_HASH_MISMATCH,
    "asset is over 64 MiB": SOURCE_TOO_LARGE,
    "asset has more than one hard link": SOURCE_HARD_LINK,
    "asset is not a regular file": SOURCE_NOT_REGULAR,
    "ledger is not a regular file": SOURCE_NOT_REGULAR,
    "ledger path is outside /workspace/jobs": SOURCE_OUTSIDE,
    "asset path is outside /workspace/output/productions": SOURCE_OUTSIDE,
    "not an edited_production ledger": SOURCE_RECORD_INVALID,
}
# The exceptions it can raise instead (a traceback's last line), by their prefix.
LEDGER_FETCH_TRACEBACKS = (
    ("FileNotFoundError:", SOURCE_MISSING),
    ("OSError: [Errno 40] Too many levels of symbolic links", SOURCE_LINK),  # ELOOP from O_NOFOLLOW
    ("json.decoder.JSONDecodeError:", SOURCE_RECORD_INVALID),
)
# wan_ledger.fetch_asset's own checks of what came back.
LEDGER_CLIENT_MESSAGES = {
    "asset is over 64 MiB": SOURCE_TOO_LARGE,
    "asset bytes do not match the sha256": SOURCE_HASH_MISMATCH,
}


@dataclass(frozen=True)
class VolumeBytes:
    """One file read from the Wan volume. ``source`` is ``job_output`` or ``upload``;
    ``name`` the job ID or the upload's file name."""

    source: str
    name: str
    sha256: str
    data: bytes = field(repr=False)


def _sha256(value: Any, label: str) -> str:
    if not isinstance(value, str) or not SHA256.fullmatch(value):
        raise RequestInvalid(label, "sha256 must be 64 lower-case hex digits")
    return value


def upload_name(sha256: str, suffix: str) -> str:
    """``<first 16 hex digits>.png`` (or ``.wav``): how ``poc/wan.py`` and ``poc/s2v.py``
    named an upload."""
    label = "wan_volume.fetch_upload"
    _sha256(sha256, label)
    if suffix not in UPLOAD_SUFFIXES:
        raise RequestInvalid(label, "suffix must be .png or .wav")
    return sha256[:16] + suffix


def _last_line(text: str) -> str:
    lines = [line for line in text.splitlines() if line.strip()]
    return lines[-1].strip() if lines else ""


class VolumeReader:
    """Reads single files on the Wan volume. There is deliberately no method that writes."""

    def __init__(self, runner: Runner, *, target: ExecTarget = WAN_API,
                 upload_snippet: pinned.PinnedInput | None = None,
                 output_snippet: pinned.PinnedInput | None = None):
        def take(item, name):
            return pinned.check(item, name) if item else pinned.load(name)
        self.runner = runner
        self.target = target
        self.upload_snippet = take(upload_snippet, UPLOAD_SNIPPET)
        self.output_snippet = take(output_snippet, OUTPUT_SNIPPET)

    # Commands --------------------------------------------------------------------------

    def upload_command(self, sha256: str, suffix: str) -> Command:
        label = "wan_volume.fetch_upload"
        name = upload_name(sha256, suffix)
        pinned.check(self.upload_snippet, UPLOAD_SNIPPET)
        return Command(label, self.target.argv(self.upload_snippet.text, name, sha256), b"",
                       UPLOAD_TIMEOUT_S, self.target.describe())

    def job_output_command(self, job_id: str, sha256: str) -> Command:
        label = "wan_volume.fetch_job_output"
        if not isinstance(job_id, str) or not JOB_ID.fullmatch(job_id):
            raise RequestInvalid(label, "job_id must be 32 lower-case hex digits")
        _sha256(sha256, label)
        pinned.check(self.output_snippet, OUTPUT_SNIPPET)
        return Command(label, self.target.argv(self.output_snippet.text, job_id, sha256), b"",
                       OUTPUT_TIMEOUT_S, self.target.describe())

    # Reads -------------------------------------------------------------------------------

    def fetch_upload(self, sha256: str, suffix: str) -> VolumeBytes:
        """The bytes of the E0 upload with this SHA-256 (``suffix`` ``.png`` or ``.wav``)."""
        command = self.upload_command(sha256, suffix)
        data = self._read(command, sha256, MAX_UPLOAD_BYTES)
        return VolumeBytes("upload", upload_name(sha256, suffix), sha256, data)

    def fetch_job_output(self, job_id: str, sha256: str) -> VolumeBytes:
        """The bytes of Wan job ``job_id``'s output, which must hash to ``sha256``."""
        command = self.job_output_command(job_id, sha256)
        return VolumeBytes("job_output", job_id, sha256,
                           self._read(command, sha256, MAX_OUTPUT_BYTES))

    def _read(self, command: Command, sha256: str, limit: int) -> bytes:
        result = self.runner.run(command)
        if not isinstance(result, Completed):
            raise TypeError("a runner must return Completed")
        if result.returncode != 0:
            raise refusal(command, result) or failure(command, result)
        data = result.stdout
        if len(data) > limit:
            raise AdapterError(SOURCE_TOO_LARGE, command.label,
                               f"the answer is over the {limit}-byte limit")
        if hashlib.sha256(data).hexdigest() != sha256:
            raise AdapterError(SOURCE_HASH_MISMATCH, command.label,
                               "the bytes received do not hash to the expected sha256")
        return data


def refusal(command: Command, result: Completed) -> AdapterError | None:
    """The named error for a snippet's ``REFUSED <reason>`` (exit status 3, last stderr
    line), or None for any other failure."""
    if result.returncode != REFUSED_EXIT:
        return None
    stderr = redact(result.stderr)
    found = _REFUSED.fullmatch(_last_line(stderr))
    if not found or found.group(1) not in REASONS:
        return None
    code, message = REASONS[found.group(1)]
    return AdapterError(code, command.label, message, detail=stderr[-DETAIL_LIMIT:],
                        returncode=result.returncode, redacted_stderr=stderr)


def ledger_fetch_refusal(error: AdapterError) -> str | None:
    """Which ``adapter.source_*`` refusal an error of ``LedgerReader.fetch_asset`` is,
    from the fixed messages of its pinned snippet and its own two checks; None for any
    other failure (a timeout, a ``kubectl`` failure, an unknown message), which the
    caller must treat as a stop, not as an absent file."""
    if error.code == RESPONSE_INVALID:
        return LEDGER_CLIENT_MESSAGES.get(error.message)
    if error.code != COMMAND_FAILED or error.returncode != 1:
        return None
    last = _last_line(error.redacted_stderr)
    if last in LEDGER_FETCH_MESSAGES:
        return LEDGER_FETCH_MESSAGES[last]
    for prefix, code in LEDGER_FETCH_TRACEBACKS:
        if last.startswith(prefix):
            return code
    return None


__all__ = ["LEDGER_FETCH_MESSAGES", "MAX_OUTPUT_BYTES", "MAX_UPLOAD_BYTES", "OUTPUT_SNIPPET",
           "REASONS", "UPLOAD_FOLDER", "UPLOAD_SNIPPET", "VolumeBytes", "VolumeReader",
           "ledger_fetch_refusal", "refusal", "upload_name"]
