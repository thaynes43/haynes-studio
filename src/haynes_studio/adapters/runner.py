"""The command-runner boundary.

A service call is data: a :class:`Command` (argument vector, stdin bytes, timeout and a
label) handed to an injected :class:`Runner`. Clients build commands and parse
:class:`Completed` results; they never start a process themselves. Tests and later
stories pass a fake runner (``haynes_studio.adapters.fakes``).

:class:`SubprocessRunner` is the real runner, a thin ``subprocess.run`` wrapper. No
test and no CI job calls it. It inherits the caller's environment (``kubectl`` needs its
kubeconfig) and reads none of it itself.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from typing import Protocol

from haynes_studio.adapters.errors import COMMAND_FAILED, NOT_FOUND, TIMEOUT, AdapterError, safe_detail


@dataclass(frozen=True)
class Command:
    """One process to run: ``argv``, the bytes to write to its stdin, and a timeout."""

    label: str
    argv: tuple[str, ...] = field(repr=False)
    stdin: bytes = field(default=b"", repr=False)
    timeout_s: float = 30.0
    target: str = ""  # a short, credential-free description for messages

    def __post_init__(self):
        if not self.argv or not all(isinstance(part, str) for part in self.argv):
            raise ValueError("argv must be a non-empty tuple of strings")
        if not isinstance(self.stdin, bytes):
            raise ValueError("stdin must be bytes")
        if not self.timeout_s > 0:
            raise ValueError("timeout_s must be positive")


@dataclass(frozen=True)
class Completed:
    """What a runner returns: exit status and both output streams, as bytes."""

    returncode: int
    stdout: bytes = field(default=b"", repr=False)
    stderr: bytes = field(default=b"", repr=False)


class Runner(Protocol):
    """Runs one command and returns its result. Raises :class:`AdapterError` with code
    ``adapter.timeout`` when the timeout passes, or ``adapter.command_failed`` when the
    process cannot start; a non-zero exit status is a result, not an exception."""

    def run(self, command: Command) -> Completed: ...


class SubprocessRunner:
    """The real runner. Thin by design: no shell, no retries, no environment edits."""

    def run(self, command: Command) -> Completed:
        # Errors are raised after the except blocks so that neither ``__cause__`` nor
        # ``__context__`` keeps the raw exception (full argv, unredacted stderr).
        problem = None
        try:
            result = subprocess.run(list(command.argv), input=command.stdin, capture_output=True,
                                    timeout=command.timeout_s, check=False)
        except subprocess.TimeoutExpired as expired:
            problem = AdapterError(TIMEOUT, command.label,
                                   f"no answer from {command.target or command.argv[0]} "
                                   f"within {command.timeout_s:g} s",
                                   detail=safe_detail(expired.stderr))
        except OSError as error:
            problem = AdapterError(COMMAND_FAILED, command.label,
                                   f"could not start {command.argv[0]}: {error.strerror}")
        if problem is not None:
            raise problem
        return Completed(result.returncode, result.stdout, result.stderr)


@dataclass(frozen=True)
class ExecTarget:
    """A container to ``kubectl exec`` into, and the interpreter that runs a snippet there."""

    namespace: str
    workload: str
    container: str
    interpreter: str

    def argv(self, code: str, *args: str) -> tuple[str, ...]:
        """``kubectl exec -i -n <ns> <workload> -c <container> -- <python> -c <code> <args>``,
        the same vector the PoC scripts pass to ``subprocess.run``."""
        return ("kubectl", "exec", "-i", "-n", self.namespace, self.workload, "-c", self.container,
                "--", self.interpreter, "-c", code, *args)

    def describe(self) -> str:
        return f"kubectl exec -n {self.namespace} {self.workload} -c {self.container}"


# The routes in docs/reference/services.md, as the PoC scripts use them.
KOKORO = ExecTarget("ai", "deploy/kokoro", "app", "python")  # poc/studio.py synthesize
WHISPER = ExecTarget("ai", "deploy/whisper", "app", "python")  # poc/studio.py transcribe
COMFYUI = ExecTarget("ai", "comfyui-0", "app", "python3")  # poc/comfy.py EXEC
WAN_API = ExecTarget("ai", "deploy/wan-video", "api", "python3")  # poc/deliver.py REMOTE


def failure(command: Command, result: Completed, *, error=AdapterError, **extra) -> AdapterError:
    """The error for a non-zero exit: code ``adapter.command_failed``, or
    ``adapter.not_found`` when the in-pod snippet reported an HTTP 404."""
    detail = safe_detail(result.stderr)
    code = NOT_FOUND if "HTTP Error 404" in detail else COMMAND_FAILED
    return error(code, command.label, f"{command.target or command.argv[0]} exited "
                                      f"{result.returncode}", detail=detail,
                 returncode=result.returncode, **extra)


def run_checked(runner: Runner, command: Command, *, error=AdapterError) -> Completed:
    """Run ``command``; raise :func:`failure` on a non-zero exit."""
    result = runner.run(command)
    if not isinstance(result, Completed):
        raise TypeError("a runner must return Completed")
    if result.returncode != 0:
        raise failure(command, result, error=error)
    return result
