"""OIDC discovery, confidential code exchange and verification of the ID token."""

import base64
import hashlib
import secrets
from threading import Lock
from time import monotonic
from urllib.parse import parse_qsl, quote_plus, urlencode, urlsplit, urlunsplit

import httpx
import jwt

from .config import OIDCSettings, https_url
from .errors import APIError, forbidden


def random_secret() -> str:
    return secrets.token_urlsafe(32)


def auth_url(endpoint: str, params: dict[str, str]) -> str:
    parts = urlsplit(endpoint)
    query = parse_qsl(parts.query, keep_blank_values=True)
    if set(params).intersection(key for key, _ in query):
        raise ValueError("OIDC authorization endpoint overrides protocol parameters")
    return urlunsplit(parts._replace(query=urlencode([*query, *params.items()])))


class OIDC:
    def __init__(self, settings: OIDCSettings, transport: httpx.BaseTransport | None = None):
        self.settings = settings
        self.transport = transport
        self._metadata_cache: tuple[float, dict] | None = None
        self._jwks_cache: tuple[str, float, list] | None = None
        self._metadata_lock = Lock()
        self._jwks_lock = Lock()

    def _client(self):
        return httpx.Client(transport=self.transport, timeout=5, trust_env=False,
                            follow_redirects=False)

    def _metadata(self) -> dict:
        with self._metadata_lock:
            if self._metadata_cache is not None:
                expires, metadata = self._metadata_cache
                if monotonic() < expires:
                    return metadata
            try:
                with self._client() as client:
                    metadata = self._discover(client)
            except (httpx.HTTPError, ValueError) as error:
                raise APIError(503, "auth.provider_unavailable", "OIDC discovery is unavailable") from error
            self._metadata_cache = monotonic() + self.settings.cache_ttl_seconds, metadata
            return metadata

    def _discover(self, client: httpx.Client) -> dict:
        doc = client.get(self.settings.issuer.rstrip("/") + "/.well-known/openid-configuration")
        metadata = doc.raise_for_status().json()
        if not isinstance(metadata, dict) or metadata.get("issuer") != self.settings.issuer:
            raise ValueError("OIDC discovery issuer mismatch")
        for name in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
            endpoint = metadata.get(name)
            if not isinstance(endpoint, str) or not https_url(endpoint):
                raise ValueError("OIDC discovery requires HTTPS endpoints")
        return metadata

    def _refresh_jwks(self, client: httpx.Client, uri: str) -> list:
        try:
            jwks = client.get(uri).raise_for_status().json()
            if not isinstance(jwks, dict) or not isinstance(jwks.get("keys"), list):
                raise ValueError("OIDC key set is malformed")
        except (httpx.HTTPError, ValueError) as error:
            raise APIError(503, "auth.provider_unavailable", "OIDC signing keys are unavailable") from error
        keys = [key for key in jwks["keys"] if isinstance(key, dict)]
        self._jwks_cache = uri, monotonic() + self.settings.cache_ttl_seconds, keys
        return keys

    def _signing_keys(self, client: httpx.Client, uri: str, kid: str) -> list:
        with self._jwks_lock:
            cached = self._jwks_cache
            if cached is None or cached[0] != uri or monotonic() >= cached[1]:
                keys = self._refresh_jwks(client, uri)
            else:
                keys = cached[2]
            if not any(key.get("kid") == kid for key in keys):
                keys = self._refresh_jwks(client, uri)
            return keys

    def authorize(self, state: str, nonce: str, verifier: str) -> str:
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest())
        metadata = self._metadata()
        try:
            return auth_url(metadata["authorization_endpoint"], {
                "response_type": "code", "client_id": self.settings.client_id,
                "redirect_uri": self.settings.redirect_uri, "scope": "openid profile",
                "state": state, "nonce": nonce,
                "code_challenge": challenge.decode("ascii").rstrip("="),
                "code_challenge_method": "S256",
            })
        except ValueError as error:
            raise APIError(503, "auth.provider_unavailable", "OIDC discovery is unavailable") from error

    def exchange(self, code: str, nonce: str, verifier: str) -> dict:
        metadata = self._metadata()
        try:
            with self._client() as client:
                auth = (quote_plus(self.settings.client_id), quote_plus(self.settings.client_secret))
                response = client.post(metadata["token_endpoint"], auth=auth, data={
                    "grant_type": "authorization_code", "code": code,
                    "redirect_uri": self.settings.redirect_uri, "code_verifier": verifier,
                })
                if response.status_code in (400, 401):
                    raise APIError(401, "auth.oidc_invalid", "OIDC refused the authorization code")
                token = response.raise_for_status().json()["id_token"]
                return self._verified_claims(client, metadata["jwks_uri"], token, nonce)
        except httpx.HTTPError as error:
            raise APIError(503, "auth.provider_unavailable", "OIDC exchange is unavailable") from error
        except (KeyError, TypeError, ValueError, jwt.PyJWTError, OverflowError) as error:
            raise APIError(401, "auth.oidc_invalid", "OIDC returned an invalid ID token") from error

    def _verified_claims(self, client: httpx.Client, jwks_uri: str, token: str, nonce: str) -> dict:
        header = jwt.get_unverified_header(token)
        kid = header.get("kid")
        if header.get("alg") != "RS256" or not isinstance(kid, str) or not kid:
            raise ValueError("OIDC signing key ID and RS256 are required")
        keys = [key for key in self._signing_keys(client, jwks_uri, kid) if key.get("kid") == kid
                and key.get("kty") == "RSA" and key.get("use", "sig") == "sig"
                and key.get("alg", "RS256") == "RS256"]
        if len(keys) != 1:
            raise ValueError("OIDC signing key is unavailable or ambiguous")
        key = jwt.PyJWK(keys[0], algorithm="RS256").key
        if key.key_size < 2048:
            raise ValueError("OIDC signing key is too small")
        claims = jwt.decode(token, key, algorithms=["RS256"],
                            audience=self.settings.client_id, issuer=self.settings.issuer,
                            leeway=self.settings.leeway_seconds, options={
                                "require": ["iss", "sub", "aud", "exp", "iat", "nonce"],
                            })
        audience = claims["aud"]
        if ("azp" in claims or isinstance(audience, list) and len(audience) > 1):
            if claims.get("azp") != self.settings.client_id:
                raise ValueError("OIDC authorized party mismatch")
        if not isinstance(claims["nonce"], str) or claims["nonce"] != nonce:
            raise ValueError("OIDC nonce mismatch")
        if claims["sub"] not in self.settings.allowed_subjects:
            raise forbidden("auth.subject_forbidden", "This OIDC subject is outside the Studio allowlist")
        return claims
