"""Release evidence from immutable run metadata and the local licence register."""

from collections.abc import Mapping

from haynes_studio.api.errors import APIError
from haynes_studio.build.provenance import CREDIT_ROLES, ROLE_LABEL, Register, credits
from haynes_studio.delivery.model import LEGACY_WAN_LEDGER
from haynes_studio.delivery.validate import validate_delivery
from haynes_studio.store.layout import is_sha256

AI_DESCRIPTION_LINE = "This video was AI-generated."


def _refuse(code: str, message: str, *, evidence=None):
    raise APIError(422, f"approval.{code}", message, evidence=evidence)


def refuse_legacy(run: dict | None, delivery: dict | None) -> None:
    if ((run is not None and (run.get("legacy") is not None or run["status"] == "imported"))
            or (delivery is not None and delivery["store"]["adapter"] == LEGACY_WAN_LEDGER)):
        _refuse("legacy_run", "Imported legacy runs are ineligible for go-live")


def verify_delivery(run: dict, delivery: dict | None, master_sha256: str) -> dict:
    refuse_legacy(run, delivery)
    if run["status"] != "succeeded" or not run.get("finished_at"):
        _refuse("run_unfinished", "A successful, finished run is required")
    if (delivery is None or validate_delivery(delivery)
            or delivery["verification"]["sha256_verified"] is not True):
        _refuse("delivery_unverified", "The run requires a verified delivery")
    outputs = run.get("outputs") or {}
    if (delivery["id"] != run.get("delivery_id") or delivery["run_id"] != run["id"]
            or delivery["master"]["sha256"] != outputs.get("master_sha256")):
        _refuse("delivery_mismatch", "The delivery does not match the run's recorded master")
    if master_sha256 != delivery["master"]["sha256"]:
        _refuse("not_exact_run", "The supplied master hash must match the exact delivered run")
    if not is_sha256((run.get("snapshot") or {}).get("sha256")):
        _refuse("provenance_missing", "The run requires a pinned snapshot hash")
    return {"result": "pass", "run_status": run["status"], "finished_at": run["finished_at"],
            "delivery_id": delivery["id"], "master_sha256": master_sha256,
            "verification": delivery["verification"]}


def _licence_evidence(engines: list[dict], register: Register) -> dict:
    rows = []
    for engine in engines:
        key = engine["key"]
        entry = register.engines.get(key)
        licence = register.licence(key) if entry and entry["role"] == engine["role"] else None
        rows.append({"engine_key": key, "register_key": key if licence is not None else None,
                     "licence": licence})
        for model in engine["files"]:
            sha = model.get("sha256")
            entry = next((file for file in register.files
                          if file["engine"] == key and model["name"] in
                          (file["name"], file["key"], *file.get("recorded_as", []))
                          and (file.get("sha256") is None or file["sha256"] == sha)), None)
            rows.append({"engine_key": key, "file": model["name"], "sha256": sha,
                         "register_key": entry["key"] if entry else None,
                         "licence": entry["licence"] if entry else None})

    missing = False
    for row in rows:
        licence = row["licence"]
        row["state"] = ("missing" if licence is None else
                        "unknown" if licence["commercial_use"] == "unknown" else "recorded")
        missing |= licence is None
    evidence = {"result": "fail" if missing else "pass", "rows": rows}
    if missing:
        _refuse("licence_missing", "An engine or model file lacks a matching licence register row",
                evidence=evidence)
    return evidence


def _public_credits(engines: list[dict], public: dict) -> list[dict[str, str]]:
    # The build emits public credits with reported hardware only. The private engine
    # hardware field can also contain a deployment location from the register.
    recorded = {entry["engine_key"]: entry["text"] for entry in public.get("credits", [])}
    hardware = {}
    used = [engine for engine in engines if engine["role"] in CREDIT_ROLES]
    if not any(engine["role"] == "video" for engine in used):
        _refuse("provenance_missing", "The run must identify its video generator")
    for engine in used:
        key, name, reported = engine["key"], engine["name"], engine.get("hardware")
        if reported:
            expected = f"{ROLE_LABEL[engine['role']]}: {name} on {reported}"
            if recorded.get(key) == expected[:200]:
                hardware[key] = reported
    return credits(used, hardware)


def release_checks(run: dict, delivery_check: dict, platform_setting: bool, register: Register) -> dict:
    provenance = run.get("provenance")
    engines = provenance.get("engines") if isinstance(provenance, Mapping) else None
    if not engines:
        _refuse("provenance_missing", "The finished run requires recorded engine provenance")
    public = provenance.get("public") or {}
    if public.get("ai_generated") is not True or platform_setting is not True:
        _refuse("ai_label_missing", "Go-live requires the AI-generated label and synthetic-content setting")
    licences = _licence_evidence(engines, register)
    public_credits = _public_credits(engines, public)
    return {
        "delivery": delivery_check,
        "licences": licences,
        "ai_label": {"result": "pass", "platform_setting": True, "description_line": True,
                     "description": "\n".join([AI_DESCRIPTION_LINE,
                                                *(credit["text"] for credit in public_credits)])},
        "public_credits": public_credits,
        "external_inputs": [{"id": item["id"], "kind": item["kind"]}
                            for item in provenance.get("inputs_externally_generated", [])],
    }
