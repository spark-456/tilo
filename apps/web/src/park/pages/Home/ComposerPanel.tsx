// The composer column of Home (reference "Tilo App Home.dc.html"): the example chips while idle, the
// "drafting" line, the plan card, and the glass panel with the task input and the size of job.
// Presentation only: the phase, the query and the 900 ms draft are HomePage's.
import type { Effort, QuickCost, SwitchReason } from "../../api/types";
import { type SegmentOption, SegmentedControl } from "../../components";
import { type IntakeClient, IntakeControl } from "./IntakeControl";
import { EFFORTS, type Mode, SWITCH_WORDS, quickCostLine } from "./homeData";

export type Phase = "idle" | "drafting" | "plan";

/** What the Quick part of the composer shows (COST-FAST-1). A Quick ask makes no world and no plan. */
export type QuickView =
  | { state: "idle" }
  | { state: "asking" }
  | { state: "answered"; text: string; cost: QuickCost | null; sample: boolean }
  | { state: "switch"; reason: SwitchReason }
  | { state: "error"; message: string };

export const QUICK_IDLE: QuickView = { state: "idle" };

const EFFORT_OPTIONS: SegmentOption[] = EFFORTS.map((e) => ({
  value: e.key,
  label: e.label,
  tone: "heroInk",
}));

function QuickCard({
  view,
  sending,
  onSwitch,
}: { view: QuickView; sending: boolean | undefined; onSwitch: () => void }) {
  if (view.state === "asking") {
    // No spinner, no progress: a plain line while the one call is out.
    return (
      // biome-ignore lint/a11y/useSemanticElements: the design's status line is a div with role="status"
      <div role="status" className="park-home-drafting">
        Asking Tilo
      </div>
    );
  }
  if (view.state === "error") {
    return (
      <div role="alert" className="park-home-quick park-home-quick--note">
        <span>{view.message}</span>
      </div>
    );
  }
  if (view.state === "switch") {
    return (
      // biome-ignore lint/a11y/useSemanticElements: a labelled region around an offer, not a fieldset
      <div
        role="region"
        aria-label="Quick answer"
        className="park-home-quick park-home-quick--note"
      >
        <span>{`This needs Thinking. ${SWITCH_WORDS[view.reason]}`}</span>
        <button type="button" className="park-home-change" disabled={sending} onClick={onSwitch}>
          Switch to Thinking
        </button>
      </div>
    );
  }
  if (view.state !== "answered") return null;
  const cost = quickCostLine(view.cost);
  return (
    // biome-ignore lint/a11y/useSemanticElements: a labelled region around an answer, not a fieldset
    <div role="region" aria-label="Quick answer" className="park-home-quick">
      <div className="park-home-quick__head">
        <span className="park-home-tier">QUICK</span>
        {view.sample ? <span className="park-home-quick__sample">Sample answer</span> : null}
      </div>
      <p className="park-home-quick__text">{view.text}</p>
      {cost ? <div className="park-home-quick__cost">{cost}</div> : null}
    </div>
  );
}

export interface ComposerProps {
  /** I6: absent until an upload route and transport are available. */
  readonly intakeClient?: IntakeClient;
  readonly mode: Mode;
  readonly modes: readonly Mode[];
  readonly query: string;
  /** What the person typed, or the size's example task when the box is empty. */
  readonly shown: string;
  readonly phase: Phase;
  /** A start is on its way to the server: the confirm control waits (live only). */
  readonly sending?: boolean;
  /** QA-DEMO-1: a demo session. The plan is a labelled sample and confirming opens the sample world. */
  readonly sample?: boolean;
  /** Quick or Thinking (COST-FAST-1); Thinking when not given. */
  readonly effort?: Effort;
  readonly onEffort?: (effort: Effort) => void;
  readonly quick?: QuickView;
  /** "Switch to Thinking" on a Quick offer: the same text goes as Thinking. */
  readonly onSwitch?: () => void;
  readonly onQuery: (value: string) => void;
  readonly onMode: (key: string) => void;
  readonly onChip: (label: string) => void;
  readonly onDraft: () => void;
  readonly onConfirm: () => void;
  readonly onChange: () => void;
}

