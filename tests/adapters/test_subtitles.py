"""Subtitle files and all their dialogue are invented here at test time."""

import errno
import hashlib
import hmac
import json
import logging
import os
import stat
import traceback
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from haynes_studio.adapters import subtitles
from haynes_studio.adapters.errors import AdapterError
from haynes_studio.adapters.subtitles import CueRange, FilesystemSubtitleSource, TimeRange
from haynes_studio.adapters.subtitle_staging import SceneStaging, SituationBeat
from haynes_studio.api.archive_routes import ArchiveAppend, ArchiveCreate, _stored_payload
from haynes_studio.mcp.arguments import AddArchiveVersion, CreateArchiveRecord

pytestmark = pytest.mark.skipif(os.name != "posix" or not hasattr(os, "O_PATH"), reason="Linux source")

TITLE = "The Quartz Teacup"
EPISODE = "Episode 07.srt"
LINE = "Tavren parks seven velvet kettles beneath moons."
RECEIPT_KEY = bytes(range(32))


def srt(*blocks):
    return "\n\n".join(
        f"{index}\n{start} --> {end}\n{text}"
        for index, (start, end, text) in enumerate(blocks, start=1)
    ) + "\n"


@pytest.fixture
def source(tmp_path):
    root = tmp_path / "private fixture"
    title = root / TITLE
    title.mkdir(parents=True)
    (title / EPISODE).write_bytes(srt(
        ("00:00:02,100", "00:00:03,800", "Zevri weighs lunar pebbles."),
        ("00:00:01,000", "00:00:02,800", f"<i>{LINE}</i>"),
        ("00:00:04,000", "00:00:04,800", "Mivren misplaces a wooden receipt."),
    ).replace("\n", "\r\n").encode("utf-8-sig"))
    return root, FilesystemSubtitleSource(root, source_id="sampleSource", receipt_key=RECEIPT_KEY)


def read(adapter, selection=CueRange(1, 3), *, title=TITLE, episode=EPISODE):
    return adapter.read_scene(title, episode, selection, scene_number=7, principal="person_42")


def archive_document(request):
    return request.send(json.loads)


def test_discovery_and_read_leave_a_read_only_tree_untouched(source):
    root, adapter = source
    second = root / "Another title"
    second.mkdir()
    (root / TITLE / "notes.txt").write_text("A tray inventory.")
    (root / TITLE / "episodes.vtt").mkdir()
    (root / TITLE / "link.srt").symlink_to(EPISODE)
    (root / "alias").symlink_to(second, target_is_directory=True)
    paths = (root, *root.rglob("*"))
    permissions = {}
    for path in paths:
        if not path.is_symlink():
            permissions[path] = stat.S_IMODE(path.stat().st_mode)
            os.utime(path, ns=(1_000_000_000, 2_000_000_000))
            path.chmod(0o555 if path.is_dir() else 0o444)

    def metadata():
        result = {}
        for path in paths:
            info = path.lstat()
            result[path] = (
                info.st_ino, info.st_mode, info.st_size, info.st_nlink, info.st_uid, info.st_gid,
                info.st_atime_ns, info.st_mtime_ns, info.st_ctime_ns,
            )
        return result

    try:
        before = metadata()
        assert adapter.list_titles() == ("Another title", TITLE)
        assert adapter.list_episodes(TITLE) == (EPISODE,)
        assert adapter.list_episodes("Another title") == ()
        scene = read(adapter)
        assert [(cue.number, cue.start_ms, cue.end_ms, cue.text) for cue in scene.cues] == [
            (2, 1000, 2800, LINE), (1, 2100, 3800, "Zevri weighs lunar pebbles."),
        ]
        assert metadata() == before
        assert set(root.rglob("*")) == set(paths) - {root}
    finally:
        for path, mode in permissions.items():
            path.chmod(mode)


@pytest.mark.parametrize("invalid", ["..", "../The Quartz Teacup", "/outside", "a/b", "a\\b", "."])
def test_rejects_nonlocal_selectors(source, invalid):
    _, adapter = source
    for call in (
        lambda: adapter.list_episodes(invalid),
        lambda: read(adapter, title=invalid),
        lambda: read(adapter, episode=invalid),
    ):
        with pytest.raises(AdapterError, match="adapter.source_outside"):
            call()


