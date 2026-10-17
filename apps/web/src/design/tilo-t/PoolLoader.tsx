import { type ReactNode, useEffect, useRef, useState } from "react";
import { ASSET, CARD, STILL } from "./poolAssets";
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
const LOOP_MS = LEAP_MS + SINK_MS;
/** A task's planning card says so when it has waited this long (wall time only; it names no event). */
const PLANNING_SLOW_MS = 45_000;
const SITE_COPY = {
  leap: ["Loading Tilo", "Fetching your workspace"],
  swim: ["Still loading", "The request is still loading"],
  sink: ["Ready", "The request finished"],
} as const;
/**
 * Shared Tilo T loader. A site load waits 300 ms before it appears and then plays one full leap; the screen behind
 * remains mounted and aria-busy while active.
 *
 * A task never covers its page: the world stays mounted and clickable, and one compact card sits over its top edge
 * from the recorded `world.started` until `world.planned` or `world.failed` (or the first recorded work).
 *
 * Task API: <PoolLoader kind="task" events={worldEvents}>…page…</PoolLoader>
 * Site API: <PoolLoader kind="site" loading={isLoading}>…page…</PoolLoader>
 */
export function PoolLoader(props: PoolLoaderProps) {
  return props.kind === "task" ? (
    <TaskPlanning events={props.events}>{props.children}</TaskPlanning>
  ) : (
    <SitePool loading={props.loading}>{props.children}</SitePool>
  );
}

function TaskPlanning({
  events,
  children,
}: { events: readonly PoolLoaderEvent[]; children: ReactNode }) {
  const has = (type: string) => events.some((event) => event.type === type);
  // triggeredBy: world.started (shown) and world.planned / world.failed (hidden)
  const active = has("world.started") && !has("world.planned") && !has("world.failed");
  const [slow, setSlow] = useState(false);
  useEffect(() => {
    if (!active) {
      setSlow(false);
      return undefined;
    }
    const timer = window.setTimeout(() => setSlow(true), PLANNING_SLOW_MS);
    return () => window.clearTimeout(timer);
  }, [active]);
  return (
    <div className="tt-pool-host" data-testid="tt-pool-host">
      <div className="tt-pool-page" aria-busy={active}>
        {children}
      </div>
      {active ? (
        <aside className="tt-plan-card" role="status" aria-live="polite" data-testid="tt-plan-card">
          <img className="tt-plan-card__art" src={CARD} alt="" width="56" height="22" />
          <div className="tt-plan-card__text">
            <strong>Director is planning</strong>
            <span>
              {slow
                ? "Taking longer than usual · waiting for world.planned"
                : "world.started · waiting for world.planned"}
            </span>
          </div>
        </aside>
      ) : null}
    </div>
  );
}

function SitePool({ loading, children }: { loading: boolean; children: ReactNode }) {
  const shownAt = useRef(0);
  const activeRef = useRef(loading);
  activeRef.current = loading;
  const [visible, setVisible] = useState(false);
  const [phase, setPhase] = useState<PoolPhase>("leap");

  useEffect(() => {
    if (!loading) return;
    // triggeredBy: a site request that remains pending for more than 300 ms
    const timer = window.setTimeout(() => {
      shownAt.current = performance.now();
      setPhase("leap");
      setVisible(true);
    }, MIN_LOAD_MS);
    return () => window.clearTimeout(timer);
  }, [loading]);

  useEffect(() => {
    if (!visible || phase !== "leap") return;
    const timer = window.setTimeout(() => setPhase(activeRef.current ? "swim" : "sink"), LEAP_MS);
    return () => window.clearTimeout(timer);
  }, [visible, phase]);

  useEffect(() => {
    if (!visible || phase !== "swim" || loading) return;
    // triggeredBy: the site request finishing
    setPhase("sink");
  }, [loading, phase, visible]);

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

  const [title, subtitle] = SITE_COPY[phase];
  return (
    <div className="tt-pool-host" data-testid="tt-pool-host">
      <div
        className={`tt-pool-page${visible ? " tt-pool-page--covered" : ""}${phase === "sink" ? " tt-pool-page--sink" : ""}`}
        aria-busy={loading}
      >
        {children}
      </div>
      {visible ? (
        <div className="tt-pool-overlay" data-phase={phase}>
          <div className="tt-pool-scrim" aria-hidden="true" />
          <div className="tt-pool__stage" role="status" aria-live="polite" aria-busy={loading}>
            <picture aria-hidden="true">
              <source media="(prefers-reduced-motion: reduce)" srcSet={STILL} />
              <img className="tt-pool__asset" src={ASSET} alt="" width="552" height="727" />
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
