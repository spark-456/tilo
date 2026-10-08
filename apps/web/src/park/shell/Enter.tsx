// A toast, a popover or a menu comes in (WEB-MOTION-3, FR-UX-12): opacity and a few px of transform, in the shell
// stylesheet (`.park-shell__enter`, park.shell.css). The wrapper adds no box (display: contents). It mounts in the
// "pre" state, reads its layout once so the browser has styled that state, then settles to "in": the stylesheet's
// transition runs between the two. No timer, no frame loop, no animation call: the only trigger is the element being
// opened by a person's click (the bell, the avatar, a decision). Reduced motion and 'still' make "pre" and "in" look
// the same (the stylesheet's last block), so the element is simply there.
import { type ReactNode, useLayoutEffect, useRef, useState } from "react";

export function Enter({ children }: { children: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  const [state, setState] = useState<"pre" | "in">("pre");
  useLayoutEffect(() => {
    // `display: contents` has no box of its own: the child is the thing that was styled in "pre".
    void ref.current?.firstElementChild?.getBoundingClientRect();
    setState("in");
  }, []);
  return (
    <div ref={ref} className="park-shell__enter" data-enter={state}>
      {children}
    </div>
  );
}
