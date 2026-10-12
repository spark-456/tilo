import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import { PAGE_LABEL, type PageId } from "../park/app/AppCtx";
import { Button } from "../park/components";
import { CoachMark } from "./CoachMark";
import { trapTab } from "./focus";
import "./onboarding.css";
import { pageTourSteps } from "./pageSteps";
import { hasSeen, markSeen } from "./storage";
import { onTourRequest } from "./tourEvents";

export interface PageTourLayerProps {
  page: PageId;
  firstRun: boolean;
  autoInvite?: boolean;
  userKey: string;
}
type Phase = { key: string; step: number | null } | null;

function Invitation({
  page,
  begin,
  close,
}: { page: PageId; begin: () => void; close: () => void }) {
  const ref = useRef<HTMLDivElement>(null);
  const id = useId();
  useEffect(() => ref.current?.focus(), []);
  return (
    <div className="onb-scrim">
      <div
        ref={ref}
        // biome-ignore lint/a11y/useSemanticElements: reuse the existing onboarding dialog/focus pattern
        role="dialog"
        aria-modal="true"
        aria-labelledby={`${id}-title`}
        aria-describedby={`${id}-body`}
        tabIndex={-1}
        className="onb-card"
        onKeyDown={trapTab}
      >
        <h2 id={`${id}-title`} className="onb-welcome-title">
          Take a tour of {PAGE_LABEL[page]}?
        </h2>
        <p id={`${id}-body`} className="onb-body">
          A 30-second look at what is here and what to try first.
        </p>
        <div className="onb-row">
          <Button variant="primary" onClick={begin}>
            Take the tour
          </Button>
          <Button variant="secondary" onClick={close}>
            Not now
          </Button>
        </div>
      </div>
    </div>
  );
}

/** FIRST-RUN: display state and per-person/per-page local storage only; no sample data, writes or model calls. */
export function PageTourLayer({ page, firstRun, autoInvite = true, userKey }: PageTourLayerProps) {
  const key = `page:${JSON.stringify([userKey, page])}`;
  const [phase, setPhase] = useState<Phase>(null);
  const opener = useRef<HTMLElement | null>(null);
  const wasOpen = useRef(false);
  const steps = useMemo(() => pageTourSteps(page), [page]);
  const open = useCallback(
    (step: number | null) => {
      const at = document.activeElement;
      opener.current =
        at instanceof HTMLElement && at !== document.body && !at.closest('[role="menu"]')
          ? at
          : document.querySelector('button[aria-label="Account menu"]');
      setPhase({ key, step });
    },
    [key],
  );
  const close = useCallback(() => setPhase(null), []);
  useEffect(
    () => () => {
      if (opener.current?.isConnected) opener.current.focus();
    },
    [],
  );
  useEffect(() => {
    if (!firstRun) {
      setPhase(null);
      return;
    }
    if (!autoInvite || hasSeen(key)) return; // effect replay preserves this mount's already-open invitation
    markSeen(key);
    open(null);
  }, [firstRun, autoInvite, key, open]);
  useEffect(
    () =>
      onTourRequest(() => {
        if (firstRun) open(0);
      }),
    [firstRun, open],
  );
  const visible = firstRun && phase?.key === key;
  useEffect(() => {
    if (visible) {
      wasOpen.current = true;
      return;
    }
    if (wasOpen.current && opener.current?.isConnected) opener.current.focus();
    wasOpen.current = false;
    opener.current = null;
  }, [visible]);
  useEffect(() => {
    if (!visible) return;
    const onEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") close();
    };
    document.addEventListener("keydown", onEscape);
    return () => document.removeEventListener("keydown", onEscape);
  }, [visible, close]);
  if (!visible || !phase) return null;
  if (phase.step === null)
    return <Invitation page={page} begin={() => setPhase({ key, step: 0 })} close={close} />;
  const index = phase.step;
  const step = steps[index];
  if (!step) return null;
  return (
    <>
      {/* biome-ignore lint/a11y/useSemanticElements: same polite status region as ONBOARD-1 */}
      <div role="status" aria-live="polite" data-onboarding="" className="onb-sr">
        Step {index + 1} of {steps.length}: {step.title}
      </div>
      <CoachMark
        step={step}
        index={index}
        total={steps.length}
        onBack={() => setPhase({ key, step: Math.max(0, index - 1) })}
        onNext={() => setPhase({ key, step: Math.min(steps.length - 1, index + 1) })}
        onEnd={close}
      />
    </>
  );
}