def test_rejects_absolute_file_outside_root_and_ambiguous_root(source, tmp_path):
    _, adapter = source
    outside = tmp_path / "outside.srt"
    outside.write_text("An invented line.")
    with pytest.raises(AdapterError, match="adapter.source_outside"):
        read(adapter, episode=str(outside))
    for root in ("/", "relative", f"{tmp_path}/../elsewhere"):
        with pytest.raises(AdapterError, match="adapter.source_outside"):
            FilesystemSubtitleSource(root, source_id="sampleSource", receipt_key=RECEIPT_KEY)


def test_refuses_links_in_root_ancestors_title_and_episode(source, tmp_path):
    root, adapter = source
    alias = tmp_path / "source link"
    alias.symlink_to(root, target_is_directory=True)
    (root / "title link").symlink_to(root / TITLE, target_is_directory=True)
    (root / TITLE / "episode link.srt").symlink_to(root / TITLE / EPISODE)
    with pytest.raises(AdapterError, match="adapter.source_link"):
        FilesystemSubtitleSource(alias, source_id="sampleSource", receipt_key=RECEIPT_KEY).list_titles()
    with pytest.raises(AdapterError, match="adapter.source_link"):
        FilesystemSubtitleSource(
            alias / "child", source_id="sampleSource", receipt_key=RECEIPT_KEY,
        ).list_titles()
    with pytest.raises(AdapterError, match="adapter.source_link"):
        adapter.list_episodes("title link")
    with pytest.raises(AdapterError, match="adapter.source_link"):
        read(adapter, title="title link")
    with pytest.raises(AdapterError, match="adapter.source_link"):
        read(adapter, episode="episode link.srt")


def test_nonregular_and_hardlinked_files_are_not_opened(source, monkeypatch):
    root, adapter = source
    title = root / TITLE
    os.mkfifo(title / "pipe.srt")
    (title / "folder.srt").mkdir()
    os.link(title / EPISODE, title / "hard.srt")

    def forbid_read(_fd):
        pytest.fail("Refused file was opened for reading")

    monkeypatch.setattr(subtitles, "_read_descriptor", forbid_read)
    for name in ("pipe.srt", "folder.srt"):
        with pytest.raises(AdapterError, match="adapter.source_not_regular"):
            read(adapter, episode=name)
    with pytest.raises(AdapterError, match="adapter.source_hard_link"):
        read(adapter, episode="hard.srt")


def test_rejects_character_device_before_opening_for_io(source, monkeypatch):
    root, adapter = source
    info = (root / TITLE / EPISODE).stat()
    real_fstat = os.fstat

    def fstat(fd):
        result = real_fstat(fd)
        if (result.st_dev, result.st_ino) == (info.st_dev, info.st_ino):
            return SimpleNamespace(st_mode=stat.S_IFCHR | 0o444)
        return result

    monkeypatch.setattr(os, "fstat", fstat)
    with pytest.raises(AdapterError, match="adapter.source_not_regular"):
        read(adapter)


def test_nested_mount_is_refused(source, monkeypatch):
    root, adapter = source
    title_ino = (root / TITLE).stat().st_ino
    monkeypatch.setattr(subtitles, "_mount_id", lambda fd: os.fstat(fd).st_ino == title_ino)
    with pytest.raises(AdapterError, match="adapter.source_outside"):
        adapter.list_episodes(TITLE)
    with pytest.raises(AdapterError, match="adapter.source_outside"):
        read(adapter)


def test_denial_and_missing_errors_carry_no_private_path(source, monkeypatch, caplog):
    root, adapter = source
    with pytest.raises(AdapterError, match="adapter.source_missing"):
        read(adapter, episode="absent.srt")
    real_open = os.open

    def open_denied(path, flags, **kwargs):
        if path == EPISODE:
            raise PermissionError(13, "Permission denied", str(root / TITLE / EPISODE))
        return real_open(path, flags, **kwargs)

    monkeypatch.setattr(os, "open", open_denied)
    with caplog.at_level(logging.DEBUG), pytest.raises(AdapterError) as caught:
        read(adapter)
    assert caught.value.code == "subtitle.access_denied"
    assert caught.value.__context__ is None
    error = "".join(traceback.format_exception(caught.value))
    for private in (str(root), TITLE, EPISODE, LINE):
        assert private not in error
        assert private not in caplog.text


