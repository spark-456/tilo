// SEC-15 / FR-UX-10: the one way the Park shell ends the page's real sign-in session (Park may reuse only the
// `src/api` seam, so the shell reaches the sign-in controller through here). Returns false when there is no session to
// end (a local host, the fixture world, a build with no Firebase config): the caller keeps the prototype's behaviour.
// The controller's sign-out never rejects; the sign-in gate takes the page from there.
import { hasSession } from "../auth/auth";
import { session } from "../auth/session";

export function endSession(): boolean {
  if (!hasSession(session.getState())) return false;
  session.signOut().catch(() => undefined);
  return true;
}
