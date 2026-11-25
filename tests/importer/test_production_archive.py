"""The admin entry point refuses invalid archives before opening a destination."""

import hashlib
import json

import pytest

from haynes_studio.api.key_admin import run
from haynes_studio.canonical import to_document
from haynes_studio.delivery.model import Delivery
from haynes_studio.delivery.validate import validate_delivery
from haynes_studio.importer.production_archive import verify_archive
from haynes_studio.library import Library
from haynes_studio.library.resolve import resolve
from haynes_studio.library.validate import validate_asset_version
from haynes_studio.store import blob_locator, canonical_json
from tests.build_story.fixtures import example
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


def archive_set(fixture, occlusion):
    plate = still_version(200, "b" * 64, kind="set")
    plate["scope"] = {"production_id": fixture.production_id}
    plate["content"].update(width=64, height=48,
                            locator=blob_locator(fixture.production_id, "b" * 64, "image/png"))
    return {**plate, "occlusion": occlusion}


def rewrite_snapshot(fixture):
    data = canonical_json(fixture.snapshot)
    digest = hashlib.sha256(data).hexdigest()
    fixture.run["snapshot"].update(sha256=digest,
                                   locator=blob_locator(fixture.production_id, digest, "application/json"))
    (fixture.root / "snapshot.json").write_bytes(data)
    (fixture.root / "run.json").write_bytes(canonical_json(fixture.run))


@pytest.mark.parametrize(("declaration", "error"), [
    ("board", "snapshot_invalid snapshot.json /story/boards/0/layout/check_poses occlusion.check_unavailable"),
    ("set", "asset_versions asset-versions.json /1/occlusion occlusion.check_unavailable"),
    ("reversed-box", "asset_versions asset-versions.json /1/occlusion/foreground/0/hint/xyxy schema.invalid"),
    ("outside-point", "asset_versions asset-versions.json /1/occlusion/focal_props/0/hint/xy schema.invalid"),
    ("malformed", "asset_versions asset-versions.json /1 schema.invalid"),
])
def test_archive_checks_visibility_declarations_before_publication(tmp_path, monkeypatch, capsys,
                                                                 declaration, error):
    fixture = make_archive(tmp_path / "job")
    if declaration == "board":
        fixture.snapshot["story"]["boards"][0]["layout"]["check_poses"] = [{"key": "still", "frame": 0}]
        rewrite_snapshot(fixture)
    else:
        block = {"foreground": [{"key": "shelf", "label": None, "layer_order": 10}], "focal_props": []}
        plate = archive_set(fixture, block)
        versions = [fixture.asset, [] if declaration == "malformed" else plate]
        if declaration == "reversed-box":
            block["foreground"][0]["hint"] = {"kind": "box", "xyxy": [20, 0, 10, 10]}
        if declaration == "outside-point":
            prop = still_version(201, "c" * 64)
            prop.update(kind="prop", scope=plate["scope"])
            prop["content"].update(width=32, height=32,
                                   locator=blob_locator(fixture.production_id, "c" * 64, "image/png"))
            versions.append(prop)
            block["focal_props"] = [{
                "key": "menu", "label": "menu", "depth": "separate", "layer_order": 20,
                "source_asset_version_id": prop["id"], "hint": {"kind": "point", "xy": [32, 10]},
            }]
        (fixture.root / "asset-versions.json").write_bytes(canonical_json(versions))
    fixture.receipt.write_bytes(canonical_json(fixture.files()))

    monkeypatch.setenv("STUDIO_MIGRATION_DATABASE_URL", "unused dsn")
    dest = tmp_path / "empty-store"
    monkeypatch.setenv("STUDIO_STORE_ROOT", str(dest))
    assert run(fixture.args()) == 1
    result = capsys.readouterr()
    assert result.out == "" and result.err.strip() == f"import_production.{error}"
    assert not dest.exists()


def test_archive_empty_declarations_are_omitted_in_editable_view(tmp_path):
    fixture = make_archive(tmp_path / "job")
    fixture.snapshot["story"]["boards"][0]["layout"]["check_poses"] = []
    plate = archive_set(fixture, None)
    fixture.snapshot["resolved_asset_versions"].append({
        "id": plate["id"], "kind": plate["kind"], "sha256": plate["content"]["sha256"],
    })
    rewrite_snapshot(fixture)
    (fixture.root / "asset-versions.json").write_bytes(canonical_json([fixture.asset, plate]))
    fixture.receipt.write_bytes(canonical_json(fixture.files()))

    with verify_archive(fixture.root, fixture.receipt, name=fixture.name, kind=KIND,
                        recovered=False) as archive:
        assert "check_poses" not in archive.story["boards"][0]["layout"]
        assert "occlusion" not in archive.versions[1]
        assert archive.snapshot["story"] == archive.story
        assert archive.snapshot_pin["sha256"] != fixture.run["snapshot"]["sha256"]
        assert archive.members["snapshot.json"].read() == canonical_json(fixture.snapshot)
