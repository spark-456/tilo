// The signed-out page (SEC-15 / SIGNIN), in Studio (STUDIO-6, design/studio-v2 "Tilo S Landing"): a header, the hero
// with Google and a demo session, then the landing (a recorded replay of a sample run, how it works, safety, skills)
// in a chunk of its own. The hero is drawn at once; the landing arrives below it into a reserved box, so nothing
// above it moves (CLS) and the art engines stay off the entry bundle (NFR-01). Tilo never handles passwords: no
// field, no form (PRD 16.1). The buttons are real; what they do is the gate's (`SignInGate`).
import { Component, type ReactNode, Suspense, lazy } from "react";
import "../park/tokens/park.css";
import "../park/tokens/park.opaque.css";
import "../park/tokens/themes.css";
import "../park/studio/fonts";
import { Logo } from "../landing/Logo";
import { ThemeToggle } from "../landing/ThemeToggle";
import { useNightToggle } from "../landing/media";
import "../landing/landing.css";

const LandingBody = lazy(() => import("../landing/LandingBody"));

/** The landing below the hero is extra: if its chunk does not arrive (a deploy while the page is open, a dropped
 * network) the hero and its buttons stay and the page does not go blank. */
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
  const [night, toggle] = useNightToggle();
  return (
    <div
      className="landing"
      data-testid="sign-in"
      data-park
      data-theme="studio"
      data-time={night ? "night" : "day"}
    >
      <header className="landing-head">
        <Logo />
        <nav className="landing-head__nav" aria-label="On this page">
          <a href="#how">How it works</a>
          <a href="#safety">Safety</a>
          <a href="#skills">Skills</a>
        </nav>
        <ThemeToggle night={night} onToggle={toggle} />
      </header>
      <main className="landing-hero">
        <h1 className="landing-hero__title">
          Describe the work. <span className="landing-mark">Watch your team do it.</span>
        </h1>
        <p className="landing-hero__lead">
          Plain words in. A small city of AI helpers plans it, does it, and checks with you before
          anything important.
        </p>
        <div className="landing-hero__actions">
          <button
            type="button"
            className="landing-btn landing-btn--primary"
            disabled={busy}
            aria-busy={busy ? "true" : undefined}
            onClick={onGoogle}
          >
            <span className="landing-btn__g">
              <GoogleMark />
            </span>
            Continue with Google
          </button>
          <button
            type="button"
            className="landing-link-btn landing-link-btn--big"
            disabled={busy}
            onClick={onDemo}
          >
            Explore a demo session
          </button>
        </div>
        <p className="landing-hero__note">
          A sample company to explore. Demo sessions replay recorded runs.
        </p>
        {signOutFailedText ? (
          <p className="landing-error" role="alert" data-testid="sign-out-failed">
            {signOutFailedText}
          </p>
        ) : null}
        {failed && (
          <p className="landing-error" role="alert">
            {failedText}
          </p>
        )}
        <p className="landing-hero__legal">
          By continuing you agree to Tilo’s <a href="/terms">Terms</a> and{" "}
          <a href="/privacy">Privacy Policy</a>.
        </p>
        <QuietBoundary>
          <Suspense fallback={<div className="landing-hero__stage landing-hero__stage--held" />}>
            <LandingBody night={night} busy={busy} onGoogle={onGoogle} onDemo={onDemo} />
          </Suspense>
        </QuietBoundary>
      </main>
    </div>
  );
}
