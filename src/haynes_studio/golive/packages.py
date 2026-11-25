"""Immutable private release packages and manual publication observations."""

import json
from hashlib import sha256
from math import gcd

import sqlalchemy as sa

from haynes_studio.api.errors import APIError
from haynes_studio.canonical.ids import Minter
from haynes_studio.db.problems import NotFound
from haynes_studio.db.runs import IdempotencyMismatch, actor_key, timestamp
from haynes_studio.db.schema import publications, release_packages
from haynes_studio.store import COLLISION, StoreError, blob_locator, canonical_json

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
    rows = conn.execute(sa.select(release_packages).where(release_packages.c.run_id == run_id)
                        .order_by(release_packages.c.target_id, release_packages.c.position.desc())).mappings()
    return [_load(row) for row in rows]


def by_digest(conn, run_id, digest):
    row = conn.execute(sa.select(release_packages).where(
        release_packages.c.run_id == run_id, release_packages.c.sha256 == digest,
    )).mappings().one_or_none()
    if row is None:
        raise NotFound
    return _load(row)


def _load(row):
    data = row["document_bytes"]
    try:
        if len(data) != row["bytes"] or sha256(data).hexdigest() != row["sha256"]:
            raise ValueError("Package bytes differ from the indexed length or hash")
        document = json.loads(data)
        if document["run_id"] != row["run_id"] or document["target"]["id"] != row["target_id"]:
            raise ValueError("Package run or target differs from the index")
    except (ValueError, TypeError, KeyError) as error:
        raise APIError(503, "release.package_record_changed",
                       "The database package failed its integrity check") from error
    return {**row, "document": document}


def preferred_for_targets(rows, current):
    """Pick current evidence when available, otherwise the newest version of each target."""
    preferred = {}
    for row in rows:
        target = row["target_id"]
        selected = preferred.get(target)
        if selected is None or (selected["document"]["release_checks"] != current
                                and row["document"]["release_checks"] == current):
            preferred[target] = row
    return preferred.values()


def download(store, production_id, row):
    locator = blob_locator(production_id, row["sha256"], MEDIA_TYPE)
    try:
        with store.open(locator) as source:
            data = source.read(row["bytes"])
            exact_size = len(data) == row["bytes"] and not source.read(1)
    except (OSError, StoreError) as error:
        raise APIError(503, "release.store_unavailable", "The package download copy is unavailable") from error
    if not exact_size or sha256(data).hexdigest() != row["sha256"]:
        raise APIError(503, "release.package_changed", "The package download copy failed its integrity check")
    return data


def _publish_copy(store, production_id, data, digest):
    try:
        store.publish(data, scope=production_id, media_type=MEDIA_TYPE, expected_sha256=digest)
    except StoreError as error:
        if error.code == COLLISION:
            raise APIError(503, "release.package_changed", "A different copy occupies the package path") from error
        raise APIError(503, "release.store_unavailable", "The package copy could not be stored") from error
    except OSError as error:
        raise APIError(503, "release.store_unavailable", "The package copy could not be stored") from error


def save(conn, store, production_id, document, existing):
    data = canonical_json(document)
    digest = sha256(data).hexdigest()
    receipt = {"sha256": digest, "bytes": len(data)}
    prior = next((item for item in existing if item["sha256"] == digest), None)
    if prior is not None:
        return restore_copy(store, production_id, prior), False
    _publish_copy(store, production_id, data, digest)
    conn.execute(release_packages.insert().values(
        **receipt, run_id=document["run_id"], target_id=document["target"]["id"], document_bytes=data,
    ))
    return receipt, True


def restore_copy(store, production_id, row):
    _publish_copy(store, production_id, row["document_bytes"], row["sha256"])
    return {"sha256": row["sha256"], "bytes": row["bytes"]}


def approval_for(conn, document):
    return records.exact_approval(conn, document["run_id"], document["run_snapshot_sha256"],
                                  document["delivery_id"], document["master"]["sha256"])


def require_current_delivery(document, evidence):
    delivery = evidence["delivery"]
    if (document["run_snapshot_sha256"] != evidence["provenance"]["snapshot_sha256"]
            or document["delivery_id"] != delivery["delivery_id"]
            or document["master"]["sha256"] != delivery["master_sha256"]):
        raise APIError(422, "approval.not_exact_run", "The package must match the current verified delivery")


def publication_for_target(conn, index):
    return conn.scalar(sa.select(publications.c.document).join(release_packages)
                       .where(release_packages.c.run_id == index["run_id"],
                              release_packages.c.target_id == index["target_id"]))


def publication_replay(conn, run_id, actor, key, digest, location, published_at):
    document = conn.scalar(sa.select(publications.c.document).where(
        publications.c.run_id == run_id, publications.c.idempotency_actor == actor_key(actor),
        publications.c.idempotency_key == key,
    ))
    if document is not None and (document["package_sha256"], document["location"], document["published_at"]) != (
        digest, location, timestamp(published_at) if published_at is not None else None,
    ):
        raise IdempotencyMismatch
    return document


def record_publication(conn, digest, approval, location, who, display_name, when, published_at, key):
    document = {
        "schema": "studio.publication/v1", "id": Minter().mint("pub"),
        "package_sha256": digest, "approval_id": approval["id"],
        "run_id": approval["run_id"], "master_sha256": approval["master_sha256"],
        "location": location, "recorded_by": who, "recorded_by_display_name": display_name,
        "recorded_at": timestamp(when), "published_at": timestamp(published_at) if published_at else None,
    }
    conn.execute(publications.insert().values(
        id=document["id"], package_sha256=digest, approval_id=approval["id"], run_id=approval["run_id"],
        idempotency_actor=actor_key(who), idempotency_key=key, document=document,
    ))
    return document
