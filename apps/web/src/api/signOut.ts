// SEC-15 / FR-UX-10: the one way the Park shell ends the page's real sign-in session (Park may reuse only the
// `src/api` seam, so the shell reaches the sign-in controller through here). Returns false when there is no session to
// end (a local host, the fixture world, a build with no Firebase config): the caller keeps the prototype's behaviour.
// The controller's sign-out never rejects. Once the session is really over the page is loaded afresh at "/": the
// module-level HTTP clients, their caches and polls belong to the person who just left, and nothing of them may serve
// the next person on a shared machine (BQ-SIGNIN-4). A sign-out the SDK refused (`signOutFailed`) loads nothing: the
// SDK still holds the person, so a full load would restore them; the sign-in gate says so in plain words instead.
// The gate takes it from there.
import { hasSession } from "../auth/auth";
import { session } from "../auth/session";
import { livePushFlow } from "./pushEnv";

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

/** FR-CHN-17d: this browser's push subscription is the person's, so it goes before they do (best effort,
 * two seconds at most; none in the fixture world, a demo or a browser that never turned it on). */
function releasePush(): Promise<void> | null {
  const flow = livePushFlow();
  if (flow === null) return null;
  return Promise.race([flow.release(), new Promise<void>((done) => setTimeout(done, 2000))]);
}

/** Signs the page's session out. Resolves true after loading "/" afresh when the session really ended, false when the
 * SDK refused (nothing is loaded). Rejects only if the controller itself throws. */
export async function finishSession(): Promise<boolean> {
  const releasing = releasePush();
  if (releasing !== null) await releasing;
  await session.signOut();
  const state = session.getState();
  const ended = state.status === "signed_out" && state.signOutFailed !== true;
  if (ended) {
    forgetPerson();
    window.location.assign("/");
  }
  return ended;
}

export function endSession(): boolean {
  if (!hasSession(session.getState())) return false;
  finishSession().catch(() => undefined);
  return true;
}
