"""Convert a mounted worker secret to its worker-only bearer format."""

import re

# The API accepts at most 128 base64url characters on the worker route.
# The prefix makes the bearer longer than a generated agent key and keeps
# it out of the alphanumeric-only form used for externally minted agent keys.
PREFIX = "worker_"
MAX_SECRET_LENGTH = 128 - len(PREFIX)
_SECRET = re.compile(rf"[A-Za-z0-9]{{48,{MAX_SECRET_LENGTH}}}")
_BEARER = re.compile(rf"{PREFIX}{_SECRET.pattern}")


def worker_bearer(secret: str) -> str:
    if _SECRET.fullmatch(secret):
        return PREFIX + secret
    raise ValueError("Invalid worker secret format")


def valid_worker_bearer(token: str) -> bool:
    return _BEARER.fullmatch(token) is not None
