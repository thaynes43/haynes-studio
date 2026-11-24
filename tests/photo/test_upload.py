from __future__ import annotations

import hashlib
import io
from dataclasses import replace

import pytest
from PIL import Image, PngImagePlugin

from haynes_studio.canonical.model import Principal
from haynes_studio.errors import ContractError
from haynes_studio.library import Library
from haynes_studio.photo import ExternalProvenance, can_select_photo, import_photo, plan_photo, record_photo
from haynes_studio.photo.validation import MAX_UPLOAD_BYTES
from tests.photo.conftest import BY, NOW, PNG


def declaration(ids=()) -> ExternalProvenance:
    return ExternalProvenance("Declared image model", "An external prompt for the same board.",
                              "example-session", "example-harness", ids, False)


def upload_bytes(tmp_path, fmt: str, *, dimensions=(24, 12), metadata=True) -> bytes:
    image = Image.new("RGB", dimensions, "red")
    attributes = {}
    if metadata and fmt == "PNG":
        info = PngImagePlugin.PngInfo()
        info.add_text("Comment", "synthetic private metadata")
        attributes["pnginfo"] = info
    if metadata and fmt in ("JPEG", "WEBP"):
        exif = Image.Exif()
        exif[274] = 6  # EXIF orientation: rotate the displayed photo 90 degrees.
        exif[315] = "synthetic private metadata"
        attributes["exif"] = exif
    path = tmp_path / f"upload.{fmt.lower()}"
    image.save(path, format=fmt, **attributes)
    return path.read_bytes()


@pytest.mark.parametrize(("fmt", "media_type", "size"), [
    ("PNG", PNG, (24, 12)), ("JPEG", "image/jpeg", (12, 24)), ("WEBP", "image/webp", (12, 24)),
])
def test_upload_validates_and_records_clean_png_with_provenance(world, tmp_path, fmt, media_type, size):
    story, board, library, ids, _, publish = world
    plan = plan_photo(story, board, library)
    raw = upload_bytes(tmp_path, fmt)
    declared = replace(declaration((ids[2],)), upload_sha256=hashlib.sha256(raw).hexdigest())
    prepared = import_photo(plan, library, data=raw, media_type=media_type, declared=declared, by=BY)
    result = record_photo(prepared, library, publish=publish, by=BY, now=NOW)
    document = result.library.document(result.version.id)
    assert document["kind"] == "photo" and document["state"] == "board"
    assert document["content"]["media_type"] == PNG
    assert document["content"]["sha256"] == hashlib.sha256(prepared.image.png).hexdigest()
    assert document["content"]["sha256"] != declared.upload_sha256
    with Image.open(io.BytesIO(prepared.image.png)) as image:
        assert image.size == size and image.mode == "RGB"
        assert not image.info
    provenance = document["provenance"]
    generator = provenance["generator"]
    assert provenance["origin"] == "uploaded"
    assert provenance["external"] == {
        "externally_generated": True, "paid_api": False, "declared_by": "agent",
        "server_computed_sha256": True,
        "agent": {"kind": "agent", "key_id": BY.key_id,
                  "session": declared.session, "harness": declared.harness},
    }
    assert generator["model"] == declared.model and generator["prompt"] == declared.prompt
    assert generator["source_asset_version_ids"] == [ids[2]]
    assert generator["params"]["upload_sha256"] == declared.upload_sha256
    assert generator["params"]["upload_media_type"] == media_type
    assert generator["params"]["source_assets"] == [
        {"version_id": ids[2], "sha256": library.version(ids[2]).content.sha256}
    ]
    assert can_select_photo(result.version, plan, story, board, result.library)
    revised = replace(board, photo=replace(board.photo, prompt="New draft prompt"))
    assert not can_select_photo(result.version, plan, story, revised, result.library)


def test_duplicate_bytes_keep_independent_version_records(world, tmp_path):
    story, board, library, _, _, publish = world
    plan = plan_photo(story, board, library)
    raw = upload_bytes(tmp_path, "PNG")
    original = import_photo(plan, library, data=raw, media_type=PNG, declared=declaration(), by=BY)
    first = record_photo(original, library, publish=publish, by=BY, now=NOW)
    prior = first.library.document(first.version.id)
    another = import_photo(plan, first.library, data=raw, media_type=PNG,
                           declared=replace(declaration(), prompt="Another actual prompt."), by=BY)
    second = record_photo(another, first.library, publish=publish, by=BY, now=NOW)
    assert second.version.asset_id == first.version.asset_id
    assert second.version.content == first.version.content
    assert (first.version.number, second.version.number) == (1, 2)
    assert second.version.id != first.version.id
    assert second.library.document(first.version.id) == prior
    assert second.version.provenance["generator"]["prompt"] == "Another actual prompt."
    assert library.get(first.version.id) is None


