"""Implemented people-only actions reject sessions before a lookup or state change."""
from __future__ import annotations

import pytest

from haynes_studio.adapters.wan import Halt, InFlightJob, WanClipClient
from haynes_studio.canonical.model import Principal, require_human
from haynes_studio.library import EMPTY, promote
from tests.canonical.fixtures import NOW, OPERATOR

SESSION = Principal(kind="agent_session", session="op864-test", harness="Codex", model="gpt-6.1-sol")
CLI_SESSION = Principal(kind="cli", command="studio test", operator=SESSION)
HUMAN = Principal.from_document(OPERATOR)


@pytest.mark.parametrize("actor", [SESSION, CLI_SESSION])
def test_promote_asset_version_refuses_an_agent_session(actor):
    with pytest.raises(ValueError, match="promote_asset_version requires a human operator"):
        promote(EMPTY, "not-even-looked-up", by=actor, now=NOW)
    assert not EMPTY.versions


@pytest.mark.parametrize("actor", [SESSION, CLI_SESSION])
def test_clear_in_flight_refuses_an_agent_session_without_forgetting_the_job(actor, monkeypatch):
    job = InFlightJob("a" * 32, "unknown", "in_flight", "b" * 64)
    monkeypatch.setattr(WanClipClient, "_unsettled", job)
    with pytest.raises(ValueError, match="clear_in_flight requires a human operator"):
        WanClipClient.clear_in_flight(by=actor)
    assert WanClipClient.in_flight() is job


@pytest.mark.parametrize("actor", [SESSION, CLI_SESSION])
def test_clear_halt_refuses_an_agent_session_without_lifting_the_halt(actor, monkeypatch):
    halt = Halt("a" * 32, ("foreign",))
    monkeypatch.setattr(WanClipClient, "_halt", halt)
    with pytest.raises(ValueError, match="clear_halt requires a human operator"):
        WanClipClient.clear_halt(by=actor)
    assert WanClipClient.halted() is halt


@pytest.mark.parametrize("actor", [HUMAN, Principal(kind="cli", command="test", operator=HUMAN)])
def test_human_only_guard_accepts_a_human_or_its_cli_wrapper(actor):
    require_human(actor, "test")


@pytest.mark.parametrize("actor", [
    Principal(kind="agent", key_id="key_test"), Principal(kind="worker", worker_id="test"),
    Principal(kind="cli", command="test"), Principal(kind="human"),
    Principal(kind="human", iss="issuer", sub="subject", session="extra"),
    Principal(kind="cli", command="nested", operator=CLI_SESSION),
])
def test_human_only_guard_refuses_other_principals_and_malformed_humans(actor):
    with pytest.raises(ValueError, match="requires a human operator"):
        require_human(actor, "test")
