// Configuration and pure domain helpers for Skills trust thresholds, run fixes, and monthly helper summaries
// (FR-SKL-04, FR-SKL-05, FR-SKL-06, FR-SKL-07). The required number of good runs for trust lives in
// SKILL_TRUST_CONFIG, never hardcoded in component logic.
import type { Skill } from "../../api/types";

export interface SkillTrustConfig {
  readonly minGoodRunsForTrust: number;
  readonly baseMonthlyAnswersAndFixes: number;
  readonly mistakesDeltaSinceJuly: string;
  readonly helperMonthLabel: string;
}

export const SKILL_TRUST_CONFIG: SkillTrustConfig = {
  minGoodRunsForTrust: 5,
  baseMonthlyAnswersAndFixes: 41,
  mistakesDeltaSinceJuly: "−38%",
  helperMonthLabel: "September",
};

export interface SkillFixEntry {
  readonly rateId: string;
  readonly skillName: string;
  readonly stepIndex: number;
  readonly stepLabel: string;
  readonly instruction: string;
}

/** Returns true only when the recorded run-history bars contain at least `config.minGoodRunsForTrust` good runs. */
export function canTrustSkill(
  bars: readonly number[],
  config: SkillTrustConfig = SKILL_TRUST_CONFIG,
): boolean {
  const goodRuns = bars.filter((b) => b > 0).length;
  return goodRuns >= config.minGoodRunsForTrust;
}

/** Applies a logged step fix to a skill's steps for its next run. */
export function applySkillFix(skill: Skill, stepIndex: number, instruction: string): Skill {
  const trimmed = instruction.trim();
  if (!trimmed) return skill;
  const idx = Math.max(0, Math.min(skill.steps.length - 1, stepIndex));
  const steps = skill.steps.map((step, i) => (i === idx ? `${step} (${trimmed})` : step));
  return { ...skill, steps };
}
