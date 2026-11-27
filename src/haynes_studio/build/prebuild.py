"""The build's pre-build check and snapshot (contract section 8; story 406).

Everything a build needs to know before its first clip, read from the draft, the
library and the store and from nothing else:

1. **Facts** (story 405's :func:`~haynes_studio.voice.voice_facts`) with the current
   voice engine named, so a board voice signed with another engine is stale (VOICE-9).
2. **Resolution** of every asset version the story names (story 382's resolver), and
   the motion records of every layered board (story 457's resolver through story 426's
   :func:`~haynes_studio.layered.pin.pin_story`).
3. **The pre-build check**: story 379's :func:`~haynes_studio.stages.preflight` (the
   ``queue_run`` rules: voices, photos, methods; every reference resolved, every blob
   present and re-hashed; the cast entry's motion pin is a reference), then each board's
   adapter check: :func:`haynes_studio.wholeframe.check_board` for whole-frame boards and
   :func:`haynes_studio.layered.check_board` (with the board's motion, the frame size
   and the speech-to-video size) for layered ones. Each problem names its board.
4. **The snapshot** (``studio.run-snapshot/v1``): the story and its boards by value, no
   ``derived`` blocks, and every asset version the build reads pinned by hash, with no
   run ID or time, so the same draft gives the same canonical bytes.
"""

from __future__ import annotations

import copy
import hashlib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from haynes_studio.build.validate import SNAPSHOT_SCHEMA, validate_run_snapshot
from haynes_studio.cache.plan import LayeredMotion, Toolchain
from haynes_studio.canonical import Facts, Story, load_story
from haynes_studio.canonical.derive import board_clock
from haynes_studio.canonical.validate import WRITE
from haynes_studio.errors import WARNING, ContractError, Violation, blocking
from haynes_studio.formats.recipe import PIN_PATH, method_violation
from haynes_studio.jsonio import thaw
from haynes_studio.layered import check_board as layered_check
from haynes_studio.layered.errors import LayeredError
from haynes_studio.layered.foreground import (
    MASK_MISSING, MASK_STALE, SET_LOOP_SOURCE_UNKNOWN, PictureForeground, RoleMask,
    check_role_images, resolve_picture_roles,
)
from haynes_studio.layered.pin import pin_story
from haynes_studio.library import Library
from haynes_studio.library.model import AssetVersion, locator_for
from haynes_studio.library.resolve import Resolution, resolve
from haynes_studio.stages.preflight import (
    DEFINITION_ONLY,
    BlobRef,
    PreflightError,
    PreflightReport,
    Problem,
    ResolvedVersion,
    preflight,
)
from haynes_studio.store import PRESENT, Store, StoreError, canonical_json
from haynes_studio.photo.plan import photo_facts
from haynes_studio.voice import voice_facts
from haynes_studio.wholeframe import check_board as wholeframe_check

WAV = "audio/wav"


@dataclass(frozen=True)
class Prepared:
    """What the pre-build check found: the story model (boards embedded), its facts,
    what the library resolved, the layered boards' motion records and every problem."""

    document: Mapping[str, Any]
    library: Library
    story: Story | None
    facts: Facts
    resolution: Resolution
    resolved: Mapping[str, ResolvedVersion]
    motion: LayeredMotion | None
    report: PreflightReport
    format_version: Mapping[str, Any] | None = None
    foreground_roles: tuple[RoleMask, ...] = ()
    set_loop_source: AssetVersion | None = None

    @property
    def ok(self) -> bool:
        return self.report.ok and self.story is not None

    def ensure_buildable(self, source: str = "<story>") -> None:
        if not self.ok:
            raise PreflightError(source, self.report)


def draft_document(story: Mapping[str, Any]) -> dict[str, Any]:
    """The story and its boards as a client writes them: no ``derived`` blocks."""
    out = copy.deepcopy(dict(story))
    out.pop("derived", None)
    out["boards"] = [{k: v for k, v in board.items() if k != "derived"}
                     for board in out.get("boards") or []]
    return out


