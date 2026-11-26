"""The admin entry point refuses invalid archives before opening a destination."""

import json
from hashlib import sha256

import pytest

from haynes_studio.api.key_admin import run
from haynes_studio.canonical import to_document
from haynes_studio.delivery.model import Delivery
from haynes_studio.delivery.validate import validate_delivery
from haynes_studio.importer.production_archive import verify_archive
from haynes_studio.library import Library
from haynes_studio.library.resolve import resolve
from haynes_studio.library.validate import validate_asset_version
from haynes_studio.store import LocalStore, blob_locator, canonical_json
from tests.build_story.fixtures import World, example, ident
from tests.importer.production_fixture import FRAMES, KIND, make_archive
from tests.motion.fixtures import still_version


@pytest.mark.parametrize(("damage", "error"), [
    ("proxy", "archive_hash proxy.mp4"),
    ("provenance", "archive_missing wan-service-run.json"),
    ("extra", "archive_extra"),
    ("member_link", "archive_member proxy.mp4"),
    ("directory_link", "archive_directory"),
    ("parent_link", "archive_directory"),
])
def test_archive_refusals(tmp_path, monkeypatch, capsys, damage, error):
    fixture = make_archive(tmp_path / "job")
    dest = tmp_path / "empty-store"
    dest.mkdir()
    proxy = fixture.root / "proxy.mp4"
    if damage == "proxy":
        data = proxy.read_bytes()
        proxy.write_bytes(data[:-1] + bytes([data[-1] ^ 1]))
    elif damage == "provenance":
        (fixture.root / "wan-service-run.json").unlink()
    elif damage == "extra":
        (fixture.root / "third.mp4").write_bytes(proxy.read_bytes())
    elif damage == "member_link":
        target = tmp_path / "original"
        proxy.rename(target)
        proxy.symlink_to(target)
    elif damage == "directory_link":
        link = tmp_path / "archive-link"
        link.symlink_to(fixture.root, target_is_directory=True)
        fixture.root = link
    elif damage == "parent_link":
        link = tmp_path / "job-link"
        link.symlink_to(fixture.root.parent, target_is_directory=True)
        fixture.root = link / fixture.root.name

    monkeypatch.setenv("STUDIO_MIGRATION_DATABASE_URL", "unused dsn")
    monkeypatch.setenv("STUDIO_STORE_ROOT", str(dest))
    assert run(fixture.args()) == 1
    result = capsys.readouterr()
    assert result.out == ""
    assert result.err.strip() == f"import_production.{error}"
    assert list(dest.iterdir()) == []


@pytest.mark.parametrize(("damage", "error"), [
    ("tampered", "archive_hash"),
    ("run_id", "recovered_ledger"),
    ("proxy_hash", "recovered_ledger"),
])
def test_recovered_ledger_refused_before_destination(tmp_path, monkeypatch, capsys, damage, error):
    fixture = make_archive(tmp_path / "job", recovered=True)
    path = fixture.root / "ledger.json"
    data = path.read_bytes()
    ledger = json.loads(data)
    if damage == "tampered":
        path.write_bytes(data.replace(b"studio-private-view", b"studio-private-fake"))
        assert len(path.read_bytes()) == len(data) and path.read_bytes() != data
    else:
        if damage == "run_id":
            ledger["provenance"]["run_id"] = ledger["provenance"]["production_id"]
        else:
            ledger["sha256"] = "0" * 64
        path.write_text(json.dumps(ledger))
        fixture.receipt.write_text(json.dumps(fixture.files()))
    monkeypatch.setenv("STUDIO_MIGRATION_DATABASE_URL", "unused dsn")
    dest = tmp_path / "store"
    monkeypatch.setenv("STUDIO_STORE_ROOT", str(dest))
    assert run(fixture.args()) == 1
    assert capsys.readouterr().err.strip() == f"import_production.{error} ledger.json"
    assert not dest.exists()


def test_recovered_delivery_verification_round_trip(tmp_path):
    fixture = make_archive(tmp_path / "job", recovered=True)
    with verify_archive(fixture.root, fixture.receipt, name=fixture.name, kind=KIND,
                        recovered=True) as archive:
        delivery = archive.delivery
    verification = delivery["verification"]
    assert "decoded_frames" not in verification
    assert to_document(Delivery.from_document(delivery)) == delivery
    metadata = verification["recovered_container_metadata_only"]
    assert metadata["frames"] == FRAMES
    verification["decoded_frames"] = FRAMES
    assert validate_delivery(delivery)
    verification.pop("decoded_frames")
    legacy = example("delivery-legacy-r4.json")
    legacy_verification = legacy["verification"]
    legacy_verification.pop("decoded_frames")
    legacy_verification["recovered_container_metadata_only"] = {
        **metadata, "frames": legacy["master"]["frames"],
    }
    assert [v.path for v in validate_delivery(legacy)] == ["/verification"]
    metadata["frames"] += 1
    assert [v.path for v in validate_delivery(delivery)] == [
        "/verification/recovered_container_metadata_only/frames",
    ]
    verification.pop("recovered_container_metadata_only")
    assert [v.path for v in validate_delivery(delivery)] == ["/verification"]


def test_canonical_archive_refuses_recovery_metadata(tmp_path, monkeypatch, capsys):
    fixture = make_archive(tmp_path / "job")
    path = fixture.root / "delivery.json"
    delivery = json.loads(path.read_bytes())
    verification = delivery["verification"]
    verification.pop("decoded_frames")
    verification["recovered_container_metadata_only"] = {
        "frames": FRAMES, "ledger_id": "a" * 32, "ledger_sha256": "b" * 64,
    }
    path.write_text(json.dumps(delivery))
    fixture.receipt.write_text(json.dumps(fixture.files()))
    monkeypatch.setenv("STUDIO_MIGRATION_DATABASE_URL", "unused dsn")
    monkeypatch.setenv("STUDIO_STORE_ROOT", str(tmp_path / "store"))
    assert run(fixture.args()) == 1
    assert capsys.readouterr().err.strip() == "import_production.delivery_invalid delivery.json"


