// "Help your agents get better" section of the Skills page (design: Tilo App Skills.dc.html lines 215-300):
// - Questions agents saved up
// - Rate recent runs (FR-SKL-05: thumbs up/down, step picker, fix instruction applied to next run and logged)
// - Ready for your review (FR-SKL-06: run-history bars, Mark as trusted / Keep learning gated by SKILL_TRUST_CONFIG)
// - Who helped this month (FR-SKL-07: Mistakes since July, Answers and fixes, per-person counts only, never message content)
import { useState } from "react";
import type { Learn, Skill } from "../../api/types";
import type { AppCtx } from "../../app/AppCtx";
import { cx } from "../../components/cx";
import { SKILL_TRUST_CONFIG, type SkillFixEntry, canTrustSkill } from "./skillConfig";
import { agent, icon } from "./skillsKit";

export interface HelpProps {
  app: AppCtx;
  skills: readonly Skill[];
  learn: Learn;
  ans: Readonly<Record<string, string>>;
  rate: Readonly<Record<string, "up" | "down">>;
  fixed: Readonly<Record<string, SkillFixEntry>>;
  rev: Readonly<Record<string, "trusted" | "learning">>;
  onAnswer: (skillId: string, skillName: string, label: string) => void;
  onRateUp: (rateId: string) => void;
  onRateDown: (rateId: string) => void;
  onSaveFix: (entry: SkillFixEntry) => void;
  onReview: (skillId: string, skillName: string, decision: "trusted" | "learning") => void;
}

function ThumbIcon({ down }: { down?: boolean }) {
  return (
    <svg
      width={17}
      height={17}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2.2}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={down ? "park-skills-thumb--down" : undefined}
    >
      <title>{down ? "Thumbs down" : "Thumbs up"}</title>
      <path d="M7 11v9H4v-9h3zm0 0l4-8c1.7 0 3 1.3 3 3v3h5a2 2 0 0 1 2 2.3l-1.2 7A2 2 0 0 1 17.8 20H7" />
    </svg>
  );
}

