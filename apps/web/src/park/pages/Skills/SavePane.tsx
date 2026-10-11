// Step 4, "Save": the skill's name, who can use it and when it runs; once saved, the banner with
// "View in library" and "Teach another" (design: `t.isSave`). The skill starts as Learning.
import { cx } from "../../components/cx";
import { agent } from "./skillsKit";
import { SAVE, TRIGGERS, savedLine, sharedWith } from "./teachData";
import type { PaneProps } from "./useTeach";

export function SavePane({ t, night, user }: PaneProps) {
  if (t.saved) {
    return (
      <div className="park-skills-pane park-skills-pane--grid">
        <div className="park-skills-saved">
          <div className="park-skills-saved-tile">
            {agent({ role: "builder", rank: "lead", expr: "delighted" }, 70, night)}
          </div>
          <div className="park-skills-saved-text">
            <div className="park-skills-saved-title">
              “{t.taught?.name ?? t.name}” is now a skill
            </div>
            <div className="park-skills-saved-line">
              {savedLine(sharedWith(t.scope, user.org), t.trig)}
            </div>
          </div>
          <button type="button" className="park-skills-view" onClick={t.view}>
            View in library
          </button>
          <button type="button" className="park-skills-another" onClick={t.reset}>
            Teach another
          </button>
        </div>
      </div>
    );
  }
  // Live, only what POST /v1/skills takes: a skill for the person, run when they ask.
  const scopes = [
    { key: "me", label: "Just me" },
    ...(t.live ? [] : [{ key: "team", label: user.org } as const]),
  ] as const;
  const triggers = t.live ? TRIGGERS.filter((o) => o.key === "ask") : TRIGGERS;
  return (
    <div className="park-skills-pane park-skills-pane--grid">
      <div className="park-skills-save-col">
        <label className="park-skills-field">
          <span className="park-skills-label">{SAVE.nameLabel}</span>
          <input
            className="park-skills-save-name"
            value={t.name}
            onChange={(e) => t.setName(e.target.value)}
          />
        </label>
        <div className="park-skills-field">
          <span className="park-skills-label">{SAVE.who}</span>
          <div className="park-skills-picker">
            {scopes.map((o) => (
              <button
                key={o.key}
                type="button"
                aria-pressed={t.scope === o.key}
                className={cx("park-skills-pick", t.scope === o.key && "park-skills-pick--on")}
                onClick={() => t.setScope(o.key)}
              >
                {o.label}
              </button>
            ))}
          </div>
        </div>
        <div className="park-skills-field">
          <span className="park-skills-label">{SAVE.when}</span>
          <div className="park-skills-picker">
            {triggers.map((o) => (
              <button
                key={o.key}
                type="button"
                aria-pressed={t.trig === o.key}
                className={cx("park-skills-pick", t.trig === o.key && "park-skills-pick--on")}
                onClick={() => t.setTrig(o.key)}
              >
                {o.label}
              </button>
            ))}
          </div>
        </div>
      </div>
      <div className="park-skills-save-col park-skills-save-col--side">
        <div className="park-skills-starts">
          <div className="park-skills-starts-tile">
            {agent({ role: "builder", rank: "lead", expr: "talking" }, 40, night)}
          </div>
          <div className="park-skills-starts-text">
            It starts as <b>Learning</b>. {SAVE.note}
          </div>
        </div>
        <div className="park-skills-grow" />
        <div className="park-skills-actions-row">
          <button type="button" className="park-skills-back" onClick={t.back}>
            Back
          </button>
          <button type="button" className="park-skills-go" disabled={t.busy} onClick={t.save}>
            Save skill
          </button>
        </div>
      </div>
    </div>
  );
}
