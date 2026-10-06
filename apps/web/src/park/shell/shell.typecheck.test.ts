// WEB-3b: Vitest does not evaluate types, so the expectTypeOf checks below pass silently at runtime. The
// second test runs the TypeScript compiler (strict, noUncheckedIndexedAccess, exactOptionalPropertyTypes) over
// src/park and test-support/park and fails on any error in park/shell, in the WEB-3b test support, or in
// park/app (which WEB-3b extends).
import type { ReactNode } from "react";
import { describe, expect, expectTypeOf, it } from "vitest";
import { parkTypeErrors } from "../../../test-support/park/typecheck";
import type { ParkState, ParkStore } from "../app/store";
import type { AppShell } from "./AppShell";
import type { BootSplash } from "./BootSplash";

describe("WEB_3b_typecheck: the pinned surface", () => {
  it("WEB_3b_typecheck_openWorld_and_the_loader_state", () => {
    expectTypeOf<ParkStore["openWorld"]>().toEqualTypeOf<(id: string) => void>();
    expectTypeOf<NonNullable<ParkState["wl"]>["id"]>().toEqualTypeOf<string>();
    expectTypeOf<NonNullable<ParkState["wl"]>["step"]>().toEqualTypeOf<number>();
  });

  it("WEB_3b_typecheck_AppShell_takes_children_and_BootSplash_takes_ready", () => {
    expectTypeOf<typeof AppShell>().parameter(0).toEqualTypeOf<{ children: ReactNode }>();
    expectTypeOf<typeof BootSplash>().parameter(0).toEqualTypeOf<{ ready: boolean }>();
  });
});

describe("WEB_3b_typecheck: park/shell compiles with the repo's strict options", () => {
  it("WEB_3b_typecheck_park_shell_has_no_type_errors", { timeout: 240_000 }, () => {
    const errors = parkTypeErrors().filter(
      (e) =>
        e.startsWith("src/park/shell/") ||
        e.startsWith("src/park/app/") ||
        e.startsWith("test-support/park/shell"),
    );
    expect(errors).toEqual([]);
  });
});
