"""Environment-only runtime configuration."""

import json
import os
from dataclasses import dataclass, field
from urllib.parse import urlsplit


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
        if not self.allowed_subjects or any(not isinstance(s, str) or not s for s in self.allowed_subjects):
            raise ValueError("STUDIO_OIDC_ALLOWED_SUBJECTS must list verified OIDC subjects")
        if not 60 <= self.session_seconds <= 86400:
            raise ValueError("STUDIO_SESSION_SECONDS must be between 60 and 86400")
        if self.leeway_seconds < 0:
            raise ValueError("STUDIO_OIDC_LEEWAY_SECONDS must be nonnegative")
        if self.cache_ttl_seconds <= 0:
            raise ValueError("STUDIO_OIDC_CACHE_TTL_SECONDS must be positive")

    @property
    def redirect_uri(self):
        return self.public_origin + "/auth/callback"


def from_environment() -> OIDCSettings:
    try:
        subjects = json.loads(os.environ["STUDIO_OIDC_ALLOWED_SUBJECTS"])
        if not isinstance(subjects, list) or not all(isinstance(s, str) for s in subjects):
            raise ValueError("STUDIO_OIDC_ALLOWED_SUBJECTS must be a JSON array of strings")
        return OIDCSettings(os.environ["STUDIO_OIDC_ISSUER"], os.environ["STUDIO_OIDC_CLIENT_ID"],
                            os.environ["STUDIO_OIDC_CLIENT_SECRET"], os.environ["STUDIO_PUBLIC_ORIGIN"],
                            frozenset(subjects),
                            session_seconds=int(os.environ.get("STUDIO_SESSION_SECONDS", "28800")),
                            leeway_seconds=int(os.environ.get("STUDIO_OIDC_LEEWAY_SECONDS", "60")),
                            cache_ttl_seconds=int(os.environ.get("STUDIO_OIDC_CACHE_TTL_SECONDS", "300")))
    except KeyError as missing:
        raise ValueError(f"{missing.args[0]} is required") from None
