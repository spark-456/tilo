// "Teach Tilo something new": the card head with the teacher and the step bar, then the pane of the step the
// person is on (design: Tilo App Skills.dc.html, README Skills 2). The flow itself lives in useTeach.
import type { RefObject } from "react";
import { ApiReadState } from "../../components/ApiReadState";
import { cx } from "../../components/cx";
import { LearnPane } from "./LearnPane";
import { RunPane } from "./RunPane";
import { SavePane } from "./SavePane";
import { ShowPane } from "./ShowPane";
import { agent } from "./skillsKit";
import { STEP_LABELS } from "./teachData";
import type { PaneProps } from "./useTeach";

export const CARD_TITLE = "Teach Tilo something new";
export const CARD_SUB =
  "Show it once. Tilo repeats it, you check the result, and it becomes a skill your agents can reuse.";

export function TeachCard({
  t,
  night,
  user,
  cardRef,
  retryRead,
}: PaneProps & { cardRef: RefObject<HTMLElement>; retryRead: () => void }) {
  const expr = t.saved ? "delighted" : t.rec || t.stage === 2 ? "focused" : "talking";
  return (
    <section ref={cardRef} aria-label="Teach a skill" className="park-skills-card">
      <div className="park-skills-card-head">
        <div className="park-skills-teacher">
          {agent({ role: "research", rank: "lead", expr }, 58, night)}
        </div>
        <div className="park-skills-card-text">
          <h2 className="park-skills-card-title">{CARD_TITLE}</h2>
          <div className="park-skills-card-sub">{CARD_SUB}</div>
        </div>
        <ol aria-label="Steps" className="park-skills-steps">
          {STEP_LABELS.map((label, i) => {
            const tone = i < t.stage ? "done" : i === t.stage ? "now" : "next";
            return (
              <li key={label}>
                <button
                  type="button"
                  className={cx("park-skills-step", !t.reach[i] && "park-skills-step--locked")}
                  disabled={!t.reach[i] || t.saved}
                  aria-current={i === t.stage ? "step" : undefined}
                  onClick={() => t.goStep(i)}
                >
                  <span className={`park-skills-seg park-skills-seg--${tone}`} />
                  <span
                    className={cx(
                      "park-skills-step-label",
                      i === t.stage && "park-skills-step-label--now",
                    )}
                  >
                    <span className={`park-skills-dot park-skills-dot--${tone}`}>{i + 1}</span>
                    {label}
                  </span>
                </button>
              </li>
            );
          })}
        </ol>
      </div>
      {t.live && t.busy && t.stage === 0 ? (
        <output className="park-skills-card-sub">Reading your description…</output>
      ) : null}
      {t.live ? (
        <div data-skills-action-state="" style={{ blockSize: 176 }}>
          <div data-testid={t.failure != null ? "skills-teach-error" : undefined}>
            <ApiReadState
              error={t.failure}
              pending={false}
              retryRead={retryRead}
              title="The skill could not be updated"
            />
          </div>
        </div>
      ) : null}
      {t.stage === 0 ? <ShowPane t={t} night={night} user={user} /> : null}
      {t.stage === 1 ? <LearnPane t={t} night={night} user={user} /> : null}
      {t.stage === 2 ? <RunPane t={t} night={night} user={user} /> : null}
      {t.stage === 3 ? <SavePane t={t} night={night} user={user} /> : null}
    </section>
  );
}