def resolved_versions(resolution: Resolution, library: Library,
                      production_id: str) -> dict[str, ResolvedVersion]:
    """The blobs a build reads of each resolved version: a voice reads none; a board
    voice reads its track and takes; any other kind its content."""
    out: dict[str, ResolvedVersion] = {}
    for item in resolution.resolved:
        if item.version_id in out:
            continue
        version = library.version(item.version_id)
        if version.recorded_without_media:
            out[item.version_id] = ResolvedVersion(recorded_without_media=True)
        elif item.kind == "voice":
            out[item.version_id] = DEFINITION_ONLY
        elif item.kind == "board_voice":
            voice = version.voice
            blobs = []
            if voice is not None and voice.track is not None:
                blobs.append(BlobRef(voice.track.sha256, voice.track.locator))
            for take in voice.takes if voice is not None else ():
                blobs.append(BlobRef(take.sha256, locator_for(take.sha256, WAV, production_id)))
            out[item.version_id] = ResolvedVersion(tuple(dict.fromkeys(blobs)))
        elif item.sha256 is not None and item.locator is not None:
            out[item.version_id] = ResolvedVersion.of(item.sha256, item.locator)
    return out


def _adapter_problems(story: Story, *, facts: Facts, motion: LayeredMotion | None,
                      toolchain: Toolchain, frame_size: tuple[int, int]) -> list[Problem]:
    """Each board's adapter check, located like the pre-build check's problems."""
    found = []
    s2v_size = tuple(thaw(toolchain.s2v_profile).get("size", ()))
    i2v_fps = thaw(toolchain.i2v_profile).get("source_fps", 24)
    for index, board in enumerate(story.boards or ()):
        if board.method.layer == "whole_frame":
            clock = board_clock(board, facts)
            violations = wholeframe_check(board, frames=None if clock is None else clock.frames,
                                          source_fps=i2v_fps, clip_frames=toolchain.i2v_clip_frames)
        else:
            violations = layered_check(story, board, motion=None if motion is None else
                                       motion.boards.get(board.id), frame_size=frame_size,
                                       s2v_size=s2v_size if len(s2v_size) == 2 else None)
        for violation in violations:
            path = violation.path
            if path.startswith("/boards/"):  # the motion resolver's pointers name the board
                path = "/" + path.split("/", 3)[3] if path.count("/") > 2 else ""
            if path.startswith("/set"):  # the story's set: a story field, on this board
                story_path = path
            else:
                story_path = f"/boards/{index}{path}"
            found.append(Problem(
                violation.rule, violation.status, story_path, violation.message,
                board_id=board.id, board_number=board.number,
                legacy_shot=board.origin.legacy_shot if board.origin else None, field=path))
    return found


def _metadata_present(_locator, _sha):
    # Resolution during queueing pins the declaration. Full preflight checks bytes.
    return PRESENT


def _foreground_checks(story: Story, library: Library, motion: LayeredMotion,
                       store: Store | None) -> tuple[PictureForeground, list[Problem]]:
    if story.set is None:
        return PictureForeground(), []
    version = library.get(story.set.asset_version_id)

    foreground = PictureForeground()
    problems = []
    for index, board in enumerate(story.boards or (None,)):
        board_motion = motion.boards.get(board.id) if board is not None else None
        loop_id = None
        if board_motion is not None:
            loop_id = (story.set.motion_asset_version_id if board_motion.set is None
                       else board_motion.set.version_id)
        try:
            picture = resolve_picture_roles(version, board, library, production_id=story.production_id,
                                            loop_version_id=loop_id)
            if picture.roles or picture.loop_source is not None:
                foreground = picture
        except LayeredError as error:
            field = error.where
            if board is None or field.startswith("/set/occlusion/foreground/"):
                return PictureForeground(), [Problem(error.code, error.status, field, error.message, field=field)]
            path = field if field.startswith("/set/") else f"/boards/{index}{field}"
            problems.append(Problem(error.code, error.status, path, error.message, field=field,
                                    board_id=board.id, board_number=board.number,
                                    legacy_shot=board.origin.legacy_shot if board.origin else None))
    if foreground.roles and store is not None and not problems:
        try:
            check_role_images(version.content, foreground.roles, store)
        except (LayeredError, StoreError) as error:
            field = getattr(error, "where", "") or ""
            if not field.startswith("/set/"):
                field = "/set/occlusion"
            problems.append(Problem(error.code, getattr(error, "status", "invalid"),
                                    field, error.message, field=field))
    return foreground, problems


