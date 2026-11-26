"""Inventory serialization sites that could carry a board or asset version.

A sink can receive a document through a generic argument, under any symbol name.
Inventory the output operations themselves and keep runtime coverage of the
canonical boundaries in the build, API, archive and library suites.
"""

import ast
import hashlib
import json
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
INVENTORY = Path(__file__).with_name("document-writers.json")
SOURCE_DIRS = ("src/haynes_studio", "titles", "scripts")
SERIALIZERS = {"_create", "canonical_json", "dump", "dumps", "model_dump_json", "write",
               "write_text", "write_bytes"}
DOCUMENT_COLUMNS = {"document", "snapshot", "frozen_library", "text"}


def sites(source):
    tree = ast.parse(source)
    aliases = {item.asname for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
               for item in node.names if item.asname and item.name in SERIALIZERS}
    for call in ast.walk(tree):
        if not isinstance(call, ast.Call):
            continue
        name = getattr(call.func, "attr", getattr(call.func, "id", ""))
        if name in SERIALIZERS or name in aliases or (name == "values" and DOCUMENT_COLUMNS.intersection(
            item.arg for item in call.keywords
        )):
            yield ast.dump(call, include_attributes=False)


def inventory():
    for directory in SOURCE_DIRS:
        for path in sorted((ROOT / directory).rglob("*.py")):
            counts = Counter(sites(path.read_text(encoding="utf-8")))
            if counts:
                digest = hashlib.sha256(json.dumps(sorted(counts.items())).encode("utf-8")).hexdigest()
                yield path.relative_to(ROOT).as_posix(), [counts.total(), digest]


def test_document_serialization_sites_match_the_audited_inventory():
    expected = json.loads(INVENTORY.read_text(encoding="utf-8"))
    actual = dict(inventory())
    changed = {name for name in expected.keys() | actual.keys() if expected.get(name) != actual.get(name)}
    assert not changed, ("Check document writers against the canonical board and asset version serialization "
                         f"boundaries before updating the inventory: {sorted(changed)}")


@pytest.mark.parametrize(("source", "expected"), [
    ("def save(value, outfile):\n    outfile.write_bytes(value.model_dump_json().encode())", 2),
    ("def save(value, outfile):\n    payload = {'layout': value.layout}\n"
     "    outfile.write_text(json.dumps(payload))", 2),
    ("def save(value, conn):\n    conn.execute(table.insert().values(document=value))", 1),
])
def test_a_direct_serializer_with_a_generic_argument_adds_inventory_sites(source, expected):
    assert len(list(sites(source))) == expected
