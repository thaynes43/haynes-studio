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
        # a password with a slash, in a URL that is not an exact environment value
        "postgresql://u:sec/retextra@127.0.0.1/studio_test":
            "postgresql://u:<redacted>@127.0.0.1/studio_test",
        # conninfo quoting: doubled and escaped quotes, double quotes with a space
        "host=db password='it''s quotedtail' dbname=x": "host=db password=<redacted> dbname=x",
        "host=db password='it\\'s tail' dbname=x": "host=db password=<redacted> dbname=x",
        'host=db password="my tail-secret" dbname=x': "host=db password=<redacted> dbname=x",
        # compact JSON: a port is not a password, and the match never crosses a quote
        '{"url":"http://h:8080/p","mail":"x@y"}': '{"url":"http://h:8080/p","mail":"x@y"}',
        # a port, a path and a later @ are not a password
        "see https://example.invalid:8080/hook?mail=dev@example.invalid now":
            "see https://example.invalid:8080/hook?mail=dev@example.invalid now",
        "https://[::1]:8080/health": "https://[::1]:8080/health",
        # double quotes with an escaped or doubled quote inside
        'host=db password="say \\"tail-secret9\\"" dbname=x':
            "host=db password=<redacted> dbname=x",
        'host=db password="say ""tail-secret9" dbname=x': "host=db password=<redacted> dbname=x",
    }
    for text, expected in cases.items():
        assert policy.redact(text, environ) == expected


def test_redaction_survives_a_sensitive_value_that_is_a_keyword():
    environ = {"DB_PASSWORD": "password"}
    clean = policy.redact("host=localhost password=SuperSecret9 dbname=studio_test", environ)
    assert "SuperSecret9" not in clean
    assert clean.endswith("=<redacted> dbname=studio_test")


def test_redaction_hides_a_whole_database_url_value():
    environ = {"STUDIO_TEST_DATABASE_URL": "postgresql://u:hunter22@db.internal/studio_test"}
    text = "cannot reach postgresql://u:hunter22@db.internal/studio_test now"
    assert policy.redact(text, environ) == "cannot reach <redacted> now"


@pytest.mark.parametrize("value", ["canary\nleakXXXX", "canary\\leakXY", "it's canary-token"])
def test_redaction_covers_the_forms_pytest_prints(value):
    environ = {"STUDIO_FAKE_TOKEN": value}
    lines = "\n".join(f"+ {line}" for line in value.splitlines())
    report = f"AssertionError: assert {value!r} == 'nope'\n{lines}\nraw {value}"
    clean = policy.redact(report, environ)
    for piece in value.splitlines():
        if len(piece) >= 8:
            assert piece not in clean
    assert repr(value)[1:-1] not in clean


def test_checkout_guard_ignores_git_environment(tmp_path, monkeypatch):
    root = tmp_path / "checkout"
    root.mkdir()
    _git(root, "init", "--quiet")
    (root / "render.out").write_text("oops\n", encoding="utf-8")
    for name in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
        monkeypatch.setenv(name, str(tmp_path / "elsewhere"))
    assert policy.checkout_snapshot(root) == frozenset({"?? render.out"})


def test_checkout_guard_keeps_the_git_it_started_with(tmp_path, monkeypatch):
    root = tmp_path / "checkout"
    root.mkdir()
    _git(root, "init", "--quiet")
    assert policy.checkout_snapshot(root) == frozenset()
    fake = tmp_path / "bin"
    fake.mkdir()
    (fake / "git").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    (fake / "git").chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake}{os.pathsep}{os.environ['PATH']}")
    (root / "render.out").write_text("oops\n", encoding="utf-8")
    assert policy.checkout_snapshot(root) == frozenset({"?? render.out"})


def test_url_password_match_is_bounded():
    # The scan after "scheme://user:" stops at 256 characters, so it stays linear on a
    # long token (compact JSON with many URLs took quadratic time before the bound).
    covered = f"http://u:{'x' * 256}@host/db"
    assert policy.redact(covered, {}) == "http://u:<redacted>@host/db"
    beyond = f"http://u:{'x' * 257}@host/db"
    assert policy.redact(beyond, {}) == beyond


@pytest.mark.parametrize(("environ", "text"), [
    ({"DB_PASSWORD": "my tail-secret"}, "host=db password=my tail-secret dbname=x"),
    ({"DB_PASSWORD": "my\ttail-secret"}, "host=db password=my\ttail-secret dbname=x"),
    ({"STUDIO_TEST_DATABASE_URL": "postgresql://u:my tail-secret@db.internal/studio_test"},
     "host=db password=my tail-secret dbname=x"),
    ({"STUDIO_TEST_DATABASE_URL": "postgresql://u:sec/retextra9@db.internal/studio_test"},
     "connect failed for user u with sec/retextra9 on 127.0.0.1"),
])
def test_a_spaced_or_embedded_password_is_not_split(environ, text):
    clean = policy.redact(text, environ)
    assert "tail-secret" not in clean and "retextra9" not in clean
    assert "dbname=x" in clean or "127.0.0.1" in clean


def test_redaction_covers_a_value_that_a_report_shortened():
    token = "PREFIXLEAK" + "B" * 500
    environ = {"STUDIO_FAKE_TOKEN": token}
    shortened = "assert 'PREFIXLEAKBB...BBBBBBBBBBBBB' == 'nope'"
    assert policy.redact(shortened, environ) == "assert '<redacted>...<redacted>' == 'nope'"
    cut = "E     + " + token[:40]
    assert policy.redact(cut, environ) == "E     + <redacted>"


def test_a_database_url_does_not_strip_ordinary_words():
    environ = {"STUDIO_TEST_DATABASE_URL": "postgresql://postgres@localhost:5432/studio_test"}
    text = "tests/db/test_round_trip.py::test_server_is_postgres_16 in studio_test"
    assert policy.redact(text, environ) == text
