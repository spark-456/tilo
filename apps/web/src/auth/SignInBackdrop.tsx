// The Park city behind the sign-in card: the same drawn scene as the app's backdrop (park/shell/scene.ts), still, fixed,
// full-bleed and hidden from assistive technology. A chunk of its own (SignInScreen lazy-loads it), so the sign-in card
// never waits for the scene and the landing bundle does not carry it (NFR-01).
import { useEffect, useState } from "react";
import { sceneScale } from "../park/app/pins";
import { backdropScene } from "../park/shell/scene";
import "../park/shell/park.shell.css";
import "../park/tokens/park.css";
import "../park/tokens/park.opaque.css";

const size = () => ({ vw: window.innerWidth, vh: window.innerHeight });

export default function SignInBackdrop({ time }: { time: "day" | "night" }) {
  const [win, setWin] = useState(size);
  useEffect(() => {
    const onResize = () => setWin(size);
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);
  const scale = sceneScale(win.vw, win.vh);
  return (
    <div data-park data-time={time} data-motion="still">
      <div aria-hidden="true" className="park-shell__backdrop" data-lite="">
        <div className="park-shell__scene" style={{ transform: `scale(${scale.toFixed(4)})` }}>
          {backdropScene(time, "still").el}
        </div>
      </div>
    </div>
  );
}