def _set_source_pin(version: AssetVersion) -> dict[str, str]:
    return {"id": version.id, "kind": version.kind, "sha256": version.content.sha256}


def require_frozen_roles(snapshot: Mapping[str, Any], library: Library, *,
                         store: Store | None = None) -> PictureForeground:
    """Check the set, loop source and each mask against the frozen pins."""
    document = snapshot["story"]
    setting = document.get("set") or {}
    selected = setting.get("asset_version_id")
    version = library.get(selected)
    if selected is not None and version is None:
        raise ContractError("<run snapshot>", [Violation(
            "ref.unknown", "/set/asset_version_id", "The selected set version is absent from the frozen library",
        )])
    declared = version.occlusion if version is not None else None
    if (declared is None and setting.get("motion_asset_version_id") is None
            and (selected is None or not any(v.has("set_loop") for v in library.versions.values()))):
        return PictureForeground()
    problems = blocking(validate_run_snapshot(snapshot, context=WRITE))
    if problems:
        raise ContractError("<run snapshot>", problems)
    pins = {pin["id"]: pin for pin in snapshot["resolved_asset_versions"]}
    if declared is not None:
        if pins[version.id].get("sha256") != version.content.sha256:
            problems.append(Violation(MASK_STALE, "/resolved_asset_versions",
                                      "The snapshot set hash differs from the declared set still"))
        for role in declared["foreground"]:
            if role["mask"]["version_id"] not in pins:
                problems.append(Violation(MASK_MISSING, "/resolved_asset_versions",
                                          "The snapshot must pin each declared role mask"))
    if problems:
        raise ContractError("<run snapshot>", problems)

    story = Story.from_document(document)
    motion = pin_story(document, library, _metadata_present)
    foreground, issues = _foreground_checks(story, library, motion, store)
    for role in foreground.roles:
        if pins[role.version_id] != role.snapshot_entry():
            problems.append(Violation(MASK_STALE, "/resolved_asset_versions",
                                      "The snapshot must pin the resolved role mask version"))
    source = foreground.loop_source
    if source is not None and pins.get(source.id) != _set_source_pin(source):
        problems.append(Violation(SET_LOOP_SOURCE_UNKNOWN, "/resolved_asset_versions",
                                  "The snapshot must pin the set loop's source version and still hash"))
    problems.extend(Violation(p.rule, p.path, p.message, p.status) for p in issues)
    if problems:
        raise ContractError("<run snapshot>", problems)
    return foreground


def prepare(document: Mapping[str, Any], *, library: Library, store: Store | None,
            toolchain: Toolchain, frame_size: tuple[int, int], current_engine: str,
            jobs: Iterable[Any] = (), check_photo_currency: bool = False,
            format_version: Mapping[str, Any] | None = None, mask_store: Store | None = None) -> Prepared:
    """Run the pre-build check of a draft story (boards embedded). Never raises for a
    story that cannot be built: every problem is in ``report``. With no store,
    resolve declared content identities and require the worker to verify the bytes."""
    document = draft_document(document)
    facts = voice_facts(library, document, jobs, current_engine=current_engine)
    verify = store.verify if store is not None else _metadata_present
    resolution = resolve(document, library, lambda locator, sha: verify(locator, sha) == PRESENT)
    production = document.get("production_id")
    resolved = resolved_versions(resolution, library, production) if isinstance(production, str) else {}
    try:
        story = load_story(document, context=WRITE, source="<story>")
    except Exception as error:  # a draft that breaks a write rule: the check lists it
        story = None
        problems = tuple(Problem(v.rule, v.status, v.path, v.message, field=v.path)
                         for v in getattr(error, "violations", ()))
        return Prepared(document, library, None, facts, resolution, resolved, None, PreflightReport(
            problems or (Problem("schema.invalid", "invalid", "", str(error)),)))
    if check_photo_currency:
        facts = facts.merged(photo_facts(story, library))
    report = preflight(story, facts=facts, resolved=resolved, store=store)
    problems = list(report.problems)
    if story.format_version_id is not None:
        if format_version is None or format_version["id"] != story.format_version_id:
            problems.append(Problem("ref.unknown", "invalid", PIN_PATH,
                                    "The pinned format version is unavailable", field=PIN_PATH))
        else:
            for index, board in enumerate(document["boards"]):
                issue = method_violation(format_version["recipe"], board)
                if issue is not None:
                    problems.append(Problem(
                        issue.rule, issue.status, f"/boards/{index}{issue.path}", issue.message,
                        board_id=board["id"], board_number=board["number"],
                        legacy_shot=(board.get("origin") or {}).get("legacy_shot"), field=issue.path,
                    ))
    # The motion records every layered board plays (story 457's resolver); a board's
    # problems stay on its BoardMotion, and the layered check reports them.
    motion = pin_story(document, library, verify, production_id=story.production_id)
    if story.boards is not None:
        problems += _adapter_problems(story, facts=facts, motion=motion, toolchain=toolchain,
                                      frame_size=frame_size)
    foreground, foreground_problems = _foreground_checks(story, library, motion, mask_store or store)
    problems += foreground_problems
    seen, unique = set(), []
    for problem in problems:  # a refusal both checks report (method.unavailable) once
        key = (problem.rule, problem.board_id, problem.field)
        if key not in seen:
            seen.add(key)
            unique.append(problem)
    order = {board_id: i for i, board_id in enumerate(story.board_order)}
    # Mask admission can also make a selected photo stale. Report the set refusal first.
    unique.sort(key=lambda p: (not p.rule.startswith("occlusion."),
                               -1 if p.board_id is None else order.get(p.board_id, len(order)),
                               p.field, p.rule, p.message))
    return Prepared(document, library, story, facts, resolution, resolved, motion,
                    PreflightReport(tuple(unique)), format_version, foreground.roles, foreground.loop_source)