@pytest.mark.parametrize("mount_flag", ["ST_RDONLY", "ST_NOATIME", None], ids=["read-only", "noatime", "writable"])
def test_noatime_open_refusal_only_falls_back_on_safe_mounts(source, monkeypatch, mount_flag):
    _, adapter = source
    mount_flags = getattr(os, mount_flag) if mount_flag else 0
    real_open = os.open
    reopen_flags = []

    def open_with_nonowner_refusal(path, flags, **kwargs):
        if path.startswith("/proc/self/fd/"):
            reopen_flags.append(flags)
            if flags & os.O_NOATIME:
                raise PermissionError(errno.EPERM, "O_NOATIME refused")
        return real_open(path, flags, **kwargs)

    monkeypatch.setattr(os, "open", open_with_nonowner_refusal)
    monkeypatch.setattr(os, "fstatvfs", lambda fd: SimpleNamespace(f_flag=mount_flags))
    if mount_flags:
        assert read(adapter).cues[0].text == LINE
        assert reopen_flags == [os.O_RDONLY | os.O_NOATIME, os.O_RDONLY]
    else:
        with pytest.raises(AdapterError, match="subtitle.access_denied"):
            read(adapter)
        assert reopen_flags == [os.O_RDONLY | os.O_NOATIME]


def test_vtt_bom_settings_header_metadata_ids_markup_and_overlap(source):
    root, adapter = source
    data = (
        "WEBVTT synthetic notes\r\nKind: captions\r\n\r\n"
        "NOTE stage cue\r\nThis is metadata.\r\n\r\n"
        "STYLE\r\n::cue { color: lime }\r\n\r\n"
        "REGION\r\nid:booth\r\n\r\n"
        "vending-booth\r\n00:02.000 --> 00:03.500 align:start\r\n"
        "<v Tavren><c.green>Glazed &amp; lacquered.</c></v>\r\n\r\n"
        "00:01:01.200 --> 00:01:02.900\r\nZeph's copper umbrella hums.\r\n\r\n"
        "00:01.000 --> 00:02.100\r\nMivren counts <00:01.500>spools.\r\n"
    )
    (root / TITLE / "alternate.VTT").write_bytes(data.encode("utf-8-sig"))
    scene = read(adapter, TimeRange(0, 4000), episode="alternate.VTT")
    assert [(cue.number, cue.start_ms, cue.end_ms, cue.text) for cue in scene.cues] == [
        (3, 1000, 2100, "Mivren counts spools."),
        (1, 2000, 3500, "Glazed & lacquered."),
    ]
    assert [cue.number for cue in read(adapter, TimeRange(1001, 4000), episode="alternate.VTT").cues] == [1]


def test_legacy_srt_encodings(source):
    root, adapter = source
    text = "0:00:01.000 --> 0:00:02.000\nTâve’s {\\an8}ceramic poncho."
    path = root / TITLE / EPISODE
    path.write_bytes(text.encode("utf-16"))
    assert read(adapter, CueRange(1, 2)).cues[0].text == "Tâve’s ceramic poncho."
    path.write_bytes(text.encode("cp1252"))
    with pytest.raises(AdapterError, match="subtitle.encoding"):
        read(adapter, CueRange(1, 2))
    opted_in = FilesystemSubtitleSource(
        root, source_id="sampleSource", receipt_key=RECEIPT_KEY, allow_windows_1252=True,
    )
    assert read(opted_in, CueRange(1, 2)).cues[0].text == "Tâve’s ceramic poncho."
    path.write_bytes(text.encode("utf-32"))
    with pytest.raises(AdapterError, match="subtitle.encoding"):
        read(opted_in, CueRange(1, 2))


