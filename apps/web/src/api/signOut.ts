// SEC-15 / FR-UX-10: the one way the Park shell ends the page's real sign-in session (Park may reuse only the
// `src/api` seam, so the shell reaches the sign-in controller through here). Returns false when there is no session to
// end (a local host, the fixture world, a build with no Firebase config): the caller keeps the prototype's behaviour.
// The controller's sign-out never rejects. Once the session is really over the page is loaded afresh at "/": the
// module-level HTTP clients, their caches and polls belong to the person who just left, and nothing of them may serve
// the next person on a shared machine (BQ-SIGNIN-4). The sign-in gate takes it from there.
import { hasSession } from "../auth/auth";
import { session } from "../auth/session";

/** The Home composer's remembered Quick / Thinking choice (park/pages/Home/effortStore.ts): the person's, not the next one's. */
const EFFORT_KEYS = "tilo.park.effort.";

function forgetPerson(): void {
  try {
    for (const key of Object.keys(window.localStorage)) {
      if (key.startsWith(EFFORT_KEYS)) window.localStorage.removeItem(key);
    }
  } catch {
    // storage absent or blocked: nothing was kept there
  }
}

export function endSession(): boolean {
  if (!hasSession(session.getState())) return false;
  session
    .signOut()
    .then(() => {
      if (session.getState().status === "signed_out") {
        forgetPerson();
        window.location.assign("/");
      }
    })
    .catch(() => undefined);
  return true;
}
