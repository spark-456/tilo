// SEC-15 / FR-UX-10: the one way the Park shell ends the page's real sign-in session (Park may reuse only the
// `src/api` seam, so the shell reaches the sign-in controller through here). Returns false when there is no session to
// end (a local host, the fixture world, a build with no Firebase config): the caller keeps the prototype's behaviour.
// The controller's sign-out never rejects. Once the session is really over the page is loaded afresh at "/": the
// module-level HTTP clients, their caches and polls belong to the person who just left, and nothing of them may serve
// the next person on a shared machine (BQ-SIGNIN-4). The sign-in gate takes it from there.
import { hasSession } from "../auth/auth";
import { session } from "../auth/session";

export function endSession(): boolean {
  if (!hasSession(session.getState())) return false;
  session
    .signOut()
    .then(() => {
      if (session.getState().status === "signed_out") window.location.assign("/");
    })
    .catch(() => undefined);
  return true;
}