@pytest.mark.parametrize(("episode", "data", "code"), [
    (EPISODE, b"unframed synthetic prose", "subtitle.format"),
    (EPISODE, b"1\n00:00:04,000 --> 00:00:01,000\nA backward clock.", "subtitle.format"),
    (EPISODE, b"1\n00:00:91,000 --> 00:00:92,000\nBizarre clock.", "subtitle.format"),
    (EPISODE, b"1\n00:00:01,000 --> 00:00:02,000\nQuartz\n2\n"
              b"00:00:02,000 --> 00:00:03,000\nTeacup", "subtitle.format"),
    (EPISODE, b"1\n00:00:01,000 --> 00:00:02,000\nQuartz\x00teacup.", "subtitle.format"),
    ("captions.vtt", b"NOHEADER\n\n00:00.000 --> 00:01.000\nGreen twine.", "subtitle.format"),
    ("captions.vtt", b"WEBVTT\n00:00.000 --> 00:01.000\nGreen twine.", "subtitle.format"),
    ("captions.vtt", "WEBVTT\n\n00:00.000 --> 00:01.000\nCôite.".encode("utf-16"), "subtitle.encoding"),
])
def test_refuses_malformed_or_unsupported_subtitles(source, episode, data, code):
    root, adapter = source
    (root / TITLE / episode).write_bytes(data)
    with pytest.raises(AdapterError) as caught:
        read(adapter, CueRange(1, 2), episode=episode)
    assert caught.value.code == code


@pytest.mark.parametrize("selection", [
    CueRange(0, 2), CueRange(2, 2), CueRange(1, 5), CueRange(True, 2),
    CueRange(1, 82), TimeRange(0, 120001), TimeRange(1000, 2100), TimeRange(-1, 2000),
])
def test_refuses_invalid_empty_or_excessive_ranges(source, selection):
    with pytest.raises(AdapterError, match="subtitle.range"):
        read(source[1], selection)


def test_file_and_discovery_limits(source, monkeypatch):
    root, adapter = source
    path = root / TITLE / "huge.srt"
    with path.open("wb") as file:
        file.truncate(subtitles.MAX_FILE_BYTES + 1)
    assert adapter.list_episodes(TITLE) == (EPISODE,)
    with pytest.raises(AdapterError, match="adapter.source_too_large"):
        read(adapter, episode=path.name)
    monkeypatch.setattr(subtitles, "MAX_DIRECTORY_ENTRIES", 1)
    with pytest.raises(AdapterError, match="subtitle.limit"):
        adapter.list_episodes(TITLE)


def test_growth_past_byte_limit_is_refused(source, monkeypatch):
    root, adapter = source
    path = root / TITLE / EPISODE
    monkeypatch.setattr(subtitles, "MAX_FILE_BYTES", path.stat().st_size)
    open_read = subtitles._read_descriptor

    def append_before_open(fd):
        with path.open("ab") as file:
            file.write(b"\n")
        return open_read(fd)

    monkeypatch.setattr(subtitles, "_read_descriptor", append_before_open)
    with pytest.raises(AdapterError, match="adapter.source_too_large"):
        read(adapter)


def test_same_size_file_change_during_read_is_refused(source, monkeypatch):
    root, adapter = source
    path = root / TITLE / EPISODE
    original = path.read_bytes()
    replacement = original.replace(b"Tavren", b"Karven")
    assert len(replacement) == len(original) and replacement != original
    real_read = os.read

    def read_then_change(fd, size):
        chunk = real_read(fd, size)
        if chunk:
            path.write_bytes(replacement)
            os.utime(path, ns=(1_000_000_000, 2_000_000_000))
        return chunk

    monkeypatch.setattr(os, "read", read_then_change)
    with pytest.raises(AdapterError, match="adapter.source_changed"):
        read(adapter)


@pytest.mark.parametrize(("count", "length", "end"), [
    (1, 4097, "00:00:02,000"), (3, 3000, "00:00:02,000"),
    (81, 1, "00:00:02,000"), (10001, 1, "00:00:02,000"),
    (1, 2, "00:02:01,001"),
])
def test_parser_and_scene_limits(source, count, length, end):
    root, adapter = source
    data = srt(*[("00:00:01,000", end, "q" * length)] * count)
    (root / TITLE / EPISODE).write_text(data)
    selection = CueRange(1, 2) if count == 1 else TimeRange(0, 4000)
    with pytest.raises(AdapterError, match="subtitle.limit"):
        read(adapter, selection)


