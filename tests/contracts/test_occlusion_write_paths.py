"""Inventory of the product paths that can persist board and version documents."""

import ast
import asyncio
import json
import re
from collections import defaultdict
from pathlib import Path

import pytest

from haynes_studio.canonical import load_story, to_document, validate_board
from haynes_studio.canonical.model import Board
from haynes_studio.db.drafts import STORY_FIELDS
from haynes_studio.drafting.apply import apply_draft
from haynes_studio.drafting.document import Draft
from haynes_studio.errors import ContractError
from haynes_studio.mcp.tools import OPERATIONS
from tests.canonical.fixtures import example


SOURCE = Path(__file__).resolve().parents[2] / "src" / "haynes_studio"
DOCUMENT_CALLS = {
    "_insert_board", "_replace_board", "add_board", "edit_board", "create_story", "edit_story",
    "import_draft", "_insert_imported_draft", "import_version", "import_all", "record_asset_version",
    "_validated_version", "verify_archive", "_pins", "archive.append", "apply_archive.apply",
    "apply_into", "require_valid_boards",
    "archive_bytes", "board_snapshot", "board_write_document", "story_write_document",
    "snapshot_write_document", "version_write_document", "version_document",
    "from_version_documents", "make_snapshot", "snapshot_bytes", "runs.enqueue",
    "_read_inputs", "_write_outputs", "with_derived", "catalog.find_assets", "catalog.get_asset",
    "catalog.board_versions", "draft.board", "inputs.freeze",
    "library.document", "result.library.documents", "_stored_snapshot",
}
DOCUMENT_TABLES = {"boards", "asset_versions", "archive_versions", "runs"}
DOCUMENT_FILES = {"story.json", "library.json", "snapshot.json", "asset-versions.json"}
SERIALIZERS = {"dump", "dumps", "_create", "canonical_json", "write", "write_text", "write_bytes", "publish",
               "write_json"}
