"""Immutable private release packages and manual publication observations."""

import json
from hashlib import sha256
from math import gcd

import sqlalchemy as sa

from haynes_studio.api.errors import APIError
from haynes_studio.canonical.ids import Minter
from haynes_studio.db.runs import timestamp
from haynes_studio.db.schema import publications, release_packages
from haynes_studio.store import StoreError, blob_locator, canonical_json

from . import records

PLATFORM = "youtube-shorts"
MEDIA_TYPE = "application/json"


def targets(snapshot):
    pin = (snapshot or {}).get("format_version")
    return [target for target in pin["recipe"]["targets"] if target["platform"] == PLATFORM] if pin else []


def build(run, snapshot, delivery, target_id, release_checks):
    pin = (snapshot or {}).get("format_version")
    if pin is None:
        raise APIError(422, "release.format_missing", "The run froze no format recipe")
    target = next((item for item in targets(snapshot) if item["id"] == target_id), None)
    if target is None:
        raise APIError(422, "release.target_unknown", "Choose a YouTube Shorts target in the frozen recipe",
                       path="/target_id")
    rules = target["rules"]
    master = delivery["master"]
    maximum = rules["max_length_ms"]
    length = {"frames": master["frames"], "fps": master["fps"], "max_length_ms": maximum}
    if maximum is None:
        raise APIError(422, "release.maximum_unset", "The frozen target must declare a platform maximum",
                       evidence=length)
    if master["frames"] * 1000 > master["fps"] * maximum:
        raise APIError(422, "release.over_length", "The master exceeds the frozen target's platform maximum",
                       evidence=length)
    width, height = master["width"], master["height"]
    factor = gcd(width, height)
    aspect = f"{width // factor}:{height // factor}"
    configured = rules["aspect"]
    if configured is not None:
        horizontal, vertical = map(int, configured.split(":"))
        if width * vertical != height * horizontal:
            raise APIError(422, "release.aspect_mismatch", "The master does not match the frozen target's aspect",
                           evidence={"master_aspect": aspect, "target_aspect": configured})
    return {
        "schema": "studio.release-package/v1",
        "run_id": run["id"], "run_snapshot_sha256": run["snapshot"]["sha256"],
        "delivery_id": delivery["id"], "format_version_id": pin["id"], "format_sha256": pin["sha256"],
        "master": {field: master[field] for field in ("sha256", "bytes", "media_type")},
        "target": target,
        "description": release_checks["ai_label"]["description"],
        "checklist": [
            "Turn on the synthetic-content setting.",
            f"Use the {configured or aspect} master.",
            f"Keep the video within the target maximum of {maximum} ms.",
        ],
        "release_checks": release_checks,
        "target_checks": {
            "length": {"result": "pass", **length},
            "aspect": {"result": "pass", "master_aspect": aspect, "target_aspect": configured},
        },
    }


def for_run(conn, run_id):
    return conn.execute(sa.select(release_packages).where(release_packages.c.run_id == run_id)
                        .order_by(release_packages.c.target_id)).mappings().all()


def load(store, production_id, row):
    locator = blob_locator(production_id, row["sha256"], MEDIA_TYPE)
    try:
        with store.open(locator) as source:
            data = source.read(row["bytes"] + 1)
        if len(data) == row["bytes"] and sha256(data).hexdigest() == row["sha256"]:
            return json.loads(data)
    except (OSError, StoreError) as error:
        raise APIError(503, "release.store_unavailable", "The package could not be read") from error
    raise APIError(503, "release.package_changed", "The stored package does not match its content reference")


def save(conn, store, production_id, document):
    data = canonical_json(document)
    digest = sha256(data).hexdigest()
    try:
        store.publish(data, scope=production_id, media_type=MEDIA_TYPE, expected_sha256=digest)
    except (OSError, StoreError) as error:
        raise APIError(503, "release.store_unavailable", "The package could not be stored") from error
    row = {"sha256": digest, "bytes": len(data), "run_id": document["run_id"],
           "target_id": document["target"]["id"]}
    conn.execute(release_packages.insert().values(**row))
    return row


def approval_for(conn, document):
    return records.exact_approval(conn, document["run_id"], document["run_snapshot_sha256"],
                                  document["delivery_id"], document["master"]["sha256"])


def saved_checks(conn, store, row, delivery):
    run = row["document"]
    approval = records.exact_approval(conn, run["id"], run["snapshot"]["sha256"],
                                      delivery["id"], delivery["master"]["sha256"], include_withdrawn=True)
    if approval is not None:
        return approval["release_checks"]
    for stored in for_run(conn, run["id"]):
        package = load(store, row["production_id"], stored)
        if (package["run_snapshot_sha256"], package["delivery_id"], package["master"]["sha256"]) == (
            run["snapshot"]["sha256"], delivery["id"], delivery["master"]["sha256"],
        ):
            return package["release_checks"]
    return None


def publication_for(conn, digest):
    return conn.scalar(sa.select(publications.c.document).where(publications.c.package_sha256 == digest))


def record_publication(conn, digest, approval, location, who, display_name, when, published_at):
    document = {
        "schema": "studio.publication/v1", "id": Minter().mint("pub"),
        "package_sha256": digest, "approval_id": approval["id"],
        "run_id": approval["run_id"], "master_sha256": approval["master_sha256"],
        "location": location, "recorded_by": who, "recorded_by_display_name": display_name,
        "recorded_at": timestamp(when), "published_at": timestamp(published_at) if published_at else None,
    }
    conn.execute(publications.insert().values(id=document["id"], package_sha256=digest,
                                             approval_id=approval["id"], document=document))
    return document
