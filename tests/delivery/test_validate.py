"""The ``studio.delivery/v1`` schema, validator and model (contract section 8)."""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path

import pytest

from haynes_studio.canonical.model import to_document
from haynes_studio.delivery import (
    PROXY_LIMIT_BYTES,
    Delivery,
    media_kind_of,
    proxy_byte_limit,
    validate_delivery,
)
from haynes_studio.schemas import load_schema
from haynes_studio.store import is_locator

EXAMPLES = Path(__file__).resolve().parents[2] / "docs" / "contracts" / "examples" / "valid"
NEW = json.loads((EXAMPLES / "delivery.json").read_text())
LEGACY = json.loads((EXAMPLES / "delivery-legacy-r4.json").read_text())
H = "ab" * 32
PRD2 = "prd_01M79V9FC00000000000000002"


@pytest.mark.parametrize("example", [NEW, LEGACY], ids=["new", "legacy-r4"])
@pytest.mark.parametrize("context", ["read", "write", "queue_run"])
def test_the_contract_examples_validate_in_every_context(example, context):
    assert validate_delivery(example, context=context) == []


@pytest.mark.parametrize("example", [NEW, LEGACY], ids=["new", "legacy-r4"])
def test_the_model_round_trips_the_examples(example):
    model = Delivery.from_document(example)
    assert to_document(model) == example
    assert model.is_legacy == (example is LEGACY)
    with pytest.raises(AttributeError):
        model.id = "dlv_x"  # read-only


def _set(document, path, value):
    *parents, last = path.strip("/").split("/")
    target = document
    for part in parents:
        target = target[int(part)] if isinstance(target, list) else target[part]
    if value is _DELETE:
        del target[last]
    else:
        target[last] = value


_DELETE = object()
LOCATOR = NEW["master"]["locator"]

CASES = [
    # (example, path, value, rule, reported path)
    (NEW, "/schema", "studio.delivery/v2", "schema.unsupported", "/schema"),
    (NEW, "/colour", "blue", "schema.unknown_field", "/colour"),
    (NEW, "/derived", {}, "schema.unknown_field", "/derived"),
    (NEW, "/id", "dlv_123", "id.malformed", "/id"),
    (NEW, "/id", "run_01M79V9FC00000000000000001", "id.type_mismatch", "/id"),
    (NEW, "/run_id", "dlv_01M79V9FC00000000000000001", "id.type_mismatch", "/run_id"),
    (NEW, "/created_at", "2026-11-13 09:20", "schema.invalid", "/created_at"),
    (NEW, "/master/locator", "../" + LOCATOR, "store.locator_invalid", "/master/locator"),
    (NEW, "/master/locator", "/" + LOCATOR, "store.locator_invalid", "/master/locator"),
    (NEW, "/master/locator", LOCATOR.replace("f10b4e92", "f10b4e93"), "store.locator_invalid",
     "/master/locator"),
    (NEW, "/master/locator", LOCATOR.replace("/f1/", "/aa/"), "store.locator_invalid",
     "/master/locator"),
    (NEW, "/master/locator", LOCATOR.replace(".mp4", ".wav"), "store.locator_invalid",
     "/master/locator"),
    (NEW, "/master/locator", "library/sha256/f1/" + LOCATOR.rsplit("/", 1)[1],
     "store.locator_invalid", "/master/locator"),
    (NEW, "/proxy/locator", NEW["proxy"]["locator"].replace(
        "prd_01M79V9FC00000000000000001", PRD2), "store.locator_invalid", "/proxy/locator"),
    (NEW, "/master/locator", None, "schema.invalid", "/master/locator"),
    (NEW, "/master/legacy_path", "productions/x/final.mp4", "schema.invalid",
     "/master/legacy_path"),
    (NEW, "/master/fps", 25, "schema.invalid", "/master/fps"),
    (NEW, "/master/fps", 24.5, "schema.invalid", "/master/fps"),
    (NEW, "/master/video_codec", "hevc", "schema.invalid", "/master/video_codec"),
    (NEW, "/proxy/audio_codec", "opus", "schema.invalid", "/proxy/audio_codec"),
    (NEW, "/master/media_type", "video/quicktime", "schema.invalid", "/master/media_type"),
    (NEW, "/master/sha256", "F" * 64, "schema.invalid", "/master/sha256"),
    (NEW, "/master/bytes", 0, "schema.invalid", "/master/bytes"),
    (NEW, "/master/width", 1080.5, "schema.invalid", "/master/width"),
    (NEW, "/master/width", 720, "schema.invalid", "/master/width"),
    (NEW, "/proxy/width", 1080, "schema.invalid", "/proxy/width"),
    (NEW, "/proxy", None, "schema.invalid", "/proxy"),
    (NEW, "/proxy/frames", 1086, "schema.invalid", "/proxy/frames"),
    (NEW, "/proxy/bytes", PROXY_LIMIT_BYTES, "schema.invalid", "/proxy/bytes"),
    (NEW, "/verification/decoded_frames", 1086, "schema.invalid", "/verification/decoded_frames"),
    (NEW, "/verification/expected_frames", 1088, "schema.invalid",
     "/verification/expected_frames"),
    (NEW, "/verification/sha256_verified", False, "schema.invalid",
     "/verification/sha256_verified"),
    (NEW, "/verification/proxy_under_bytes", 26_000_000, "schema.invalid",
     "/verification/proxy_under_bytes"),
    (NEW, "/verification/proxy_under_bytes", _DELETE, "schema.invalid",
     "/verification/proxy_under_bytes"),
    (NEW, "/verification/source", "titles/x/validation.json", "schema.invalid", "/verification"),
    (NEW, "/store/writable", False, "schema.invalid", "/store/writable"),
    (NEW, "/store/adapter", "s3", "schema.invalid", "/store/adapter"),
    (NEW, "/legacy", LEGACY["legacy"], "schema.invalid", "/legacy"),
    (LEGACY, "/store/writable", True, "schema.invalid", "/store/writable"),
    (LEGACY, "/proxy", NEW["proxy"], "schema.invalid", "/proxy"),
    (LEGACY, "/master/locator", LOCATOR, "schema.invalid", "/master/locator"),
    (LEGACY, "/master/legacy_path", None, "schema.invalid", "/master/legacy_path"),
    (LEGACY, "/master/legacy_path", "/workspace/output/productions/x/edit/final.mp4",
     "schema.invalid", "/master/legacy_path"),
    (LEGACY, "/master/legacy_path", "productions/../jobs/final.mp4", "schema.invalid",
     "/master/legacy_path"),
    (LEGACY, "/verification/source", _DELETE, "schema.invalid", "/verification/source"),
    (LEGACY, "/verification/source", "../validation.json", "schema.invalid",
     "/verification/source"),
    (LEGACY, "/verification/proxy_under_bytes", PROXY_LIMIT_BYTES, "schema.invalid",
     "/verification"),
    (LEGACY, "/legacy", None, "schema.invalid", "/legacy"),
    (LEGACY, "/legacy/ledger_id", "032F1BB2", "schema.invalid", "/legacy/ledger_id"),
    (LEGACY, "/legacy/kind", "video", "schema.invalid", "/legacy/kind"),
    (LEGACY, "/legacy/url", "https://video.haynesops.com/videos/" + "0" * 32 + "/file",
     "schema.invalid", "/legacy/url"),
    (LEGACY, "/legacy/url", "http://example.invalid/x", "schema.invalid", "/legacy/url"),
    (LEGACY, "/legacy/extra", 1, "schema.unknown_field", "/legacy/extra"),
]


