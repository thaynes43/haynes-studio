"""The Winter Menu recovery map: complete, exact, unverified, and committed as built."""

from __future__ import annotations

import json
import re
import shutil

import pytest

from haynes_studio.adapters import recovery
from tests.support.policy import REPO_ROOT

TITLE = REPO_ROOT / "titles" / "the-winter-menu"
COMMITTED_JSON = REPO_ROOT / "docs" / "reference" / "legacy-recovery-map.json"
COMMITTED_MD = REPO_ROOT / "docs" / "reference" / "legacy-recovery-map.md"
BEGIN, END = "<!-- recovery-map:begin -->\n", "<!-- recovery-map:end -->"
HEX64 = re.compile(r"[0-9a-f]{64}")
MAP = recovery.build(REPO_ROOT)


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_committed_json_is_the_build():
    assert COMMITTED_JSON.read_text(encoding="utf-8") == recovery.render(MAP), \
        "rebuild: python -m haynes_studio.adapters.recovery > docs/reference/legacy-recovery-map.json"


def test_committed_markdown_table_is_the_build():
    text = COMMITTED_MD.read_text(encoding="utf-8")
    table = text.split(BEGIN, 1)[1].split(END, 1)[0]
    assert table == recovery.markdown_rows(MAP)


def _expected_inputs():
    """Every input, worked out here from the manifests and evidence independently."""
    expected = set()
    for n, (manifest, evidence) in enumerate([("manifest.json", "evidence"),
                                              ("manifest-r2.json", "evidence-r2"),
                                              ("manifest-r3.json", "evidence-r3"),
                                              ("manifest-r4.json", "evidence-r4")], start=1):
        m = load(TITLE / manifest)
        expected |= {(n, "still", f) for shot in m["shots"] for f in shot["dolls"].values()}
        expected.add((n, "set", m["set"]["image"]))
        expected |= {(n, "sfx", s["file"]) for s in m["sfx"].values()}
        expected |= {(n, "bed", b["file"]) for b in m.get("beds", {}).values()}
        expected |= {(n, "take", t["file"]) for t in load(TITLE / evidence / "speech.json")["lines"]}
    prompts = load(TITLE / "prompts.json")
    sources = {c["source"] for c in prompts["cutouts"]} | {prompts["set"]["source"]}
    sources |= {r["source"].removesuffix(".png") for r in prompts["renders"]
                if r["name"] in sources and r["source"]}
    expected |= {(1, "render", f"{s}.png") for s in sources}
    expected |= {(4, "keyframe", k["file"]) for k in load(TITLE / "video-e0/keyframes.json")}
    return expected


def test_every_input_has_exactly_one_row():
    rows = {(r["revision"], r["role"], r["file"]) for r in MAP["rows"]}
    assert len(rows) == len(MAP["rows"]) == MAP["summary"]["rows"]
    assert rows == _expected_inputs()
    assert MAP["summary"]["by_revision"] == {"r1": 22, "r2": 17, "r3": 25, "r4": 34}


def test_every_row_has_a_hash_or_missing_and_its_sources():
    for row in MAP["rows"]:
        assert row["sha256"] == recovery.MISSING or HEX64.fullmatch(row["sha256"]), row["key"]
        if row["sha256"] != recovery.MISSING:
            assert row["hash_recorded_in"], row["key"]
    assert MAP["summary"]["missing_sha256"] == sum(r["sha256"] == "missing" for r in MAP["rows"])


def _walk(value, path=""):
    if isinstance(value, dict):
        for key, item in value.items():
            yield f"{path}/{key}", key, item
            yield from _walk(item, f"{path}/{key}")
    elif isinstance(value, list):
        for i, item in enumerate(value):
            yield from _walk(item, f"{path}/{i}")


def test_nothing_is_claimed_to_exist():
    statuses = {item for _, key, item in _walk(MAP) if key == "status"}
    assert statuses == {"unverified"}
    keys = {key for _, key, _ in _walk(MAP)}
    assert not keys & {"exists", "present", "available", "verified", "found"}
    for row in MAP["rows"]:
        assert row["status"] == "unverified"
        assert all(loc["status"] == "unverified" for loc in row["locators"])


def test_private_paths_stay_as_recorded():
    text = recovery.render(MAP)
    assert "/home/" not in text and "studio-jobs" in text
    for row in MAP["rows"]:
        for loc in row["locators"]:
            if loc["kind"] == "job_dir":
                assert loc["job_dir"].startswith("~/studio-jobs/"), row["key"]
            if loc["kind"] in ("wan_pvc", "wan_upload"):
                assert loc["path"].startswith("/workspace/") and ".." not in loc["path"]


def test_delivered_inputs_point_at_their_ledger_copy():
    ledgers = {n: load(TITLE / e / "production.json") for n, e in
               [(1, "evidence"), (2, "evidence-r2"), (3, "evidence-r3"), (4, "evidence-r4")]}
    for row in MAP["rows"]:
        pvc = [loc for loc in row["locators"] if loc["kind"] == "wan_pvc"]
        if row["role"] in ("still", "set", "sfx", "take"):
            ledger = ledgers[row["revision"]]
            loc, = pvc
            asset, = [a for a in ledger["assets"] if a["path"] == loc["path"]]
            assert (loc["ledger_id"], asset["sha256"], asset["bytes"]) == \
                (ledger["id"], row["sha256"], row["bytes"])
        elif row["role"] == "bed":
            assert not pvc and row["locator_gaps"]  # poc/deliver.py never copied beds


def _copy_title(tmp_path):
    shutil.copytree(TITLE, tmp_path / "titles" / "the-winter-menu")
    return tmp_path / "titles" / "the-winter-menu"


def test_an_unrecorded_hash_is_missing(tmp_path):
    title = _copy_title(tmp_path)
    timeline = load(title / "evidence-r2/timeline.json")
    timeline["audio"] = [a for a in timeline["audio"] if a.get("kind") != "bed"]
    (title / "evidence-r2/timeline.json").write_text(json.dumps(timeline))
    built = recovery.build(tmp_path)
    row, = [r for r in built["rows"] if r["key"] == "r2:bed:sfx/fire-s701.wav"]
    assert (row["sha256"], row["hash_recorded_in"]) == ("missing", [])
    assert built["summary"]["missing_sha256"] == 1


def test_conflicting_records_stop_the_build(tmp_path):
    title = _copy_title(tmp_path)
    speech = load(title / "evidence-r4/speech.json")
    speech["lines"][0]["sha256"] = "0" * 64
    (title / "evidence-r4/speech.json").write_text(json.dumps(speech))
    with pytest.raises(recovery.RecoveryConflict, match="r4:take:voices/line-1.wav"):
        recovery.build(tmp_path)


def test_check_command(tmp_path, capsys):
    assert recovery.main(["--root", str(REPO_ROOT), "--check", str(COMMITTED_JSON)]) == 0
    other = tmp_path / "map.json"
    other.write_text("{}\n")
    assert recovery.main(["--root", str(REPO_ROOT), "--check", str(other)]) == 1
    assert "differs" in capsys.readouterr().out
