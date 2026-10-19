// LANDING-2: scroll reveal for the signed-out landing. An element is marked `landing-reveal` and gets `is-in` once it
// has scrolled into view (IntersectionObserver). The marks are the whole of this module's job: what they look like is
// the stylesheet's (transform and opacity only, so nothing shifts the layout). It is decoration, not a world: nothing
// here depicts an agent or a run. Where the browser asks for reduced motion, or has no IntersectionObserver, nothing is
// marked at all and the page is simply there. Dependency-free; lives in the landing chunk.
import {
  type CSSProperties,
  type ElementType,
  type HTMLAttributes,
  type ReactNode,
  useEffect,
  useRef,
  useState,
} from "react";
import { usePrefersReducedMotion } from "./media";

/** True when reveal marks should be put on the page: motion is welcome and the browser can tell what is in view. */
export function useRevealArmed(): boolean {
  const reduce = usePrefersReducedMotion();
  return !reduce && typeof IntersectionObserver === "function";
}

interface RevealProps extends HTMLAttributes<HTMLElement> {
  readonly as?: ElementType;
  /** Position among siblings: the stylesheet staggers children by it. */
  readonly index?: number;
  readonly children?: ReactNode;
}

export function Reveal({
  as: Tag = "div",
  index,
  className,
  style,
  children,
  ...rest
}: RevealProps) {
  const armed = useRevealArmed();
  const ref = useRef<HTMLElement>(null);
  const [seen, setSeen] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!armed || !el || seen) return;
    const io = new IntersectionObserver(
      (entries) => {
        // In view, or already scrolled past (an anchor jump): either way it must not stay hidden.
        const top = (e: IntersectionObserverEntry) => e.rootBounds?.top ?? 0;
        if (entries.some((e) => e.isIntersecting || e.boundingClientRect.top < top(e))) {
          setSeen(true);
          io.disconnect();
        }
      },
      { rootMargin: "0px 0px -8% 0px", threshold: 0.05 },
    );
    io.observe(el);
    return () => io.disconnect();
  }, [armed, seen]);
  const marks = armed ? (seen ? "landing-reveal is-in" : "landing-reveal") : "";
  const css = index === undefined ? style : ({ ...style, "--i": index } as CSSProperties);
  return (
    <Tag
      ref={ref}
      className={[className, marks].filter(Boolean).join(" ") || undefined}
      style={css}
      {...rest}
    >
      {children}
    </Tag>
  );
}