@pytest.mark.parametrize("example, path, value, rule, at", CASES,
                         ids=[f"{'legacy' if c[0] is LEGACY else 'new'}{c[1]}={str(c[2])[:20]}"
                              for c in CASES])
def test_each_rule_is_reported_at_its_field(example, path, value, rule, at):
    document = copy.deepcopy(example)
    _set(document, path, value)
    found = validate_delivery(document, context="write")
    assert (rule, at) in {(v.rule, v.path) for v in found}, [str(v) for v in found]


def test_integral_floats_are_integers():
    document = copy.deepcopy(NEW)
    document["master"]["frames"] = 1087.0
    document["verification"]["proxy_under_bytes"] = 25_000_000.0
    assert validate_delivery(document) == []
    assert Delivery.from_document(document).master.frames == 1087


@pytest.mark.parametrize("document", [None, [], "delivery", 7, {}, {"schema": None},
                                      {"schema": "studio.delivery/v1"},
                                      {**NEW, "master": None}, {**NEW, "master": []},
                                      {**NEW, "verification": {"decoded_frames": "x"}},
                                      {**NEW, "legacy": {"url": 7}},
                                      {**NEW, "proxy": {"locator": 7}}])
def test_a_malformed_document_is_reported_never_raised(document):
    found = validate_delivery(document)
    assert found and all(v.status == "invalid" for v in found)


def test_a_deeply_nested_document_is_refused_at_the_root():
    deep: dict = {}
    for _ in range(70):
        deep = {"x": deep}
    found = validate_delivery({**NEW, "legacy": deep})
    assert [(v.rule, v.path) for v in found] == [("schema.invalid", "")]


def test_an_unknown_context_is_a_caller_error():
    with pytest.raises(ValueError):
        validate_delivery(NEW, context="publish")


def test_the_proxy_limit_is_25_mb_per_minute():
    assert proxy_byte_limit(1) == proxy_byte_limit(1087) == proxy_byte_limit(1440) == 25_000_000
    assert proxy_byte_limit(2880) == 50_000_000
    assert proxy_byte_limit(1441) == 25_017_361
    for bad in (0, -1, 1.0, True, "1440"):
        with pytest.raises(ValueError):
            proxy_byte_limit(bad)


def test_media_kinds():
    assert media_kind_of(1080, 1920) == "short"
    assert media_kind_of(1920, 1080) == "video"
    assert media_kind_of(720, 1280) is None


@pytest.mark.parametrize("locator", [
    LOCATOR, NEW["proxy"]["locator"], "library/sha256/ab/" + H + ".mp4",
    "productions/prd_01M79V9FC00000000000000001/sha256/ab/" + H + ".json",
    "../" + LOCATOR, LOCATOR + "\n", LOCATOR.upper(), LOCATOR.replace(".mp4", ".mov"),
    "productions/prd_x/sha256/ab/" + H + ".mp4", "productions/prd_01M79V9FC00000000000000001/records/x.json",
])
def test_the_schema_locator_grammar_agrees_with_the_store(locator):
    schema = load_schema("studio.asset-version.v1.schema.json")["$defs"]["content"]["properties"]
    pattern = schema["locator"]["pattern"]
    assert bool(re.fullmatch(pattern, locator)) == is_locator(locator)
