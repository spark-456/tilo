// Step 2, "Tilo's version": Tilo's four steps with an "Ask me first" switch on each, one question for the
// person, the estimates and the way on (design: Tilo App Skills.dc.html, `t.isLearn`).
import { cx } from "../../components/cx";
import { agent, icon } from "./skillsKit";
import { BUBBLE_TAIL, LEARN_NOTE, PLAN, QUESTION, estimateSkillPlan } from "./teachData";
import type { PaneProps } from "./useTeach";

export function LearnPane({ t, night }: PaneProps) {
  const est = estimateSkillPlan(PLAN, t.ask, t.currency);
  const estimates = [
    { k: "Each run", v: est.run },
    { k: "Time", v: est.time },
    { k: "Stops to ask", v: est.stops },
  ];
  return (
    <div className="park-skills-pane park-skills-pane--grid">
      <div className="park-skills-learn-col">
        <div className="park-skills-bubble-row">
          <div className="park-skills-bubble-tile">
            {agent({ role: "builder", rank: "lead", expr: "talking" }, 40, night)}
          </div>
          <div className="park-skills-bubble">
            Here’s how I’d do <b>{t.name}</b>
            {BUBBLE_TAIL}
          </div>
        </div>
        {PLAN.map((p, i) => {
          const on = t.ask[i] === true;
          return (
            <div key={p.text} className="park-skills-plan-row">
              <span className="park-skills-plan-n">{i + 1}</span>
              <span className="park-skills-plan-main">
                <span className="park-skills-plan-text">{p.text}</span>
                <span className="park-skills-plan-tool">
                  {icon(p.icon, 12)}
                  {p.tool}
                </span>
              </span>
              <button
                type="button"
                role="switch"
                aria-checked={on}
                className={cx("park-skills-ask", on && "park-skills-ask--on")}
                onClick={() => t.toggleAsk(i)}
              >
                Ask me first
                <span className={cx("park-skills-ask-track", on && "park-skills-ask-track--on")}>
                  <span className={cx("park-skills-ask-knob", on && "park-skills-ask-knob--on")} />
                </span>
              </button>
            </div>
          );
        })}
      </div>
      <div className="park-skills-learn-col park-skills-learn-col--side">
        <div className="park-skills-question">
          <div className="park-skills-question-head">
            <div className="park-skills-question-tile">
              {agent({ role: "builder", expr: "puzzled" }, 38, night)}
            </div>
            <div className="park-skills-question-text">
              <div className="park-skills-question-eyebrow">{QUESTION.eyebrow}</div>
              <div className="park-skills-question-q">{QUESTION.text}</div>
            </div>
          </div>
          <div className="park-skills-answers">
            {QUESTION.answers.map((a) => (
              <button
                key={a}
                type="button"
                aria-pressed={t.qAns === a}
                className={cx("park-skills-answer", t.qAns === a && "park-skills-answer--on")}
                onClick={() => t.setQAns(a)}
              >
                {a}
              </button>
            ))}
          </div>
        </div>
        <div className="park-skills-estimates">
          {estimates.map((m) => (
            <div key={m.k} className="park-skills-estimate">
              <div className="park-skills-estimate-k">{m.k}</div>
              <div className="park-skills-estimate-v">{m.v}</div>
            </div>
          ))}
        </div>
        <div className="park-skills-note">{LEARN_NOTE}</div>
        <div className="park-skills-grow" />
        <div className="park-skills-actions-row">
          <button type="button" className="park-skills-back" onClick={t.back}>
            Back
          </button>
          <button type="button" className="park-skills-go" onClick={t.next}>
            Let Tilo try it
          </button>
        </div>
      </div>
    </div>
  );
}