DOCUMENT_NAMES = {
    "story", "board", "boards", "snapshot", "library", "asset_versions", "frozen_library",
    "STORY_FILE", "STORY_OUT", "LIBRARY_FILE", "LIBRARY_OUT", "BOARD_SCHEMA", "ASSET_VERSION_SCHEMA",
}


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
            if tail in SERIALIZERS:
                # Include raw JSON and filesystem writes even if the function
                # never calls a recognized model or SQLAlchemy writer.
                expressions = node.args
                if isinstance(func, ast.Attribute) and tail.startswith("write"):
                    expressions = [func.value, *expressions]
                args = [arg for expr in expressions if not isinstance(expr, ast.JoinedStr)
                        for arg in ast.walk(expr)]
                if tail == "_create" or any(
                    (isinstance(arg, ast.Name) and arg.id in DOCUMENT_NAMES)
                    or (isinstance(arg, ast.Attribute) and arg.attr in DOCUMENT_NAMES)
                    or (isinstance(arg, ast.Constant) and isinstance(arg.value, str)
                        and arg.value in DOCUMENT_FILES | {"studio.board/v1", "studio.asset-version/v1"})
                    for arg in args
                ):
                    calls[self.function].add(f"serialize:{name}")
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
    assert actual == set(line.strip() for line in """
        api/archive_routes _validated_version draft.archive_bytes
        api/archive_routes add_version _validated_version archive.append
        api/archive_routes apply_version apply_archive.apply
        api/archive_routes create_record _validated_version archive.append
        api/job_routes _board_job drafts.board_snapshot
        api/job_routes _upload_inputs drafts.board_snapshot
        api/job_routes get_job_result version_document
        api/job_routes list_versions catalog.board_versions
        api/job_routes request_matte version_document
        api/matte_completion complete_matte catalog.record_asset_version
        api/media_completion complete_candidate catalog.record_asset_version version_document
        api/media_completion complete_voice catalog.record_asset_version drafts.board_snapshot version_document
        api/media_completion record_board_photo catalog.record_asset_version drafts.board_snapshot version_document
        api/routes create_board draft.board drafts.add_board
        api/routes create_story drafts.create_story
        api/routes get_asset catalog.get_asset
        api/routes search_assets catalog.find_assets
        api/routes update_board drafts.edit_board
        api/routes update_story drafts.edit_story
        api/run_routes get_run_snapshot _stored_snapshot
        api/run_routes queue_run inputs.freeze runs.enqueue snapshot_bytes
        assets/candidate record_candidate import_version
        assets/matte _make_candidate import_version
        build/pipeline _build make_snapshot snapshot_bytes
        build/prebuild make_snapshot snapshot_write_document
        build/prebuild snapshot_bytes serialize:canonical_json
        build/validate snapshot_write_document story_write_document
        canonical/__init__ load_story story_write_document
        canonical/legacy_import import_manifest with_derived
        canonical/model to_document board_write_document
        canonical/occlusion story_write_document board_write_document
        canonical/validate validate_board board_write_document
        canonical/validate validate_story story_write_document
        cli _build _read_inputs
        cli _import _write_outputs serialize:json.dump with_derived
        cli _read_inputs Library.from_version_documents story_write_document
        cli _voice _read_inputs result.library.documents serialize:_create
        cli _write_outputs serialize:_create
        db/catalog _load_versions Library.from_version_documents
        db/catalog _version version_document
        db/catalog promote_version record_asset_version version_document
        db/catalog record_asset_version asset_versions.insert version_document version_write_document
        db/drafts _insert_board board_write_document boards.insert
        db/drafts _insert_imported_draft Library.from_version_documents _insert_board record_asset_version
        db/drafts _replace_board board_write_document boards.update
        db/drafts add_board _insert_board
        db/drafts board board_write_document
        db/drafts board_snapshot board_write_document
        db/drafts edit_board _replace_board
        db/drafts import_draft _insert_imported_draft story_write_document
        db/drafts remove_board board_write_document boards.update
        db/drafts reorder board_write_document boards.update
        db/drafts select_board_media _replace_board
        db/runs _save runs.update
        db/runs enqueue runs.insert
        db/staging_archive append archive_versions.insert
        drafting/apply apply_draft apply_into
        drafting/apply apply_into draft.require_valid_boards
        drafting/archive apply drafts.add_board drafts.edit_board
        drafting/cli _apply apply_into
        drafting/document archive_bytes self.require_valid_boards
        drafting/document parse board_write_document
        drafting_benchmark _preservation serialize:canonical_json
        drafting_benchmark score Library.from_version_documents
        importer/command main Library.from_version_documents result.library.documents serialize:_create
        importer/production _persist drafts.import_draft runs.insert
        importer/production run verify_archive
        importer/production_archive _canonical _pins snapshot_write_document
        importer/production_archive _pins Library.from_version_documents version_write_document
        importer/production_archive verify_archive serialize:canonical_json
        importer/run _check_records import_version
        library/library _check version_document version_write_document
        library/library document version_document
        library/library from_version_documents version_write_document
        library/library import_all import_version
        library/library import_version version_document
        library/library promote import_version
        library/model version_document version_write_document
        library/winter_menu build_winter_menu_library import_all
        motion/winter_menu build_e0_motion import_all
        photo/record record_photo version_document
        queue/inputs freeze make_snapshot version_document
        queue/media_inputs checked_photo Library.from_version_documents
        queue/media_inputs documents version_document
        queue/media_worker _matte Library.from_version_documents version_document
        queue/media_worker _voice Library.from_version_documents version_document
        queue/worker _inputs Library.from_version_documents snapshot_bytes
        voice/build make_voice import_version
        voice/plan _stock_voice library.document
    """.splitlines() if line.strip())

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


