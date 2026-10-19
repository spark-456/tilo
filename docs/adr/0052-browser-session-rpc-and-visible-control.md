# ADR-0052: Browser session RPC and visible control

- Status: Accepted (owner approval, 19 Oct 2026)
- Extends ADR-0051; requirements FR-CON-07, FR-CON-08, FR-AGT-03 and HR-1 to HR-7.

## Decision

`tilo-browser` owns an isolated, allowlisted session. An authenticated internal RPC starts and ends a session and performs one validated action at a time: navigate, click, type, scroll or extract. Each result reports the target box (or the viewport for an action without an element target) and a masked screenshot artifact. The service masks password, card and one-time-code fields before a frame can leave its process. Tilo never enters credentials.

The browse-step executor records each successful action as `browser.acted`, using the existing browser event family and fixtures. The World and skill-run browser panels derive their frame, caption and AI cursor target solely from those recorded events. Pause and Stop are explicit controls; a clock alone never advances the cursor.

Live tilo-api calls the internal RPC at `TILO_BROWSER_URL` with a Google ID token. Tilo-browser accepts it only when `TILO_BROWSER_AUDIENCE` matches that URL and `TILO_BROWSER_CALLERS` names the API service account; unset values deny the session routes.

Code assigns risk by the action and inspected element, not by model output. Reading and searching an allowlisted page are T1. Submitting, posting, sending, buying and signing in require a person's T3 gate before any side effect; the first release closes the session and links the person to the site for manual continuation. No approval resumes that action automatically. The existing allowlisted egress policy applies to navigation, redirects and subresources. No public unauthenticated route is added.

## Consequences

The RPC can be exercised with a fake browser in CI. The panel can replay the same recorded events as a live run. Session state is process local, so a deployment must pin the browser service to one instance until session routing exists. A session lost on restart ends safely, and sites that require blocked third-party hosts may render incompletely.
