"""Environment-only runtime configuration."""

import json
import os
from dataclasses import dataclass, field
from urllib.parse import urlsplit

DEFAULT_STORE_FRESHNESS_SECONDS = 30


def https_url(value: str) -> bool:
    try:
        parts = urlsplit(value)
        return (parts.scheme == "https" and bool(parts.hostname)
                and parts.username is None and parts.password is None
                and not parts.fragment and not any(ord(char) < 33 for char in value)
                and "\\" not in value)
    except ValueError:
        return False


@dataclass(frozen=True)
class OIDCSettings:
    issuer: str
    client_id: str
    client_secret: str = field(repr=False)
    public_origin: str
    allowed_subjects: frozenset[str]
    session_seconds: int = 8 * 60 * 60
    leeway_seconds: int = 60
    cache_ttl_seconds: int = 5 * 60
    failure_ttl_seconds: int = 10
    allowed_groups: frozenset[str] = frozenset()

    def __post_init__(self):
        if not https_url(self.issuer) or urlsplit(self.issuer).query:
            raise ValueError("STUDIO_OIDC_ISSUER must be an HTTPS issuer URL")
        if not https_url(self.public_origin) or not urlsplit(self.public_origin).netloc:
            raise ValueError("STUDIO_PUBLIC_ORIGIN must be an HTTPS origin")
        origin = urlsplit(self.public_origin)
        if self.public_origin != f"https://{origin.netloc}":
            raise ValueError("STUDIO_PUBLIC_ORIGIN must have only scheme and authority")
        if not self.client_id or not self.client_secret:
            raise ValueError("The OIDC client ID and client secret are required")
        if any(not isinstance(s, str) or not s for s in self.allowed_subjects):
            raise ValueError("STUDIO_OIDC_ALLOWED_SUBJECTS must list verified OIDC subjects")
        if any(not isinstance(group, str) or not group for group in self.allowed_groups):
            raise ValueError("STUDIO_OIDC_ALLOWED_GROUPS must list OIDC group names")
        if not (self.allowed_subjects or self.allowed_groups):
            raise ValueError(
                "At least one of STUDIO_OIDC_ALLOWED_SUBJECTS and STUDIO_OIDC_ALLOWED_GROUPS must be non-empty"
            )
        if not 60 <= self.session_seconds <= 86400:
            raise ValueError("STUDIO_SESSION_SECONDS must be between 60 and 86400")
        if not 0 <= self.leeway_seconds <= 300:
            raise ValueError("STUDIO_OIDC_LEEWAY_SECONDS must be between 0 and 300")
        if not 1 <= self.cache_ttl_seconds <= 3600:
            raise ValueError("STUDIO_OIDC_CACHE_TTL_SECONDS must be between 1 and 3600")
        if not 1 <= self.failure_ttl_seconds <= 60:
            raise ValueError("STUDIO_OIDC_FAILURE_TTL_SECONDS must be between 1 and 60")

    @property
    def redirect_uri(self):
        return self.public_origin + "/auth/callback"


def _allowlist_from_environment(name: str) -> frozenset[str]:
    message = f"{name} must be a JSON array of non-empty strings"
    try:
        values = json.loads(os.environ.get(name, "[]"))
    except ValueError:
        raise ValueError(message) from None
    if not isinstance(values, list) or not all(isinstance(value, str) and value for value in values):
        raise ValueError(message)
    return frozenset(values)


def from_environment() -> OIDCSettings:
    try:
        return OIDCSettings(os.environ["STUDIO_OIDC_ISSUER"], os.environ["STUDIO_OIDC_CLIENT_ID"],
                            os.environ["STUDIO_OIDC_CLIENT_SECRET"], os.environ["STUDIO_PUBLIC_ORIGIN"],
                            _allowlist_from_environment("STUDIO_OIDC_ALLOWED_SUBJECTS"),
                            session_seconds=int(os.environ.get("STUDIO_SESSION_SECONDS", "28800")),
                            leeway_seconds=int(os.environ.get("STUDIO_OIDC_LEEWAY_SECONDS", "60")),
                            cache_ttl_seconds=int(os.environ.get("STUDIO_OIDC_CACHE_TTL_SECONDS", "300")),
                            failure_ttl_seconds=int(os.environ.get("STUDIO_OIDC_FAILURE_TTL_SECONDS", "10")),
                            allowed_groups=_allowlist_from_environment("STUDIO_OIDC_ALLOWED_GROUPS"))
    except KeyError as missing:
        raise ValueError(f"{missing.args[0]} is required") from None


def store_freshness_from_environment() -> int:
    name = "STUDIO_STORE_FRESHNESS_SECONDS"
    seconds = int(os.getenv(name, str(DEFAULT_STORE_FRESHNESS_SECONDS)))
    if not 5 <= seconds <= 300:
        raise ValueError(f"{name} must be between 5 and 300")
    return seconds
