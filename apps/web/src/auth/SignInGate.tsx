// SEC-15 / SIGNIN: the app sits behind this gate. "unavailable" (a local host, the fixture world, a build with no
// Firebase config) shows the app and no sign-in UI at all, so dev, tests and the fixture deploy work as before
// (EFF-01); "unknown" (the SDK has not answered) shows nothing, so nothing flashes; "signed_out" shows the panel
// and not the app; "google" or "anonymous" shows the app. Tilo never handles passwords: Google signs the person
// in, in its own window, and the panel has no field and no form (PRD 16.1). Neutral role tokens only.
import { type ReactNode, useState, useSyncExternalStore } from "react";
import type { AuthController, SignInResult } from "./auth";

const FAILED = "Signing in did not work. Please try again.";

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
  return <SignInPanel auth={auth} />;
}

function SignInPanel({ auth }: { readonly auth: AuthController }) {
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);

  const run = (start: () => Promise<SignInResult>): void => {
    if (busy) return;
    setBusy(true);
    setFailed(false);
    start().then(
      (result) => {
        setBusy(false);
        setFailed(!result.ok && result.reason !== "cancelled");
      },
      () => {
        setBusy(false);
        setFailed(true);
      },
    );
  };

  return (
    <main className="screen-body" data-testid="sign-in">
      <h1>Sign in to Tilo</h1>
      <p>
        Sign in with your Google account, or look around in a demo session. Google handles the
        sign-in in its own window.
      </p>
      <div className="need-actions">
        <button
          type="button"
          className="primary"
          disabled={busy}
          aria-busy={busy ? "true" : undefined}
          onClick={() => run(() => auth.signInWithGoogle())}
        >
          Sign in with Google
        </button>
        <button
          type="button"
          className="secondary"
          disabled={busy}
          onClick={() => run(() => auth.signInAnonymously())}
        >
          Try a demo session
        </button>
      </div>
      {failed && (
        <p className="need-error" role="alert">
          {FAILED}
        </p>
      )}
    </main>
  );
}
