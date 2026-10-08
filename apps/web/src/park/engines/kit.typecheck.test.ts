// WEB-1c: the kit port is typed code, not a JS file renamed. Vitest does not evaluate types, so this runs the
// TypeScript compiler (apps/web/tsconfig.json options: strict, noUncheckedIndexedAccess,
// exactOptionalPropertyTypes) over kit.ts and fails on any error, on a ts directive and on any use of `any`.
// It also compiles a small in-memory consumer ("probe") against kit.ts, which pins the exported signatures and
// the exact member set at type level: `createKit(h, deps)` returns exactly { W, TP, ck, icon, agent, building,
// world, art, strip }, art() and strip() take a World of the typed fixtures, and the bad calls do not compile
// (an unused @ts-expect-error in the probe is itself an error). The builder also runs
// `pnpm --filter @tilo/web run typecheck`.
import { describe, expect, it } from "vitest";
import {
  kitAnyUses,
  kitDirectives,
  kitExists,
  kitTypeErrors,
  probeErrors,
} from "../../../test-support/park/kitTypecheck";

const PROBE = `
import type { ArtSlot, Dec, Plan, World } from "../api/types";
import { ICON_NAMES, createKit } from "./kit";
import type { H, ParkEnv } from "./types";

declare const h: H;
declare const world: World;
declare const slot: ArtSlot;
declare const parkEnv: ParkEnv;

const kit = createKit(h, { plans: (_dec?: Dec): Record<string, Plan> => ({}) });
const withEnv = createKit(h, { plans: () => ({}), env: parkEnv });
const withFakeEnv = createKit(h, { plans: () => ({}), env: { createObjectURL: () => "blob:x" } });

type Same<A, B> = [A] extends [B] ? ([B] extends [A] ? true : false) : false;
export const exactMembers: Same<
  keyof typeof kit,
  "W" | "TP" | "ck" | "icon" | "agent" | "building" | "world" | "art" | "strip"
> = true;
export const sameKitType: Same<typeof kit, typeof withEnv> = true;

export const used = {
  withFakeEnv,
  i1: kit.icon("home"),
  i2: kit.icon("home", 12),
  a1: kit.agent({ role: "builder", expr: "walking" }, 90, true),
  a2: kit.agent({}),
  b1: kit.building("library", "active", "research", 150, true),
  b2: kit.building("library", "idle"),
  b3: kit.building(slot[0], slot[1], slot[2], 150, false),
  w1: kit.world("k1", { depot: true }, false),
  w2: kit.world("fresh"),
  art: kit.art(world, 150, true),
  art2: kit.art(world),
  strip: kit.strip(world, 90, false),
  c1: kit.ck("k", () => 1) satisfies number,
  c2: kit.ck("k", () => "s") satisfies string,
  names: ICON_NAMES satisfies readonly string[],
  w: kit.W.icon,
  tp: [kit.TP.scene, kit.TP.world, kit.TP.building, kit.TP.agent],
};

// @ts-expect-error icon takes a name
kit.icon(5);
// @ts-expect-error planId is a string
kit.world(1);
// @ts-expect-error agent takes a look object
kit.agent("builder");
// @ts-expect-error building needs a state
kit.building("library");
// @ts-expect-error the deps are required
createKit(h);
// @ts-expect-error the plan source is required
createKit(h, {});
// @ts-expect-error the factory comes first
createKit({ plans: () => ({}) });
`;

describe("WEB_1c_typecheck: kit.ts compiles with the repo's strict options", () => {
  it("WEB_1c_typecheck_kit_ts_exists", () => {
    expect(kitExists(), "apps/web/src/park/engines/kit.ts is missing").toBe(true);
  });

  it("WEB_1c_typecheck_kit_has_no_type_errors", { timeout: 180_000 }, async () => {
    expect(kitExists(), "nothing to compile: kit.ts is missing").toBe(true);
    expect(await kitTypeErrors()).toEqual([]);
  });

  it("WEB_1c_typecheck_no_ts_ignore_ts_nocheck_or_ts_expect_error", () => {
    expect(kitExists()).toBe(true);
    expect(kitDirectives()).toEqual([]);
  });

  it("WEB_1c_typecheck_no_any", () => {
    expect(kitExists()).toBe(true);
    expect(kitAnyUses(), "`any` is not allowed in kit.ts; use unknown or a real type").toEqual([]);
  });
});

describe("WEB_1c_typecheck: the exported signatures", () => {
  it(
    "WEB_1c_typecheck_a_consumer_compiles_against_createKit_and_the_bad_calls_do_not",
    { timeout: 180_000 },
    async () => {
      expect(kitExists()).toBe(true);
      expect(await probeErrors(PROBE)).toEqual([]);
    },
  );

  it("WEB_1c_typecheck_the_probe_catches_a_missing_export", { timeout: 180_000 }, async () => {
    // Guards the test above against passing for the wrong reason: a consumer of a name kit.ts lacks fails.
    expect(kitExists()).toBe(true);
    const errs = await probeErrors(
      'import { noSuchExport } from "./kit";\nexport const x = noSuchExport;\n',
    );
    expect(errs.length).toBeGreaterThan(0);
  });
});
