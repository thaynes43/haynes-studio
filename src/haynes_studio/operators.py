"""Self-reported CLI operators. These flags do not authenticate or grant access."""

from __future__ import annotations

import argparse
import re
from urllib.parse import urlsplit

from haynes_studio.canonical.model import Principal

_AGENT_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")


def add_operator_arguments(parser: argparse.ArgumentParser) -> None:
    group = parser.add_argument_group("operator", "Give one complete set: human or agent session.")
    group.add_argument("--operator-iss", metavar="ISS", help="the person's OIDC issuer")
    group.add_argument("--operator-sub", metavar="SUB", help="their OIDC subject (never an email)")
    group.add_argument("--operator-session", metavar="SESSION", help="the agent session's name")
    group.add_argument("--operator-harness", metavar="HARNESS", help="the agent session's harness")
    group.add_argument("--operator-model", metavar="MODEL", help="the agent session's model")


def operator_from_args(args: argparse.Namespace, *, private_import: bool = False) -> Principal:
    """Require exactly one complete flag set, preserving each CLI's human checks."""
    human = (args.operator_iss, args.operator_sub)
    session = (args.operator_session, args.operator_harness, args.operator_model)
    has_human = any(v is not None for v in human)
    has_session = any(v is not None for v in session)
    if has_human == has_session:
        raise ValueError("give exactly one operator set: --operator-iss and --operator-sub, "
                         "or --operator-session, --operator-harness and --operator-model")
    if has_session:
        for name, value in zip(("session", "harness", "model"), session):
            if (not isinstance(value, str) or not value or value != value.strip()
                    or _AGENT_CONTROL.search(value)):
                raise ValueError(f"--operator-{name} is required and must be nonempty text "
                                 "without control characters or surrounding whitespace")
        return Principal(kind="agent_session", session=session[0], harness=session[1],
                         model=session[2])
    iss, sub = human
    control = re.compile(r"[\x00-\x1f\x7f]" if private_import else r"[\x00-\x1f\x7f-\x9f]")

    def bad(value):
        return not isinstance(value, str) or not value or bool(control.search(value)) or any(
            c.isspace() for c in value)

    try:
        parts = urlsplit(iss) if isinstance(iss, str) else None
        issuer_ok = parts is not None and parts.scheme in ("https", "http") and bool(parts.hostname)
    except ValueError:
        issuer_ok = False
    if bad(iss) or not issuer_ok:
        raise ValueError("--operator-iss is required and must be an OIDC issuer "
                         "(an http or https URL with a host, no spaces)")
    if bad(sub) or len(sub) > 255 or (private_import and "@" in sub):
        raise ValueError("--operator-sub is required and must be an OIDC subject "
                         "(1 to 255 characters, no spaces or control characters" +
                         (" or @)" if private_import else ")"))
    return Principal(kind="human", iss=iss, sub=sub)
