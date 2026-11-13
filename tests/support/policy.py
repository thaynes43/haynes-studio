"""Pure helpers behind the test policy: thread limits, output redaction, the checkout guard.

Kept free of pytest so the policy's own tests can call them directly.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# docs/contracts/studio-contracts-v1.md section 14, "Limits".
THREAD_LIMITS = {"STUDIO_THREADS": 2, "OMP_NUM_THREADS": 2, "OPENBLAS_NUM_THREADS": 1}


def apply_thread_limits(environ=os.environ) -> dict[str, str]:
    """Cap the thread variables at the contract's limits; a smaller positive value stays."""
    applied = {}
    for name, limit in THREAD_LIMITS.items():
        current = environ.get(name, "")
        if not (current.isdigit() and 1 <= int(current) <= limit):
            environ[name] = str(limit)
        applied[name] = environ[name]
    return applied


# Environment variables whose values never appear in test output.
_SENSITIVE_NAME = re.compile(
    r"TOKEN|SECRET|PASSWORD|PASSWD|PASSPHRASE|API_?KEY|PRIVATE_KEY|ACCESS_KEY"
    r"|CREDENTIAL|COOKIE|DATABASE_URL|DSN",
    re.IGNORECASE,
)
_MIN_SECRET_LENGTH = 8
# scheme://user:password@ -> scheme://user:<redacted>@. The password runs to the last @
# of the token, so one that contains @ or / is covered. A URL with a port and an @ later
# in its path loses that stretch too, which is the safe direction.
_URL_PASSWORD = re.compile(r"(?P<head>\b[a-z][a-z0-9+.-]*://[^\s/:@]*:)\S+@", re.IGNORECASE)
# libpq conninfo: password=secret, password='a secret' (with \' or '' inside) or
# password="a secret"
_CONNINFO_PASSWORD = re.compile(
    r"""(?P<head>\bpassword\s*=\s*)(?:'(?:[^'\\]|\\.|'')*'|"[^"]*"|[^\s'"]+)""",
    re.IGNORECASE,
)
REDACTED = "<redacted>"


def _redact_patterns(text: str) -> str:
    text = _URL_PASSWORD.sub(r"\g<head>" + REDACTED + "@", text)
    return _CONNINFO_PASSWORD.sub(r"\g<head>" + REDACTED, text)


def _forms(value: str) -> set[str]:
    """The shapes a value takes in a report: as is, as repr() prints it, line by line
    (pytest diffs print one line each), and each of those after the patterns ran."""
    forms = {value, repr(value)[1:-1]}
    for form in tuple(forms):
        forms.update(line for line in form.splitlines() if len(line) >= _MIN_SECRET_LENGTH)
    forms.update(_redact_patterns(form) for form in tuple(forms))
    forms.discard("")
    return forms


def sensitive_values(environ=os.environ) -> list[str]:
    values: set[str] = set()
    for name, value in environ.items():
        if _SENSITIVE_NAME.search(name) and len(value) >= _MIN_SECRET_LENGTH:
            values |= _forms(value)
    return sorted(values, key=len, reverse=True)


def redact(text: str, environ=os.environ) -> str:
    # Patterns first: a sensitive value that equals a keyword ("password") must not
    # rewrite the text the patterns look for.
    text = _redact_patterns(text)
    for value in sensitive_values(environ):
        text = text.replace(value, REDACTED)
    return text


# Tool caches that a test session may create; everything else is a new file.
_CACHE_PARTS = {"__pycache__", ".pytest_cache"}


def checkout_snapshot(root: Path) -> frozenset[str] | None:
    """Status entries (untracked, ignored and changed) of the git checkout at root.

    The guard catches a test that leaves output in the checkout by mistake. It is not
    a sandbox: an ignored directory (``.venv/``, ``web/node_modules/``, an existing
    ``/jobs/``) is one entry, so new files inside a directory that was already there
    are not seen (a new directory is); nothing under ``.git/`` is listed; any path with
    a ``__pycache__`` or ``.pytest_cache`` part is exempt; and a second edit to a file
    that was already listed does not add an entry.

    Returns None when root is not the top of a git checkout, or when git cannot run.
    At session start that turns the guard off rather than guessing; at session end
    the plugin treats it as a failure, never as "nothing changed".

    git runs without any GIT_* variable, so a test that sets GIT_DIR, GIT_WORK_TREE or
    GIT_INDEX_FILE cannot point the scan at another repository.
    """
    env = {name: value for name, value in os.environ.items() if not name.startswith("GIT_")}
    try:
        top = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, check=True, env=env,
        ).stdout.strip()
        if Path(top).resolve() != Path(root).resolve():
            return None
        listed = subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain=v1", "-z",
             "--untracked-files=all", "--ignored=matching"],
            capture_output=True, check=True, env=env,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return None
    entries = set()
    fields = iter(os.fsdecode(listed).split("\0"))
    for field in fields:
        if not field:
            continue
        status, path = field[:2], field[3:]
        if "R" in status or "C" in status:
            next(fields, None)  # the rename source
        if _CACHE_PARTS.intersection(path.rstrip("/").split("/")):
            continue
        entries.add(f"{status} {path}")
    return frozenset(entries)


def checkout_changes(before: frozenset[str], after: frozenset[str]) -> list[str]:
    """Entries present after the session and not before it, sorted."""
    return sorted(after - before)