def test_resolver_skips_byte_check_for_recorded_pin(tmp_path):
    fixture = make_archive(tmp_path / "job")
    assert [v.path for v in validate_asset_version({**fixture.asset, "recorded_without_media": False})] == [
        "/recorded_without_media",
    ]
    library = Library.from_version_documents([{**fixture.asset, "recorded_without_media": True}])
    result = resolve(fixture.snapshot["story"], library,
                     lambda *_: pytest.fail("a recorded pin must not probe the store"))
    assert result.complete
    assert result.version_ids() == {fixture.asset["id"]}


def test_legacy_archive_keeps_original_asset_bytes(tmp_path):
    fixture = make_archive(tmp_path / "job")
    fixture.asset["provenance"]["generator"]["params"] = {"cfg": 1.0}
    data = canonical_json([fixture.asset])
    (fixture.root / "asset-versions.json").write_bytes(data)
    fixture.receipt.write_bytes(canonical_json(fixture.files()))
    with verify_archive(fixture.root, fixture.receipt, name=fixture.name, kind=KIND,
                        recovered=False) as archive:
        assert canonical_json(archive.versions) == data


@pytest.mark.parametrize(("change", "code"), [
    ("valid", None),
    ("missing_pin", "occlusion.mask_missing"),
    ("wrong_hash", "occlusion.mask_stale"),
    ("wrong_snapshot_hash", "occlusion.mask_stale"),
    ("pixel_limit", "occlusion.mask_invalid"),
    ("byte_limit", "occlusion.mask_invalid"),
    ("noncanonical", "occlusion.noncanonical"),
])
def test_archive_requires_declared_mask_ids_and_hashes_in_the_snapshot(tmp_path, monkeypatch, capsys, change, code):
    fixture = make_archive(tmp_path / "job")
    set_doc = still_version(73, "c" * 64, kind="set")
    mask = still_version(72, "b" * 64)
    cast = still_version(74, "d" * 64)
    world = World(tmp_path, LocalStore(tmp_path))
    world.voice(ident("asv", 75), 75, "af_heart")
    [voice] = world.docs
    mask.update(kind="prop", capabilities=["mask"], attributes={})
    width, height = (4097, 4096) if change == "pixel_limit" else (64, 32)
    for item in (set_doc, mask, cast):
        item["scope"] = {"production_id": fixture.production_id}
        item["content"].update(width=width, height=height, locator=blob_locator(
            fixture.production_id, item["content"]["sha256"], "image/png",
        ))
    if change == "byte_limit":
        mask["content"]["bytes"] = 20 * 1024 * 1024 + 1
    set_doc["occlusion"] = {"foreground": [{
        "key": "table", "layer_order": 15,
        "mask": {"version_id": mask["id"], "sha256": "a" * 64 if change == "wrong_hash" else "b" * 64,
                 "still_sha256": "c" * 64, "width": width, "height": height},
    }]}
    if change == "noncanonical":
        set_doc["occlusion"] = {"foreground": None}
    story = fixture.snapshot["story"]
    story["set"] = {"asset_version_id": set_doc["id"], "motion_asset_version_id": None,
                    "foreground_edge_px": None, "foreground_feather_px": None, "legacy_fire": None}
    story["cast"] = [{"slot": "a", "name": "Synthetic cast", "voice_version_id": voice["id"]}]
    board = story["boards"][0]
    board.update(method={"layer": "layered", "motion": "i2v"}, seeds={},
                 cast=[{"slot": "a", "asset_version_id": cast["id"]}])
    board["layout"]["foreground"] = True
    for item in (set_doc, mask, cast):
        if item is mask and change == "missing_pin":
            continue
        digest = "0" * 64 if item is mask and change == "wrong_snapshot_hash" else item["content"]["sha256"]
        fixture.snapshot["resolved_asset_versions"].append({
            "id": item["id"], "kind": item["kind"], "sha256": digest,
        })
    fixture.snapshot["resolved_asset_versions"].append({
        "id": voice["id"], "kind": "voice", "sha256": None,
        "definition_signature": world.library().pin(voice["id"]),
    })
    data = canonical_json(fixture.snapshot)
    digest = sha256(data).hexdigest()
    fixture.run["snapshot"].update(sha256=digest, locator=blob_locator(
        fixture.production_id, digest, "application/json",
    ))
    (fixture.root / "snapshot.json").write_bytes(data)
    (fixture.root / "run.json").write_bytes(canonical_json(fixture.run))
    versions = [fixture.asset, set_doc, mask, cast, voice]
    (fixture.root / "asset-versions.json").write_bytes(canonical_json(versions))
    fixture.receipt.write_bytes(canonical_json(fixture.files()))
    if code is None:
        with verify_archive(fixture.root, fixture.receipt, name=fixture.name, kind=KIND,
                            recovered=False) as archive:
            assert archive.versions == versions
        return
    dest = tmp_path / "empty-store"
    dest.mkdir()
    monkeypatch.setenv("STUDIO_MIGRATION_DATABASE_URL", "unused dsn")
    monkeypatch.setenv("STUDIO_STORE_ROOT", str(dest))
    assert run(fixture.args()) == 1
    result = capsys.readouterr()
    assert result.err.strip() == f"import_production.{code} asset-versions.json"
    assert list(dest.iterdir()) == []
