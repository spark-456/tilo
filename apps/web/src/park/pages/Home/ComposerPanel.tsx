// The composer column of Home (reference "Tilo App Home.dc.html"): the example chips while idle, the
// "drafting" line, the plan card, and the glass panel with the task input and the size of job.
// Presentation only: the phase, the query and the 900 ms draft are HomePage's. The "Start a real task" link
// under the panel is the one element the design does not have.
import { type SegmentOption, SegmentedControl } from "../../components";
import type { Mode } from "./homeData";

export type Phase = "idle" | "drafting" | "plan";

export interface ComposerProps {
  readonly mode: Mode;
  readonly modes: readonly Mode[];
  readonly query: string;
  /** What the person typed, or the size's example task when the box is empty. */
  readonly shown: string;
  readonly phase: Phase;
  /** A start is on its way to the server: the confirm control waits (live only). */
  readonly sending?: boolean;
  readonly onQuery: (value: string) => void;
  readonly onMode: (key: string) => void;
  readonly onChip: (label: string) => void;
  readonly onDraft: () => void;
  readonly onConfirm: () => void;
  readonly onChange: () => void;
}

export function ComposerPanel(p: ComposerProps) {
  const { mode, phase } = p;
  const options: SegmentOption[] = p.modes.map((m) => ({
    value: m.key,
    label: m.label,
    tone: "heroInk",
  }));
  return (
    <div className="park-home-composer">
      {phase === "idle" ? (
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
          {/* motion: restored in WEB-3 (BQ-WEB-3): the ring turns */}
          <span className="park-home-spin" aria-hidden="true" />
          {`Tilo is drafting a ${mode.word} for “${p.shown}”`}
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
          </div>
          <div className="park-home-plan__actions">
            <button
              type="button"
              className="park-home-confirm"
              disabled={p.sending}
              aria-busy={p.sending ? true : undefined}
              onClick={p.onConfirm}
            >
              {mode.confirm}
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
            {mode.start}
          </button>
        </div>
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
          <div className="park-home-hint">{mode.hint}</div>
        </div>
      </div>
      {/* Not in the design (docs/park-designed-not-in-prd/Home.md): the composer above is fixture-only until
          FR-UX-13, so this plain link opens the old app's real intake form (a full navigation, not app.go). */}
      <a className="park-home-real" href="/start">
        Start a real task
      </a>
    </div>
  );
}
