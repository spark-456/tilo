import { type ReactNode, useEffect, useRef, useState } from "react";
import "./PoolLoader.css";

type PoolPhase = "leap" | "swim" | "sink";
export type PoolLoaderEvent = { readonly type: string; readonly ts?: string };
export type PoolLoaderProps = {
  children: ReactNode;
} & (
  | { kind: "site"; loading: boolean }
  | { kind: "task"; events: readonly PoolLoaderEvent[] }
);

const MIN_LOAD_MS = 300;
const LEAP_MS = 2600;
const SINK_MS = 2000;
const RECENT_END_MS = 10_000;
const LOOP_MS = LEAP_MS + SINK_MS;
const ASSET = "/loader/pool-46a6cd3d6b84.webp";
const STILL = "/loader/pool-9182ba9a51a9.png";
const SITE_COPY = {
  leap: ["Loading Tilo", "Fetching your workspace"],
  swim: ["Still loading", "The request is still loading"],
  sink: ["Ready", "The request finished"],
} as const;
const TASK_COPY = {
  leap: ["Starting your world", "world.started"],
  swim: ["The Director is still planning", "Waiting for world.planned"],
  sink: ["Your plan is ready", "world.planned"],
} as const;
/**
 * Shared Tilo T loader. Site and task loads wait 300 ms before appearing; task event timestamps preserve that gate
 * when world.started and world.planned arrive together. The leap finishes before a completed task sinks; active tasks
 * swim after the leap. The screen behind remains mounted and aria-busy while active.
 *
 * Task API: <PoolLoader kind="task" events={worldEvents}>…page…</PoolLoader>
 * Site API: <PoolLoader kind="site" loading={isLoading}>…page…</PoolLoader>
 */
export function PoolLoader(props: PoolLoaderProps) {
  const shownAt = useRef(0);
  const isTask = props.kind === "task";
  const startedEvent = isTask ? props.events.find((event) => event.type === "world.started") : undefined;
  const plannedEvent = isTask ? props.events.find((event) => event.type === "world.planned") : undefined;
  const failedEvent = isTask ? props.events.find((event) => event.type === "world.failed") : undefined;
  const started = startedEvent !== undefined;
  const planned = plannedEvent !== undefined;
  const failed = failedEvent !== undefined;
  const terminalEvent = plannedEvent ?? failedEvent;
  const recordedDuration =
    startedEvent?.ts && terminalEvent?.ts
      ? Date.parse(terminalEvent.ts) - Date.parse(startedEvent.ts)
      : Number.NaN;
  const active =
    props.kind === "task" ? started && !planned && !failed : props.loading;
  const activeRef = useRef(active);
  activeRef.current = active;
  const [visible, setVisible] = useState(false);
  const [phase, setPhase] = useState<PoolPhase>("leap");
  // One play per mount: without it the buffered replay below re-opened the overlay every time it closed.
  const playedRef = useRef(false);

  useEffect(() => {
    if (isTask) {
      if (!started || visible || playedRef.current) return;
      if (!active) {
        // Buffered world.started plus a terminal event plays only when their real event times exceed the 300 ms gate,
        // and only for a run that ended just now; a world opened after it ended shows at once.
        if (!Number.isFinite(recordedDuration) || recordedDuration < MIN_LOAD_MS) return;
        const endedAt = terminalEvent?.ts ? Date.parse(terminalEvent.ts) : Number.NaN;
        if (!Number.isFinite(endedAt) || Date.now() - endedAt > RECENT_END_MS) return;
        playedRef.current = true;
        shownAt.current = performance.now();
        setPhase("leap");
        setVisible(true);
        return;
      }
      // triggeredBy: world.started (recorded event); short runs cancel this 300 ms reveal.
      const timer = window.setTimeout(() => {
        playedRef.current = true;
        shownAt.current = performance.now();
        setPhase("leap");
        setVisible(true);
      }, MIN_LOAD_MS);
      return () => window.clearTimeout(timer);
    }
    if (!active) return;
    // triggeredBy: a site request that remains pending for more than 300 ms
    const timer = window.setTimeout(() => {
      shownAt.current = performance.now();
      setPhase("leap");
      setVisible(true);
    }, MIN_LOAD_MS);
    return () => window.clearTimeout(timer);
  }, [active, isTask, recordedDuration, started, terminalEvent, visible]);

  useEffect(() => {
    if (!visible || phase !== "leap") return;
    const timer = window.setTimeout(() => setPhase(activeRef.current ? "swim" : "sink"), LEAP_MS);
    return () => window.clearTimeout(timer);
  }, [visible, phase]);

  useEffect(() => {
    if (!visible || phase !== "swim" || active) return;
    // triggeredBy: world.planned/world.failed, or the site request finishing
    setPhase("sink");
  }, [active, phase, visible]);

  useEffect(() => {
    if (!visible || phase !== "sink") return;
    const reduced = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
    const elapsed = Math.max(0, performance.now() - shownAt.current);
    const remaining = reduced ? 200 : LOOP_MS - (elapsed % LOOP_MS);
    const timer = window.setTimeout(() => {
      setVisible(false);
    }, remaining);
    return () => window.clearTimeout(timer);
  }, [phase, visible]);

  const busy = active;
  const [title, subtitle] =
    isTask && phase === "sink" && failed
      ? ["The world stopped", "world.failed"]
      : (isTask ? TASK_COPY : SITE_COPY)[phase];
  return (
    <div className="tt-pool-host" data-testid="tt-pool-host">
      <div
        className={`tt-pool-page${visible ? " tt-pool-page--covered" : ""}${phase === "sink" ? " tt-pool-page--sink" : ""}`}
        aria-busy={busy}
      >
        {props.children}
      </div>
      {visible ? (
        <div className="tt-pool-overlay" data-phase={phase}>
          <div className="tt-pool-scrim" aria-hidden="true" />
          <div
            className="tt-pool__stage"
            role="status"
            aria-live="polite"
            aria-busy={busy}
          >
            <picture aria-hidden="true">
              <source media="(prefers-reduced-motion: reduce)" srcSet={STILL} />
              <img className="tt-pool__asset" src={ASSET} alt="" width="560" height="412" />
            </picture>
            <div className="tt-pool__caption" aria-atomic="true">
              <strong>{title}</strong>
              <span>{subtitle}</span>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
