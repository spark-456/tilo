// ONBOARD-1: one tour step as a coach mark over the real element it is about. A non-modal dialog (the page stays
// usable): named by its title, described by its text, and tied to the target by adding its text to the target's
// aria-describedby while the step shows. It is placed and outlined from the target's box and re-placed on resize and
// scroll; Tab is not trapped (the page stays usable); it never animates (nothing moves without a recorded event, HR-1) and has no filled primary button (UX-1).
import { type KeyboardEvent, useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { Button } from "../park/components";
import "./onboarding.css";
import { COPY, type TourStep } from "./steps";

interface Box {
  top: number;
  left: number;
  width: number;
  height: number;
}

export interface CoachMarkProps {
  step: TourStep;
  index: number;
  total: number;
  onBack: () => void;
  onNext: () => void;
  onEnd: () => void;
  /** The sample step's action. */
  onOpenSample?: () => void;
}

const MARGIN = 16;
const GAP = 12;
const ROOM = 220; // what a mark needs below its target before it goes above

const boxOf = (el: Element): Box => {
  const r = el.getBoundingClientRect();
  return { top: r.top, left: r.left, width: r.width, height: r.height };
};
const same = (a: Box | null, b: Box | null): boolean =>
  a === b ||
  (a !== null &&
    b !== null &&
    a.top === b.top &&
    a.left === b.left &&
    a.width === b.width &&
    a.height === b.height);

export function CoachMark({
  step,
  index,
  total,
  onBack,
  onNext,
  onEnd,
  onOpenSample,
}: CoachMarkProps) {
  const ref = useRef<HTMLDivElement>(null);
  const id = useId();
  const titleId = `onb-title-${id}`;
  const bodyId = `onb-body-${id}`;
  const [target, setTarget] = useState<Element | null>(null);
  const [box, setBox] = useState<Box | null>(null);
  const last = index === total - 1;

  // Find the step's real element and measure it; again whenever the window changes shape or the page scrolls.
  useLayoutEffect(() => {
    const measure = (): void => {
      const el = step.target();
      setTarget((t) => (t === el ? t : el));
      const next = el ? boxOf(el) : null;
      setBox((b) => (same(b, next) ? b : next));
    };
    measure();
    window.addEventListener("resize", measure);
    window.addEventListener("scroll", measure, true);
    return () => {
      window.removeEventListener("resize", measure);
      window.removeEventListener("scroll", measure, true);
    };
  }, [step]);

  // A page still arriving (the Home chunk): look again as the document changes, until the element is there.
  useEffect(() => {
    if (target) return;
    const watch = new MutationObserver(() => {
      const el = step.target();
      if (!el) return;
      setTarget(el);
      setBox(boxOf(el));
    });
    watch.observe(document.body, { childList: true, subtree: true });
    return () => watch.disconnect();
  }, [target, step]);

  // Bring a target that is off screen into view (instant: no smooth scrolling).
  useEffect(() => {
    if (target && typeof target.scrollIntoView === "function") {
      target.scrollIntoView({ block: "nearest", inline: "nearest" });
    }
  }, [target]);

  // The target is described by this text while the step shows.
  useEffect(() => {
    if (!target) return;
    const before = target.getAttribute("aria-describedby");
    target.setAttribute("aria-describedby", before ? `${before} ${bodyId}` : bodyId);
    return () => {
      if (before) target.setAttribute("aria-describedby", before);
      else target.removeAttribute("aria-describedby");
    };
  }, [target, bodyId]);

  // Focus moves into the mark when the tour opens (the layer gives it back on close), not on every step.
  useEffect(() => ref.current?.focus(), []);

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>): void => {
    if (e.key === "ArrowRight" && !last) {
      e.preventDefault();
      onNext();
    } else if (e.key === "ArrowLeft" && index > 0) {
      e.preventDefault();
      onBack();
    }
  };

  const vw = window.innerWidth;
  const vh = window.innerHeight;
  const width = Math.min(340, vw - 2 * MARGIN);
  let style: Record<string, number> | undefined;
  if (box) {
    const left = Math.max(
      MARGIN,
      Math.min(box.left + box.width / 2 - width / 2, vw - width - MARGIN),
    );
    const below = box.top + box.height + GAP + ROOM <= vh;
    style = below
      ? { width, left, top: box.top + box.height + GAP }
      : { width, left, bottom: Math.max(MARGIN, vh - box.top + GAP) };
  }

  return (
    <>
      {box ? (
        <div
          aria-hidden="true"
          className="onb-ring"
          style={{
            top: box.top - 4,
            left: box.left - 4,
            width: box.width + 8,
            height: box.height + 8,
          }}
        />
      ) : null}
      <div
        ref={ref}
        // biome-ignore lint/a11y/useSemanticElements: a non-modal coach mark that sits beside the page; native <dialog> has no such mode
        role="dialog"
        aria-modal="false"
        aria-labelledby={titleId}
        aria-describedby={bodyId}
        tabIndex={-1}
        className={`onb-card onb-coach ${box ? "" : "onb-coach--center"}`}
        style={style}
        onKeyDown={onKeyDown}
      >
        <div className="onb-eyebrow">{`Step ${index + 1} of ${total}`}</div>
        <h2 id={titleId} className="onb-coach-title">
          {step.title}
        </h2>
        <p id={bodyId} className="onb-body">
          {step.body}
        </p>
        {onOpenSample ? (
          <div className="onb-row">
            <Button variant="secondary" size="sm" onClick={onOpenSample}>
              {COPY.sample.open}
            </Button>
          </div>
        ) : null}
        <div className="onb-row">
          <Button variant="secondary" size="sm" onClick={onEnd}>
            {COPY.skipTour}
          </Button>
          <span className="onb-spacer" />
          {index > 0 ? (
            <Button variant="secondary" size="sm" onClick={onBack}>
              {COPY.back}
            </Button>
          ) : null}
          {last ? (
            <Button variant="secondary" size="sm" onClick={onEnd}>
              {COPY.done}
            </Button>
          ) : (
            <Button variant="secondary" size="sm" onClick={onNext}>
              {COPY.next}
            </Button>
          )}
        </div>
      </div>
    </>
  );
}
