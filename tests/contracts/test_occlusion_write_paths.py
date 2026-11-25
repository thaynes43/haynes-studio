"""Inventory of the product paths that can persist board and version documents."""

import ast
import asyncio
import json
import re
from collections import defaultdict
from pathlib import Path

import pytest

from haynes_studio.canonical import validate_board
from haynes_studio.db.drafts import STORY_FIELDS
from haynes_studio.drafting.apply import apply_draft
from haynes_studio.drafting.document import Draft
from haynes_studio.mcp.tools import OPERATIONS
from tests.canonical.fixtures import example


SOURCE = Path(__file__).resolve().parents[2] / "src" / "haynes_studio"
DOCUMENT_CALLS = {
    "_insert_board", "_replace_board", "add_board", "edit_board", "create_story", "edit_story",
    "import_draft", "_insert_imported_draft", "import_version", "import_all", "record_asset_version",
    "_validated_version", "verify_archive", "_pins", "archive.append", "apply_archive.apply",
    "apply_into", "require_valid_boards",
}
DOCUMENT_TABLES = {"boards", "asset_versions", "archive_versions"}


def write_calls(tree):
    """Identify writers by their mutation calls and the tables they touch."""
    aliases = {
        alias.asname: alias.name
        for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
        for alias in node.names if alias.asname is not None
    }
    calls = defaultdict(set)

    class Writers(ast.NodeVisitor):
        function = "<module>"

        def visit_FunctionDef(self, node):
            previous = self.function
            self.function = node.name
            self.generic_visit(node)
            self.function = previous

        visit_AsyncFunctionDef = visit_FunctionDef

        def visit_Call(self, node):
            func = node.func
            name = ast.unparse(func)
            tail = name.rsplit(".", 1)[-1]
            if name in DOCUMENT_CALLS or aliases.get(tail, tail) in DOCUMENT_CALLS:
                calls[self.function].add(name)
            if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
                table = aliases.get(func.value.id, func.value.id)
                if table in DOCUMENT_TABLES and tail in {"insert", "update"}:
                    calls[self.function].add(f"{table}.{tail}")
            if tail in {"insert", "update"} and node.args and isinstance(node.args[0], ast.Name):
                table = aliases.get(node.args[0].id, node.args[0].id)
                if table in DOCUMENT_TABLES:
                    calls[self.function].add(f"{table}.{tail}")
            self.generic_visit(node)

    Writers().visit(tree)
    return {" ".join((function, *sorted(targets))) for function, targets in calls.items()}


def test_visibility_declaration_write_paths_are_accounted_for():
    # Catalog completion and pipeline writers build their own non-set inputs.
    # Media selection, reorder and removal cannot take a layout payload. They
    # are listed because they reach a board document write.
    actual = {
        f"{path.relative_to(SOURCE).with_suffix('')} {call}"
        for path in SOURCE.rglob("*.py")
        for call in write_calls(ast.parse(path.read_text(encoding="utf-8")))
    }
    assert actual == {
        "api/archive_routes _validated_version draft.require_valid_boards",
        "api/archive_routes add_version _validated_version archive.append",
        "api/archive_routes apply_version apply_archive.apply",
        "api/archive_routes create_record _validated_version archive.append",
        "api/matte_completion complete_matte catalog.record_asset_version",
        "api/media_completion complete_candidate catalog.record_asset_version",
        "api/media_completion complete_voice catalog.record_asset_version",
        "api/media_completion record_board_photo catalog.record_asset_version",
        "api/routes create_board drafts.add_board",
        "api/routes create_story drafts.create_story",
        "api/routes update_board drafts.edit_board",
        "api/routes update_story drafts.edit_story",
        "assets/candidate record_candidate import_version",
        "assets/matte _make_candidate import_version",
        "db/catalog promote_version record_asset_version",
        "db/catalog record_asset_version asset_versions.insert",
        "db/drafts _insert_board boards.insert",
        "db/drafts _insert_imported_draft _insert_board record_asset_version",
        "db/drafts _replace_board boards.update",
        "db/drafts add_board _insert_board",
        "db/drafts edit_board _replace_board",
        "db/drafts import_draft _insert_imported_draft",
        "db/drafts remove_board boards.update",
        "db/drafts reorder boards.update",
        "db/drafts select_board_media _replace_board",
        "db/staging_archive append archive_versions.insert",
        "drafting/archive apply drafts.add_board drafts.edit_board",
        "drafting/apply apply_draft apply_into",
        "drafting/apply apply_into draft.require_valid_boards",
        "drafting/cli _apply apply_into",
        "importer/production _persist drafts.import_draft",
        "importer/production run verify_archive",
        "importer/production_archive _canonical _pins",
        "importer/run _check_records import_version",
        "library/library import_all import_version",
        "library/library promote import_version",
        "library/winter_menu build_winter_menu_library import_all",
        "motion/winter_menu build_e0_motion import_all",
        "voice/build make_voice import_version",
    }

    write_routes = {
        ("POST", "/v1/stories/{id}/boards"),
        ("PATCH", "/v1/boards/{id}"),
        ("POST", "/v1/productions/{id}/archive-records"),
        ("POST", "/v1/archive-records/{id}/versions"),
        ("POST", "/v1/archive-versions/{id}/apply"),
    }
    assert {name for name, op in OPERATIONS.items()
            if (op.method, re.sub(r"\{[^}]+\}", "{id}", op.path)) in write_routes} == {
        "studio_add_board", "studio_patch_board", "studio_create_archive_record",
        "studio_add_archive_version", "studio_apply_archive_storyboard",
    }
    assert STORY_FIELDS.isdisjoint({"boards", "layout", "check_poses", "occlusion"})


@pytest.mark.parametrize("previous", [None, {}], ids=["initial-apply", "redraft"])
def test_draft_apply_rejects_poses_before_any_mcp_tool_call(previous):
    fixture = SOURCE.parents[1] / "tests" / "drafting" / "fixtures" / "first.json"
    document = json.loads(fixture.read_bytes())
    document["boards"][0]["fields"]["layout"]["check_poses"] = [{"key": "still", "frame": 0}]
    draft = Draft.parse(json.dumps(document).encode())

    class NoCalls:
        async def call_tool(self, *args, **kwargs):
            pytest.fail("invalid draft reached MCP")

    result = asyncio.run(apply_draft(NoCalls(), draft, previous))
    assert result.error == {"code": "draft.invalid", "violations": [{
        "code": "occlusion.check_unavailable", "path": "/boards/0/fields/layout/check_poses",
    }]}


@pytest.mark.parametrize(("keys", "rule", "index"), [
    (["still", "still"], "ref.duplicate", 1),
    (["still\n"], "schema.invalid", 0),
])
def test_board_write_keeps_malformed_pose_diagnostics(keys, rule, index):
    board = example("valid/story-winter-menu-r4.json")["boards"][0]
    board.pop("derived", None)
    board["layout"]["check_poses"] = [{"key": key, "frame": 0} for key in keys]
    assert [(v.rule, v.path) for v in validate_board(board, context="write")] == [
        (rule, f"/layout/check_poses/{index}/key"),
    ]
