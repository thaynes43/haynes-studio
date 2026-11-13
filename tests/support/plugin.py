"""pytest policy for haynes-studio (docs/process/testing.md, contract section 14).

- Thread variables are capped before collection; the run is serial (no xdist).
- ``db`` tests skip with a reason unless STUDIO_TEST_DATABASE_URL is set;
  ``--require-db`` turns that skip into a usage error, so a CI job cannot pass
  green on skipped database tests.
- ``live`` tests run only with ``-m live --live-story=<id>``, and only those whose
  ``@pytest.mark.live(story=<id>)`` names that story.
- The checkout guard fails the session if it adds a file to the checkout.
- Failure text and captured output are redacted: values of token, secret and
  database-URL variables, and URL passwords, never reach the log.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from tests.support import database, policy, synthetic

_GUARD_BEFORE = pytest.StashKey[frozenset]()
_GUARD_ADDED = pytest.StashKey[list]()
_LIVE_HELP = "live: runs only with -m live --live-story=<id> (docs/process/testing.md)"
MARKERS = (
    f"db: needs {database.URL_ENV} to a disposable PostgreSQL 16 database whose name "
    f"starts with {database.DATABASE_PREFIX}; skipped with a reason when unset",
    "live(story): calls a real service; runs only with -m live --live-story=<id> "
    "naming the story that authorizes it; never in CI",
)


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("haynes-studio")
    group.addoption(
        "--live-story", metavar="ID", default=None,
        help="run the live tests that this tracker story authorizes; needs -m live",
    )
    group.addoption(
        "--require-db", action="store_true", default=False,
        help=f"fail instead of skipping db tests when {database.URL_ENV} is unset",
    )


@pytest.hookimpl(tryfirst=True)
def pytest_configure(config: pytest.Config) -> None:
    policy.apply_thread_limits()
    for marker in MARKERS:
        config.addinivalue_line("markers", marker)
    story = config.getoption("--live-story")
    if story is not None:
        if not story.isdigit():
            raise pytest.UsageError("--live-story takes a tracker story number, e.g. 512")
        if not config.getoption("markexpr"):
            raise pytest.UsageError("--live-story needs -m live")


def pytest_report_header(config: pytest.Config) -> list[str]:
    limits = " ".join(f"{name}={os.environ[name]}" for name in policy.THREAD_LIMITS)
    url_state = "set" if os.environ.get(database.URL_ENV) else "unset, db tests skip"
    story = config.getoption("--live-story")
    return [
        f"studio limits: {limits}; serial, no xdist",
        f"studio db: {database.URL_ENV} {url_state}",
        f"studio live: {'story ' + story if story else 'off'}",
    ]


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    url_set = bool(os.environ.get(database.URL_ENV))
    story = config.getoption("--live-story")
    for item in items:
        if item.get_closest_marker("db") and not url_set:
            if config.getoption("--require-db"):
                raise pytest.UsageError(f"--require-db: {database.URL_ENV} is unset")
            item.add_marker(pytest.mark.skip(reason=database.SKIP_REASON))
        live = item.get_closest_marker("live")
        if live is None:
            continue
        owner = live.kwargs.get("story", live.args[0] if live.args else None)
        if owner is None or not str(owner).isdigit():
            raise pytest.UsageError(
                f"{item.nodeid}: @pytest.mark.live needs story=<tracker story number>"
            )
        if story is None:
            item.add_marker(pytest.mark.skip(reason=_LIVE_HELP))
        elif str(owner) != story:
            item.add_marker(pytest.mark.skip(
                reason=f"live: authorized by story {owner}, not --live-story={story}"
            ))


# Checkout guard -------------------------------------------------------------


def pytest_sessionstart(session: pytest.Session) -> None:
    before = policy.checkout_snapshot(session.config.rootpath)
    if before is not None:
        session.config.stash[_GUARD_BEFORE] = before


def pytest_sessionfinish(session: pytest.Session) -> None:
    before = session.config.stash.get(_GUARD_BEFORE, None)
    if before is None:
        return
    after = policy.checkout_snapshot(session.config.rootpath) or frozenset()
    added = policy.checkout_changes(before, after)
    session.config.stash[_GUARD_ADDED] = added
    if added and session.exitstatus == pytest.ExitCode.OK:
        session.exitstatus = pytest.ExitCode.TESTS_FAILED


def pytest_terminal_summary(terminalreporter, config: pytest.Config) -> None:
    added = config.stash.get(_GUARD_ADDED, [])
    if not added:
        return
    terminalreporter.write_sep("=", "checkout guard: the session changed the checkout", red=True)
    for entry in added:
        terminalreporter.write_line(f"  {entry}")
    terminalreporter.write_line(
        "Tests write under tmp_path, never into the checkout (docs/process/testing.md)."
    )


# Redaction ------------------------------------------------------------------


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo):
    report = yield
    if report.longrepr is not None:
        if isinstance(report.longrepr, tuple):  # a skip: (path, line, reason)
            path, line, reason = report.longrepr
            report.longrepr = (path, line, policy.redact(reason))
        else:
            text = str(report.longrepr)
            clean = policy.redact(text)
            if clean != text:
                report.longrepr = clean
    report.sections = [(title, policy.redact(body)) for title, body in report.sections]
    return report


# Fixtures -------------------------------------------------------------------


@pytest.fixture
def synthetic_wav(tmp_path: Path) -> Path:
    """A one-second mono 16 kHz sine tone under the test's tmp_path."""
    return synthetic.write_sine_wav(tmp_path / "tone.wav")


@pytest.fixture(scope="session")
def studio_db() -> Iterator[database.StudioTestDatabase]:
    """A fresh schema in a disposable studio_test* database, dropped at session end."""
    url = os.environ.get(database.URL_ENV, "")
    if not url:
        pytest.skip(database.SKIP_REASON)
    try:
        dbname = database.check_url(url)
    except database.RefusedTarget as refused:
        pytest.fail(f"db: refused: {refused}", pytrace=False)

    import psycopg
    from psycopg import sql

    schema = database.new_schema_name()
    database.check_schema_name(schema)
    try:
        admin = psycopg.connect(url, autocommit=True, connect_timeout=10)
    except psycopg.Error as error:
        reason = policy.redact(str(error).splitlines()[0] if str(error) else "")
        pytest.fail(f"db: cannot connect to {dbname}: {type(error).__name__}: {reason}", pytrace=False)
    with admin:
        try:
            database.check_connection(admin)
        except database.RefusedTarget as refused:
            pytest.fail(f"db: refused after connecting: {refused}", pytrace=False)
        admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        try:
            yield database.StudioTestDatabase(dbname=dbname, schema=schema, url=url)
        finally:
            admin.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


@pytest.fixture
def db_conn(studio_db: database.StudioTestDatabase):
    """A connection with search_path set to the session schema; rolled back after the test."""
    import psycopg

    options = f"-c search_path={studio_db.schema} -c statement_timeout=30000"
    with psycopg.connect(studio_db.url, connect_timeout=10, options=options) as conn:
        database.check_connection(conn)
        try:
            yield conn
        finally:
            conn.rollback()
