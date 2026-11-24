# Studio images

Story [433](https://work.haynesnetwork.com/work_packages/433) defines two
`linux/amd64` images for story [434](https://work.haynesnetwork.com/work_packages/434).
The [Studio images workflow](../../.github/workflows/studio-images.yml) builds and
smokes both on every pull request and on `main`. The `main` publish job loads the
same image archives that passed the smoke tests and pushes them to GHCR.

## Images and digests

| Package | Lookup tag | UID:GID | Port | Default command |
| --- | --- | --- | --- | --- |
| `ghcr.io/thaynes43/haynes-studio` | `sha-<full commit>` | `10001:10001` | `8000` | `studio-api serve --host 0.0.0.0 --port 8000` |
| `ghcr.io/thaynes43/haynes-studio-web` | `sha-<full commit>` | `101:101` | `8080` | `/usr/sbin/nginx -g 'daemon off;'` |

Use the full merged commit SHA. The workflow summary under **Publish tested Studio
images** records each registry digest alongside that revision. You can also resolve
both tags at the registry.

```sh
revision=$(git rev-parse origin/main)
for name in studio studio-web; do
  repository="ghcr.io/thaynes43/$name"
  digest=$(docker buildx imagetools inspect "$repository:sha-$revision" \
    --format '{{.Manifest.Digest}}') || exit 1
  printf '%s@%s\n' "$repository" "$digest"
done
```

Pin the `repository@sha256:...` references in haynes-ops. PRs build the checked-out
PR merge revision and report local build digests. Registry digests come from a
successful `main` publish. The `org.opencontainers.image.revision` label records
the checkout SHA and `org.opencontainers.image.source` links the package to the
repository.

GHCR documents first publication with the publishing repository's `GITHUB_TOKEN`
when the job grants `packages: write`. A new package starts private. As of
2026-11-24, neither Studio package was visible to anonymous pulls, and the
target `ai` namespace's default service account had no pull secret. The existing
public `ghcr.io/thaynes43/dev-env` image is the cluster precedent. After the first
successful `main` publish, the package owner needs to set both packages to
**Public** in their GHCR package settings for the same anonymous pull path.
If either name already belongs to an unlinked package and GHCR refuses the push,
the package owner needs to grant `thaynes43/haynes-studio` **Write** under that
package's **Manage Actions access**. Verify anonymous access to both published
digests before story 434 uses them.
[GitHub Container Registry](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry)
[GitHub package access settings](https://docs.github.com/en/packages/learn-github-packages/configuring-a-packages-access-control-and-visibility)

## Runtime configuration

Set a read-only root filesystem and mount a writable `/tmp` for each container.
The Python image uses `/tmp` for `HOME` and `TMPDIR`. It disables bytecode writes.
The nginx image keeps its PID and temporary paths under `/tmp` and logs to stdout
and stderr. Its web root and configuration can stay read-only.

| Process | Required environment | Optional environment | Probe or completion |
| --- | --- | --- | --- |
| API | `STUDIO_DATABASE_URL`, `STUDIO_STORE_ROOT`, `STUDIO_PUBLIC_ORIGIN`, `STUDIO_OIDC_ISSUER`, `STUDIO_OIDC_CLIENT_ID`, `STUDIO_OIDC_CLIENT_SECRET`, `STUDIO_OIDC_ALLOWED_SUBJECTS` | `STUDIO_DATABASE_SCHEMA`, `STUDIO_STORE_FRESHNESS_SECONDS`, `STUDIO_OIDC_LEEWAY_SECONDS`, `STUDIO_OIDC_CACHE_TTL_SECONDS`, `STUDIO_OIDC_FAILURE_TTL_SECONDS`, `STUDIO_SESSION_SECONDS` | `GET /healthz` returns 204. `GET /readyz` returns 204 when PostgreSQL and the store are ready. |
| Migration Job | `STUDIO_MIGRATION_DATABASE_URL` | `STUDIO_DATABASE_SCHEMA`, default `studio`. Match the API and precreate it. | Run `studio-api-migrate upgrade head`. Exit status 0 is success. |
| Web | None | None | `GET /index.html` on port 8080 returns 200. |

See [Studio API](studio-api.md#environment) for values and defaults. Mount the
shared D39 store at `STUDIO_STORE_ROOT` with write access for UID 10001 so the API
can perform its store readiness check and publish blobs. The migration Job and
web container need no store mount. The two PostgreSQL identities belong to their
respective processes. The web ingress sends `/v1/` and `/auth/` to the API
on the same origin. The web container returns 404 for those paths and serves
the SPA for UI routes. HTML is served with `Cache-Control: no-store`. Hashed Vite
assets use a one-year immutable cache policy.

Override the Python image's command for `studio` or the migration Job. MCP and
queue worker commands can use the same image once their package entry points and
runtime settings land. Run entry points directly from the installed environment.
The final filesystem contains the package, its migrations, runtime libraries and
the bundled ffmpeg executable. Build tooling, wheel test media and the unused
SciPy Sobol sample tables are excluded.

## Build inputs and smoke checks

The Dockerfiles pin their base images by digest. The Python build uses CPython
3.12 and uv 0.13.6. `uv sync --locked --no-dev` installs the runtime dependencies
and a separate, hash-constrained Hatchling build installs Studio's wheel. Node 24
builds the web app with the pnpm version pinned in `web/package.json` and
`pnpm install --frozen-lockfile`. CI uses the checkout's commit timestamp as
`SOURCE_DATE_EPOCH` and rewrites exported layer timestamps.

The workflow checks the image labels and user IDs, then scans both runtime
filesystems for the repository's prohibited media extensions and credential
filenames. The certifi HTTPS trust bundle must contain only public X.509
certificates. The Python smoke runs the CLI, imports the installed dependencies,
loads TLS trust, runs OpenAPI generation and migrates a disposable PostgreSQL 16
database. The web smoke verifies the HTML, SPA fallback, cache headers and
reserved path 404s. Both smoke tests use read-only root filesystems.
