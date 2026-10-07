// WEB-4: Vitest does not evaluate types, so this runs the TypeScript compiler (strict, noUncheckedIndexedAccess,
// exactOptionalPropertyTypes) over src/park and test-support/park and fails on any error in the Home page,
// its tests or the Home test support. Pinned types: `HomePage` takes `{ app: AppCtx }` and returns a node;
// `useSchedule()` returns the store's `Schedule`.
import { describe, expect, expectTypeOf, it } from "vitest";
import { parkTypeErrors } from "../../../../test-support/park/typecheck";
import type { AppCtx } from "../../app/AppCtx";
import type { useSchedule } from "../../app/context";
import type { Schedule } from "../../app/store";
import type { HomePage } from "./HomePage";

describe("WEB_4_typecheck: Home compiles with the repo's strict options", () => {
  it("WEB_4_typecheck_HomePage_takes_the_app_prop_and_useSchedule_returns_a_Schedule", () => {
    expectTypeOf<Parameters<typeof HomePage>[0]>().toEqualTypeOf<{ app: AppCtx }>();
    expectTypeOf<ReturnType<typeof useSchedule>>().toEqualTypeOf<Schedule>();
  });

  it("WEB_4_typecheck_home_has_no_type_errors", { timeout: 180_000 }, async () => {
    const errors = (await parkTypeErrors()).filter(
      (e) =>
        e.startsWith("src/park/pages/Home/") ||
        e.startsWith("test-support/park/home") ||
        e.startsWith("src/park/app/context.tsx") ||
        e.startsWith("src/park/app/pages.ts"),
    );
    expect(errors).toEqual([]);
  });
});