export function HelpSection({
  app,
  skills,
  learn,
  ans,
  rate,
  fixed,
  rev,
  onAnswer,
  onRateUp,
  onRateDown,
  onSaveFix,
  onReview,
}: HelpProps) {
  const [fixing, setFixing] = useState<string | null>(null);
  const [fixStep, setFixStep] = useState<number | null>(null);
  const [fixText, setFixText] = useState("");

  const asksSrc = skills.filter((s) => s.ask);
  const qLeftN = asksSrc.filter((s) => !ans[s.id]).length;
  const mine = Object.keys(ans).length + Object.keys(fixed).length + Object.keys(rate).length;
  const helpersWithMine = learn.helpers.map((p) => ({
    id: p.id,
    name: p.you ? `${p.name} (you)` : p.name,
    init: p.init,
    c: p.c,
    impact: p.impact,
    n: p.n + (p.you ? mine : 0),
  }));
  const maxH = Math.max(1, ...helpersWithMine.map((p) => p.n));

  return (
    <section aria-label="Help your agents get better" className="park-skills-section">
      <div>
        <h2 className="park-skills-h2">Help your agents get better</h2>
        <div className="park-skills-section-sub">
          A minute here saves hours of rework later. Answer once and every agent using the skill
          learns it.
        </div>
      </div>
      <div className="park-skills-help-grid">
        <div className="park-skills-help-col">
          <div className="park-skills-help-card">
            <div className="park-skills-help-card-head">
              <h3 className="park-skills-h3">Questions agents saved up</h3>
              <span
                className={cx(
                  "park-skills-help-count",
                  qLeftN ? "park-skills-help-count--amber" : "park-skills-help-count--ok",
                )}
              >
                {qLeftN ? `${qLeftN} waiting` : "All answered"}
              </span>
            </div>
            {asksSrc.map((s) => {
              const a = ans[s.id];
              return (
                <div
                  key={s.id}
                  className={cx("park-skills-ask-item", a && "park-skills-ask-item--done")}
                >
                  <div className="park-skills-ask-top">
                    <div className="park-skills-ask-avatar">
                      {agent({ role: s.role, expr: a ? "delighted" : "puzzled" }, 36, app.night)}
                    </div>
                    <div className="park-skills-ask-body">
                      <div className="park-skills-ask-skill">{s.name}</div>
                      <div className="park-skills-ask-q">{s.ask?.q}</div>
                    </div>
                  </div>
                  {!a ? (
                    <div className="park-skills-ask-opts">
                      {s.ask?.a.map((label) => (
                        <button
                          key={label}
                          type="button"
                          className="park-skills-ask-opt"
                          onClick={() => onAnswer(s.id, s.name, label)}
                        >
                          {label}
                        </button>
                      ))}
                    </div>
                  ) : (
                    <div className="park-skills-ask-done">
                      {icon("check", 12)}
                      {`“${a}” · every agent now knows`}
                    </div>
                  )}
                </div>
              );
            })}
          </div>

          <div className="park-skills-help-card park-skills-help-card--rates">
            <div className="park-skills-help-card-head">
              <h3 className="park-skills-h3">Rate recent runs</h3>
              <span className="park-skills-help-hint">Thumbs down lets you fix the step</span>
            </div>
            {learn.rates.map((r) => {
              const v = rate[r.id];
              const isFixing = fixing === r.id;
              const isFixed = Boolean(fixed[r.id]) && !isFixing;
              return (
                <div key={r.id} className="park-skills-rate-row">
                  <div className="park-skills-rate-main">
                    <div className="park-skills-rate-info">
                      <div className="park-skills-rate-name">{r.name}</div>
                      <div className="park-skills-rate-meta">{r.meta}</div>
                    </div>
                    <div className="park-skills-rate-actions">
                      {isFixed ? <span className="park-skills-rate-fixed">Fix saved</span> : null}
                      <button
                        type="button"
                        aria-label="Good run"
                        aria-pressed={v === "up"}
                        className={cx(
                          "park-skills-rate-btn",
                          v === "up" && "park-skills-rate-btn--up",
                        )}
                        onClick={() => {
                          onRateUp(r.id);
                          if (fixing === r.id) setFixing(null);
                        }}
                      >
                        <ThumbIcon />
                      </button>
                      <button
                        type="button"
                        aria-label="Something went wrong"
                        aria-pressed={v === "down"}
                        className={cx(
                          "park-skills-rate-btn",
                          v === "down" && "park-skills-rate-btn--down",
                        )}
                        onClick={() => {
                          onRateDown(r.id);
                          setFixing(r.id);
                          setFixStep(null);
                          setFixText("");
                        }}
                      >
                        <ThumbIcon down />
                      </button>
                    </div>
                  </div>
                  {isFixing ? (
                    <div className="park-skills-fix-box">
                      <div className="park-skills-fix-title">Which step went wrong?</div>
                      <div className="park-skills-fix-steps">
                        {r.steps.map((label, i) => {
                          const on = fixStep === i;
                          return (
                            <button
                              key={label}
                              type="button"
                              aria-pressed={on}
                              className={cx(
                                "park-skills-fix-step",
                                on && "park-skills-fix-step--on",
                              )}
                              onClick={() => setFixStep(i)}
                            >
                              {label}
                            </button>
                          );
                        })}
                      </div>
                      <textarea
                        aria-label="What should it do instead"
                        placeholder="What should it do instead?"
                        rows={2}
                        className="park-skills-fix-input"
                        value={fixText}
                        onChange={(e) => setFixText(e.currentTarget.value)}
                      />
                      <div className="park-skills-fix-actions">
                        <button
                          type="button"
                          className="park-skills-fix-cancel"
                          onClick={() => setFixing(null)}
                        >
                          Cancel
                        </button>
                        <button
                          type="button"
                          className="park-skills-fix-save"
                          onClick={() => {
                            const idx = fixStep ?? 0;
                            onSaveFix({
                              rateId: r.id,
                              skillName: r.name,
                              stepIndex: idx,
                              stepLabel: r.steps[idx] ?? "",
                              instruction: fixText,
                            });
                            setFixing(null);
                          }}
                        >
                          Save fix
                        </button>
                      </div>
                    </div>
                  ) : null}
                </div>
              );
            })}
          </div>
        </div>

        <div className="park-skills-help-col">
          <div className="park-skills-help-card">
            <h3 className="park-skills-h3">Ready for your review</h3>
            {learn.reviews.map((v) => {
              const s = skills.find((x) => x.id === v.id);
              const decision = rev[v.id];
              const eligible = canTrustSkill(v.bars, SKILL_TRUST_CONFIG);
              const skillName = s?.name ?? v.id;
              return (
                <div
                  key={v.id}
                  className={cx(
                    "park-skills-review-card",
                    decision === "trusted" && "park-skills-review-card--trusted",
                  )}
                >
                  <div className="park-skills-review-head">
                    <div className="park-skills-review-avatar">
                      {agent(
                        {
                          role: s?.role ?? "builder",
                          expr: decision === "trusted" ? "delighted" : "neutral",
                        },
                        44,
                        app.night,
                      )}
                    </div>
                    <div className="park-skills-review-info">
                      <div className="park-skills-review-name">{skillName}</div>
                      <div className="park-skills-review-meta">{v.meta}</div>
                    </div>
                  </div>
                  <div role="img" aria-label={v.meta} className="park-skills-review-bars">
                    {v.bars.map((b, i) => (
                      <span
                        // biome-ignore lint/suspicious/noArrayIndexKey: bars are positional run-history slots
                        key={i}
                        className={cx(
                          "park-skills-review-bar",
                          b ? "park-skills-review-bar--ok" : "park-skills-review-bar--bad",
                        )}
                        style={{ height: b ? `${12 + ((i * 7) % 12)}px` : "24px" }}
                      />
                    ))}
                  </div>
                  {!decision ? (
                    <div className="park-skills-review-actions">
                      <button
                        type="button"
                        disabled={!eligible}
                        className="park-skills-review-trust"
                        onClick={() => {
                          if (!eligible) return;
                          onReview(v.id, skillName, "trusted");
                        }}
                      >
                        Mark as trusted
                      </button>
                      <button
                        type="button"
                        className="park-skills-review-keep"
                        onClick={() => onReview(v.id, skillName, "learning")}
                      >
                        Keep learning
                      </button>
                    </div>
                  ) : (
                    <div
                      className={cx(
                        "park-skills-review-result",
                        decision === "trusted"
                          ? "park-skills-review-result--ok"
                          : "park-skills-review-result--hero",
                      )}
                    >
                      {decision === "trusted"
                        ? "Trusted. Tilo stops asking before routine steps."
                        : `Still learning. Tilo checks again after ${SKILL_TRUST_CONFIG.minGoodRunsForTrust} more runs.`}
                    </div>
                  )}
                </div>
              );
            })}
          </div>

          <div className="park-skills-help-card">
            <div className="park-skills-help-card-head">
              <h3 className="park-skills-h3">Who helped this month</h3>
              <span className="park-skills-help-hint">{SKILL_TRUST_CONFIG.helperMonthLabel}</span>
            </div>
            <div className="park-skills-who-stats">
              <div className="park-skills-who-stat park-skills-who-stat--ok">
                <div className="park-skills-who-stat-k">Mistakes since July</div>
                <div className="park-skills-who-stat-v">
                  {SKILL_TRUST_CONFIG.mistakesDeltaSinceJuly}
                </div>
              </div>
              <div className="park-skills-who-stat park-skills-who-stat--hero">
                <div className="park-skills-who-stat-k">Answers and fixes</div>
                <div className="park-skills-who-stat-v">
                  {String(SKILL_TRUST_CONFIG.baseMonthlyAnswersAndFixes + mine)}
                </div>
              </div>
            </div>
            {helpersWithMine.map((p) => (
              <div key={p.id} className="park-skills-helper-row">
                <div className="park-skills-helper-init" style={{ background: p.c }}>
                  {p.init}
                </div>
                <div className="park-skills-helper-info">
                  <div className="park-skills-helper-name">{p.name}</div>
                  <div className="park-skills-helper-impact">{p.impact}</div>
                </div>
                <div className="park-skills-helper-bar-col">
                  <span className="park-skills-helper-n">{String(p.n)}</span>
                  <span className="park-skills-helper-track">
                    <span
                      className="park-skills-helper-fill"
                      style={{ width: `${Math.round((p.n / maxH) * 100)}%` }}
                    />
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}
