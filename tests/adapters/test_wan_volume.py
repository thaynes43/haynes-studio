"""The read-only volume reads of story 846: every guard, run for real.

The fake volume runs the pinned snippets themselves against a temporary folder that
stands in for ``/workspace`` (``FakeWanVolume``), so each guard meets a real symbolic
link, hard link, FIFO, folder, sparse file or swapped file. Nothing is sent anywhere.
"""

from __future__ import annotations

import ast
import hashlib
import inspect
import json
import os
import re

import pytest

from haynes_studio.adapters import errors, pinned, wan_ledger, wan_volume
from haynes_studio.adapters.errors import AdapterError, PinMismatch, RequestInvalid
from haynes_studio.adapters.fakes import FailingRunner, FakeRunner, FakeWanVolume
from haynes_studio.adapters.runner import Completed
from haynes_studio.adapters.wan_ledger import LedgerReader
from haynes_studio.adapters.wan_volume import VolumeReader, ledger_fetch_refusal

SNIPPETS = ("wan_upload_read.py", "wan_job_output_read.py")
JOB = "a" * 32
DATA = b"synthetic clip bytes " * 64
SHA = hashlib.sha256(DATA).hexdigest()
NAME = SHA[:16] + ".png"


@pytest.fixture
def vol(tmp_path):
    return FakeWanVolume(tmp_path / "pod" / "workspace")


def reader(vol):
    return VolumeReader(FakeRunner(vol))


def refused(call) -> str:
    with pytest.raises(AdapterError) as caught:
        call()
    return caught.value.code


def clip_path(vol, job=JOB):
    return vol.root / "output" / "video" / f"{job}_00001_.mp4"


def upload_path(vol):
    return vol.root / "input" / "studio-e0" / NAME


# Read-only by construction ---------------------------------------------------------------

WRITE_WORDS = {"write", "publish", "put", "post", "delete", "remove", "unlink", "link", "rename",
               "replace", "save", "create", "mkdir", "touch", "chmod", "copy", "move", "store"}
# Every call the two snippets make, by full name, and the read-only methods they call on
# values. A snippet may also call a function it defines itself.
ALLOWED_CALLS = {"SystemExit", "isinstance", "len", "all", "bytes", "bytearray", "json.loads",
                 "re.fullmatch", "hashlib.sha256", "os.open", "os.stat", "os.fstat", "os.read",
                 "os.close", "stat.S_ISLNK", "stat.S_ISDIR", "stat.S_ISREG", "sys.stderr.write",
                 "sys.stdout.buffer.write", "held.append", "job.get"}
ALLOWED_METHODS = {"hexdigest", "split", "endswith"}
NEVER = ("O_WRONLY", "O_RDWR", "O_CREAT", "O_TRUNC", "O_APPEND", "O_EXCL", "unlink", "rename",
         "remove", "replace", "chmod", "chown", "symlink", "mkdir", "rmdir", "truncate", "utime",
         "urlopen", "subprocess", "socket", "shutil", "open(", "pathlib")


def test_the_reader_has_no_write_method():
    public = {name for name, _ in inspect.getmembers(VolumeReader) if not name.startswith("_")}
    assert public == {"fetch_upload", "upload_command", "fetch_job_output", "job_output_command"}
    for name in public:
        assert not set(name.split("_")) & WRITE_WORDS, name