export function ComposerPanel(p: ComposerProps) {
  const { mode, phase } = p;
  const effort = p.effort ?? "thinking";
  const quick = p.quick ?? QUICK_IDLE;
  const quickMode = effort === "quick";
  const effortNote = EFFORTS.find((e) => e.key === effort)?.note ?? "";
  const options: SegmentOption[] = p.modes.map((m) => ({
    value: m.key,
    label: m.label,
    tone: "heroInk",
  }));
  return (
    <div className="park-home-composer">
      <QuickCard view={quick} sending={p.sending} onSwitch={p.onSwitch ?? (() => undefined)} />
      {phase === "idle" && quick.state === "idle" ? (
        <div className="park-home-chips">
          {mode.chips.map((label) => (
            <button
              key={label}
              type="button"
              className="park-home-chip"
              onClick={() => p.onChip(label)}
            >
              {label}
            </button>
          ))}
        </div>
      ) : null}
      {phase === "drafting" ? (
        // biome-ignore lint/a11y/useSemanticElements: the design's status line is a div with role="status"
        <div role="status" className="park-home-drafting">
          {/* a still ring: the draft is a fixed-timer stand-in with no call behind it, so it does not turn (HR-1) */}
          <span className="park-home-spin" aria-hidden="true" />
          {p.sample
            ? `Showing a sample plan for “${p.shown}”`
            : `Tilo is drafting a ${mode.word} for “${p.shown}”`}
        </div>
      ) : null}
      {phase === "plan" ? (
        <div className="park-home-plan">
          <div className="park-home-plan__main">
            <div className="park-home-plan__head">
              <span className="park-home-tier">{mode.tier.toUpperCase()}</span>
              <span className="park-home-plan__query">{p.shown}</span>
            </div>
            <div className="park-home-meta">
              {(
                [
                  ["Agents", mode.agents],
                  ["Cost", mode.cost],
                  ["Time", mode.eta],
                ] as const
              ).map(([k, v]) => (
                <span key={k}>
                  <span className="park-home-meta__k">{k}</span>{" "}
                  <span className="park-home-meta__v">{v}</span>
                </span>
              ))}
            </div>
            <ol className="park-home-steps">
              {mode.steps.map((text, i) => (
                <li key={text} className="park-home-step">
                  <span className="park-home-step__n">{i + 1}</span>
                  {text}
                </li>
              ))}
            </ol>
            {p.sample ? (
              <p className="park-home-plan__sample">
                Sample plan. Demo sessions replay a recorded run; sign in to start your own.
              </p>
            ) : null}
          </div>
          <div className="park-home-plan__actions">
            <button
              type="button"
              className="park-home-confirm"
              disabled={p.sending}
              aria-busy={p.sending ? true : undefined}
              onClick={p.onConfirm}
            >
              {p.sample ? "Open the sample world" : mode.confirm}
            </button>
            <button
              type="button"
              className="park-home-change"
              disabled={p.sending}
              onClick={p.onChange}
            >
              Change brief
            </button>
          </div>
        </div>
      ) : null}
      <div className="park-home-panel park-home-glass">
        <IntakeControl client={p.intakeClient}>
          <div className="park-home-input-row">
            <div className="park-home-logo">
              <div className="park-home-logo__face">
                <div className="park-home-logo__dot" />
                <div className="park-home-logo__dot" />
              </div>
            </div>
            <input
              className="park-home-input"
              type="text"
              aria-label="Describe your task"
              value={p.query}
              placeholder={`e.g. ${mode.example}`}
              onChange={(e) => p.onQuery(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") p.onDraft();
              }}
            />
            <button type="button" className="park-home-start" onClick={p.onDraft}>
              {quickMode ? "Ask" : mode.start}
            </button>
          </div>
        </IntakeControl>
        <div className="park-home-mode-row">
          <div className="park-home-size">
            <SegmentedControl
              label="Size of job"
              options={options}
              value={mode.key}
              onChange={p.onMode}
              sliding
            />
          </div>
          <div className="park-home-effort">
            <SegmentedControl
              label="Depth"
              options={EFFORT_OPTIONS}
              value={effort}
              onChange={(value) => p.onEffort?.(value as Effort)}
              sliding
            />
          </div>
          <div className="park-home-hint">{quickMode ? effortNote : mode.hint}</div>
        </div>
      </div>
    </div>
  );
}
