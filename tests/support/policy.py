"""Pure helpers behind the test policy: thread limits, output redaction, the checkout guard.

Kept free of pytest so the policy's own tests can call them directly.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from urllib.parse import unquote, urlsplit

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
# The longest head or tail of a value that a shortened repr keeps (pytest's widest
# window is 240 characters, about 119 from each end).
_FRAGMENT_MAX = 128
# The password in scheme://user:password@host. Two shapes: one without a slash, which
# runs to the last @ before the next slash (so it may contain @); or one with a slash,
# which runs to the first @ and must not look like a port ("8080/..."). Both stop at
# whitespace or a double quote and at 256 characters, so the scan stays linear on a
# long token such as compact JSON.
_URL_PASSWORD = re.compile(
    r"""\b[a-z][a-z0-9+.-]*://[^\s/:@"]*:"""
    r"""(?P<secret>[^\s/"]{1,256}|(?!\d{1,5}/)[^\s@"]{1,256})@""",
    re.IGNORECASE,
)
# The password in a libpq conninfo: password=secret, password='a secret' or
# password="a secret", with \x or a doubled quote inside the quoted forms.
_CONNINFO_PASSWORD = re.compile(
    r"""\bpassword\s*=\s*(?P<secret>'(?:[^'\\]|\\.|'')*'|"(?:[^"\\]|\\.|"")*"|[^\s'"]+)""",
    re.IGNORECASE,
)
REDACTED = "<redacted>"


def _inner_passwords(value: str) -> set[str]:
    """Passwords inside a sensitive value that is itself a URL or a conninfo string."""
    found: set[str] = set()
    if "://" in value:
        try:
            password = urlsplit(value).password
        except ValueError:
            password = None
        if password:
            found |= {password, unquote(password)}
        for match in _URL_PASSWORD.finditer(value):
            found |= {match["secret"], unquote(match["secret"])}
    for match in _CONNINFO_PASSWORD.finditer(value):
        raw = match["secret"]
        found.add(raw)
        if raw[:1] in "'\"" and len(raw) >= 2:
            quote = raw[0]
            inner = raw[1:-1]
            found |= {inner, inner.replace("\\" + quote, quote).replace(quote * 2, quote)}
    return found


def sensitive_values(environ=os.environ) -> list[str]:
    """Every string to remove: sensitive values of 8 characters or more, the passwords
    inside URL and conninfo values, each as is, as repr() prints it, and line by line
    (pytest diffs print one line each). Longest first."""
    values: set[str] = set()
    for name, value in environ.items():
        if not _SENSITIVE_NAME.search(name):
            continue
        for secret in {value} | _inner_passwords(value):
            forms = {secret, repr(secret)[1:-1]}
            for form in tuple(forms):
                forms.update(form.splitlines())
            values |= {form for form in forms if len(form) >= _MIN_SECRET_LENGTH}
    return sorted(values, key=len, reverse=True)


def _occurrences(text: str, value: str) -> list[tuple[int, int]]:
    spans = []
    at = text.find(value)
    while at != -1:
        spans.append((at, at + len(value)))
        at = text.find(value, at + 1)
    return spans


def _fragments(text: str, value: str) -> list[tuple[int, int]]:
    """Where text holds a head or a tail of value, 8 characters or more.

    A report may shorten a long value to ``'head...tail'`` or cut a line in the middle
    of it; the exact value is then absent but most of it is still readable.
    """
    size = _MIN_SECRET_LENGTH
    spans = []
    head, tail = value[:size], value[-size:]
    for at, _ in _occurrences(text, head):
        end = at + size
        limit = min(len(text), at + min(len(value), _FRAGMENT_MAX))
        while end < limit and text[end] == value[end - at]:
            end += 1
        spans.append((at, end))
    for at, end in _occurrences(text, tail):
        start = at
        index = len(value) - size  # position in value of the tail's first character
        floor = max(0, end - _FRAGMENT_MAX)
        while start > floor and index > 0 and text[start - 1] == value[index - 1]:
            start -= 1
            index -= 1
        spans.append((start, end))
    return spans


def _is_single_token(value: str) -> bool:
    """A key or token, not a URL or a phrase: only these are matched by fragment, so a
    database URL does not strip the word ``postgres`` out of every report."""
    return "://" not in value and not any(char.isspace() for char in value)


def redact(text: str, environ=os.environ) -> str:
    """Replace secrets in text with ``<redacted>``.

    Every match is found on the original text and the matches are merged, so one rule
    cannot hide text from another (a sensitive value equal to the word ``password``, or
    a pattern that only covers the first word of a spaced password).
    """
    spans = [match.span("secret") for match in _URL_PASSWORD.finditer(text)]
    spans += [match.span("secret") for match in _CONNINFO_PASSWORD.finditer(text)]
    for value in sensitive_values(environ):
        spans += _occurrences(text, value)
        if _is_single_token(value):
            spans += _fragments(text, value)
    merged: list[list[int]] = []
    for start, end in sorted(span for span in spans if span[0] < span[1]):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    pieces = []
    last = 0
    for start, end in merged:
        pieces += [text[last:start], REDACTED]
        last = end
    pieces.append(text[last:])
    return "".join(pieces)


# Tool caches that a test session may create; everything else is a new file.
_CACHE_PARTS = {"__pycache__", ".pytest_cache"}


_git_path: str | None = None


def _git_executable() -> str:
    """The git the guard runs, resolved once (at the session-start scan), so a test that
    later puts another ``git`` first on PATH does not change it."""
    global _git_path
    if _git_path is None:
        _git_path = shutil.which("git")
    return _git_path or "git"


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
    GIT_INDEX_FILE cannot point the scan at another repository, and it is the git found
    at the first scan, whatever PATH says later.
    """
    env = {name: value for name, value in os.environ.items() if not name.startswith("GIT_")}
    git = _git_executable()
    try:
        top = subprocess.run(
            [git, "-C", str(root), "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, check=True, env=env,
        ).stdout.strip()
        if Path(top).resolve() != Path(root).resolve():
            return None
        listed = subprocess.run(
            [git, "-C", str(root), "status", "--porcelain=v1", "-z",
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
