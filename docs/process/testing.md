# Testing

How to run, add and extend the tests. The suites, markers and limits are fixed by
[section 14 of the contract](../contracts/studio-contracts-v1.md#14-test-contract) and the
stack by [section 13](../contracts/studio-contracts-v1.md#13-stack-pin); this page is the
working detail. Story [424](https://work.haynesnetwork.com/work_packages/424) built it.

## Commands

From the repository root, one suite at a time:

| Suite | Command | Needs | Where |
|---|---|---|---|
| `source` (default) | `uv run pytest` | nothing: no network, credentials, GPU, Postgres or media | session pods and CI |
| `db` | `uv run pytest -m db` | `STUDIO_TEST_DATABASE_URL` (below) | CI; anywhere with a disposable PostgreSQL 16 |
| `browser` | `cd web && pnpm test:e2e` | Playwright's Chromium | CI; locally where installed |
| `live` | `uv run pytest -m live --live-story=<id>` | a story that authorizes it, and its service | never in CI; opt-in only |

First-time setup:

```sh
UV_PYTHON_DOWNLOADS=never uv sync --locked --python 3.11   # session pods: system Python 3.11
cd web && pnpm install --frozen-lockfile                   # only for the browser suite
```

`uv sync --locked` fails if `uv.lock` is stale; after changing dependencies in
`pyproject.toml`, run `uv lock` and commit both files. Python is 3.11 or 3.12
(`requires-python = ">=3.11,<3.13"`); write nothing 3.12-only. uv never downloads an
interpreter (`python-downloads = "never"`). Do not run `playwright install` in a
session pod; the browser suite is proven in CI.

Useful options: `-m db --require-db` fails instead of skipping when the database URL
is unset (the CI `db` job uses it, so it cannot pass on skipped tests);
`uv run pytest tests/contracts` runs one folder.

## Suites

- **`source`**: everything not marked `db` or `live`. It includes the
  contract-example harness, the fixture policy and the plugin's own tests. `db` tests
  are collected and **skipped with their reason** when `STUDIO_TEST_DATABASE_URL` is
  unset; `live` tests are skipped unless asked for.
- **`db`**: tests marked `@pytest.mark.db`, using the `studio_db` or `db_conn`
  fixture. A test that uses either fixture without the marker is a usage error, so
  it cannot fall outside both the `source` and `db` jobs.
- **`browser`**: Playwright specs in `web/e2e/`. Today one smoke opens the committed
  mockup [`docs/design/studio-ui-mockup/index.html`](../design/studio-ui-mockup/index.html)
  and checks that it renders with no script error and no network request. The web app
  (E6) adds its own specs here.
- **`live`**: tests marked `@pytest.mark.live(story=<id>)`. They run only with
  exactly `-m live --live-story=<id>` naming that story, and never when `CI` or
  `GITHUB_ACTIONS` is set; any other `-m` with `--live-story`, or a live test
  without `story=`, is a usage error. A live run writes to a new private job
  directory and stops at its story's caps.

## Limits

- `STUDIO_THREADS=2`, `OMP_NUM_THREADS=2`, `OPENBLAS_NUM_THREADS=1`: the pytest plugin
  sets them before collection (a smaller value you set stays). Pass ffmpeg
  `-threads 2` and render `--workers 1` in tests.
- Serial: pytest-xdist is disabled (`-p no:xdist`); Playwright runs `workers: 1` with
  no retries; Vitest, when the web app adds it, runs `--maxWorkers=2`.
- One suite at a time in a session pod. Timing tests use fake clocks, never sleeps or
  retry loops.

## Output

Failures print codes and paths, not data: the harness fails with one line per problem
and no traceback. The plugin also redacts failure text, collection errors and captured
output: values (8 characters or more) of environment variables whose names contain
`TOKEN`, `SECRET`, `PASSWORD`, `API_KEY`, `DATABASE_URL` and similar, any
`scheme://user:password@` password and any conninfo `password=` value become
`<redacted>`. Output a test prints under `-s` is not captured, so it is not redacted.
Never print `os.environ` or a connection string in a test.

## Fixture policy

- **Committed fixtures are text only:** the public manifests and evidence JSON, and the
  contract examples. `scripts/checks/check_no_media.py` still runs.
- **Synthetic media is made at test time** under pytest's `tmp_path`, outside the
  checkout, 10 s or less (360x640 for images unless a test needs delivery size). For
  audio use the `synthetic_wav` fixture (a 1 s, 16 kHz mono tone) or
  `tests.support.synthetic.write_sine_wav(tmp_path / "x.wav", seconds=...)`; both
  refuse a path in the checkout and a clip over 10 s. Use the standard library unless
  the story has already locked a media library.
- **Service fakes** (TTS, ASR, image, Wan, store) return deterministic synthetic bytes;
  frozen responses are JSON with hashes.
- **Checkout guard:** the plugin snapshots `git status` (untracked, ignored and changed
  files) when the session starts and fails the session if anything new appears by the
  end, listing each path. `__pycache__/` and `.pytest_cache/` are exempt. An ignored
  directory that already exists (`.venv/`, `web/node_modules/`, an old `/jobs/`) is
  one entry, so files added inside it are not seen; a new directory is. The guard is
  off when the rootdir is not the top of a git checkout; the header line
  `studio checkout guard:` says which. Playwright writes its results to the OS temp
  directory for the same reason.

## Disposable Postgres (`db`)

`STUDIO_TEST_DATABASE_URL` must name a PostgreSQL 16 database whose name starts with
`studio_test`, for example `postgresql://postgres@localhost:5432/studio_test`. It is
never `database/postgres16`.

- The fixture reads the database name from the URL before connecting and refuses a
  URL without one (libpq would fall back to `PGDATABASE` or the user name) or with any
  other name; it checks the connected database name again before its first statement.
- `studio_db` (session scope) creates one fresh schema, `studio_test_` plus 16 random
  hex digits, with `CREATE SCHEMA` (never adopting an existing one), and drops only
  that schema with `DROP SCHEMA ... CASCADE` when the session ends.
- `db_conn` (per test) is a psycopg 3 connection with `search_path` set to that schema
  and a 30 s statement timeout; it is rolled back after the test.
- The URL never appears in a repr, a header or a failure; CI uses trust
  authentication, so its URL has no password.

## Contract examples

`tests/contracts/test_examples.py` checks every file under
[`docs/contracts/examples/`](../contracts/examples/):

- `test_example_shape`: the file is strict JSON (no duplicate keys, no `NaN`) and an
  object of a known type (a `schema` of `studio.<type>/v<major>` with a section 2 type,
  `v1` for a valid example; the legacy manifest, detected by `shots`, `frame` and
  `job`; or the section 12 error envelope). An invalid case has exactly the
  `studio.invalid-case/v1` wrapper fields, a JSON Pointer `path`, a `rule` in the
  [rule index](../contracts/studio-contracts-v1.md#15-rule-index), an `expect` that
  matches that rule's status, and context `queue_run` when the status says the rule
  fires at queue. The index's example links must point at cases that declare the
  rule.
- `test_example_validates`: if `tests/contracts/registry.py` has a validator for the
  example's type, a valid example must validate and an invalid case must fail with
  exactly its `rule` and `expect`. A malformed example fails here too, never pending.
  With no validator the test reports **PENDING**
  (letter `P`), the summary counts it as `pending`, never `passed` or `skipped`, and a
  closing **contract validators pending** section lists every pending type by name.

A problem reads `<path>: rule <code>: <check>: <message>`, for example
`docs/contracts/examples/invalid/time-negative.json: rule time.negative: validator.mismatch: expected exactly time.negative in context write, got schema.unknown_field (invalid) at /colour`.
A wrong example is reported to the contract's owner, not edited by a test story.

### Register a validator

The story that lands a type's schema and validator (378: `legacy.manifest`; 404:
`production`, `story`, `board`, `story-timing`, `method-capabilities`; later stories
the rest) adds one entry to `VALIDATORS` in `tests/contracts/registry.py` in the same
PR:

```python
from haynes_studio.contracts import validate_board  # the story's own module

VALIDATORS = {
    "board": validate_board,
}
```

The harness calls `validator(document, context=...)`:

- `context` is `read` for a valid example (a document as the server returns it, so
  `derived` fields are present), and the case's `write` or `queue_run` for an invalid
  case. A `queue_run` case must return nothing blocking in `write` (the document saves)
  and exactly its rule in `queue_run`.
- It returns an iterable of violations: objects with `rule`, `status` and `path`
  attributes (`tests.contracts.harness.Violation` is one) or `(rule, status, path)`
  tuples. `status` is `invalid`, `unavailable`, `forbidden` or `warning`; warnings
  never fail a document. An empty result means valid.
- If the product API differs, register a small adapter function in `registry.py`
  rather than changing the harness.

Keys are the names in `harness.ALL_TYPES`; a key outside it fails
`test_registry_keys_are_known_types`. Once registered, every example of the type
must pass, so a story registers a type only when all its examples do.

## Add a test

- Put source tests in `tests/<area>/test_*.py` (each folder has an `__init__.py`); use
  `tmp_path` for every file a test writes.
- Mark database tests `@pytest.mark.db` and use `db_conn`; mark service tests
  `@pytest.mark.live(story=<id>)`. Unknown markers fail (`--strict-markers`), and
  warnings are errors.
- Shared helpers go in `tests/support/`. The policy plugin is
  `tests/support/plugin.py`; its own tests run inner sessions with `pytester`.
- Browser specs go in `web/e2e/*.spec.ts`; `pnpm typecheck` checks them.
- A runtime library (numpy, PyAV and the rest of section 13) is added by the story
  that first needs it, to `[project].dependencies`, with `uv lock`.

## CI

[`.github/workflows/tests.yml`](../../.github/workflows/tests.yml) runs on every pull
request and on pushes to `main`, with a read-only token and no secrets. Actions are
pinned by commit SHA. The checks, by exact name:

| Check | What it runs |
|---|---|
| `source (3.11)` | `uv sync --locked`, then `uv run pytest` on Python 3.11 |
| `source (3.12)` | the same on Python 3.12 |
| `db` | `uv run pytest -m db --require-db` against a `postgres:16` service container |
| `browser` | `pnpm install --frozen-lockfile`, `pnpm typecheck`, then `pnpm test:e2e` on Chromium (headless shell) |
| `check-links` | [`check-links.yml`](../../.github/workflows/check-links.yml): relative Markdown links |
| `check-syntax` | [`check-syntax.yml`](../../.github/workflows/check-syntax.yml): PoC Python, title, graph and contract-example JSON |
| `Check no media` | [`check-no-media.yml`](../../.github/workflows/check-no-media.yml): no media or weights in git |

The coordinator chooses which checks are required; the Claude review
(`claude-code-review.yml`) is advisory and never required.
