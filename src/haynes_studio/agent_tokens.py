"""Agent bearer token formats shared by registration, the API and MCP."""

import re

MAX_AGENT_TOKEN_LENGTH = 128
# Generated tokens encode 32 random bytes as 43 unpadded base64url characters.
# Password generators for mounted secrets supply at least 48 alphanumeric characters.
AGENT_TOKEN_PATTERN = rf"(?:[A-Za-z0-9_-]{{43}}|[A-Za-z0-9]{{48,{MAX_AGENT_TOKEN_LENGTH}}})"
_AGENT_TOKEN = re.compile(AGENT_TOKEN_PATTERN)


def valid_agent_token(token: str | None) -> bool:
    return token is not None and _AGENT_TOKEN.fullmatch(token) is not None
