"""Pinned graphs and snippets: every file has its recorded hash, a changed one is
refused before anything runs, and no client reads another checkout."""

from __future__ import annotations

import ast
import hashlib
from importlib.resources import files

import pytest

from haynes_studio.adapters import pinned
from haynes_studio.adapters.comfyui import ImageClient
from haynes_studio.adapters.errors import PinMismatch
from haynes_studio.adapters.fakes import FakeComfyUI, FakeKokoro, FakeRunner, FakeWanLedger
from haynes_studio.adapters.kokoro import KokoroClient, SpeechRequest
from haynes_studio.adapters.wan_ledger import LedgerReader
from haynes_studio.adapters.whisper import WhisperClient
from tests.support.policy import REPO_ROOT

FOLDER = files("haynes_studio.adapters").joinpath(pinned.FOLDER)
PACKAGE = REPO_ROOT / "src" / "haynes_studio"


def test_folder_holds_exactly_the_pinned_files():
    assert sorted(item.name for item in FOLDER.iterdir()) == sorted(pinned.PINS)


@pytest.mark.parametrize("name", sorted(pinned.PINS))
def test_each_file_has_its_pinned_hash(name):
    data = FOLDER.joinpath(name).read_bytes()
    assert hashlib.sha256(data).hexdigest() == pinned.PINS[name].sha256
    assert pinned.load(name).sha256 == pinned.PINS[name].sha256


@pytest.mark.parametrize("name", sorted(n for n, p in pinned.PINS.items() if p.kind == "snippet"))
def test_snippets_are_python_for_the_pod(name):
    ast.parse(pinned.load(name).text)  # valid Python, never imported or run here


@pytest.mark.parametrize("name", sorted(pinned.PINS))
def test_a_changed_copy_is_refused_on_load(tmp_path, name):
    data = pinned.load(name).data
    (tmp_path / name).write_bytes(data.replace(b"127.0.0.1", b"127.0.0.2", 1) + b"\n")
    with pytest.raises(PinMismatch) as caught:
        pinned.load(name, root=tmp_path)
    assert caught.value.expected == pinned.PINS[name].sha256


def test_an_unknown_or_renamed_file_is_refused():
    with pytest.raises(PinMismatch):
        pinned.load("other.json")
    item = pinned.load("kokoro_tts.py")
    with pytest.raises(PinMismatch):
        pinned.check(item, "whisper_asr.py")


def _changed(name):
    item = pinned.load(name)
    return pinned.PinnedInput(name, item.data + b"\n# changed\n")


@pytest.mark.parametrize("make", [
    lambda: KokoroClient(FakeRunner(), snippet=_changed("kokoro_tts.py")),
    lambda: WhisperClient(FakeRunner(), snippet=_changed("whisper_asr.py")),
    lambda: ImageClient(FakeRunner(), prompt_snippet=_changed("comfyui_prompt.py")),
    lambda: ImageClient(FakeRunner(), queue_snippet=_changed("comfyui_queue.py")),
    lambda: ImageClient(FakeRunner(), t2i_graph=_changed("qwen_image_2_1_t2i_API.json")),
    lambda: ImageClient(FakeRunner(), edit_graph=_changed("qwen_image_2_1_edit_API.json")),
    lambda: LedgerReader(FakeRunner(), read_snippet=_changed("wan_ledger_read.py")),
    lambda: LedgerReader(FakeRunner(), list_snippet=_changed("wan_ledger_list.py")),
    lambda: LedgerReader(FakeRunner(), fetch_snippet=_changed("wan_ledger_fetch.py")),
])
def test_clients_refuse_a_changed_input(make):
    with pytest.raises(PinMismatch):
        make()


def test_a_snippet_changed_after_construction_is_refused_before_running():
    runner = FakeRunner(FakeKokoro(), FakeComfyUI(), FakeWanLedger())
    client = KokoroClient(runner)
    client.snippet = _changed("kokoro_tts.py")
    with pytest.raises(PinMismatch):
        client.synthesize(SpeechRequest("af_heart", "x"))
    reader = LedgerReader(runner)
    reader.list_snippet = _changed("wan_ledger_list.py")
    with pytest.raises(PinMismatch):
        reader.list()
    assert runner.calls == []


def test_no_adapter_code_reads_another_checkout_or_home():
    for path in (PACKAGE / "adapters").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for needle in ("haynes-ops/kubernetes", "repos/haynes-ops", "Path.home", "expanduser",
                       "os.environ", "getenv"):
            assert needle not in text, f"{path.relative_to(REPO_ROOT)}: {needle}"


def test_only_the_runner_module_uses_subprocess():
    for path in (PACKAGE / "adapters").glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        names |= {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
        if path.name != "runner.py":
            assert "subprocess" not in names, path.name
