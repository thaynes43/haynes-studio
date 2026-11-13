"""Every contract example: shape always; validation once its type has a validator."""

from __future__ import annotations

import pytest

from tests.contracts import harness
from tests.contracts.registry import VALIDATORS

RULES = harness.load_rule_index()
PATHS = harness.discover()


def _id(path):
    return path.relative_to(harness.EXAMPLES_DIR).as_posix()


def test_examples_exist():
    kinds = {path.relative_to(harness.EXAMPLES_DIR).parts[0] for path in PATHS}
    assert {"valid", "invalid"} <= kinds, f"no examples found under {harness.EXAMPLES_DIR}"


@pytest.mark.parametrize("path", PATHS, ids=_id)
def test_example_shape(path):
    harness.fail_on(harness.check_example(path, RULES))


@pytest.mark.parametrize("path", PATHS, ids=_id)
def test_example_validates(path, request):
    example, problems = harness.load(path)
    harness.fail_on(problems)  # a malformed example is never pending
    request.node.user_properties.append((harness.CHECKED, example.type))
    validator = VALIDATORS.get(example.type)
    if validator is None:
        request.node.user_properties.append((harness.PENDING, example.type))
        return
    harness.fail_on(harness.check_with_validator(example, validator))


def test_rule_index_links_match_cases():
    harness.fail_on(harness.check_index_links(RULES))


def test_registry_keys_are_known_types():
    unknown = sorted(set(VALIDATORS) - set(harness.ALL_TYPES))
    assert not unknown, f"registry.py names unknown types: {unknown}"
    assert all(callable(v) for v in VALIDATORS.values()), "registry values must be callable"


def test_type_list_matches_contract():
    assert harness.listed_types() == harness.STUDIO_TYPES
