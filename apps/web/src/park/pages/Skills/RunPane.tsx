// Step 3, "Try run": the desk and the lead builder over a practice run, and the four steps with what each is
// doing. A step set to ask first stops on amber "Asking you" until the person says yes (design: `t.isTry`).
import { cx } from "../../components/cx";
import { agent, desk, icon } from "./skillsKit";
import { PLAN, TRY, TRY_RUN_FIXTURE_EVENTS, formatTryRunResult } from "./teachData";
import type { PaneProps } from "./useTeach";

type Tone = "done" | "asking" | "working" | "waiting";

export function RunPane({ t, night }: PaneProps) {
  const { run, waiting, runDone } = t;
  const result = formatTryRunResult(TRY_RUN_FIXTURE_EVENTS, PLAN.length);
  const pill = runDone
    ? "Finished"
    : waiting
      ? "Waiting for you"
      : `Step ${Math.max(0, run) + 1} of 4`;
  const pillTone = runDone ? "done" : waiting ? "asking" : "working";
  const face = runDone ? "delighted" : waiting ? "needs" : "focused";
  const deskState = runDone ? "complete" : waiting ? "needs" : "active";
  return (
    <div className="park-skills-pane park-skills-pane--grid">
      <div className="park-skills-art">
        <div className="park-skills-art-top">
          <span className="park-skills-art-pill">{TRY.practice}</span>
          <span className={`park-skills-art-pill park-skills-art-pill--${pillTone}`}>{pill}</span>
        </div>
        <div>{desk(deskState, night)}</div>
        <div>
          {agent(
            { role: "builder", rank: "lead", expr: face, ring: waiting, facing: "R" },
            96,
            night,
          )}
        </div>
      </div>
      <div className="park-skills-run-col">
        {PLAN.map((p, i) => {
          const done = run > i || runDone;
          const current = run === i && !runDone;
          const asking = current && waiting;
          const tone: Tone = done ? "done" : asking ? "asking" : current ? "working" : "waiting";
          return (
            <div key={p.text} className={`park-skills-run-step park-skills-run-step--${tone}`}>
              <div className="park-skills-run-line">
                <span className={`park-skills-run-dot park-skills-run-dot--${tone}`}>
                  {done ? icon("check", 12) : i + 1}
                </span>
                <span className="park-skills-run-text">{p.text}</span>
                <span className={`park-skills-run-st park-skills-run-st--${tone}`}>
                  {done ? "Done" : asking ? "Asking you" : current ? "Working…" : "Waiting"}
                </span>
              </div>
              {asking ? (
                <div className="park-skills-answer-row">
                  <div className="park-skills-answer-prompt">
                    Add <b>{TRY.prompt}</b>
                    {TRY.promptTail}
                  </div>
                  <button type="button" className="park-skills-yes" onClick={t.approve}>
                    {TRY.yes}
                  </button>
                </div>
              ) : null}
            </div>
          );
        })}
        {runDone ? (
          <div className="park-skills-result">
            <div className="park-skills-result-text">
              <div className="park-skills-result-title">{result.title}</div>
              <div className="park-skills-result-line">{result.sub}</div>
            </div>
            <button type="button" className="park-skills-fix" onClick={t.back}>
              Fix a step
            </button>
            <button type="button" className="park-skills-looks" onClick={t.next}>
              Looks right
            </button>
          </div>
        ) : null}
      </div>
    </div>
  );
}