# Follow the value into the actual sink. Merely calling a guard somewhere
# in the function is insufficient, for example if the raw value is written
# instead of the return value. Source-archive publication uses verified original
# members. The run pin and stored snapshot use the canonical output.
SINK_FLOW = {
    ("canonical/model", "to_document"): (
        "board_write_document(out) if isinstance(value, Board) else out",
    ),
    ("canonical/__init__", "with_derived"): ("out = to_document(story)",),
    ("canonical/legacy_import", "import_manifest"): (
        "story = with_derived(story, facts=facts, source=manifest.source)",
    ),
    ("cli", "_read_inputs"): (
        "story = story_write_document(story)",
        "(story, Library.from_version_documents(versions, context=context))",
    ),
    ("cli", "_voice"): (
        "story, library = _read_inputs(args, context='write')",
        "documents = ((STORY_OUT, result.story), (LIBRARY_OUT, result.library.documents()))",
        "_create(out_dir / name, document)",
    ),
    ("cli", "_write_outputs"): (
        "targets = [(out_dir / STORY_FILE, result.story), (out_dir / MAP_FILE, result.import_map)]",
    ),
    ("importer/command", "main"): (
        "Library.from_version_documents(_document(args.library), context='write')",
        "documents = result.library.documents()",
        "_create(target / LIBRARY_FILE, documents)",
    ),
    ("library/model", "version_document"): (
        "return version_write_document(out, source_content=source_content)",
    ),
    ("library/library", "document"): (
        "return version_document(version, self.assets[version.asset_id])",
    ),
    ("library/library", "documents"): (
        "self.document(v.id)",
    ),
    ("db/catalog", "_version"): (
        "return version_document(replace(version, occlusion=None), Asset.from_document(row.asset))",
    ),
    ("db/catalog", "record_asset_version"): (
        "document = version_write_document(document, source_content=source_content)", "document=document",
    ),
    ("db/drafts", "_insert_board"): ("doc = board_write_document(doc)", "document=doc"),
    ("db/drafts", "_replace_board"): ("doc = board_write_document(doc)", "document=doc"),
    ("db/drafts", "reorder"): (
        "updated.boards[id_board] = board_write_document(_board_changed(held, by, 'reordered', now, acknowledgment))",
        "document=updated.boards[id_board]",
    ),
    ("db/drafts", "remove_board"): (
        "document=board_write_document(_board_changed(held, by, 'removed', now, acknowledgment))",
    ),
    ("db/drafts", "board"): ("board_write_document(self.boards[id_])",),
    ("db/drafts", "board_snapshot"): (
        "story = {**draft.story, 'boards': [board_write_document(board)], 'board_order': [board_id]}",
    ),
    ("api/archive_routes", "_validated_version"): ("data = draft.archive_bytes()",),
    ("api/archive_routes", "create_record"): ("data=data",),
    ("api/archive_routes", "add_version"): ("data=data",),
    ("db/staging_archive", "append"): ("payload = {**payload, 'text': data.decode('utf-8')}",),
    ("drafting/document", "parse"): (
        "item['fields'] = board_write_document(fields)",
        "archive_bytes = canonical_json(raw) if changed else data",
    ),
    ("drafting/document", "archive_bytes"): ("self.require_valid_boards()", "return self._archive_bytes"),
    ("build/prebuild", "make_snapshot"): ("snapshot = snapshot_write_document(snapshot)", "return snapshot"),
    ("build/validate", "snapshot_write_document"): ("canonical = story_write_document(story, prefix='/story')",),
    ("build/pipeline", "_build"): (
        "snapshot = make_snapshot(prepared, library, studio=inputs.studio)",
        "data, sha = snapshot_bytes(snapshot)", "records.create(run, data)",
    ),
    ("queue/inputs", "freeze"): (
        "snapshot = make_snapshot(prepared, library, studio=studio)",
        "version_document(library.version(entry['id']), library.asset_of(entry['id']))",
        "return (snapshot, documents)",
    ),
    ("api/run_routes", "queue_run"): (
        "frozen, library = inputs.freeze(prepared, studio=request.app.state.build_revision)",
        "data, sha = snapshot_bytes(frozen)", "snapshot=frozen", "library=library",
    ),
    ("db/runs", "enqueue"): ("snapshot=snapshot", "frozen_library=library"),
    ("importer/production_archive", "_canonical"): ("snapshot = snapshot_write_document(source)",),
    ("importer/production_archive", "_pins"): (
        "library = Library.from_version_documents(value, context='write')",
        "pinned.append(version_write_document(by_id[version.id]))",
    ),
    ("importer/production", "_persist"): ("snapshot=archive.snapshot", "frozen_library=archive.versions"),
    ("importer/production", "_publish"): ("archive.snapshot_data", "expected_sha256=pin['sha256']"),
    ("importer/production", "_imported_run"): ("archive.snapshot_pin",),
}


@pytest.mark.parametrize("module,function", SINK_FLOW)
def test_serialized_value_flows_through_canonical_output(module, function):
    tree = ast.parse((SOURCE / f"{module}.py").read_text(encoding="utf-8"))
    body = next(node for node in ast.walk(tree)
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function)
    expressions = {ast.unparse(node) for node in ast.walk(body)
                   if isinstance(node, (ast.expr, ast.stmt, ast.keyword))}
    assert set(SINK_FLOW[module, function]) <= expressions


def test_inventory_discovers_a_raw_filesystem_writer_without_a_model_call():
    tree = ast.parse("""
def export(story, destination):
    destination.write_text(json.dumps(story))
""")
    assert write_calls(tree) == {"export serialize:destination.write_text serialize:json.dumps"}


@pytest.mark.parametrize("empty", [None, []])
def test_board_write_model_serializes_empty_poses_like_omission(empty):
    story = example("valid/story-winter-menu-r4.json")
    story.pop("derived")
    for board in story["boards"]:
        board.pop("derived")
    expected = to_document(load_story(story, context="write"))
    story["boards"][0]["layout"]["check_poses"] = empty
    assert to_document(load_story(story, context="write")) == expected
    assert to_document(Board.from_document(story["boards"][0])) == expected["boards"][0]
    story["boards"][0]["layout"]["check_poses"] = [{"key": "still", "frame": 0}]
    with pytest.raises(ContractError, match="occlusion.check_unavailable"):
        to_document(Board.from_document(story["boards"][0]))


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
