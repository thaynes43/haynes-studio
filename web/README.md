# Studio web app

The static Storyboard UI from [story 413](https://work.haynesnetwork.com/work_packages/413).
The [v6 mockup](../docs/design/studio-ui-mockup/index.html) is the interaction reference.

```sh
cd web
pnpm install --frozen-lockfile
pnpm typecheck
pnpm test
pnpm exec playwright install --only-shell chromium
pnpm test:e2e
```

Playwright builds and serves `dist/` on loopback, runs one Chromium worker and mocks
the Studio API and login redirects. It also opens the standalone mockup. Results
go to the OS temp directory. The 400 × 860 and 1280 × 900 tests assert the actual
layout, navigation and focus. `pnpm build` emits the static app for story 433.
The [behaviour matrix](../docs/reference/web-behaviour-matrix.md) maps the specs
and documents the separate, opt-in installed playback check.

## Routes and state

- `/productions` and `/editor/board` share a hierarchy of production ID, media
  kind, story ID and optional `boards/<id>`. The editor also has `photo` under a
  board and `runs` and `runs/compare` under a story.
- `/editor` opens the Editor landing. `/editor/assets` and `/editor/assets/generate`
  accept a production filter, or a full production/media/story/board filter.
  Breadcrumb buttons remove the descendant context.
- `/settings/user` shows the current display name and theme. `/settings/admin`
  is a placeholder.

The API supplies identity and navigation records. It stores the per-user
destinations in `GET /v1/me/selections` → `values.web_shell`, with
`productions`, `board` and `assets` keys. Writes preserve other keys and send
the returned `ETag` as `If-Match`. A stale revision gets one
refetch and rebase. Backstage theme is a device preference, with Dark as the
fallback when local storage is blocked or invalid.

Deployment serves the SPA routes from `index.html` and forwards `/v1/` and
`/auth/` on the same HTTPS origin. The API sets the session cookie. The client
reads the CSRF value from `/v1/me` into memory and adds it to unsafe API calls.
When a request returns 401, the shell drops signed-in state and prompts for
sign-in at the same URL. The API callback redirects to `/`; tab storage keeps
a validated return route for that round trip. If tab storage is blocked, the
callback opens Productions.

## OpenAPI types

`pnpm generate:api` runs `uv run --locked studio-api openapi` from the repository
root and generates `src/api/schema.ts` with the locked `openapi-typescript`.
Commit the generated file alongside API changes. The browser CI job checks
that it matches the repository's OpenAPI output. Run the generator from the
repository root.

```sh
pnpm --dir web generate:api
```

For a local comparison with another API revision, pass the path to its exported
OpenAPI JSON.
