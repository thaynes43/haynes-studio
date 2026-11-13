"""Fixture policy: synthetic media at test time, outside the checkout; the checkout guard."""

from __future__ import annotations

import os
import subprocess
import wave

import pytest

from tests.support import policy, synthetic


def test_synthetic_wav_is_made_under_tmp_path(synthetic_wav, tmp_path):
    assert synthetic_wav.parent == tmp_path.resolve()
    assert policy.REPO_ROOT not in synthetic_wav.parents
    with wave.open(str(synthetic_wav), "rb") as clip:
        assert (clip.getnchannels(), clip.getsampwidth(), clip.getframerate()) == (1, 2, 16_000)
        assert clip.getnframes() == 16_000
    assert synthetic_wav.stat().st_size < 64 * 1024


def test_synthetic_media_refuses_the_checkout_and_long_clips(tmp_path):
    with pytest.raises(ValueError, match="outside the checkout"):
        synthetic.write_sine_wav(policy.REPO_ROOT / "tests" / "tone.wav")
    with pytest.raises(ValueError, match="0 to 10 s"):
        synthetic.write_sine_wav(tmp_path / "long.wav", seconds=10.5)
    assert not (policy.REPO_ROOT / "tests" / "tone.wav").exists()


def _git(root, *args):
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


def test_checkout_guard_reports_new_and_changed_files(tmp_path):
    root = tmp_path / "checkout"
    root.mkdir()
    _git(root, "init", "--quiet")
    (root / ".gitignore").write_text("*.wav\n", encoding="utf-8")
    (root / "kept.txt").write_text("one\n", encoding="utf-8")
    _git(root, "add", "kept.txt", ".gitignore")
    before = policy.checkout_snapshot(root)
    assert before is not None

    (root / "out").mkdir()
    (root / "out" / "render.txt").write_text("new\n", encoding="utf-8")
    (root / "clip.wav").write_bytes(b"RIFF")  # ignored files count too
    (root / "kept.txt").write_text("two\n", encoding="utf-8")
    (root / "pkg" / "__pycache__").mkdir(parents=True)
    (root / "pkg" / "__pycache__" / "mod.cpython-311.pyc").write_bytes(b"")
    (root / ".pytest_cache").mkdir()
    (root / ".pytest_cache" / "README.md").write_text("cache\n", encoding="utf-8")

    added = policy.checkout_changes(before, policy.checkout_snapshot(root))
    assert added == ["!! clip.wav", "?? out/render.txt", "AM kept.txt"]


def test_checkout_guard_is_off_outside_a_checkout_top(tmp_path):
    assert policy.checkout_snapshot(tmp_path) is None
    if (policy.REPO_ROOT / ".git").exists():
        assert policy.checkout_snapshot(policy.REPO_ROOT / "tests") is None
        assert policy.checkout_snapshot(policy.REPO_ROOT) is not None


def test_thread_limits_cap_and_keep_smaller_values():
    environ = {"STUDIO_THREADS": "8", "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "x"}
    assert policy.apply_thread_limits(environ) == {
        "STUDIO_THREADS": "2", "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1",
    }
    for name, limit in policy.THREAD_LIMITS.items():
        assert 1 <= int(os.environ[name]) <= limit


def test_redaction_hides_secret_values_and_passwords():
    environ = {"STUDIO_FAKE_TOKEN": "canary-token-value", "HOME": "/home/someone"}
    cases = {
        "got canary-token-value in /home/someone": "got <redacted> in /home/someone",
        "postgresql://user:hunter22@db:5432/studio_test":
            "postgresql://user:<redacted>@db:5432/studio_test",
        "postgresql://user:p@ss@db/studio_test": "postgresql://user:<redacted>@db/studio_test",
        "postgresql://postgres@localhost:5432/studio_test":
            "postgresql://postgres@localhost:5432/studio_test",
        "host=db password=hunter22 dbname=studio_test":
            "host=db password=<redacted> dbname=studio_test",
        "host=db password = 'a secret' dbname=x": "host=db password = <redacted> dbname=x",
        "https://example.invalid:8080/path": "https://example.invalid:8080/path",
    }
    for text, expected in cases.items():
        assert policy.redact(text, environ) == expected
