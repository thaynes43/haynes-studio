"""Prefixed ULIDs (contract section 2, P-01)."""

from __future__ import annotations

import re

import pytest

from haynes_studio.canonical.ids import ID_PATTERN, PREFIXES, Minter, is_id, ulid

CONTRACT_PATTERN = (r"^(prd|sty|brd|lin|cue|nte|ast|asv|job|run|dlv|apr|key|fmv|pub|fbk)"
                    r"_[0-7][0-9A-HJKMNP-TV-Z]{25}$")


def test_pattern_is_the_contracts():
    assert ID_PATTERN == CONTRACT_PATTERN
    assert len(PREFIXES) == 16


def test_ulid_encoding_is_crockford_upper_case():
    assert ulid(0, 0) == "0" * 26
    assert ulid((1 << 48) - 1, (1 << 80) - 1) == "7" + "Z" * 25
    with pytest.raises(ValueError):
        ulid(1 << 48, 0)


def test_minted_ids_match_and_sort_in_mint_order():
    clock = iter([1_700_000_000_000] * 3 + [1_700_000_000_001]).__next__
    minter = Minter(clock=clock, random_bits=lambda: (1 << 80) - 2)
    ids = [minter.mint("brd") for _ in range(4)]
    assert all(re.match(CONTRACT_PATTERN, value) for value in ids)
    assert ids == sorted(ids) and len(set(ids)) == 4  # monotonic within one ms, overflow included


def test_real_minter_and_is_id():
    value = Minter().mint("sty")
    assert is_id(value) and is_id(value, "sty") and not is_id(value, "brd")
    assert not is_id("sty_01jcil0u000000000000000001") and not is_id(None)
    with pytest.raises(ValueError):
        Minter().mint("xyz")


@pytest.mark.parametrize("value", ["sty_01M79V9FC00000000000000001\n",
                                   "sty_01M79V9FC00000000000000001 ",
                                   "\nsty_01M79V9FC00000000000000001"])
def test_the_whole_value_must_be_an_id(value):
    """`$` alone also matches before a trailing newline; the whole string must match."""
    assert not is_id(value) and not is_id(value, "sty")
