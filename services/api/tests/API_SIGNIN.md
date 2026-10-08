# SEC-15 / SIGNIN: app sign-in with Google (Firebase Authentication) and anonymous demo sessions (what the acceptance tests pin)

Source: PRD 6 platform row "Firebase Authentication: Google sign-in and anonymous demo sessions"; PRD supplement
SEC-15 (visitor or judge, enforced server-side); PRD 16.1 (Tilo never handles passwords); PRD R-06; FR-UX-10 (account
menu: Sign out); BQ-XWORLD-10 (`Principal.full_session`). Decisions: anonymous demo sessions yes; the OAuth consent
screen goes **In production** (user, 7 Oct; BQ-SIGNIN-1). Choices the PRD does not make are BQ-SIGNIN-1..7 in
`docs/open-questions.md`. Tests (all fail until built):

| Where | File |
| --- | --- |
| API verifier, user id mapping, Principal | `services/api/tests/test_SEC_15_SIGNIN_firebase_verifier.py` (helpers `_signin_lib.py`) |
| API 401 matrix, dev mode, SEC-15 gate end to end | `services/api/tests/test_SEC_15_SIGNIN_principal.py` |
| Web controller over the Firebase Auth SDK (faked) | `apps/web/src/auth/auth.SIGNIN.test.ts` |
| Web sign-in gate and panel | `apps/web/src/auth/SignInGate.SIGNIN.test.tsx` |
| Bearer header on every API call | `apps/web/src/api/http.authToken.SIGNIN.test.ts` |
| Sign out in the account menu | `apps/web/src/park/shell/AccountMenu.signOut.SIGNIN.test.tsx` |
| Gmail consent: unverified-app sentence | `apps/web/src/screens/S_08.unverified.SIGNIN.test.tsx` |
| Setup sheet in `infra/ACCESS.md`, Hosting CSP, static web rules | `tests/repo/test_SEC_15_SIGNIN_docs_and_csp.py` |

## New code the tests name

API (`services/api/src/tilo_api/firebase_auth.py`, beside `appcheck.py`, same cache / single-flight / cooldown pattern):
`FirebaseIdTokenVerifier(project, *, fetch, clock, wall).verify(token)`, `TokenRefused(code)`, `JWKS_URL`,
`ISSUER_PREFIX`, `MAX_TOKEN_CHARS`, `user_id_for(uid)`, `principal_from_claims(claims, *, channel)`; and in `deps`:
`get_firebase_verifier()`, with `get_current_principal(request)` (or the PROD-WIRE `resolve_principal(request)` it
delegates to) reading `Authorization: Bearer`. `AccessGate._decide` must hand the request to the resolver.
Web (`apps/web/src/auth/`): `auth.ts` (`createAuth`), `session.ts` (`session`), `SignInGate.tsx`; `authToken` getter
in `api/ClientProvider.tsx` handed to `chooseClient`, `parkApi`, `createLiveApi`, `HttpClient`.

## The Gmail consent sentence (S-08, before the redirect to Google)

Because the consent screen is In production without Google verification of the restricted Gmail scopes, Google shows its
unverified-app warning on every Gmail consent (capped at 100 new users until verified). When the consent card is for
the `gmail` connector, the S-08 sheet shows this exact text in one element with `data-testid="consent-unverified-note"`,
placed before the Connect and Hold buttons, and not for connectors Google does not flag (Drive):

> Google will show a warning that this app is not verified, because Google has not finished reviewing Tilo's access to Gmail. Tilo asks only for the access listed above. To continue, choose Advanced on Google's page, then continue to Tilo.

The Park Connectors page's Connect is page-local state today (no connect endpoint yet); when it starts the live Gmail
OAuth redirect it must show the same sentence first.

## User console checklist (the sheet pinned in `infra/ACCESS.md`, section 11, in order)

1. Firebase console, project `essential-wares-510320-f0`, Authentication: Get started.
2. Sign-in method: enable the Google provider (public-facing name, support email), save.
3. Sign-in method: enable the Anonymous provider (demo sessions). Never enable Email/Password.
4. Settings, Authorized domains: `essential-wares-510320-f0.web.app` and `essential-wares-510320-f0.firebaseapp.com` listed.
5. Google Cloud console, Credentials, the Firebase web key: API restriction = Firebase App Check API, Identity Toolkit API,
   Token Service API (keep the referrer restrictions; still no Gemini API).
6. OAuth consent screen: publishing status In production (Testing is the fallback).
7. Later owner step: start Google verification for the restricted Gmail scopes.
8. Redeploy hosting (CSP and sign-in code), then check sign-in on the deployed host.
