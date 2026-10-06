// WEB-3a: Vitest does not evaluate types, so the expectTypeOf checks in AppCtx.test.ts and pages.test.tsx
// would pass silently. This runs the TypeScript compiler (strict, noUncheckedIndexedAccess,
// exactOptionalPropertyTypes) over src/park and test-support/park and fails on any error in park/app
// or in the WEB-3a test support. Same helper as the other park typecheck tests.
import { describe, expect, it } from "vitest";
import { parkTypeErrors } from "../../../test-support/park/typecheck";

describe("WEB_3a_typecheck: park/app compiles with the repo's strict options", () => {
  it("WEB_3a_typecheck_park_app_has_no_type_errors", { timeout: 180_000 }, () => {
    const errors = parkTypeErrors().filter(
      (e) =>
        e.startsWith("src/park/app/") ||
        e.startsWith("test-support/park/appHarness.ts") ||
        e.startsWith("src/Root"),
    );
    expect(errors).toEqual([]);
  });
});
