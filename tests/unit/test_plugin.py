"""The pytest policy plugin, run against small inner test sessions (pytester, in-process)."""

from __future__ import annotations

import textwrap

import pytest

PLUGIN = ("-p", "tests.support.plugin")
INNER = textwrap.dedent("""
    import os
    import pytest

    @pytest.mark.db
    def test_db():
        pass

    @pytest.mark.live(story=512)
    def test_live():
        pass

    def test_plain():
        assert os.environ["STUDIO_THREADS"] == "2"
        assert os.environ["OPENBLAS_NUM_THREADS"] == "1"
""")


@pytest.fixture
def inner(pytester, monkeypatch):
    monkeypatch.delenv("STUDIO_TEST_DATABASE_URL", raising=False)
    monkeypatch.setenv("STUDIO_THREADS", "16")
    pytester.makepyfile(test_inner=INNER)
    return pytester


def test_db_and_live_skip_with_reasons_by_default(inner):
    result = inner.runpytest(*PLUGIN, "-rs")
    result.assert_outcomes(passed=1, skipped=2)
    result.stdout.fnmatch_lines([
        "studio limits: STUDIO_THREADS=2 OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=1*",
        "*SKIPPED*db: STUDIO_TEST_DATABASE_URL is unset*studio_test*",
        "*SKIPPED*live: runs only with -m live --live-story=<id>*",
    ])


def test_require_db_turns_the_skip_into_an_error(inner):
    result = inner.runpytest(*PLUGIN, "-m", "db", "--require-db")
    assert result.ret == pytest.ExitCode.USAGE_ERROR
    result.stderr.fnmatch_lines(["*--require-db: STUDIO_TEST_DATABASE_URL is unset*"])


def test_live_needs_marker_expression_and_matching_story(inner):
    result = inner.runpytest(*PLUGIN, "--live-story=512")
    assert result.ret == pytest.ExitCode.USAGE_ERROR
    result.stderr.fnmatch_lines(["*--live-story needs -m live*"])

    result = inner.runpytest(*PLUGIN, "-m", "live", "--live-story=512")
    result.assert_outcomes(passed=1, deselected=2)

    result = inner.runpytest(*PLUGIN, "-m", "live", "--live-story=999", "-rs")
    result.assert_outcomes(skipped=1, deselected=2)
    result.stdout.fnmatch_lines(["*live: authorized by story 512, not --live-story=999*"])


def test_live_test_must_name_its_story(pytester):
    pytester.makepyfile(test_unnamed="""
        import pytest

        @pytest.mark.live
        def test_unnamed():
            pass
    """)
    result = pytester.runpytest(*PLUGIN)
    assert result.ret == pytest.ExitCode.USAGE_ERROR
    result.stderr.fnmatch_lines(["*@pytest.mark.live needs story=<tracker story number>*"])


def test_failure_output_is_redacted(pytester, monkeypatch):
    monkeypatch.setenv("STUDIO_FAKE_TOKEN", "canary-token-5d1e")
    pytester.makepyfile(test_leak="""
        import os

        def test_leak():
            token = os.environ["STUDIO_FAKE_TOKEN"]
            print("captured", token, "postgresql://u:pw-canary-77@h/studio_test")
            assert token == "something else"
    """)
    result = pytester.runpytest(*PLUGIN, "--showlocals")
    result.assert_outcomes(failed=1)
    output = result.stdout.str()
    assert "<redacted>" in output
    assert "canary-token-5d1e" not in output and "pw-canary-77" not in output


def test_session_that_writes_into_the_checkout_fails(pytester, monkeypatch):
    import subprocess

    subprocess.run(["git", "init", "--quiet", str(pytester.path)], check=True,
                   capture_output=True)
    pytester.makepyfile(test_writes="""
        from pathlib import Path

        def test_writes():
            Path(__file__).with_name("render.out").write_text("oops")
    """)
    result = pytester.runpytest(*PLUGIN, "-p", "no:cacheprovider")
    result.assert_outcomes(passed=1)
    assert result.ret == pytest.ExitCode.TESTS_FAILED
    result.stdout.fnmatch_lines([
        "*checkout guard: the session changed the checkout*",
        "*?? render.out*",
    ])
