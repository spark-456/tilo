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
import type { Decision, Skill } from "../../api/types";
import { cx } from "../../components/cx";
import { icon } from "../../shell/kit";
import { type RunStep, clockOf, runSteps, storyOf } from "./runSteps";
import { storySummary } from "./skillRunVisible";
import type { RunEvent } from "./useRunEvents";

export type WorldTab = "story" | "steps" | "result" | "chat";
const TABS_WITH_CHAT: readonly (readonly [WorldTab, string])[] = [
  ["story", "Story"],
  ["chat", "Chat"],
  ["result", "Result"],
  ["steps", "Steps"],
];
const TABS_WITHOUT_CHAT: readonly (readonly [WorldTab, string])[] = [
  ["story", "Story"],
  ["steps", "Steps"],
  ["result", "Result"],
];
const TAB_ICONS: Record<WorldTab, string> = {
  story: "file",
  chat: "chat",
  result: "parcel",
  steps: "check",
};
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
  const tabs = chat ? TABS_WITH_CHAT : TABS_WITHOUT_CHAT;
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

function HandIcon({ size = 18 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M8 13V6.5a1.5 1.5 0 0 1 3 0V11 M11 11V5a1.5 1.5 0 0 1 3 0v6 M14 11V6.5a1.5 1.5 0 0 1 3 0V14c0 4-2.5 7-6 7-2.6 0-4.2-1.4-5.6-3.6L4 14.5a1.5 1.5 0 0 1 2.4-1.8L8 14.5" />
    </svg>
  );
}

export interface ActiveApproval {
  readonly id: string;
  readonly seq: number;
  readonly actor?: string | undefined;
  readonly who: string;
  readonly time: string;
  readonly question: string;
  readonly exact: string;
  readonly risk: string;
  readonly cost: string;
  readonly gateId: string;
  readonly cardId?: string | undefined;
}

export function activeApprovalOf(events: readonly RunEvent[]): ActiveApproval | null {
  const resolvedGates = new Set<string>();
  const resolvedCards = new Set<string>();
  for (const e of events) {
    if (e.type === "approval.resolved") {
      const d = e.data as { gate_id?: string; card_id?: string } | null;
      if (d?.gate_id) resolvedGates.add(d.gate_id);
      if (d?.card_id) resolvedCards.add(d.card_id);
      if (e.target) resolvedGates.add(e.target);
    }
  }
  const req = [...events].reverse().find((e) => {
    if (e.type !== "approval.requested") return false;
    const d = e.data as { gate_id?: string; card_id?: string } | null;
    const gateId = d?.gate_id ?? e.target;
    const cardId = d?.card_id;
    if (gateId && resolvedGates.has(gateId)) return false;
    if (cardId && resolvedCards.has(cardId)) return false;
    const resolvedLater = events.some(
      (r) =>
        r.type === "approval.resolved" &&
        r.seq > e.seq &&
        ((e.target && r.target === e.target) ||
          (gateId && (r.data as { gate_id?: string } | null)?.gate_id === gateId)),
    );
    return !resolvedLater;
  });
  if (!req) return null;
  const d = (req.data as Record<string, unknown> | null) ?? {};
  const summary = req.summary?.trim() ?? "";
  const whoMatch = /^(.*?)\s+needs your yes/i.exec(summary);
  const who = whoMatch?.[1]
    ? whoMatch[1]
    : req.actor
      ? req.actor.charAt(0).toUpperCase() + req.actor.slice(1)
      : "Agent";
  const time = clockOf(req.ts) ? `${clockOf(req.ts)} UTC` : "";
  const question =
    typeof d.question === "string" ? d.question : summary || "Approval requested for action.";
  const exact =
    typeof d.exact === "string"
      ? d.exact
      : typeof d.action_type === "string"
        ? `Action: ${d.action_type.replace(/_/g, " ")}`
        : summary;
  // UX-AUDIT (HR-1): only what the event records; nothing recorded is "Not reported", never a guessed risk or price.
  const tier = typeof d.risk_tier === "string" ? `Tier ${d.risk_tier.replace(/^T/, "")}` : "";
  const undoable =
    d.irreversible === true
      ? "It can't be undone."
      : d.irreversible === false
        ? "It can be undone."
        : "";
  const risk =
    typeof d.risk === "string"
      ? d.risk
      : [tier && `${tier}.`, undoable].filter(Boolean).join(" ") || "Not reported";
  const cost =
    typeof d.cost === "string"
      ? d.cost
      : req.credits
        ? `${req.credits} credit${req.credits === 1 ? "" : "s"}`
        : "Not reported";
  const gateId = typeof d.gate_id === "string" ? d.gate_id : (req.target ?? "");
  const cardId = typeof d.card_id === "string" ? d.card_id : undefined;
  const id = typeof d.id === "string" ? d.id : `approval-${req.seq}`;

  return {
    id,
    seq: req.seq,
    actor: req.actor,
    who,
    time,
    question,
    exact,
    risk,
    cost,
    gateId,
    cardId,
  };
}

