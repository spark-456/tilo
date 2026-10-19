// FR-UX-10 / SEC-15 (BQ-WEB-UX10): the Park shell's view of the page's one sign-in controller (`auth/session`). Park may
// reuse only the `src/api` seam, so this is how the account menu learns who is signed in and ends the session. The shape
// is the shell's `ParkAuth` (park/shell/auth.tsx), written out here so `src/api` imports nothing from park/.
// `null` means there is no sign-in on this page (a local host, the fixture world, a build with no Firebase config, or the
// SDK has not answered yet): the shell then keeps its prototype behaviour. An anonymous demo session is shown as
// "Demo session"; the person's details are never copied anywhere, only read for display.
import { useMemo, useSyncExternalStore } from "react";
import { session } from "../auth/session";
import { finishSession } from "./signOut";

export interface SessionAuthUser {
  displayName: string | null;
  email: string | null;
  isAnonymous: boolean;
}

export interface SessionAuth {
  status: "loading" | "signedOut" | "signedIn";
  user: SessionAuthUser | null;
  signInWithGoogle(): Promise<unknown>;
  signInAnonymously(): Promise<unknown>;
  /** Resolves once the session really ended; rejects when the SDK refused (the person is still signed in). */
  signOut(): Promise<void>;
}

export const DEMO_NAME = "Demo session";

async function signOut(): Promise<void> {
  if (!(await finishSession())) throw new Error("sign_out_failed");
}

export function useSessionAuth(): SessionAuth | null {
  const state = useSyncExternalStore(session.subscribe, session.getState);
  const status = state.status;
  const name = state.status === "google" ? state.displayName : null;
  const email = state.status === "google" ? state.email : null;
  return useMemo(() => {
    if (status === "unavailable" || status === "unknown") return null;
    return {
      status: status === "signed_out" ? "signedOut" : "signedIn",
      user:
        status === "google"
          ? { displayName: name, email, isAnonymous: false }
          : status === "anonymous"
            ? { displayName: DEMO_NAME, email: null, isAnonymous: true }
            : null,
      signInWithGoogle: () => session.signInWithGoogle(),
      signInAnonymously: () => session.signInAnonymously(),
      signOut,
    } satisfies SessionAuth;
  }, [status, name, email]);
}
