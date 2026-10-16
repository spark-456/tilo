// Pausing loops (design/tilo-t/PROMPT.md: "Pause all loops when the tab is hidden"; landing loops "pause each loop when its
// section is off-screen"). A loop is CSS; these hooks only say whether it should run. Put the `tt-paused` class on the
// loop's root when `paused` is true (motion.css sets animation-play-state: paused on it and its children).
import { type RefObject, useEffect, useState } from "react";

/** True while the tab is hidden. Starts from the current state and follows visibilitychange. */
export function usePauseWhenHidden(): boolean {
  const [hidden, setHidden] = useState(() => typeof document !== "undefined" && document.hidden);
  useEffect(() => {
    const on = () => setHidden(document.hidden);
    on();
    document.addEventListener("visibilitychange", on);
    return () => document.removeEventListener("visibilitychange", on);
  }, []);
  return hidden;
}

/** True while the element is on screen. Without IntersectionObserver it reports true (the loop is never stuck off). */
export function useInView(ref: RefObject<Element | null>, rootMargin = "0px"): boolean {
  const [inView, setInView] = useState(true);
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof IntersectionObserver === "undefined") return;
    const io = new IntersectionObserver(
      (entries) => {
        const last = entries[entries.length - 1];
        if (last) setInView(last.isIntersecting);
      },
      { rootMargin },
    );
    io.observe(el);
    return () => io.disconnect();
  }, [ref, rootMargin]);
  return inView;
}

/** Both at once: a loop runs only while the tab is visible and its section is on screen. Returns the `tt-paused` class or "". */
export function useLoopPaused(ref: RefObject<Element | null>): string {
  const hidden = usePauseWhenHidden();
  const inView = useInView(ref);
  return hidden || !inView ? "tt-paused" : "";
}
