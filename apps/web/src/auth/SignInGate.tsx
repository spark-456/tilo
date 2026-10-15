// SEC-15 / SIGNIN: the app sits behind this gate. "unavailable" (a local host, the fixture world, a build with no
// Firebase config) shows the app and no sign-in UI at all, so dev, tests and the fixture deploy work as before
// (EFF-01); "unknown" (the SDK has not answered) shows nothing, so nothing flashes; "signed_out" shows the panel
// and not the app (the Park sign-in screen, SignInScreen); "google" or "anonymous" shows the app. Tilo never handles passwords: Google signs the person
// in, in its own window, and the panel has no field and no form (PRD 16.1). Neutral role tokens only.
import { type ReactNode, useRef, useState, useSyncExternalStore } from "react";
import { SignInScreen } from "./SignInScreen";
import type { AuthController, SignInResult } from "./auth";

const FAILED = "Signing in did not work. Please try again.";
const SIGN_OUT_FAILED =
  "Signing out did not finish, so your session may still be open on this device. Close this browser window to be sure.";

export function SignInGate({
  auth,
  children,
}: {
  readonly auth: AuthController;
  readonly children: ReactNode;
}) {
  const state = useSyncExternalStore(auth.subscribe, auth.getState);
  if (state.status === "unavailable" || state.status === "google" || state.status === "anonymous") {
    return <>{children}</>;
  }
  if (state.status === "unknown") return null;
  return (
    <SignInPanel
      auth={auth}
      signOutFailed={state.signOutFailed === true}
      join={window.location.pathname === "/join"}
    />
  );
}

function SignInPanel({
  auth,
  signOutFailed,
  join,
}: { readonly auth: AuthController; readonly signOutFailed: boolean; readonly join: boolean }) {
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  // A ref, not the state: two clicks in one batch both see the same render, and only one sign-in may start.
  const running = useRef(false);

  const run = (start: () => Promise<SignInResult>): void => {
    if (running.current) return;
    running.current = true;
    setBusy(true);
    setFailed(false);
    start().then(
      (result) => {
        running.current = false;
        setBusy(false);
        setFailed(!result.ok && result.reason !== "cancelled");
      },
      () => {
        running.current = false;
        setBusy(false);
        setFailed(true);
      },
    );
  };

  if (join)
    return (
      <main
        data-park
        data-testid="join-sign-in"
        style={{
          width: "100%",
          maxWidth: "390px",
          boxSizing: "border-box",
          padding: "20px",
          overflowWrap: "anywhere",
        }}
      >
        <h1>Join a team</h1>
        <p>You've been invited to join a team on Tilo.</p>
        <button
          type="button"
          className="primary"
          disabled={busy}
          onClick={() => run(() => auth.signInWithGoogle())}
        >
          Continue with Google
        </button>
        {failed ? <p role="alert">{FAILED}</p> : null}
      </main>
    );
  return (
    <SignInScreen
      busy={busy}
      failed={failed}
      failedText={FAILED}
      signOutFailedText={signOutFailed ? SIGN_OUT_FAILED : null}
      onGoogle={() => run(() => auth.signInWithGoogle())}
      onDemo={() => run(() => auth.signInAnonymously())}
    />
  );
}
