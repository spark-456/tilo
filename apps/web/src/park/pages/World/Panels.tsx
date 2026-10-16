// STUDIO-3 (design/studio-v2 "Tilo S World.dc.html"): the three tabs beside the city. Story is what the team did, in
// plain words from the recorded events; Steps is the plan in order; Result is the delivered output. A tab with
// nothing recorded says so; nothing here moves or is filled in.
import {
  type KeyboardEvent,
  type ReactNode,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import { cx } from "../../components/cx";
import { type RunStep, clockOf, runSteps, storyOf } from "./runSteps";
import type { RunEvent } from "./useRunEvents";

export type WorldTab = "story" | "steps" | "result" | "chat";
const TABS: readonly (readonly [WorldTab, string])[] = [
  ["story", "Story"],
  ["steps", "Steps"],
  ["result", "Result"],
];
/** TILO-T-WORLD: a real run with a stage also has its Chat (the agents talking), after the three. */
const CHAT: readonly [WorldTab, string] = ["chat", "Chat"];
export const tabId = (t: WorldTab): string => `park-world-tab-${t}`;
export const panelId = (t: WorldTab): string => `park-world-panel-${t}`;

/** The tab list (ARIA tabs: arrows, Home and End move between them; the chosen tab is the one in the tab order). */
export function WorldTabs({
  on,
  onPick,
  counts,
  chat = false,
}: {
  on: WorldTab;
  onPick: (t: WorldTab) => void;
  counts: Partial<Record<WorldTab, string>>;
  chat?: boolean;
}) {
  const tabs = chat ? [...TABS, CHAT] : TABS;
  const refs = useRef<Record<string, HTMLButtonElement | null>>({});
  const move = (e: KeyboardEvent<HTMLButtonElement>, at: number) => {
    const to =
      e.key === "ArrowRight"
        ? (at + 1) % tabs.length
        : e.key === "ArrowLeft"
          ? (at + tabs.length - 1) % tabs.length
          : e.key === "Home"
            ? 0
            : e.key === "End"
              ? tabs.length - 1
              : -1;
    const next = tabs[to];
    if (!next) return;
    e.preventDefault();
    onPick(next[0]);
    refs.current[next[0]]?.focus();
  };
  return (
    <div role="tablist" aria-label="World views" className="park-world-tabs">
      {tabs.map(([t, label], i) => (
        <button
          key={t}
          ref={(el) => {
            refs.current[t] = el;
          }}
          type="button"
          role="tab"
          id={tabId(t)}
          aria-selected={on === t}
          aria-controls={panelId(t)}
          tabIndex={on === t ? 0 : -1}
          className={cx("park-world-tab", on === t && "park-world-tab--on")}
          onClick={() => onPick(t)}
          onKeyDown={(e) => move(e, i)}
        >
          {label}
          {counts[t] ? <span className="park-world-tab__n">{counts[t]}</span> : null}
        </button>
      ))}
    </div>
  );
}

/**
 * The scrolling body of a panel (WORLD-DESIGN). When its content is taller than the panel it can be reached by keyboard
 * (a labelled region in the tab order) and a soft fade at the bottom edge says there is more, so a long item is never
 * cut off mid-line without a hint; at the very end the fade goes. Measured from the DOM on each render and scroll.
 */
function PanelBody({ label, children }: { label: string; children: ReactNode }) {
  const body = useRef<HTMLDivElement>(null);
  const [edge, setEdge] = useState({ scrolls: false, end: true });
  const measure = () => {
    const el = body.current;
    if (!el) return;
    const scrolls = el.scrollHeight > el.clientHeight + 1;
    const end = !scrolls || el.scrollHeight - el.scrollTop - el.clientHeight < 4;
    setEdge((p) => (p.scrolls === scrolls && p.end === end ? p : { scrolls, end }));
  };
  useLayoutEffect(measure);
  return (
    <>
      <div
        ref={body}
        className="park-world-panelbody"
        onScroll={measure}
        {...(edge.scrolls
          ? { role: "region", "aria-label": `${label}, scroll for more`, tabIndex: 0 }
          : {})}
      >
        {children}
      </div>
      {edge.scrolls && !edge.end ? <div className="park-world-fade" aria-hidden="true" /> : null}
    </>
  );
}

/** One tab panel: every panel stays in the page (hidden when not chosen), so switching moves nothing else. */
export function TabPanel({
  tab,
  on,
  title,
  sub,
  aside,
  slideWhen,
  slide,
  children,
}: {
  tab: WorldTab;
  on: WorldTab;
  title: string;
  sub: string;
  aside?: string;
  /** TILO-T-WORLD: a panel that slides in (class `slide`) when this turns true while the page is open, and only then:
   * triggeredBy artifact.delivered for the Result panel. True from the start just shows. */
  slideWhen?: boolean;
  slide?: string;
  children: ReactNode;
}) {
  const was = useRef(slideWhen);
  const [slid, setSlid] = useState(false);
  useEffect(() => {
    if (slideWhen && !was.current) setSlid(true);
    was.current = slideWhen;
  }, [slideWhen]);
  return (
    <div
      role="tabpanel"
      id={panelId(tab)}
      aria-labelledby={tabId(tab)}
      hidden={on !== tab}
      className={cx("park-world-panel", slid && slide)}
      data-tab={tab}
    >
      <div className="park-world-panelhead">
        <h2 className="park-world-paneltitle">{title}</h2>
        <span className="park-world-panelsub">{sub}</span>
        {aside ? <span className="park-world-panelaside">{aside}</span> : null}
      </div>
      <PanelBody label={title}>{children}</PanelBody>
    </div>
  );
}

export function EmptyPanel({ title, line }: { title: string; line: string }) {
  return (
    <div className="park-world-emptypanel">
      <p className="park-world-emptytitle">{title}</p>
      <p className="park-world-emptyline">{line}</p>
    </div>
  );
}

/** The Story of a real run: its recorded events in plain words, newest first, with their recorded time of day. */
export function RunStory({ events }: { events: readonly RunEvent[] }) {
  const story = storyOf(events);
  if (story.length === 0)
    return (
      <EmptyPanel
        title="Nothing recorded yet"
        line="The story fills in as the run records what its agents do."
      />
    );
  return (
    <ol className="park-world-story" aria-label="What happened, newest first">
      {story.map((e) => (
        <li key={e.seq} className="park-world-storyrow">
          <span className="park-world-storytext">{e.summary}</span>
          <span className="park-world-storymeta">
            {e.type === "building.completed" ? (
              <span className="park-world-steptag park-world-steptag--done">Step done</span>
            ) : null}
            {clockOf(e.ts) ? <span>{`${clockOf(e.ts)} UTC`}</span> : null}
          </span>
        </li>
      ))}
    </ol>
  );
}

const STATE_WORD: Record<RunStep["state"], string> = {
  done: "Done",
  working: "Working",
  started: "Started",
  stopped: "Stopped here",
  planned: "Not started yet",
};

/** The plan of a real run, in order: "Step n of m" from world.planned and the unit events. */
export function RunStepList({ events }: { events: readonly RunEvent[] }) {
  const { steps, total } = runSteps(events);
  if (steps.length === 0)
    return (
      <EmptyPanel
        title="No plan recorded yet"
        line="The steps show here once the Director records the plan."
      />
    );
  const of = total ?? steps.length;
  return (
    <ol className="park-world-steps" aria-label="The plan, in order">
      {steps.map((s, i) => (
        <li
          key={s.key}
          className={cx("park-world-step", `park-world-step--${s.state}`)}
          data-state={s.state}
        >
          <span className="park-world-stepmark" aria-hidden="true">
            {s.state === "done" ? "✓" : String(i + 1)}
          </span>
          <span className="park-world-stepinfo">
            <span className="park-world-steptitle">
              {`Step ${i + 1} of ${of}`}
              <span className={cx("park-world-steptag", `park-world-steptag--${s.state}`)}>
                {STATE_WORD[s.state]}
              </span>
            </span>
            {s.title ? <span className="park-world-stepline">{s.title}</span> : null}
            {s.detail ? <span className="park-world-stepdetail">{s.detail}</span> : null}
          </span>
          {s.at ? <span className="park-world-stepat">{`${s.at} UTC`}</span> : null}
        </li>
      ))}
    </ol>
  );
}

/** "n of m done" for the Steps header and "n/m" for its tab, from the same recorded steps. */
export function stepsCount(events: readonly RunEvent[]): { done: number; of: number } | null {
  const { steps, total, done } = runSteps(events);
  const of = total ?? steps.length;
  return of > 0 ? { done, of } : null;
}
