"""Convert a mounted worker secret to its worker-only bearer format."""

import re

# The API accepts at most 128 base64url characters on the worker route.
# The prefix makes the bearer longer than a generated agent key and keeps
# it out of the alphanumeric-only form used for externally minted agent keys.
PREFIX = "worker_"
MAX_SECRET_LENGTH = 128 - len(PREFIX)
_SECRET = re.compile(rf"[A-Za-z0-9]{{48,{MAX_SECRET_LENGTH}}}")
_LEGACY_SECRET = re.compile(r"[A-Za-z0-9_-]{43,128}")


def worker_bearer(secret: str, *, allow_legacy: bool = False) -> str:
    if _SECRET.fullmatch(secret):
        return PREFIX + secret
    if allow_legacy and _LEGACY_SECRET.fullmatch(secret):
        return secret
    raise ValueError("Invalid worker secret format")
