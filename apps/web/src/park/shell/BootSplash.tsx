// The boot splash (README "Interactions and motion": Boot; reference `Tilo App.dc.html` bootOn): a paper
// screen with the 56px logo, the 48px wordmark, a 200px bar sliding with tiloSlide and "Loading your city".
// It stays until the art engines have drawn the city; then it fades over .45s (a CSS animation, so the browser's
// own animationend says when it is over) and goes. Reduced motion and the 'still' preference skip the fade.
// A splash that was never shown (ready from the first render) is never drawn. Once it has gone, the other pages'
// bundles are fetched (README Boot: "Prefetch the page bundles afterwards").
import { useEffect, useRef, useState } from "react";
import { useSchedule } from "../app/context";
import { FADE_MARGIN_MS, SPLASH_FADE_MS, browserRunsAnimations, useMotionOff } from "./motion";
import { prefetchPages } from "./prefetch";

type Phase = "up" | "out" | "gone";

export function BootSplash({ ready }: { ready: boolean }) {
  const off = useMotionOff();
  const schedule = useSchedule();
  const [phase, setPhase] = useState<Phase>(ready ? "gone" : "up");
  const wasShown = useRef(!ready);
  if (ready && phase === "up") setPhase(off ? "gone" : "out");
  useEffect(() => {
    if (phase === "gone" && wasShown.current) prefetchPages();
  }, [phase]);
  // The browser's animationend ends the fade; if it never runs, the scheduler does, a little later.
  useEffect(() => {
    if (phase !== "out" || !browserRunsAnimations()) return undefined;
    return schedule(() => setPhase("gone"), SPLASH_FADE_MS + FADE_MARGIN_MS);
  }, [phase, schedule]);
  if (phase === "gone") return null;
  return (
    <div
      // The design's own div, role and name pinned by the spec. Loading is announced while it lasts; the
      // fade that follows is only a picture.
      role={phase === "up" ? "status" : "presentation"}
      aria-label="Loading Tilo"
      className={`park-shell__boot ${phase === "out" ? "park-shell__boot--out" : ""}`}
      onAnimationEnd={(e) => {
        if (e.target === e.currentTarget) setPhase("gone");
      }}
    >
      <div className="park-shell__bootlogo">
        <div className="park-shell__bootmark">
          <div className="park-shell__bootvisor">
            <div className="park-shell__bootdot" />
            <div className="park-shell__bootdot" />
          </div>
        </div>
        <div className="park-shell__bootword">tilo</div>
      </div>
      <div className="park-shell__bootstate">
        <div className="park-shell__boottrack">
          <div className="park-shell__bootfill" />
        </div>
        <div className="park-shell__boottext">Loading your city</div>
      </div>
    </div>
  );
}