def blocking_problems(problems: Iterable[Problem]) -> list[Problem]:
    return [problem for problem in problems if problem.status != WARNING]


def motion_versions(motion: LayeredMotion | None, library: Library) -> list[dict[str, Any]]:
    """The motion versions the layered boards' resolver pinned (cast loops and set
    loops), as snapshot entries: a loop found by search is a build input too."""
    out: dict[str, dict[str, Any]] = {}
    if motion is None:
        return []
    for board_motion in motion.boards.values():
        clips = [*board_motion.cast, board_motion.set]
        for clip in clips:
            if clip is not None and clip.version_id not in out:
                version = library.version(clip.version_id)
                out[clip.version_id] = {"id": clip.version_id, "kind": version.kind,
                                        "sha256": clip.sha256}
    return list(out.values())


def make_snapshot(prepared: Prepared, library: Library, *, studio: str) -> dict[str, Any]:
    """The ``studio.run-snapshot/v1`` of a prepared story (see the module docstring).
    ``studio`` names the toolchain asked for (``git:<commit>``)."""
    entries: dict[str, dict[str, Any]] = {}
    for item in prepared.resolution.resolved:
        entries.setdefault(item.version_id, item.snapshot_entry())
    for entry in motion_versions(prepared.motion, library):
        entries.setdefault(entry["id"], entry)
    for role in prepared.foreground_roles:
        entries.setdefault(role.version_id, role.snapshot_entry())
    if source := prepared.set_loop_source:
        entries.setdefault(source.id, _set_source_pin(source))
    snapshot = {"schema": SNAPSHOT_SCHEMA, "story": draft_document(prepared.document),
                "resolved_asset_versions": list(entries.values()),
                "toolchain_request": {"studio": studio}}
    if prepared.format_version is not None:
        snapshot["format_version"] = {key: copy.deepcopy(prepared.format_version[key])
                                      for key in ("id", "sha256", "recipe")}
    problems = blocking(validate_run_snapshot(snapshot, context=WRITE))
    if problems:  # the story passed its own checks; a snapshot that fails is a bug here
        raise AssertionError("; ".join(str(problem) for problem in problems))
    return snapshot


def snapshot_bytes(snapshot: Mapping[str, Any]) -> tuple[bytes, str]:
    """The snapshot's canonical JSON and its SHA-256: what the run pins."""
    data = canonical_json(dict(snapshot))
    return data, hashlib.sha256(data).hexdigest()


__all__ = ["Prepared", "blocking_problems", "draft_document", "make_snapshot",
           "motion_versions", "prepare", "require_frozen_roles", "resolved_versions", "snapshot_bytes"]