/** The Story of a real run: its recorded events in plain words, newest first, with their recorded time of day. */
/** A plain yes answers this decision (a served gate or consent, or a fixture approval): not a question or a form. */
export function canTapAnswer(d: Decision): boolean {
  if (d.provide || d.yes === "") return false;
  return d.card ? d.card.kind === "gate" || d.card.kind === "consent" : true;
}

/** UX-AUDIT: the served decision behind an approval card (Needs you), when there is one. */
export interface ApprovalAnswer {
  /** The decision is answered (the store's own record, set only once the Api took the answer on a live path). */
  decided: boolean;
  /** A plain yes answers it (not a question or a fields form), so Approve can sit on the card. */
  canTap: boolean;
}

export function RunStory({
  events,
  skills = [],
  answer,
  onApprove,
  onDetails,
  onLater,
}: {
  events: readonly RunEvent[];
  skills?: readonly Skill[];
  /** The approval's own decision; with none served the card can only send the person to Needs you. */
  answer?: ApprovalAnswer | undefined;
  /** Sends the real answer (the same `decide` as Needs you); the card says Approved only once `answer.decided`. */
  onApprove?: (req: ActiveApproval) => void;
  /** Opens the decision in Needs you (full item, typed answers). */
  onDetails?: (req: ActiveApproval) => void;
  /** Leaves it unanswered: nothing is sent. */
  onLater?: (req: ActiveApproval) => void;
}) {
  const [view, setView] = useState<"plain" | "trace">("plain");
  const approval = activeApprovalOf(events);
  const story = storyOf(events);
  if (story.length === 0)
    return (
      <EmptyPanel
        title="Nothing recorded yet"
        line="The story fills in as the run records what its agents do."
      />
    );
  const totalCredits = events.reduce((sum, e) => sum + (e.credits ?? 0), 0);
  return (
    <div className="park-world-storycontainer">
      <div className="park-world-storyhead">
        <div className="park-world-storytitlewrap">
          <span className="park-world-storytitle">What happened</span>
          <span className="park-world-storysub">In order · newest at the bottom</span>
        </div>
        <div role="radiogroup" aria-label="Story view" className="park-world-storyviews">
          <button
            type="button"
            // biome-ignore lint/a11y/useSemanticElements: segmented radio button control
            role="radio"
            aria-checked={view === "plain"}
            className={cx(
              "park-world-storyviewbtn",
              view === "plain" && "park-world-storyviewbtn--on",
            )}
            onClick={() => setView("plain")}
          >
            Plain
          </button>
          <button
            type="button"
            // biome-ignore lint/a11y/useSemanticElements: segmented radio button control
            role="radio"
            aria-checked={view === "trace"}
            className={cx(
              "park-world-storyviewbtn",
              view === "trace" && "park-world-storyviewbtn--on",
            )}
            onClick={() => setView("trace")}
          >
            Trace
          </button>
        </div>
      </div>
      {approval ? (
        <section
          aria-label="Needs you"
          className="park-world-approval"
          data-testid="world-approval-card"
        >
          <div className="park-world-approval-head">
            <span className="park-world-approval-avatar" aria-hidden="true">
              <span className="park-world-approval-avatarinner">
                <span className="park-world-approval-avatareye" />
                <span className="park-world-approval-avatareye" />
              </span>
            </span>
            <div className="park-world-approval-meta">
              <strong className="park-world-approval-who">{approval.who} needs your yes</strong>
              <span className="park-world-approval-sub">
                approval.requested{approval.time ? ` · ${approval.time}` : ""}
              </span>
            </div>
            <span className="park-world-approval-hand" aria-hidden="true">
              <HandIcon size={18} />
            </span>
          </div>

          <div className="park-world-approval-q">{approval.question}</div>

          <div className="park-world-approval-exact">
            <span className="park-world-approval-exactlbl">EXACT ACTION</span>
            <span className="park-world-approval-exacttxt">{approval.exact}</span>
          </div>

          <div className="park-world-approval-grid">
            <strong>Risk</strong>
            <span>{approval.risk}</span>
            <strong>Cost</strong>
            <span>{approval.cost}</span>
          </div>

          {answer?.decided ? (
            <div className="park-world-approval-done">
              {icon("check", 16)}
              <span>{`Approved. ${approval.who} is continuing.`}</span>
            </div>
          ) : (
            <div className="park-world-approval-actions">
              {answer?.canTap && onApprove ? (
                <button
                  type="button"
                  className="park-world-approval-btn park-world-approval-btn--approve"
                  onClick={() => onApprove(approval)}
                >
                  {icon("check", 16)} Approve
                </button>
              ) : null}
              {onDetails ? (
                <button
                  type="button"
                  className="park-world-approval-btn park-world-approval-btn--edit"
                  onClick={() => onDetails(approval)}
                >
                  {answer?.canTap ? "See details" : "Answer in Needs you"}
                </button>
              ) : null}
              {onLater ? (
                <button
                  type="button"
                  className="park-world-approval-btn park-world-approval-btn--decline"
                  onClick={() => onLater(approval)}
                >
                  Decide later
                </button>
              ) : null}
            </div>
          )}
        </section>
      ) : null}
      {view === "plain" ? (
        <ol className="park-world-story" aria-label="What happened, newest first">
          {story.map((e) => (
            <li key={e.seq} className="park-world-storyrow">
              <span className="park-world-storytext">{storySummary(e, skills)}</span>
              <span className="park-world-storymeta">
                {e.type === "building.completed" ? (
                  <span className="park-world-steptag park-world-steptag--done">Step done</span>
                ) : null}
                {clockOf(e.ts) ? <span>{`${clockOf(e.ts)} UTC`}</span> : null}
              </span>
            </li>
          ))}
        </ol>
      ) : (
        <section className="park-world-trace" aria-label="Run trace">
          <div className="park-world-tracehead">
            <span className="park-world-tracecol park-world-tracecol--time">TIME</span>
            <span className="park-world-tracecol park-world-tracecol--event">EVENT · DETAIL</span>
            <span className="park-world-tracecol park-world-tracecol--cr">CR</span>
          </div>
          <div className="park-world-tracerows">
            {events
              .slice()
              .reverse()
              .map((e) => (
                <div key={e.seq} className="park-world-tracerow">
                  <span className="park-world-tracetime">
                    {clockOf(e.ts) ? `${clockOf(e.ts)} UTC` : "—"}
                  </span>
                  <span className="park-world-traceinfo">
                    <strong className="park-world-traceevent">{e.type}</strong>
                    <span className="park-world-tracedetail">{storySummary(e, skills)}</span>
                  </span>
                  <span className="park-world-tracecr">
                    {e.credits != null && e.credits > 0 ? e.credits : "·"}
                  </span>
                </div>
              ))}
          </div>
          <div className="park-world-tracetotal">
            <span className="park-world-tracecol park-world-tracecol--time" />
            <span className="park-world-tracetotallabel">Total so far</span>
            <span className="park-world-tracetotalcr">{totalCredits}</span>
          </div>
        </section>
      )}
    </div>
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
