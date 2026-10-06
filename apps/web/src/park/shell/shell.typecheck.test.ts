// WEB-3b: Vitest does not evaluate types, so the expectTypeOf checks below pass silently at runtime. The second
// test runs the TypeScript compiler (strict, noUncheckedIndexedAccess, exactOptionalPropertyTypes) over
// src/park and test-support/park and fails on any error in park/shell, in the WEB-3b test support, or in the
// store and context files WEB-3b extends.
import type { ComponentType, ReactNode } from "react";
import { describe, expect, expectTypeOf, it } from "vitest";
import { parkTypeErrors } from "../../../test-support/park/typecheck";
import type { Motion } from "../app/AppCtx";
import type { ParkState, ParkStore } from "../app/store";
import type { Notification, User } from "../api/types";
import type { Spot } from "../engines/types";
import type { AccountMenu } from "./AccountMenu";
import type { AppShell } from "./AppShell";
import type { BootSplash } from "./BootSplash";
import type { CityBackdrop } from "./CityBackdrop";
import type { NotificationsPopover } from "./NotificationsPopover";
import type { TopNav } from "./TopNav";
import type { WorldLoader } from "./WorldLoader";
import type { scenePins } from "./pins";
import type { createSceneCache } from "./sceneCache";

describe("WEB_3b_typecheck: the pinned surface", () => {
  it("WEB_3b_typecheck_store_additions", () => {
    expectTypeOf<ParkStore["openWorld"]>().toEqualTypeOf<(id: string) => void>();
    expectTypeOf<ParkStore["toggleMenu"]>().toEqualTypeOf<(which: "notif" | "acct") => void>();
    expectTypeOf<ParkStore["closeMenu"]>().toEqualTypeOf<() => void>();
    expectTypeOf<ParkStore["setPins"]>().toBeCallableWith([{ x: 1, y: 2 }]);
    expectTypeOf<ParkState["wl"]>().toMatchTypeOf<{ id: string; step: number } | null>();
    expectTypeOf<{ id: string; step: number } | null>().toMatchTypeOf<ParkState["wl"]>();
    expectTypeOf<ParkState["pins"]>().toMatchTypeOf<readonly { x: number; y: number }[]>();
  });

  it("WEB_3b_typecheck_component_props", () => {
    expectTypeOf<typeof TopNav>().parameters.toEqualTypeOf<[]>();
    expectTypeOf<typeof CityBackdrop>().parameters.toEqualTypeOf<[]>();
    expectTypeOf<typeof WorldLoader>().parameters.toEqualTypeOf<[]>();
    expectTypeOf<typeof BootSplash>().parameter(0).toEqualTypeOf<{ ready: boolean }>();
    expectTypeOf<typeof AppShell>().parameter(0).toEqualTypeOf<{ children: ReactNode }>();
    expectTypeOf<typeof NotificationsPopover>()
      .parameter(0)
      .toMatchTypeOf<{ items: readonly Notification[] }>();
    expectTypeOf<typeof AccountMenu>().parameter(0).toEqualTypeOf<{ user: User }>();
    expectTypeOf<typeof TopNav>().toMatchTypeOf<ComponentType>();
  });

  it("WEB_3b_typecheck_pure_helpers", () => {
    expectTypeOf<typeof scenePins>().toEqualTypeOf<
      (spots: readonly Spot[], vw: number, vh: number) => { x: number; y: number }[]
    >();
    expectTypeOf<ReturnType<typeof createSceneCache>>().toBeFunction();
    expectTypeOf<ReturnType<typeof createSceneCache>>()
      .parameters.toEqualTypeOf<["day" | "night", Motion]>();
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