def test_metadata_only_receipt_and_keyed_archive_locator(source, caplog):
    root, adapter = source
    production = "prd_" + "1" * 26
    with caplog.at_level(logging.DEBUG):
        scene = read(adapter)
        stage = SceneStaging(scene)
        prepared = stage.archive_payload(kind="script", title="Copper Latch", text="A courier hoards hinges.")
        payload = archive_document(prepared)
    receipt = scene.provenance.as_record()
    passage = json.dumps([[1000, 2800, LINE], [2100, 3800, "Zevri weighs lunar pebbles."]],
                         separators=(",", ":")).encode()
    locator = payload["provenance"]["source_locator"]
    assert not hasattr(scene, "source_locator")
    assert locator == {"label": "sampleSource-7", "sha256": hashlib.sha256(passage).hexdigest()}
    assert read(adapter, TimeRange(0, 3800)).provenance.passage_sha256 == locator["sha256"]
    assert receipt == {
        "source_id": "sampleSource", "title_id": receipt["title_id"], "episode_id": receipt["episode_id"],
        "range": {"unit": "cue", "start": 1, "end": 3}, "principal": "person_42",
        "passage_sha256": locator["sha256"], "read_at": receipt["read_at"],
    }
    assert receipt["title_id"] != receipt["episode_id"]
    selectors = {"title_id": ("sampleSource", TITLE), "episode_id": ("sampleSource", TITLE, EPISODE)}
    for name, parts in selectors.items():
        encoded = json.dumps(parts, separators=(",", ":")).encode("utf-8")
        assert receipt[name] == hmac.digest(RECEIPT_KEY, encoded, "sha256").hex()
        assert receipt[name] != hashlib.sha256(encoded).hexdigest()
    assert datetime.fromisoformat(receipt["read_at"]).tzinfo == UTC
    assert not caplog.records
    output = json.dumps(receipt) + json.dumps(payload) + repr(scene) + repr(scene.cues) + repr(prepared)
    for private in (str(root), TITLE, EPISODE, LINE, "Zevri"):
        assert private not in output

    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(archive_source_key=b"fixture")))
    body = prepared.send(ArchiveCreate.model_validate_json)
    tool = stage.archive_payload(
        kind="script", title="Copper Latch", text="A courier hoards hinges.",
        production_id=production, idempotency_key="fixture-create",
    ).send(CreateArchiveRecord.model_validate_json)
    assert tool.provenance.source_locator.model_dump() == locator
    stored = _stored_payload(request, production, body.model_dump())["provenance"]["source_locator"]
    assert stored["label"] == locator["label"]
    assert set(stored) == {"label", "hmac_sha256"}
    assert stored["hmac_sha256"] != receipt["passage_sha256"]

    append_fields = {
        "text": "The courier trades a hinge for a compass.", "revises_version_id": "arv_" + "2" * 26,
    }
    appended = stage.archive_payload(**append_fields).send(ArchiveAppend.model_validate_json)
    assert appended.provenance.source_locator.model_dump() == locator
    tool = stage.archive_payload(
        **append_fields, record_id="arc_" + "3" * 26, idempotency_key="fixture-append",
    ).send(AddArchiveVersion.model_validate_json)
    assert tool.provenance.source_locator.model_dump() == locator


def test_archive_send_refuses_an_edited_body_before_transport(source):
    stage = SceneStaging(read(source[1]))
    request = stage.archive_payload(kind="script", title="Copper Latch", text="A courier hoards hinges.")
    document = archive_document(request)
    document["text"] = LINE
    edited = json.dumps(document).encode("utf-8")
    with pytest.raises(FrozenInstanceError):
        request._body = edited

    def unexpected_send(_body):
        pytest.fail("Edited request reached the transport")

    with pytest.raises(AdapterError, match="subtitle.staging_text"):
        replace(request, _body=edited).send(unexpected_send)
    assert archive_document(request)["text"] == "A courier hoards hinges."


def test_summary_has_conflict_and_beats_timed_from_the_scene(source):
    stage = SceneStaging(read(source[1]))
    summary = stage.summarize(
        conflict="A groundskeeper and a caretaker dispute where equipment belongs.",
        beats=(SituationBeat(1, "The groundskeeper moves the inventory."),
               SituationBeat(1, "The caretaker counters by inspecting the supplies.")),
    )
    assert summary.splitlines() == [
        "Conflict — A groundskeeper and a caretaker dispute where equipment belongs.",
        "1000–2800 ms — The groundskeeper moves the inventory.",
        "2100–3800 ms — The caretaker counters by inspecting the supplies.",
    ]
    prepared = stage.archive_payload(text=summary, revises_version_id="arv_" + "2" * 26)
    assert archive_document(prepared)["text"] == summary
    with pytest.raises(AdapterError, match="Beats must cover the whole scene"):
        stage.summarize(conflict="A rivalry over equipment.", beats=(SituationBeat(1, "A move."),))


