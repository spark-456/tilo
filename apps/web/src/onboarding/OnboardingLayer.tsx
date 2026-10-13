// ONBOARD-1 (user-requested, no PRD requirement; BQ-ONBOARD-1): the first-run welcome and the guided tour of the
// Park app. ParkApp draws this inside its `[data-park]` root when the Root provides it (park/shell/tour.tsx); the
// account menu's "Take the tour" reaches it through tourEvents.ts.
//
// Once per person: the welcome marks itself seen (localStorage, try/catch) the moment it shows. It is not shown to
// unit tests (MODE=test) or automated browsers (navigator.webdriver) unless the address has ?onboarding=1, so no
// other check meets an overlay it did not ask for; "Take the tour" always works. Nothing here animates or claims that
// a run happened (HR-1..HR-7): it is words, a position and an outline.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { session } from "../auth/session";
import { useApp } from "../park/app/context";
import { CoachMark } from "./CoachMark";
import { Welcome } from "./Welcome";
import { findSampleWorld } from "./sampleWorld";
import { SAMPLE_STEP_ID, tourSteps } from "./steps";
import { hasSeen, markSeen, userKeyOf } from "./storage";
import { onTourRequest } from "./tourEvents";

type Phase = { kind: "idle" } | { kind: "welcome" } | { kind: "tour"; step: number };

export interface OnboardingLayerProps {
  /** Whether the first-run welcome may show by itself. Default: see `autoShowAllowed`. */
  enabled?: boolean;
  /** The person's key for "seen" (default: from the sign-in session). */
  userKey?: string;
  /** Looks for the sample project (default: the worlds list). Never needs to handle failure: a reject means none. */
  findSample?: () => Promise<string | null>;
}

export function autoShowAllowed(): boolean {
  try {
    if (new URLSearchParams(window.location.search).get("onboarding") === "1") return true;
  } catch {
    // no address to read
  }
  if (import.meta.env.MODE === "test") return false;
  return typeof navigator === "undefined" || navigator.webdriver !== true;
}

const accountButton = (): HTMLElement | null =>
  document.querySelector<HTMLElement>('button[aria-label="Account menu"]');

export function OnboardingLayer({
  enabled,
  userKey,
  findSample = findSampleWorld,
}: OnboardingLayerProps) {
  const app = useApp();
  const appRef = useRef(app);
  appRef.current = app;
  const [phase, setPhase] = useState<Phase>({ kind: "idle" });
  const [sample, setSample] = useState<string | null>(null);
  const asked = useRef(false);
  const opener = useRef<HTMLElement | null>(null);
  const wasOpen = useRef(false);
  const find = useRef(findSample);
  find.current = findSample;
  const allowed = enabled ?? autoShowAllowed();
  const steps = useMemo(() => tourSteps(sample), [sample]);

  // Where focus goes back to on close, and the one look for the sample project (a failure means there is none).
  const open = useCallback((next: Phase) => {
    const at = document.activeElement;
    opener.current =
      at instanceof HTMLElement && at !== document.body && !at.closest('[role="menu"]')
        ? at
        : accountButton();
    if (!asked.current) {
      asked.current = true;
      Promise.resolve()
        .then(() => find.current())
        .then(setSample, () => setSample(null));
    }
    setPhase(next);
  }, []);

  useEffect(() => {
    if (!allowed) return;
    const key = userKey ?? userKeyOf(session.getState());
    if (hasSeen(key)) return;
    markSeen(key);
    open({ kind: "welcome" });
  }, [allowed, userKey, open]);

  const begin = useCallback(() => {
    // The tour starts at Home: its first stop is the intake box.
    if (appRef.current.page !== "home") appRef.current.go("home");
    setPhase((p) => (p.kind === "idle" ? p : { kind: "tour", step: 0 }));
  }, []);
  useEffect(
    () =>
      onTourRequest(() => {
        open({ kind: "tour", step: 0 });
        if (appRef.current.page !== "home") appRef.current.go("home");
      }),
    [open],
  );

  const end = useCallback(() => setPhase({ kind: "idle" }), []);
  useEffect(() => {
    if (phase.kind !== "idle") {
      wasOpen.current = true;
      return;
    }
    if (!wasOpen.current) return;
    wasOpen.current = false;
    const back = opener.current;
    opener.current = null;
    if (back?.isConnected) back.focus();
  }, [phase.kind]);

  useEffect(() => {
    if (phase.kind === "idle") return;
    const onKey = (e: KeyboardEvent): void => {
      if (e.key === "Escape") end();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [phase.kind, end]);

  if (phase.kind === "idle") return null;
  if (phase.kind === "welcome") return <Welcome onTour={begin} onSkip={end} />;

  const index = Math.min(phase.step, steps.length - 1);
  const step = steps[index];
  if (!step) return null;
  const openSample =
    step.id === SAMPLE_STEP_ID && sample
      ? () => {
          opener.current = null; // the page change takes focus to the new page's heading
          appRef.current.go("world", { id: sample });
          end();
        }
      : undefined;
  return (
    <>
      {/* biome-ignore lint/a11y/useSemanticElements: a plain polite live region; <output> is for form results */}
      <div role="status" aria-live="polite" data-onboarding="" className="onb-sr">
        {`Step ${index + 1} of ${steps.length}: ${step.title}`}
      </div>
      <CoachMark
        step={step}
        index={index}
        total={steps.length}
        onBack={() => setPhase({ kind: "tour", step: Math.max(0, index - 1) })}
        onNext={() => setPhase({ kind: "tour", step: Math.min(steps.length - 1, index + 1) })}
        onEnd={end}
        {...(openSample ? { onOpenSample: openSample } : {})}
      />
    </>
  );
}

export default OnboardingLayer;
