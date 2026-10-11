import type { Api } from "./index";
import type { Skill } from "./types";
export interface FixBody {
  from_version: number;
  step: number;
  text: string;
  ask_first: boolean;
}
type Fixer = (id: string, body: FixBody) => Promise<Skill>;
const fixes = new WeakMap<Api, Fixer>();
export const installSkillFixer = (api: Api, fix: Fixer): void => {
  fixes.set(api, fix);
};
export function carrySkillFixer(from: Api, to: Api, enabled: () => boolean = () => true): Api {
  const fix = fixes.get(from);
  if (fix)
    installSkillFixer(to, (id, body) =>
      enabled() ? fix(id, body) : Promise.reject(new Error("Fix unavailable")),
    );
  return to;
}
export const fixSkill = (api: Api, id: string, body: FixBody): Promise<Skill> =>
  fixes.get(api)?.(id, body) ?? Promise.reject(new Error("Fix unavailable"));
