// WEB-6: Vitest does not evaluate types, so this runs the TypeScript compiler (strict, noUncheckedIndexedAccess,
// exactOptionalPropertyTypes) over src/park and test-support/park and fails on any error in the World page,
// its tests or the World test support. Pinned type: `WorldPage` takes `{ app: AppCtx }` and returns a node.
// Pinned additive fixture fields (see World.states.test.tsx): `World.heroTag?: string` and
// `DecisionFacts.spendNote?: { waiting: string; decided: string }`.
import { describe, expect, expectTypeOf, it } from "vitest";
import { parkTypeErrors } from "../../../../test-support/park/typecheck";
import type { DecisionFacts, World } from "../../api/types";
import type { AppCtx } from "../../app/AppCtx";
import type { WorldPage } from "./WorldPage";

describe("WEB_6_typecheck: World compiles with the repo's strict options", () => {
  it("WEB_6_typecheck_WorldPage_takes_the_app_prop", () => {
    expectTypeOf<Parameters<typeof WorldPage>[0]>().toEqualTypeOf<{ app: AppCtx }>();
  });

  it("WEB_6_typecheck_the_additive_fixture_fields_exist_and_are_optional", () => {
    expectTypeOf<World["heroTag"]>().toEqualTypeOf<string | undefined>();
    expectTypeOf<DecisionFacts["spendNote"]>().toEqualTypeOf<
      { waiting: string; decided: string } | undefined
    >();
  });

  it("WEB_6_typecheck_world_has_no_type_errors", { timeout: 180_000 }, () => {
    const errors = parkTypeErrors().filter(
      (e) =>
        e.startsWith("src/park/pages/World/") ||
        e.startsWith("test-support/park/world") ||
        e.startsWith("src/park/app/pages.ts") ||
        e.startsWith("src/park/api/"),
    );
    expect(errors).toEqual([]);
  });
});
