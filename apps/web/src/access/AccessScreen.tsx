import { Component, type ReactNode, Suspense, lazy, useState } from "react";
import "../park/tokens/park.css";
import "../park/tokens/park.opaque.css";
import "./AccessScreen.css";

const City = lazy(() => import("../auth/SignInBackdrop"));

class QuietCity extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  render() {
    return this.state.failed ? null : this.props.children;
  }
}

/** The sign-in city's still backdrop and a Park glass card for the server's access decision. */
export function AccessScreen({ children }: { readonly children: ReactNode }) {
  const [time, setTime] = useState<"day" | "night">("day");
  return (
    <main className="park-access" data-park data-time={time}>
      <QuietCity>
        <Suspense fallback={null}>
          <City time={time} />
        </Suspense>
      </QuietCity>
      <button
        type="button"
        className="park-access__toggle"
        aria-label={`Switch to the ${time === "day" ? "night" : "day"} city`}
        onClick={() => setTime(time === "day" ? "night" : "day")}
      >
        {time === "day" ? "Night" : "Day"}
      </button>
      <div className="park-access__card">{children}</div>
    </main>
  );
}