@pytest.mark.parametrize("name", SNIPPETS)
def test_the_snippets_only_read(name):
    """An allowlist: every call is one of these, every ``os.open`` is read-only and does
    not follow a link (the root's alone may: it is the mount point), and no write,
    rename, link, chmod, truncate or delete appears anywhere in the text."""
    text = pinned.load(name).text
    tree = ast.parse(text)
    own = {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
    opens = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            called = ast.unparse(node.func)
            base = called.rsplit(".", 1)[-1]
            assert called in ALLOWED_CALLS | own or (base in ALLOWED_METHODS and "." in called), \
                f"{name}: {ast.unparse(node)}"
            if called == "os.open":
                opens += 1
                flags = set(re.findall(r"os\.O_\w+", ast.unparse(node.args[1])))
                if ast.unparse(node.args[0]) == "ROOT":
                    assert flags == {"os.O_RDONLY", "os.O_DIRECTORY"}, ast.unparse(node)
                    assert not node.keywords
                else:
                    assert {"os.O_RDONLY", "os.O_NOFOLLOW"} <= flags <= {
                        "os.O_RDONLY", "os.O_NOFOLLOW", "os.O_DIRECTORY", "os.O_NONBLOCK"}, \
                        ast.unparse(node)
                    assert [k.arg for k in node.keywords] == ["dir_fd"], ast.unparse(node)
            if called == "os.stat":
                assert {k.arg: ast.unparse(k.value) for k in node.keywords} == \
                    {"dir_fd": "folder_fd", "follow_symlinks": "False"}, ast.unparse(node)
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = {a.name for a in node.names}
            assert names <= {"errno", "hashlib", "json", "os", "re", "stat", "sys"}, name
    assert opens == 2  # the root, and one call in step() for every folder and file
    code = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
    code = code.replace("os.open(", "os.OPEN(").replace("follow_symlinks=False", "")
    for word in NEVER:
        assert word not in code, (name, word)


def test_the_pinned_limits_are_the_clients():
    upload = pinned.load("wan_upload_read.py").text
    output = pinned.load("wan_job_output_read.py").text
    assert f"LIMIT = {wan_volume.MAX_UPLOAD_BYTES}" in upload
    assert f"LIMIT = {wan_volume.MAX_OUTPUT_BYTES}" in output
    assert "ROOT = '/workspace'" in upload and "ROOT = '/workspace'" in output
    assert "('input', 'studio-e0')" in upload
    for text in (upload, output):
        assert f"raise SystemExit({wan_volume.REFUSED_EXIT})" in text
        printed = set(re.findall(r"(?:refuse|bad)\('([a-z_]+)'\)", text)) | {"volume"}
        assert "refuse('volume' if fixed else reason)" in text
        assert printed - {"request"} <= set(wan_volume.REASONS), printed


# Job outputs -------------------------------------------------------------------------------


def test_a_job_output_is_read_and_hash_checked(vol):
    vol.add_job(JOB, DATA)
    clip = reader(vol).fetch_job_output(JOB, SHA)
    assert (clip.data, clip.sha256, clip.source, clip.name) == (DATA, SHA, "job_output", JOB)


def test_an_output_at_the_output_root_is_read(vol):
    """The API records ``/<file>`` when ComfyUI's subfolder is empty."""
    vol.add_job(JOB, DATA, output="/" + JOB + ".mp4")
    assert reader(vol).fetch_job_output(JOB, SHA).data == DATA


@pytest.mark.parametrize("job_id,sha", [("A" * 32, SHA), ("a" * 31, SHA), ("../" + "a" * 29, SHA),
                                        (JOB, "F" * 64), (JOB, SHA[:63]), (7, SHA)])
def test_a_malformed_request_is_refused_before_anything_runs(vol, job_id, sha):
    runner = FakeRunner(vol)
    with pytest.raises(RequestInvalid):
        VolumeReader(runner).fetch_job_output(job_id, sha)
    assert runner.calls == []


def test_a_missing_ledger_or_output_is_missing(vol):
    assert refused(lambda: reader(vol).fetch_job_output(JOB, SHA)) == errors.SOURCE_MISSING
    vol.add_job(JOB, None)
    assert refused(lambda: reader(vol).fetch_job_output(JOB, SHA)) == errors.SOURCE_MISSING


@pytest.mark.parametrize("change", [{"state": "running"}, {"state": "failed"}, {"id": "b" * 32},
                                    {"output": None}, {"output": 7}])
def test_a_ledger_that_is_not_a_succeeded_job_of_that_id_is_refused(vol, change):
    vol.add_job(JOB, DATA)
    ledger = vol.root / "jobs" / f"{JOB}.json"
    job = {**json.loads(ledger.read_text()), **change}
    ledger.write_text(json.dumps({k: v for k, v in job.items() if v is not None}))
    assert refused(lambda: reader(vol).fetch_job_output(JOB, SHA)) == errors.SOURCE_RECORD_INVALID


@pytest.mark.parametrize("text", ["not json", "[1, 2]", ""])
def test_an_unparseable_ledger_is_refused(vol, text):
    vol.add_job(JOB, DATA)
    (vol.root / "jobs" / f"{JOB}.json").write_text(text)
    assert refused(lambda: reader(vol).fetch_job_output(JOB, SHA)) == errors.SOURCE_RECORD_INVALID


@pytest.mark.parametrize("output", ["../jobs/x.mp4", "video/../../x.mp4", "video/./x.mp4",
                                    "video//x.mp4", "video/.hidden.mp4", "video/-x.mp4", "x.json",
                                    "video/x.mp4/", "", "//x.mp4", "a/b/c/d/e/f/g/h/i.mp4",
                                    "video/x y.mp4", "video\\x.mp4"])
def test_an_output_path_that_is_not_plain_names_below_output_is_outside(vol, output):
    vol.add_job(JOB, None, output=output, size=None)
    assert refused(lambda: reader(vol).fetch_job_output(JOB, SHA)) == errors.SOURCE_OUTSIDE


def test_a_symlinked_output_is_refused_even_to_identical_bytes(vol, tmp_path):
    vol.add_job(JOB, DATA)
    outside = tmp_path / "outside.mp4"
    outside.write_bytes(DATA)
    clip_path(vol).unlink()
    clip_path(vol).symlink_to(outside)
    assert refused(lambda: reader(vol).fetch_job_output(JOB, SHA)) == errors.SOURCE_LINK


@pytest.mark.parametrize("folder,code", [("output/video", errors.SOURCE_LINK),
                                         ("output", errors.VOLUME_UNEXPECTED),
                                         ("jobs", errors.VOLUME_UNEXPECTED)])
def test_a_symlinked_folder_on_the_path_is_refused(vol, tmp_path, folder, code):
    """A folder the record names is that record's refusal; a fixed folder of the volume
    is ``adapter.volume_unexpected``, which stops the import."""
    vol.add_job(JOB, DATA)
    real = vol.root / folder
    moved = real.rename(tmp_path / "moved")
    real.symlink_to(moved)
    assert refused(lambda: reader(vol).fetch_job_output(JOB, SHA)) == code


@pytest.mark.parametrize("folder", ["jobs", "output"])
def test_a_missing_fixed_folder_is_the_wrong_volume_not_a_missing_file(vol, folder):
    vol.add_job(JOB, DATA)
    target = vol.root / folder
    target.rename(target.with_name(folder + "-moved"))
    assert refused(lambda: reader(vol).fetch_job_output(JOB, SHA)) == errors.VOLUME_UNEXPECTED


def test_a_missing_root_is_a_failure_not_a_refusal(tmp_path):
    vol = FakeWanVolume(tmp_path / "pod" / "workspace")
    for path in sorted(vol.root.rglob("*"), reverse=True):
        path.rmdir()
    vol.root.rmdir()
    assert refused(lambda: reader(vol).fetch_upload(SHA, ".png")) == errors.COMMAND_FAILED


def test_a_symlinked_ledger_is_refused(vol, tmp_path):
    vol.add_job("b" * 32, DATA)
    ledger = vol.root / "jobs" / f"{'b' * 32}.json"
    job = json.loads(ledger.read_text())
    target = tmp_path / "ledger.json"
    target.write_text(json.dumps({**job, "id": JOB}))
    (vol.root / "jobs" / f"{JOB}.json").symlink_to(target)
    assert refused(lambda: reader(vol).fetch_job_output(JOB, SHA)) == errors.SOURCE_LINK


def test_a_fifo_or_a_folder_is_not_regular_and_never_opened(vol, monkeypatch):
    vol.add_job(JOB, DATA)
    clip_path(vol).unlink()
    os.mkfifo(clip_path(vol))  # opening it for reading would block without O_NONBLOCK
    opened = []
    real = os.open

    def spy(path, *args, **kwargs):
        opened.append(os.fspath(path))
        return real(path, *args, **kwargs)
    monkeypatch.setattr(os, "open", spy)
    assert refused(lambda: reader(vol).fetch_job_output(JOB, SHA)) == errors.SOURCE_NOT_REGULAR
    assert clip_path(vol).name not in opened and f"{JOB}.json" in opened
    monkeypatch.undo()
    clip_path(vol).unlink()
    clip_path(vol).mkdir()
    assert refused(lambda: reader(vol).fetch_job_output(JOB, SHA)) == errors.SOURCE_NOT_REGULAR


def test_a_file_where_a_folder_belongs_is_not_regular(vol):
    vol.add_job(JOB, None, output="video/" + JOB + ".mp4/x.mp4", size=None)
    (vol.root / "output" / "video").mkdir(parents=True)
    (vol.root / "output" / "video" / f"{JOB}.mp4").write_bytes(DATA)
    assert refused(lambda: reader(vol).fetch_job_output(JOB, SHA)) == errors.SOURCE_NOT_REGULAR


def test_a_hard_linked_output_is_refused(vol, tmp_path):
    vol.add_job(JOB, DATA)
    os.link(clip_path(vol), vol.root / "second-name.mp4")
    assert refused(lambda: reader(vol).fetch_job_output(JOB, SHA)) == errors.SOURCE_HARD_LINK


def test_an_oversized_output_is_refused_before_it_is_read(vol):
    vol.add_job(JOB, b"", size=None)
    with open(clip_path(vol), "r+b") as handle:  # a sparse file: nothing is really written
        handle.truncate(wan_volume.MAX_OUTPUT_BYTES + 1)
    assert refused(lambda: reader(vol).fetch_job_output(JOB, SHA)) == errors.SOURCE_TOO_LARGE


def test_an_oversized_ledger_is_refused(vol):
    vol.add_job(JOB, DATA)
    with open(vol.root / "jobs" / f"{JOB}.json", "r+b") as handle:
        handle.truncate(16 * 1024 * 1024 + 1)
    assert refused(lambda: reader(vol).fetch_job_output(JOB, SHA)) == errors.SOURCE_TOO_LARGE


def test_other_bytes_or_another_size_than_the_ledger_records_are_a_mismatch(vol):
    vol.add_job(JOB, DATA)
    other = hashlib.sha256(b"other").hexdigest()
    assert refused(lambda: reader(vol).fetch_job_output(JOB, other)) == errors.SOURCE_HASH_MISMATCH
    vol.add_job(JOB, DATA, size=len(DATA) + 1)
    assert refused(lambda: reader(vol).fetch_job_output(JOB, SHA)) == errors.SOURCE_HASH_MISMATCH


def test_a_ledger_without_a_byte_count_is_read(vol):
    vol.add_job(JOB, DATA, size=None)
    assert reader(vol).fetch_job_output(JOB, SHA).data == DATA


def _swap_after_lstat(monkeypatch, target, swap):
    """Run ``swap()`` right after the snippet's lstat of ``target``, before its open."""
    real = os.stat

    def stat(path, *args, **kwargs):
        answer = real(path, *args, **kwargs)
        if kwargs.get("dir_fd") is not None and path == target.name:
            swap()
        return answer
    monkeypatch.setattr(os, "stat", stat)


def test_a_file_swapped_for_a_link_after_its_lstat_is_refused(vol, tmp_path, monkeypatch):
    vol.add_job(JOB, DATA)
    outside = tmp_path / "same-bytes.mp4"
    outside.write_bytes(DATA)

    def swap():
        clip_path(vol).unlink()
        clip_path(vol).symlink_to(outside)
    _swap_after_lstat(monkeypatch, clip_path(vol), swap)
    assert refused(lambda: reader(vol).fetch_job_output(JOB, SHA)) == errors.SOURCE_CHANGED


def test_a_file_replaced_after_its_lstat_is_refused(vol, monkeypatch, tmp_path):
    """The old file is moved aside, not removed, so its inode stays allocated and the new
    file cannot reuse its number (ext4 would give it at once). A number reused after a
    removal in the same gap is a known limit; the hash stays the final guard."""
    vol.add_job(JOB, DATA)

    def swap():
        clip_path(vol).rename(tmp_path / "aside.mp4")
        clip_path(vol).write_bytes(DATA)  # a new inode with the same bytes
    _swap_after_lstat(monkeypatch, clip_path(vol), swap)
    assert refused(lambda: reader(vol).fetch_job_output(JOB, SHA)) == errors.SOURCE_CHANGED


@pytest.mark.parametrize("call", ["stat", "open"])
def test_a_permission_or_io_error_is_a_failure_that_stops_not_a_refusal(vol, monkeypatch, call):
    """Only the errors a swap gives (ENOENT, ELOOP, ENOTDIR, ENXIO at the open) are
    ``changed``; EACCES, EIO and the rest are a traceback, so the import stops."""
    vol.add_job(JOB, DATA)
    real = getattr(os, call)

    def denied(path, *args, **kwargs):
        if os.fspath(path) == clip_path(vol).name:
            raise PermissionError(13, "Permission denied")
        return real(path, *args, **kwargs)
    monkeypatch.setattr(os, call, denied)
    with pytest.raises(AdapterError) as caught:
        reader(vol).fetch_job_output(JOB, SHA)
    monkeypatch.undo()
    assert caught.value.code == errors.COMMAND_FAILED
    assert "PermissionError" in caught.value.redacted_stderr


# Uploads -------------------------------------------------------------------------------------


def test_an_upload_is_read_by_its_hash(vol):
    vol.add_upload(NAME, DATA)
    image = reader(vol).fetch_upload(SHA, ".png")
    assert (image.data, image.name, image.source) == (DATA, NAME, "upload")
    vol.add_upload(SHA[:16] + ".wav", DATA)
    assert reader(vol).fetch_upload(SHA, ".wav").name == SHA[:16] + ".wav"


@pytest.mark.parametrize("sha,suffix", [(SHA, ".jpg"), (SHA, "png"), (SHA, "/../x.png"),
                                        ("F" * 64, ".png"), (SHA[:16], ".png")])
def test_a_malformed_upload_request_is_refused_before_anything_runs(vol, sha, suffix):
    runner = FakeRunner(vol)
    with pytest.raises(RequestInvalid):
        VolumeReader(runner).fetch_upload(sha, suffix)
    assert runner.calls == []


def test_the_upload_name_is_checked_in_the_pod_too(vol):
    """A name that is not the hash's first 16 digits never opens a file."""
    vol.add_upload("0" * 16 + ".png", DATA)
    result = vol.run_snippet("wan_upload_read.py", vol._rooted(
        "wan_upload_read.py", pinned.load("wan_upload_read.py").text), ("0" * 16 + ".png", SHA))
    assert (result.returncode, result.stdout) == (3, b"")
    assert result.stderr.decode().strip() == "REFUSED request"


def test_a_missing_upload_is_missing_and_a_missing_upload_folder_the_wrong_volume(vol):
    assert refused(lambda: reader(vol).fetch_upload(SHA, ".png")) == errors.SOURCE_MISSING
    (vol.root / "input" / "studio-e0").rmdir()
    assert refused(lambda: reader(vol).fetch_upload(SHA, ".png")) == errors.VOLUME_UNEXPECTED


def test_a_symlinked_upload_or_upload_folder_is_refused(vol, tmp_path):
    outside = tmp_path / "same.png"
    outside.write_bytes(DATA)
    upload_path(vol).symlink_to(outside)
    assert refused(lambda: reader(vol).fetch_upload(SHA, ".png")) == errors.SOURCE_LINK
    upload_path(vol).unlink()
    folder = vol.root / "input" / "studio-e0"
    folder.rmdir()
    (tmp_path / "elsewhere").mkdir()
    (tmp_path / "elsewhere" / NAME).write_bytes(DATA)
    folder.symlink_to(tmp_path / "elsewhere")
    assert refused(lambda: reader(vol).fetch_upload(SHA, ".png")) == errors.VOLUME_UNEXPECTED


def test_a_fifo_folder_hard_link_or_oversized_upload_is_refused(vol):
    os.mkfifo(upload_path(vol))
    assert refused(lambda: reader(vol).fetch_upload(SHA, ".png")) == errors.SOURCE_NOT_REGULAR
    upload_path(vol).unlink()
    upload_path(vol).mkdir()
    assert refused(lambda: reader(vol).fetch_upload(SHA, ".png")) == errors.SOURCE_NOT_REGULAR
    upload_path(vol).rmdir()
    vol.add_upload(NAME, DATA)
    os.link(upload_path(vol), vol.root / "input" / "second-name.png")
    assert refused(lambda: reader(vol).fetch_upload(SHA, ".png")) == errors.SOURCE_HARD_LINK
    (vol.root / "input" / "second-name.png").unlink()
    with open(upload_path(vol), "r+b") as handle:
        handle.truncate(wan_volume.MAX_UPLOAD_BYTES + 1)
    assert refused(lambda: reader(vol).fetch_upload(SHA, ".png")) == errors.SOURCE_TOO_LARGE


def test_an_upload_with_other_bytes_is_a_mismatch(vol):
    vol.add_upload(NAME, DATA + b"!")
    assert refused(lambda: reader(vol).fetch_upload(SHA, ".png")) == errors.SOURCE_HASH_MISMATCH


def test_no_read_leaves_a_file_on_the_volume_changed(vol):
    vol.add_job(JOB, DATA)
    vol.add_upload(NAME, DATA)
    before = {p: (p.lstat().st_ino, p.lstat().st_mtime_ns, p.read_bytes() if p.is_file() else None)
              for p in sorted(vol.root.rglob("*"))}
    reader(vol).fetch_job_output(JOB, SHA)
    reader(vol).fetch_upload(SHA, ".png")
    refused(lambda: reader(vol).fetch_job_output(JOB, "0" * 64))
    after = {p: (p.lstat().st_ino, p.lstat().st_mtime_ns, p.read_bytes() if p.is_file() else None)
             for p in sorted(vol.root.rglob("*"))}
    assert after == before


# The client's own checks ---------------------------------------------------------------------


class Answer:
    def __init__(self, result):
        self.result, self.calls = result, []

    def run(self, command):
        self.calls.append(command)
        return self.result


def test_the_client_checks_the_hash_and_size_again():
    assert refused(lambda: VolumeReader(Answer(Completed(0, DATA + b"x"))).fetch_job_output(
        JOB, SHA)) == errors.SOURCE_HASH_MISMATCH
    big = b"\0" * (wan_volume.MAX_UPLOAD_BYTES + 1)
    assert refused(lambda: VolumeReader(Answer(Completed(0, big))).fetch_upload(
        hashlib.sha256(big).hexdigest(), ".png")) == errors.SOURCE_TOO_LARGE


def test_kubectls_exit_line_after_a_refusal_is_not_the_snippets():
    """kubectl exec ends stderr with this line when the pod's command exits non-zero."""
    trailer = b"REFUSED missing\ncommand terminated with exit code 3\n"
    assert refused(lambda: VolumeReader(Answer(Completed(3, b"", trailer))).fetch_job_output(
        JOB, SHA)) == errors.SOURCE_MISSING
    other = b"REFUSED missing\ncommand terminated with exit code 1\n"  # not this status
    assert refused(lambda: VolumeReader(Answer(Completed(3, b"", other))).fetch_job_output(
        JOB, SHA)) == errors.COMMAND_FAILED
    ledger = AdapterError(errors.COMMAND_FAILED, "x", "exited 1", returncode=1, redacted_stderr=(
        "no asset with that sha256 in the ledger\ncommand terminated with exit code 1"))
    assert ledger_fetch_refusal(ledger) == errors.SOURCE_MISSING


def test_the_fake_volume_adds_kubectls_line_like_the_real_exec(vol):
    runner = FakeRunner(vol)
    with pytest.raises(AdapterError) as caught:
        VolumeReader(runner).fetch_upload(SHA, ".png")
    assert caught.value.redacted_stderr.endswith("REFUSED missing\ncommand terminated with exit code 3")
    assert caught.value.code == errors.SOURCE_MISSING


@pytest.mark.parametrize("result", [
    Completed(1, b"", b"error: unable to upgrade connection: Forbidden\n"),
    Completed(3, b"", b"REFUSED something_else\n"),
    Completed(1, b"", b"REFUSED missing\n"),  # not the snippet's exit status
    Completed(3, b"", b"REFUSED missing\ntrailing text\n"),
    Completed(137, b"", b""),
])
def test_any_other_failure_is_not_a_refusal(result):
    with pytest.raises(AdapterError) as caught:
        VolumeReader(Answer(result)).fetch_job_output(JOB, SHA)
    assert caught.value.code == errors.COMMAND_FAILED


def test_a_changed_snippet_is_refused_before_anything_runs():
    runner = FailingRunner()
    item = pinned.load("wan_upload_read.py")
    with pytest.raises(PinMismatch):
        VolumeReader(runner, upload_snippet=pinned.PinnedInput(item.name, item.data + b"\n"))
    client = VolumeReader(runner)
    out = pinned.load("wan_job_output_read.py")
    client.output_snippet = pinned.PinnedInput(out.name, out.data + b"#")
    with pytest.raises(PinMismatch):
        client.fetch_job_output(JOB, SHA)
    assert runner.calls == []


def test_the_command_is_the_pinned_snippet_with_validated_arguments():
    command = VolumeReader(FailingRunner()).job_output_command(JOB, SHA)
    assert command.argv[:12] == ("kubectl", "exec", "-i", "-n", "ai", "deploy/wan-video", "-c",
                                 "api", "--", "python3", "-I", "-c")  # isolated mode
    assert command.argv[12] == pinned.load("wan_job_output_read.py").text
    assert command.argv[13:] == (JOB, SHA) and command.stdin == b""
    assert command.timeout_s == wan_volume.OUTPUT_TIMEOUT_S
    upload = VolumeReader(FailingRunner()).upload_command(SHA, ".wav")
    assert upload.argv[13:] == (SHA[:16] + ".wav", SHA)
    # The other clients' commands are unchanged: the ledger reader has no -I.
    assert "-I" not in LedgerReader(FailingRunner()).fetch_command("c" * 32, SHA).argv


# The ledger reader's refusals, read by their fixed messages ------------------------------------


def test_every_ledger_message_is_one_the_pinned_snippet_prints():
    text = pinned.load("wan_ledger_fetch.py").text
    built = "SystemExit(('asset' if asset else 'ledger') + ' is not a regular file')"
    assert built in text
    for message in wan_volume.LEDGER_FETCH_MESSAGES:
        assert f"SystemExit('{message}')" in text or message.endswith(" is not a regular file"), \
            message
    said = set(re.findall(r"SystemExit\('([^']+)'\)", text))
    assert said - {"invalid ledger id or sha256"} <= set(wan_volume.LEDGER_FETCH_MESSAGES)
    client = inspect.getsource(wan_ledger.LedgerReader.fetch_asset)
    for message in wan_volume.LEDGER_CLIENT_MESSAGES:
        assert f'"{message}"' in client


def _ledger(vol, data=DATA, ledger_id="c" * 32, kind="edited_production"):
    path = "/workspace/output/productions/synthetic-r1/line-1.wav"
    doc = {"id": ledger_id, "kind": kind, "assets": [{"path": path, "bytes": len(data),
                                                       "sha256": SHA}]}
    vol.add_ledger(doc, {SHA: data})
    return vol.path(path)


def fetch(vol, ledger_id="c" * 32):
    return lambda: LedgerReader(FakeRunner(vol)).fetch_asset(ledger_id, SHA)


def refusal_of(call):
    with pytest.raises(AdapterError) as caught:
        call()
    return ledger_fetch_refusal(caught.value)


def test_ledger_fetch_reads_through_the_fake_volume(vol):
    _ledger(vol)
    assert fetch(vol)().data == DATA


def test_ledger_fetch_refusals_are_named(vol, tmp_path):
    assert refusal_of(fetch(vol)) == errors.SOURCE_MISSING  # no ledger: FileNotFoundError
    asset = _ledger(vol)
    asset.unlink()
    assert refusal_of(fetch(vol)) == errors.SOURCE_MISSING  # no file: FileNotFoundError
    asset.write_bytes(DATA + b"!")
    assert refusal_of(fetch(vol)) == errors.SOURCE_HASH_MISMATCH
    asset.unlink()
    asset.mkdir()
    assert refusal_of(fetch(vol)) == errors.SOURCE_NOT_REGULAR
    asset.rmdir()
    asset.write_bytes(DATA)
    os.link(asset, tmp_path / "second")
    assert refusal_of(fetch(vol)) == errors.SOURCE_HARD_LINK
    (tmp_path / "second").unlink()
    asset.unlink()
    asset.symlink_to(tmp_path / "second")
    (tmp_path / "second").write_bytes(DATA)
    assert refusal_of(fetch(vol)) == errors.SOURCE_OUTSIDE  # resolves out of productions
    asset.unlink()
    with open(asset, "wb") as handle:
        handle.truncate(wan_ledger.MAX_ASSET_BYTES + 1)
    assert refusal_of(fetch(vol)) == errors.SOURCE_TOO_LARGE


def test_ledger_fetch_refuses_a_ledger_that_is_a_link_not_a_delivery_or_not_json(vol, tmp_path):
    _ledger(vol)
    jobs = vol.root / "jobs"
    (jobs / ("d" * 32 + ".json")).symlink_to(jobs / ("c" * 32 + ".json"))
    assert refusal_of(fetch(vol, "d" * 32)) == errors.SOURCE_LINK  # ELOOP from O_NOFOLLOW
    (tmp_path / "out.json").write_text("{}")
    (jobs / ("e" * 32 + ".json")).symlink_to(tmp_path / "out.json")
    assert refusal_of(fetch(vol, "e" * 32)) == errors.SOURCE_OUTSIDE
    _ledger(vol, ledger_id="f" * 32, kind="video")
    assert refusal_of(fetch(vol, "f" * 32)) == errors.SOURCE_RECORD_INVALID
    (jobs / ("f" * 32 + ".json")).write_text("{not json")
    assert refusal_of(fetch(vol, "f" * 32)) == errors.SOURCE_RECORD_INVALID
    other = hashlib.sha256(b"other").hexdigest()
    with pytest.raises(AdapterError) as caught:
        LedgerReader(FakeRunner(vol)).fetch_asset("c" * 32, other)
    assert ledger_fetch_refusal(caught.value) == errors.SOURCE_MISSING  # not in the ledger


def test_ledger_client_checks_are_named():
    assert refusal_of(lambda: LedgerReader(Answer(Completed(0, DATA + b"x"))).fetch_asset(
        "c" * 32, SHA)) == errors.SOURCE_HASH_MISMATCH


@pytest.mark.parametrize("error", [
    AdapterError(errors.TIMEOUT, "wan_ledger.fetch_asset", "no answer"),
    AdapterError(errors.COMMAND_FAILED, "x", "exited 1", returncode=1,
                 redacted_stderr="error: pods is forbidden"),
    AdapterError(errors.COMMAND_FAILED, "x", "exited 2", returncode=2,
                 redacted_stderr="no asset with that sha256 in the ledger"),
    AdapterError(errors.COMMAND_FAILED, "x", "exited 1", returncode=1,
                 redacted_stderr="PermissionError: [Errno 13] Permission denied"),
    AdapterError(errors.RESPONSE_INVALID, "x", "answer is not JSON"),
    AdapterError(errors.PIN_MISMATCH, "x", "changed"),
])
def test_any_other_ledger_failure_is_not_a_refusal(error):
    assert ledger_fetch_refusal(error) is None