def test_summary_rejects_dialogue_in_the_conflict_and_across_beats(source, caplog):
    stage = SceneStaging(read(source[1]))
    with caplog.at_level(logging.DEBUG):
        with pytest.raises(AdapterError, match="subtitle.verbatim") as caught:
            stage.summarize(conflict=LINE.upper(), beats=(SituationBeat(2, "A dispute about goods."),))
        with pytest.raises(AdapterError, match="subtitle.verbatim"):
            stage.summarize(conflict=f"<{LINE}>", beats=(SituationBeat(2, "A dispute about goods."),))
        with pytest.raises(AdapterError, match="subtitle.verbatim"):
            stage.summarize(
                conflict="A rivalry over equipment.",
                beats=(SituationBeat(1, "TAVREN (parks) SEVEN"), SituationBeat(1, "velvet kettles!")),
            )
    assert LINE not in str(caught.value) + caplog.text
    assert not caplog.records


@pytest.mark.parametrize("repeated", [
    "ＴＡＶＲＥＮ, parks — seven <i>velvet</i> kettles!",
    "seven velvet kettles beneath moons. Zevri weighs",
    "lunar pebbles. Tavren parks seven",
    f"<{LINE}>",
    '<span title="Tavren&#32;parks&#32;seven&#32;velvet&#32;kettles">Invented props</span>',
    r'"\u0054avren parks seven velvet kettles"',
    r'{"lines":[{"text":"\u0054avren parks seven"},{"text":"velvet kettles"}]}',
    r'{"text":"\u0054avren parks seven velvet kettles"}',
    pytest.param(r'{"cues":[{"\u0054avren parks seven velvet kettles":"A quiet prop enters."}]}',
                 id="escaped-key"),
    pytest.param(r'{"\u0054avren parks":{"seven velvet \u006bettles":"beneath moons"}}',
                 id="split-from-key-into-value"),
    pytest.param(r'{"\u0054avren parks seven":1,"velvet \u006bettles beneath moons":2}',
                 id="split-across-keys"),
    pytest.param(r'{"\u0054avren parks seven":"A prop.","velvet \u006bettles beneath":"Another prop."}',
                 id="split-across-keys-with-values-between"),
    pytest.param("Tavren\u3164parks\u3164seven\u3164velvet\u3164kettles", id="blank-filler"),
    pytest.param("Ta\u0301vren parks se\u0301ven velvet kettles", id="combining-marks"),
    pytest.param("Ta\u200bvren parks seven velvet kettles", id="zero-width"),
])
def test_archive_payload_refuses_normalized_dialogue_including_json_and_cue_joins(source, repeated):
    stage = SceneStaging(read(source[1]))
    with pytest.raises(AdapterError, match="subtitle.verbatim"):
        stage.archive_payload(text=repeated)
    with pytest.raises(AdapterError, match="subtitle.verbatim"):
        stage.archive_payload(text="A courier hoards hinges.", title=LINE)


def test_archive_operation_fields_pass_through_the_guard(source):
    stage = SceneStaging(read(source[1]))
    with pytest.raises(AdapterError, match="subtitle.verbatim"):
        stage.archive_payload(text="A courier hoards hinges.", revises_version_id="arv_" + "2" * 26,
                              idempotency_key=LINE)
    ordinary = stage.archive_payload(text="A courier hoards hinges.", revises_version_id="arv_" + "2" * 26,
                                     idempotency_key="stage-0001")
    assert archive_document(ordinary)["idempotency_key"] == "stage-0001"


def test_guard_threshold_and_staging_size(source):
    scene = read(source[1])
    assert archive_document(SceneStaging(scene).archive_payload(text="Tavren parks seven velvet"))["text"]
    with pytest.raises(AdapterError, match="subtitle.verbatim"):
        SceneStaging(scene, max_source_words=2).archive_payload(text="Tavren parks seven")
    with pytest.raises(AdapterError, match="subtitle.staging_text"):
        SceneStaging(scene).archive_payload(text="ç" * (128 * 1024 + 1))
    with pytest.raises(AdapterError, match="adapter.request_invalid"):
        SceneStaging(scene, max_source_words=0)
