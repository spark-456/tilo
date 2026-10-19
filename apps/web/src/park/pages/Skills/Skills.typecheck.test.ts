// WEB-8a: Vitest does not evaluate types, so this runs the TypeScript compiler (strict, noUncheckedIndexedAccess,
// exactOptionalPropertyTypes) over src/park and test-support/park and fails on any error in the Skills page,
// its tests or the Skills test support. Pinned types: `SkillsPage` takes `{ app: AppCtx }` and returns a node;
// `useSchedule()` returns the store's `Schedule`; `saveSkill` takes a `Skill`.
import { describe, expect, expectTypeOf, it } from "vitest";
import { parkTypeErrors } from "../../../../test-support/park/typecheck";
import type { Api } from "../../api/index";
import type { Skill } from "../../api/types";
import type { AppCtx } from "../../app/AppCtx";
import type { useSchedule } from "../../app/context";
import type { Schedule } from "../../app/store";
import type { SkillsPage } from "./SkillsPage";

describe("WEB_8a_typecheck: Skills compiles with the repo's strict options", () => {
  it("WEB_8a_typecheck_SkillsPage_takes_the_app_prop_and_useSchedule_returns_a_Schedule", () => {
    expectTypeOf<Parameters<typeof SkillsPage>[0]>().toEqualTypeOf<{ app: AppCtx }>();
    expectTypeOf<ReturnType<typeof useSchedule>>().toEqualTypeOf<Schedule>();
    expectTypeOf<Parameters<Api["saveSkill"]>[0]>().toEqualTypeOf<Skill>();
  });

  it("WEB_8a_typecheck_skills_has_no_type_errors", { timeout: 240_000 }, async () => {
    const errors = (await parkTypeErrors()).filter(
      (e) =>
        e.startsWith("src/park/pages/Skills/") ||
        e.startsWith("test-support/park/skills") ||
        e.startsWith("src/park/app/context.tsx") ||
        e.startsWith("src/park/app/pages.ts"),
    );
    expect(errors).toEqual([]);
  });
});
