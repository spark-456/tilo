# apps/web

The Tilo web client: React 18, TypeScript, Vite 6 and PixiJS 8. It is served by Firebase Hosting and talks only to
`tilo-api` over HTTP.

## Run

```sh
just setup      # once: uv sync + pnpm install + git hooks
just dev        # Vite dev server (a fixture / replay world: no backend needed)
just dev-api    # in a second terminal: tilo-api in dev mode on 127.0.0.1:8080
```

With `VITE_TILO_API_URL` unset the app uses a fixture client, so every page works from recorded data. Set it (for example
`VITE_TILO_API_URL=http://127.0.0.1:8080`) to use the real API. `just e2e-cp2` starts both for a browser walk.

The two other build-time variables are `VITE_FIREBASE_API_KEY` and `VITE_FIREBASE_PROJECT_ID`, baked in only by
`scripts/web_build_env.py` (see [docs/deploy-dev.md](../../docs/deploy-dev.md)); without them sign-in reads as
"unavailable" and App Check is off.

## How it talks to the backend

- **HTTP only.** There is no Firestore client in this app (it imports only `firebase/app`, `app-check` and `auth`), and
  `firestore.rules` denies all client access. A world's events are read by polling `GET /worlds/{id}/events` by sequence
  number (about once a second, with backoff).
- **Auth.** Firebase Google sign-in; the ID token goes in `Authorization: Bearer`. App Check (reCAPTCHA Enterprise) adds
  `X-Firebase-AppCheck`. "Explore a demo town" signs in anonymously and swaps in the fixture client, so a demo session
  replays recorded runs and is labelled as such.
- **Clients.** `src/api/` (`HttpClient`, `FixtureClient`) and the Park layer in `src/park/api/` (32 methods, live and
  fixture implementations).

## Source map (`src/`)

| Folder | What it holds |
| --- | --- |
| `park/` | the app: `pages/` (Home, Chat, Worlds, World, Skills, Needs, Ledger, Agenda, Team, Profile, Connectors, Settings, Library), `shell/` (top nav, account menu), `api/`, `app/` (router, state), `components/` (primitives), `engines/` (SVG art for the city and thumbnails) |
| `world/` | the event pipeline: `registry.generated.ts` (from `contracts/events/registry.yaml`) -> `reducer.ts` -> `store.ts` -> `frame.ts` -> `renderer.ts`; `choreographer.ts` is the only code allowed to animate |
| `worldView/`, `stage/` | the routed lenses (stage, Story, Trace, Delivery, Inspect) and the PixiJS stage with its camera |
| `auth/`, `appcheck/`, `oauth/` | sign-in gate, App Check, the connector OAuth callback |
| `landing/`, `onboarding/`, `needs-you/`, `results/`, `legal/` | signed-out landing page, first-run flow, approval cards, document and website preview, legal pages |
| `design/`, `styles/`, `display/` | generated tokens, CSS, density and stage-mode switches |
| `honesty/` | static tests that enforce the honesty rules |

Routing is a small hand-rolled History API router (`src/park/app/router.ts`, `src/router.ts`), not a library. `/park/<page>`
is an alias of every root page.

## The world and the honesty rules

The World page, Story and Trace are three views of the same recorded events. Nothing animates without a recorded event
(PRD 9.4 HR-1 to HR-7): the Pixi stage draws a frame only on input, a camera move or a recorded event, with no
always-on ticker; moves are cosmetic and capped at 2 s; unknown event types appear in Trace only; replays carry a banner
and any time compression a speed badge. `src/honesty/*.test.ts` scans the source for requestAnimationFrame, intervals,
`.animate(`, tween libraries and ticker use. Home and background city motion is decoration and the one exception.

Recorded runs: `?fixture=village-basic` plays `contracts/fixtures/streams/village-basic.jsonl`; more fixtures are in
`apps/web/fixtures/`.

## Design tokens

```sh
just tokens     # design/tokens.json -> src/styles/tokens.css, src/design/tokens.ts; config/themes/*.json -> Park themes
```

Themes are `metropolis`, `neutral` and `studio` (the default). `design/source/` and `design_handoff_tilo_web_app/` are
read-only design exports used as references.

## Mobile, PWA and push

The layout is responsive (a phone cut-off at 767 px, a compact nav at 840 px). `public/manifest.webmanifest` makes it
installable. The only service worker, `public/push-sw.js`, shows push notifications and caches nothing: there is no
offline mode. Push is enabled by the person's own click on the Profile page (`/v1/push/subscribe`).

## Tests

```sh
pnpm --filter @tilo/web run test              # Vitest: unit tests beside their source (<name>.<TICKET-ID>.test.tsx)
pnpm --filter @tilo/web run typecheck
TILO_WEB_PORT=5410 pnpm --filter @tilo/web run test:e2e   # Playwright; give each run its own port
just smoke-hosted https://essential-wares-510320-f0.web.app   # signed-out and demo smoke on the deployed site
```

`just check` runs Vitest and `tsc` but not Playwright; the end-to-end specs in `e2e/` are run by hand. See
[CLAUDE.md](CLAUDE.md) and [src/park/CLAUDE.md](src/park/CLAUDE.md) for requirement IDs and local rules.