@pytest.mark.parametrize(("changes", "rule"), [
    ({"model": " "}, "prov.external_incomplete"),
    ({"prompt": ""}, "prov.external_incomplete"),
    ({"harness": "bad\nname"}, "prov.external_incomplete"),
    ({"session": ""}, "prov.external_incomplete"),
    ({"paid_api": True}, "prov.external_incomplete"),
    ({"source_asset_version_ids": ["bad-id"]}, "prov.external_incomplete"),
    ({"source_asset_version_ids": ["asv_00000000000000000000000000"]}, "ref.unknown"),
    ({"upload_sha256": "wrong"}, "photo.hash_mismatch"),
    ({"upload_sha256": "0" * 64}, "photo.hash_mismatch"),
])
def test_invalid_provenance_is_refused(world, tmp_path, changes, rule):
    story, board, library, _, _, _ = world
    plan = plan_photo(story, board, library)
    with pytest.raises(ContractError) as found:
        import_photo(plan, library, data=upload_bytes(tmp_path, "PNG"), media_type=PNG,
                     declared=replace(declaration(), **changes), by=BY)
    assert found.value.violations[0].rule == rule


def test_invalid_bytes_mime_and_animation_are_refused(world, tmp_path):
    story, board, library, _, _, _ = world
    plan = plan_photo(story, board, library)
    data = upload_bytes(tmp_path, "PNG")
    animation = io.BytesIO()
    first = Image.new("RGB", (4, 4), "red")
    first.save(animation, format="PNG", save_all=True,
               append_images=[Image.new("RGB", (4, 4), "blue")])
    for body, mime in [(b"invalid", PNG), (data, "image/jpeg"), (data, "image/gif"),
                       (data[:-25], PNG), (animation.getvalue(), PNG)]:
        with pytest.raises(ContractError, match="photo.image_invalid"):
            import_photo(plan, library, data=body, media_type=mime, declared=declaration(), by=BY)


def test_length_and_dimensions_are_refused_before_decode(world, tmp_path, monkeypatch):
    story, board, library, _, _, _ = world
    plan = plan_photo(story, board, library)
    wide = upload_bytes(tmp_path, "PNG", dimensions=(4097, 1))

    def unexpected_decode(*_):
        pytest.fail("oversized input was decoded")

    monkeypatch.setattr(PngImagePlugin.PngImageFile, "load", unexpected_decode)
    for data in (wide, b"x" * (MAX_UPLOAD_BYTES + 1)):
        with pytest.raises(ContractError) as found:
            import_photo(plan, library, data=data, media_type=PNG, declared=declaration(), by=BY)
        assert found.value.violations[0].rule == "photo.too_large"
        assert found.value.violations[0].status == "too_large"


def test_upload_identity_and_cross_scope_sources_are_rejected(world, tmp_path):
    story, board, library, ids, _, publish = world
    plan = plan_photo(story, board, library)
    raw = upload_bytes(tmp_path, "PNG")
    with pytest.raises(ContractError, match="prov.external_incomplete"):
        import_photo(plan, library, data=raw, media_type=PNG, declared=declaration(),
                     by=Principal("worker", worker_id="worker"))
    foreign_docs = library.documents()
    foreign = next(doc for doc in foreign_docs if doc["id"] == ids[2])
    foreign["scope"]["production_id"] = "prd_00000000000000000000000001"
    foreign["content"]["locator"] = foreign["content"]["locator"].replace(
        story.production_id, foreign["scope"]["production_id"])
    with pytest.raises(ContractError, match="asset.scope_mismatch"):
        import_photo(plan, Library.from_version_documents(foreign_docs), data=raw, media_type=PNG,
                     declared=declaration((ids[2],)), by=BY)

    prepared = import_photo(plan, library, data=raw, media_type=PNG, declared=declaration(), by=BY)
    with pytest.raises(ContractError, match="prov.external_incomplete"):
        record_photo(prepared, library, publish=publish, now=NOW,
                     by=Principal("agent", key_id="key_00000000000000000000000001"))


@pytest.mark.parametrize(("returned", "rule"), [
    (lambda data, mime: ("0" * 64, ""), "store.hash_mismatch"),
    (lambda data, mime: (hashlib.sha256(data).hexdigest(), "wrong"), "store.locator_invalid"),
])
def test_bad_store_acknowledgment_fails_the_record(world, tmp_path, returned, rule):
    story, board, library, _, _, _ = world
    prepared = import_photo(plan_photo(story, board, library), library,
                            data=upload_bytes(tmp_path, "PNG"), media_type=PNG,
                            declared=declaration(), by=BY)
    before = library.documents()
    with pytest.raises(ContractError, match=rule):
        record_photo(prepared, library, publish=returned, by=BY, now=NOW)
    assert library.documents() == before
