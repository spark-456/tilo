// WEB-3a: the AppCtx contract (README "The `app` prop", plan section 10). Types are checked by the
// TypeScript compiler through typecheck.test.ts (Vitest does not evaluate expectTypeOf at runtime);
// the runtime part pins the page list and its order.
import { describe, expect, expectTypeOf, it } from "vitest";
import type { Dec, DecisionKey, TierKey, World } from "../api/types";
import { type AppCtx, type Motion, PAGE_IDS, type PageId, type Params } from "./AppCtx";
import type { ParkState } from "./store";

describe("WEB_3a_appctx: the page list", () => {
  it("UI_10_W7_appctx_keeps_the_design_pages_then_Settings", () => {
    expect([...PAGE_IDS]).toEqual([
      "home",
      "worlds",
      "world",
      "skills",
      "ledger",
      "agenda",
      "team",
      "profile",
      "connectors",
      "settings",
      "library",
      "more",
      "needs",
    ]);
  });

  it("WEB_3a_appctx_PAGE_IDS_has_no_duplicates", () => {
    expect(new Set(PAGE_IDS).size).toBe(PAGE_IDS.length);
  });
});

describe("WEB_3a_appctx: the contract is typed exactly as the README says", () => {
  it("WEB_3a_appctx_PageId_Params_Motion", () => {
    expectTypeOf<PageId>().toEqualTypeOf<
      | "home"
      | "worlds"
      | "world"
      | "skills"
      | "ledger"
      | "agenda"
      | "team"
      | "profile"
      | "connectors"
      | "settings"
      | "library"
      | "more"
      | "needs"
    >();
    expectTypeOf<(typeof PAGE_IDS)[number]>().toEqualTypeOf<PageId>();
    expectTypeOf<Params>().toEqualTypeOf<Record<string, string>>();
    expectTypeOf<Motion>().toEqualTypeOf<"lively" | "calm" | "still">();
  });

  it("WEB_3a_appctx_route_and_navigation_members", () => {
    expectTypeOf<AppCtx["page"]>().toEqualTypeOf<PageId>();
    expectTypeOf<AppCtx["params"]>().toEqualTypeOf<Params>();
    expectTypeOf<AppCtx["go"]>().toEqualTypeOf<(page: PageId, params?: Params) => void>();
  });

  it("WEB_3a_appctx_decision_members", () => {
    expectTypeOf<AppCtx["dec"]>().toEqualTypeOf<Dec>();
    expectTypeOf<AppCtx["decide"]>().toEqualTypeOf<
      (key: DecisionKey, text?: string, option?: string) => void
    >();
    expectTypeOf<AppCtx["needsLeft"]>().toEqualTypeOf<number>();
  });

  it("WEB_3a_appctx_world_and_toast_members", () => {
    expectTypeOf<AppCtx["added"]>().toEqualTypeOf<World[]>();
    expectTypeOf<AppCtx["addWorld"]>().toEqualTypeOf<(mode: TierKey, query: string) => World>();
    expectTypeOf<TierKey>().toEqualTypeOf<"quick" | "routine" | "workspace">();
    expectTypeOf<AppCtx["toast"]>().toEqualTypeOf<
      (msg: string, actionLabel?: string, action?: () => void) => void
    >();
  });

  it("WEB_3a_appctx_theme_prefs_and_layout_members", () => {
    expectTypeOf<AppCtx["time"]>().toEqualTypeOf<"day" | "night">();
    expectTypeOf<AppCtx["night"]>().toEqualTypeOf<boolean>();
    expectTypeOf<AppCtx["motion"]>().toEqualTypeOf<Motion>();
    expectTypeOf<AppCtx["setPref"]>().toEqualTypeOf<(key: string, value: unknown) => void>();
    expectTypeOf<AppCtx["prefs"]>().toEqualTypeOf<Record<string, unknown>>();
    expectTypeOf<AppCtx["vw"]>().toEqualTypeOf<number>();
    expectTypeOf<AppCtx["vh"]>().toEqualTypeOf<number>();
    expectTypeOf<AppCtx["pins"]>().toEqualTypeOf<{ x: number; y: number }[]>();
    expectTypeOf<AppCtx["ready"]>().toEqualTypeOf<boolean>();
  });

  it("WEB_3a_appctx_has_exactly_the_README_members", () => {
    expectTypeOf<keyof AppCtx>().toEqualTypeOf<
      | "page"
      | "params"
      | "go"
      | "dec"
      | "decide"
      | "needsLeft"
      | "added"
      | "addWorld"
      | "toast"
      | "time"
      | "night"
      | "motion"
      | "setPref"
      | "prefs"
      | "vw"
      | "vh"
      | "pins"
      | "ready"
    >();
  });

  it("WEB_3a_appctx_store_state_has_the_pinned_fields", () => {
    // Readonly modifiers are the builder's choice, so these are assignability checks.
    expectTypeOf<ParkState["dec"]>().toMatchTypeOf<Dec>();
    expectTypeOf<ParkState["added"]>().toMatchTypeOf<readonly World[]>();
    expectTypeOf<ParkState["prefs"]>().toMatchTypeOf<Readonly<Record<string, unknown>>>();
    expectTypeOf<ParkState["time"]>().toEqualTypeOf<"day" | "night">();
    expectTypeOf<ParkState["motion"]>().toEqualTypeOf<Motion>();
    expectTypeOf<ParkState["read"]>().toEqualTypeOf<boolean>();
    expectTypeOf<ParkState["needsLeft"]>().toEqualTypeOf<number>();
    expectTypeOf<ParkState["sources"]>().toMatchTypeOf<{ fixture: boolean; live: boolean }>();
    expectTypeOf<ParkState["menu"]>().toEqualTypeOf<"notif" | "acct" | null>();
    expectTypeOf<NonNullable<ParkState["toast"]>["message"]>().toEqualTypeOf<string>();
    expectTypeOf<NonNullable<ParkState["toast"]>["actionLabel"]>().toEqualTypeOf<
      string | undefined
    >();
    expectTypeOf<NonNullable<ParkState["toast"]>["action"]>().toEqualTypeOf<
      (() => void) | undefined
    >();
  });
});
