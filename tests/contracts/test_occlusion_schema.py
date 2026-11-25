"""Each declaration constraint rejects a document violating only that constraint."""

from copy import deepcopy

import pytest

from haynes_studio.schemas import validator_for
from tests.canonical.fixtures import example

BOARD = "studio.board.v1.schema.json"
ASSET = "studio.asset-version.v1.schema.json"
POSE = {"key": "wide", "frame": 0}
ROLE = {"key": "counter", "label": None, "layer_order": 2}
PROP = {"key": "menu", "label": "menu", "depth": "background", "layer_order": 0}
REMOVE = object()


@pytest.fixture(scope="module")
def declarations():
    board = example("valid/story-winter-menu-r4.json")["boards"][0]
    board["layout"]["check_poses"] = [POSE]
    asset = example("valid/asset-version-cast.json")
    asset.update(kind="set", attributes={}, capabilities=["opaque_plate"],
                 occlusion={"foreground": [ROLE], "focal_props": [PROP]})
    for schema, document in ((BOARD, board), (ASSET, asset)):
        assert validator_for(schema).is_valid(document)
    return {BOARD: board, ASSET: asset}


def case(name, schema, path, value=REMOVE):
    return pytest.param(schema, path, value, id=name)


def pose(name, path, value=REMOVE):
    return case("pose-" + name, BOARD, ("layout", "check_poses", *path), value)


def asset(name, path, value=REMOVE):
    return case(name, ASSET, ("occlusion", *path), value)


def targets(group, entry, required, minimum):
    return [
        asset(f"{group}-type", (group,), {}),
        asset(f"{group}-max-items", (group,), [entry] * 17),
        asset(f"{group}-item-type", (group, 0), []),
        asset(f"{group}-extra-field", (group, 0, "extra"), 1),
        *(asset(f"{group}-required-{field}", (group, 0, field)) for field in required),
        asset(f"{group}-key-type", (group, 0, "key"), 1),
        asset(f"{group}-key-pattern", (group, 0, "key"), "BAD"),
        asset(f"{group}-label-type", (group, 0, "label"), 1),
        asset(f"{group}-label-min-length", (group, 0, "label"), ""),
        asset(f"{group}-label-max-length", (group, 0, "label"), "a" * 81),
        asset(f"{group}-layer-type", (group, 0, "layer_order"), 1.5),
        asset(f"{group}-layer-min", (group, 0, "layer_order"), minimum - 1),
        asset(f"{group}-layer-max", (group, 0, "layer_order"), 1025),
        asset(f"{group}-hint-reference", (group, 0, "hint"), 1),
    ]


def hints(kind, field, valid_value, invalid_values):
    cases = [
        ("kind-const", {field: valid_value, "kind": "other"}),
        ("required-kind", {field: valid_value}),
        ("required-value", {"kind": kind}),
        ("extra-field", {"kind": kind, field: valid_value, "extra": 1}),
        *((name, {"kind": kind, field: value}) for name, value in invalid_values),
    ]
    return [asset(f"{kind}-{name}", ("foreground", 0, "hint"), value) for name, value in cases]


def coordinates(count):
    return [
        ("list-type", {}),
        ("list-min", [0] * (count - 1)),
        ("list-max", [0] * (count + 1)),
        ("item-type", [0] * (count - 1) + [1.5]),
        ("item-min", [0] * (count - 1) + [-1]),
        ("item-max", [0] * (count - 1) + [1921]),
    ]


@pytest.mark.parametrize(("schema", "path", "value"), [
    pose("type", (), {}),
    pose("min-items", (), []),
    pose("max-items", (), [POSE] * 17),
    pose("item-type", (0,), []),
    pose("required-key", (0, "key")),
    pose("required-frame", (0, "frame")),
    pose("extra-field", (0, "extra"), 1),
    pose("key-type", (0, "key"), 1),
    pose("key-pattern", (0, "key"), "BAD"),
    pose("frame-type", (0, "frame"), 0.5),
    pose("frame-min", (0, "frame"), -1),
    asset("occlusion-type", (), []),
    asset("occlusion-required-foreground", ("foreground",)),
    asset("occlusion-required-focal-props", ("focal_props",)),
    asset("occlusion-extra-field", ("extra",), []),
    *targets("foreground", ROLE, ("key", "label", "layer_order"), 1),
    *targets("focal_props", PROP, ("key", "label", "depth"), 0),
    asset("focal-prop-depth-enum", ("focal_props", 0, "depth"), "between"),
    asset("focal-prop-foreground-role-type", ("focal_props", 0, "foreground_role"), 1),
    asset("focal-prop-foreground-role-pattern", ("focal_props", 0, "foreground_role"), "BAD"),
    asset("focal-prop-source-version-type", ("focal_props", 0, "source_asset_version_id"), 1),
    asset("focal-prop-source-version-pattern", ("focal_props", 0, "source_asset_version_id"), "asv_bad"),
    *hints("point", "xy", [2, 4], coordinates(2)),
    *hints("box", "xyxy", [0, 0, 2, 4], coordinates(4)),
    *hints("text", "text", "shelf", [("value-type", 1), ("value-min", ""), ("value-max", "a" * 81)]),
])
def test_declaration_schema_rejects_each_invalid_field(declarations, schema, path, value):
    document = deepcopy(declarations[schema])
    parent = document
    for field in path[:-1]:
        parent = parent[field]
    if value is REMOVE:
        del parent[path[-1]]
    else:
        parent[path[-1]] = value
    assert not validator_for(schema).is_valid(document)


@pytest.mark.parametrize("hint", [
    None,
    {"kind": "point", "xy": [0, 1920]},
    {"kind": "box", "xyxy": [0, 0, 1920, 1920]},
    {"kind": "text", "text": "a" * 80},
])
def test_declaration_schema_accepts_supported_hint_forms(declarations, hint):
    document = deepcopy(declarations[ASSET])
    for group in ("foreground", "focal_props"):
        document["occlusion"][group][0]["hint"] = hint
    assert validator_for(ASSET).is_valid(document)
