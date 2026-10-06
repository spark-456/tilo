// WEB-1a: Vitest does not evaluate types at runtime, so the expectTypeOf checks in park/api/types.test.ts
// would pass silently. This runs the TypeScript compiler (apps/web/tsconfig.json options: strict,
// noUncheckedIndexedAccess, exactOptionalPropertyTypes) over every file under src/park and
// test-support/park, and fails on any error. The builder also runs `pnpm --filter @tilo/web run typecheck`.
import { describe, expect, it } from "vitest";
import { parkTypeErrors } from "../../test-support/park/typecheck";

describe("WEB_1a_typecheck: park files compile with the repo's strict options", () => {
  it("WEB_1a_typecheck_park_has_no_type_errors", { timeout: 180_000 }, () => {
    expect(parkTypeErrors()).toEqual([]);
  });
});
