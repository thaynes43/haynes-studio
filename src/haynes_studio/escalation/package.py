"""The immutable request sent to a responder, independent of its lifecycle."""

from datetime import timedelta
from hashlib import sha256

from haynes_studio.canonical.ids import ulid
from haynes_studio.db.runs import timestamp
from haynes_studio.schemas import validator_for
from haynes_studio.store import canonical_json

SCHEMA = "studio.escalation/v1"
SCHEMA_FILE = "studio.escalation.v1.schema.json"
RESPONDER_PREFIX = "key_0000000000"
VALID_FOR = timedelta(hours=24)
MAX_SECONDS = 15 * 60
READ_ACTIONS = ("get_escalation_check", "get_media", "studio_get_story_summary")
BOARD_ACTIONS = ("studio_get_board", "studio_patch_board", "studio_queue_run")
PATCH_FIELDS = ("layout", "seeds", "timing", "title")
FORBIDDEN_ACTIONS = (
    "go_live", "promotion", "deletion", "other_story", "other_production", "check_override", "cancel_run",
)


def digest(document):
    return sha256(canonical_json(document)).hexdigest()


def deduplication_id(run_id, check, board_id, input_sha256, artifact_sha256):
    return digest([SCHEMA, run_id, check, board_id, input_sha256, artifact_sha256])


def responder_key_id(package_id):
    # Reserve a public identifier in the epoch-zero ULID range. There is no
    # credential or grant behind it until a separate provisioning operation.
    return "key_" + ulid(0, int(package_id[:20], 16))


def make_package(run, failure_id, board_id, check, input_sha256, artifact_sha256, records, now):
    boards = [] if board_id is None else [board_id]
    document = {
        "schema": SCHEMA,
        "deduplication_id": failure_id,
        "production_id": run["production_id"],
        "story_id": run["story_id"],
        "run_id": run["id"],
        "snapshot_sha256": run["document"]["snapshot"]["sha256"],
        "board_ids": boards,
        "failure": {
            "check": check,
            "input_sha256": input_sha256,
            "results": [{"operation": "get_escalation_check", "record_sha256": record}
                        for record in records],
        },
        "artifacts": [{"operation": "get_media", "sha256": artifact_sha256}],
        "allowed_actions": list(READ_ACTIONS + (BOARD_ACTIONS if boards else ())),
        "patch_fields": list(PATCH_FIELDS if boards else ()),
        "forbidden_actions": list(FORBIDDEN_ACTIONS),
        "usage_cap": {"seconds": MAX_SECONDS, "queued_runs": len(boards)},
        "expires_at": timestamp(now + VALID_FOR),
        "responder_key": {"id": responder_key_id(failure_id), "production_id": run["production_id"],
                          "scopes": ["read", "draft:write", "runs:queue"] if boards else ["read"]},
        "callback": {"method": "POST", "operation": "report_escalation",
                     "idempotency_header": "Idempotency-Key",
                     "outcomes": ["done", "failed", "escalate"]},
    }
    validator_for(SCHEMA_FILE).validate(document)
    encoded = canonical_json(document)
    return document, encoded, sha256(encoded).hexdigest()
