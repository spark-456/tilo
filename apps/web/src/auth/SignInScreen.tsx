// The sign-in screen (SEC-15 / SIGNIN): the Park city behind a glass card with Google and a demo session. The card is
// drawn at once; the city is its own chunk and arrives behind it. Tilo never handles passwords: no field, no form
// (PRD 16.1). The two choices are real buttons; what they do is the gate's (`SignInGate`).
import { Component, type ReactNode, Suspense, lazy, useState } from "react";
import "./signin.css";

const SignInBackdrop = lazy(() => import("./SignInBackdrop"));

type Time = "day" | "night";

/** The city is decoration: if its chunk does not arrive (a deploy while the page is open, a dropped network) the
 * card stays and the page does not go blank. */
class QuietBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  render() {
    return this.state.failed ? null : this.props.children;
  }
}

function GoogleMark() {
  return (
    <svg width="20" height="20" viewBox="0 0 48 48" aria-hidden="true" focusable="false">
      <path
        fill="#EA4335"
        d="M24 9.5c3.5 0 6.6 1.2 9.1 3.6l6.8-6.8C35.8 2.4 30.3 0 24 0 14.6 0 6.5 5.4 2.6 13.2l7.9 6.1C12.4 13.6 17.7 9.5 24 9.5z"
      />
      <path
        fill="#4285F4"
        d="M46.5 24.5c0-1.6-.1-3.1-.4-4.5H24v9h12.7c-.6 3-2.3 5.5-4.8 7.2l7.5 5.8c4.4-4.1 7.1-10.1 7.1-17.5z"
      />
      <path
        fill="#FBBC05"
        d="M10.5 28.7c-.5-1.4-.8-3-.8-4.7s.3-3.3.8-4.7l-7.9-6.1C.9 16.4 0 20.1 0 24s.9 7.6 2.6 10.8l7.9-6.1z"
      />
      <path
        fill="#34A853"
        d="M24 48c6.5 0 11.9-2.1 15.9-5.8l-7.5-5.8c-2.1 1.4-4.8 2.3-8.4 2.3-6.3 0-11.6-4.1-13.5-9.8l-7.9 6.1C6.500 42.600 14.600 48 24 48z"
      />
    </svg>
  );
}

export function SignInScreen({
  busy,
  failed,
  failedText,
  signOutFailedText = null,
  onGoogle,
  onDemo,
}: {
  readonly busy: boolean;
  readonly failed: boolean;
  readonly failedText: string;
  /** A refused sign-out: the person is told their session may still be open (SIGNIN-FIX, #644). */
  readonly signOutFailedText?: string | null;
  readonly onGoogle: () => void;
  readonly onDemo: () => void;
}) {
  const [time, setTime] = useState<Time>("day");
  return (
    <main className="signin" data-testid="sign-in" data-time={time}>
      <div className="signin__city">
        <QuietBoundary>
          <Suspense fallback={null}>
            <SignInBackdrop time={time} />
          </Suspense>
        </QuietBoundary>
      </div>
      <button
        type="button"
        className="signin__toggle"
        aria-label={time === "day" ? "Switch to the night city" : "Switch to the day city"}
        onClick={() => setTime(time === "day" ? "night" : "day")}
      >
        <svg width="20" height="20" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
          {time === "day" ? (
            <path fill="currentColor" d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.800z" />
          ) : (
            <g fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
              <circle cx="12" cy="12" r="4" />
              <path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.900 4.900l1.400 1.400M17.700 17.700l1.400 1.400M4.900 19.100l1.400-1.400M17.700 6.300l1.400-1.400" />
            </g>
          )}
        </svg>
      </button>
      <div className="signin__card">
        <div className="signin__logo" aria-label="tilo" role="img">
          <div className="signin__mark">
            <div className="signin__visor">
              <div className="signin__dot" />
              <div className="signin__dot" />
            </div>
          </div>
          <div className="signin__word" aria-hidden="true">
            tilo
          </div>
        </div>
        <h1 className="signin__title">Sign in to your city</h1>
        <p className="signin__lead">
          Your agents keep working while you’re away. Sign in to see what needs you.
        </p>
        <button
          type="button"
          className="signin__btn"
          disabled={busy}
          aria-busy={busy ? "true" : undefined}
          onClick={onGoogle}
        >
          <GoogleMark />
          Continue with Google
        </button>
        <div className="signin__or" aria-hidden="true">
          OR
        </div>
        <button
          type="button"
          className="signin__btn signin__btn--demo"
          disabled={busy}
          onClick={onDemo}
        >
          <span aria-hidden="true">✦</span> Explore a demo session
        </button>
        <p className="signin__note">
          A sample company to explore. Demo sessions replay recorded runs.
        </p>
        {signOutFailedText ? (
          <p className="signin__error" role="alert" data-testid="sign-out-failed">
            {signOutFailedText}
          </p>
        ) : null}
        {failed && (
          <p className="signin__error" role="alert">
            {failedText}
          </p>
        )}
        <p className="signin__legal">
          By continuing you agree to Tilo’s <a href="/terms">Terms</a> and{" "}
          <a href="/privacy">Privacy Policy</a>.
        </p>
      </div>
    </main>
  );
}
