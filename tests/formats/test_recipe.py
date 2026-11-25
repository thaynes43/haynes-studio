import copy

import pytest

from haynes_studio.api.app import schema_app
from haynes_studio.build.validate import validate_run_snapshot
from haynes_studio.canonical.ids import Minter
from haynes_studio.formats.recipe import allowed_methods, method_violation, recipe_hash, validate_recipe
from tests.canonical.fixtures import example
from tests.formats.fixtures import doll_short, wide


@pytest.mark.parametrize("fixture", [doll_short, wide])
def test_fixture_validates_and_hashes_offline(fixture):
    recipe = fixture()["recipe"]
    assert not validate_recipe(recipe)
    assert recipe_hash(dict(reversed(list(recipe.items())))) == recipe_hash(recipe)


def test_checks_and_placeholder_record_follow_committed_values():
    recipe = doll_short()["recipe"]
    assert recipe["cast"]["team_costumes"]["yellowbirds"]["sleeves"] == "full_length"
    assert recipe["checks"]["decal.drift"] == {"min_ecc": 0.8}
    assert recipe["audio"]["master_lufs"] == -20
    assert recipe["human_gates"] == ["go_live"]
    [target] = recipe["targets"]
    assert target["state"] == "placeholder"
    assert target["account_id"] is None
    assert target["rules"] == {"max_length_ms": None, "ai_label_required": True, "aspect": "9:16"}


@pytest.mark.parametrize(("cast", "lines", "layer", "motion"), [
    ([], [{"speaker": "narrator"}], "whole_frame", "i2v"),
    ([{"slot": "a"}], [{"speaker": "narrator"}], "layered", "i2v"),
    ([{"slot": "a"}], [{"speaker": "a"}], "layered", "s2v"),
])
def test_classifies_board_and_reports_a_buildable_but_disallowed_method(cast, lines, layer, motion):
    recipe = doll_short()["recipe"]
    board = {"cast": cast, "lines": lines, "method": {"layer": layer, "motion": motion}}
    assert allowed_methods(recipe, board) == [{"layer": layer, "motion": motion}]
    assert method_violation(recipe, board) is None
    if cast:
        board["method"] = {"layer": "whole_frame", "motion": "i2v"}
        assert method_violation(recipe, board).rule == "method.unavailable"


@pytest.mark.parametrize(("mutation", "rule"), [
    (lambda r: r["shot_types"]["speaking"][0].update(layer="whole_frame"), "method.unavailable"),
    (lambda r: r["shot_types"]["ambient"][0].update(layer="layered"), "method.layered_needs_cast"),
    (lambda r: r["shot_types"]["reaction"][0].update(motion="s2v"), "method.s2v_needs_onscreen_speaker"),
    (lambda r: r["length"].update(max_ms=1), "format.length_invalid"),
    (lambda r: r["targets"][0].update(account_id="unexpected"), "format.target_invalid"),
    (lambda r: r["targets"][0]["rules"].update(aspect="9:0"), "schema.invalid"),
    (lambda r: r["targets"][0]["rules"].update(max_length_ms=-1), "schema.invalid"),
    (lambda r: r["targets"][0].update(credential="schema-fixture"), "format.credential"),
    (lambda r: r["targets"].append(copy.deepcopy(r["targets"][0])), "ref.duplicate"),
    (lambda r: r["human_gates"].append("go_live"), "schema.invalid"),
    (lambda r: r["human_gates"].__setitem__(0, "script"), "schema.invalid"),
    (lambda r: r.update(schema="studio.format-recipe/v99"), "schema.unsupported"),
])
def test_refuses_invalid_recipe(mutation, rule):
    recipe = doll_short()["recipe"]
    mutation(recipe)
    [violation] = validate_recipe(recipe)
    assert violation.rule == rule


def test_snapshot_validates_the_recipe_value_hash_and_story_pin():
    snapshot = example("valid/run-snapshot.json")
    recipe = doll_short()["recipe"]
    version_id = Minter().mint("fmv")
    snapshot["story"]["format_version_id"] = version_id
    assert any(v.path == "/format_version" for v in validate_run_snapshot(snapshot, context="write"))
    assert any(v.path == "/format_version" for v in validate_run_snapshot(snapshot, context="queue_run"))
    assert not validate_run_snapshot(snapshot, context="read")
    snapshot["format_version"] = {"id": version_id, "recipe": recipe, "sha256": recipe_hash(recipe)}
    assert not validate_run_snapshot(snapshot, context="write")
    recipe["notes"].append("Modified after hashing.")
    assert any(v.rule == "store.hash_mismatch" for v in validate_run_snapshot(snapshot))
    snapshot["format_version"]["id"] = Minter().mint("fmv")
    assert any(v.path == "/format_version/id" for v in validate_run_snapshot(snapshot))


def test_format_openapi_exposes_recipe_shape_and_access():
    document = schema_app().openapi()
    paths = document["paths"]
    assert paths["/v1/formats"]["post"]["x-studio-scope"] == "formats:write"
    assert paths["/v1/formats/{id}/versions"]["post"]["x-studio-scope"] == "formats:write"
    for path in ("/v1/formats", "/v1/formats/{id}/versions", "/v1/format-versions/{id}"):
        operation = paths[path]["get"]
        assert operation["x-studio-scope"] == "read"
        assert "x-studio-worker-read" not in operation
    schemas = document["components"]["schemas"]
    assert "targets" in schemas["FormatRecipe"]["required"]
    assert "warnings" in schemas["EstimateView"]["required"]
