import { type CSSProperties, type ReactNode, useEffect, useRef, useState } from "react";
import { Buddy } from "./Buddy";
import { useLoopPaused } from "./loops";
import "./PoolLoader.css";

type PoolPhase = "leap" | "swim" | "sink";
export type PoolLoaderEvent = { readonly type: string };
export type PoolLoaderProps = {
  children: ReactNode;
} & (
  | { kind: "site"; loading: boolean }
  | { kind: "task"; events: readonly PoolLoaderEvent[] }
);

const SITE_DELAY_MS = 300;
const LEAP_MS = 2600;
const SINK_MS = 2000;
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
const DROPS = Array.from({ length: 12 }, (_, i) => {
  const angle = Math.PI * (1.05 + (i / 11) * 0.9);
  const radius = 70 + ((i * 29) % 60);
  return {
    dx: `${Math.round(Math.cos(angle) * radius * 1.6)}px`,
    dy: `${Math.round(Math.sin(angle) * radius * 1.2 - 30)}px`,
    width: `${i % 3 ? 10 : 14}px`,
    height: `${i % 3 ? 13 : 18}px`,
    delay: `${2.236 + (i % 4) * 0.03}s`,
    color: i % 4 ? "#9FCFE0" : "#FFFFFF",
  };
});

/**
 * Shared Tilo T loader. Site loads wait 300 ms before appearing; task loaders begin only after world.started and
 * stay in swim until world.planned. The screen behind remains mounted and aria-busy while its request is active.
 *
 * Task API: <PoolLoader kind="task" events={worldEvents}>…page…</PoolLoader>
 * Site API: <PoolLoader kind="site" loading={isLoading}>…page…</PoolLoader>
 */
export function PoolLoader(props: PoolLoaderProps) {
  const poolRef = useRef<HTMLDivElement>(null);
  const paused = useLoopPaused(poolRef);
  const isTask = props.kind === "task";
  const started = isTask && props.events.some((event) => event.type === "world.started");
  const planned = isTask && props.events.some((event) => event.type === "world.planned");
  const failed = isTask && props.events.some((event) => event.type === "world.failed");
  const active =
    props.kind === "task" ? started && !planned && !failed : props.loading;
  const activeRef = useRef(active);
  activeRef.current = active;
  const [visible, setVisible] = useState(false);
  const [phase, setPhase] = useState<PoolPhase>("leap");

  useEffect(() => {
    if (!active) return;
    if (isTask) {
      // triggeredBy: world.started (recorded event)
      setPhase("leap");
      setVisible(true);
      return;
    }
    // triggeredBy: a site request that remains pending for more than 300 ms
    const timer = window.setTimeout(() => {
      setPhase("leap");
      setVisible(true);
    }, SITE_DELAY_MS);
    return () => window.clearTimeout(timer);
  }, [active, isTask]);

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
    const timer = window.setTimeout(() => {
      setVisible(false);
    }, SINK_MS);
    return () => window.clearTimeout(timer);
  }, [phase, visible]);

  const busy = active;
  const [title, subtitle] =
    isTask && phase === "sink" && failed
      ? ["The world stopped", "world.failed"]
      : (isTask ? TASK_COPY : SITE_COPY)[phase];
  const surfaceStyle = (index: number): CSSProperties =>
    ({
      "--dx": DROPS[index]?.dx,
      "--dy": DROPS[index]?.dy,
      "--tt-drop-delay": DROPS[index]?.delay,
      background: DROPS[index]?.color,
      width: DROPS[index]?.width,
      height: DROPS[index]?.height,
    }) as CSSProperties;

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
            className={`tt-pool__stage${paused ? " tt-paused" : ""}`}
            ref={poolRef}
            role="status"
            aria-live="polite"
            aria-busy={busy}
          >
            <div className={`tt-pool__water${phase === "sink" ? " tt-pool__water--closing" : ""}`}>
              {phase !== "sink" ? (
                <>
                  <span className="tt-pool__ring tt-pool__ring--one" />
                  <span className="tt-pool__ring tt-pool__ring--two" />
                  <span className="tt-pool__ring tt-pool__ring--three" />
                </>
              ) : null}
            </div>
            {phase === "leap" ? (
              <>
                <span className="tt-pool__shadow" />
                <div className="tt-pool__buddy tt-pool__buddy--leap tt-pool__leap">
                  <Buddy size={120} mood="happy" />
                </div>
                <div className="tt-pool__drops" aria-hidden="true">
                  {DROPS.map((drop, i) => (
                    <span
                      className="tt-pool__drop"
                      key={i}
                      style={{
                        ...surfaceStyle(i),
                        left: `${50 + (i % 3) * 2}%`,
                        top: "50%",
                      }}
                    />
                  ))}
                  <span className="tt-pool__splash" />
                </div>
              </>
            ) : phase === "swim" ? (
              <div className="tt-pool__swimmer">
                <div className="tt-pool__swimmer-clip">
                  <Buddy size={64} mood="swim" />
                </div>
                <span className="tt-pool__swim-ring" />
              </div>
            ) : phase === "sink" ? (
              <>
                <div className="tt-pool__buddy tt-pool__buddy--sink tt-pool__sink-buddy">
                  <Buddy size={80} mood="swim" />
                </div>
                <span className="tt-pool__sink-ripple" />
                <div className="tt-pool__bubbles" aria-hidden="true">
                  {[-14, 6, -2, 14, -20].map((x, i) => (
                    <span
                      className="tt-pool__bubble"
                      key={i}
                      style={{ left: `calc(50% + ${x}px)`, "--tt-bubble-delay": `${0.2 + i * 0.15}s` } as CSSProperties}
                    />
                  ))}
                </div>
              </>
            ) : null}
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
