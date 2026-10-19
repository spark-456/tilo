// FR-UX-12 phone pass (f), BQ-WEB-MOTION-2b: a city's picture (the world engine's one indivisible SVG draw, about
// 150 ms at 4x CPU) is drawn once and reused: on a revisit, on the Worlds list and on the World page. The key is
// what the picture is drawn from (the plan's content and the time of day), not the plan object, because every
// Api call hands back new objects. Cached and uncached markup must be identical; no animation is added.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { FakeBlob, fakeCreateObjectURL, serialiseH } from "../../../test-support/park/engineProto";
import { plans as fixturePlans } from "../api/fixtures";
import type { Plan, World } from "../api/types";
import { createKit } from "../engines/kit";
import { cityArt } from "../pages/World/worldArt";
import { makeArt, makeKit } from "../pages/Worlds/art";
import { cachedCity, clearCityCache } from "./cityCache";

const plan = (id = "k1"): Plan => (fixturePlans() as Record<string, Plan>)[id] as Plan;
const city = { tier: "City", plan: "k1" } as unknown as World;

beforeEach(() => clearCityCache());
afterEach(() => vi.restoreAllMocks());

describe("FR_UX_12 city art cache", () => {
  it("FR_UX_12_cache_hit_on_revisit: an equal plan that arrives as a new object is not drawn again", () => {
    const draw = vi.fn((p: Plan, night: boolean) => ({ drawn: p.districts.length, night }));
    const first = cachedCity(plan(), false, draw as never);
    const again = cachedCity(plan(), false, draw as never); // a new, equal object (a second Api result)
    expect(again).toBe(first);
    expect(draw).toHaveBeenCalledTimes(1);
  });

  it("FR_UX_12_cache_keyed_per_plan: another plan, or another time of day, is its own picture", () => {
    const draw = vi.fn((p: Plan, night: boolean) => ({ n: draw.mock.calls.length, night, p }));
    const a = cachedCity(plan("k1"), false, draw as never);
    const b = cachedCity(plan("hires"), false, draw as never);
    const c = cachedCity(plan("k1"), true, draw as never);
    expect(new Set([a, b, c]).size).toBe(3);
    expect(draw).toHaveBeenCalledTimes(3);
    // the same plan with a changed content (a decision on) is a miss too
    const changed = { ...plan("k1"), agents: plan("k1").agents.slice(1) } as Plan;
    expect(cachedCity(changed, false, draw as never)).not.toBe(a);
    expect(draw).toHaveBeenCalledTimes(4);
  });

  it("FR_UX_12_cache_markup_equal: the cached picture is the uncached picture, byte for byte", () => {
    const kit = createKit(serialiseH as never, {
      plans: fixturePlans as never,
      env: { Blob: FakeBlob as never, createObjectURL: fakeCreateObjectURL as never },
    });
    for (const night of [false, true]) {
      const fresh = kit.TP.world(plan(), { night });
      const kept = cachedCity(plan(), night, (p, n) => kit.TP.world(p, { night: n }));
      const hit = cachedCity(plan(), night, (p, n) => kit.TP.world(p, { night: n }));
      expect(JSON.stringify(kept)).toBe(JSON.stringify(fresh));
      expect(hit).toBe(kept);
    }
  });

  it("FR_UX_12_cache_shared_by_worlds_and_world_page: a city drawn for its card is not drawn again for its page", () => {
    const make = vi.spyOn(URL, "createObjectURL");
    const plansA = fixturePlans() as Record<string, Plan>;
    const plansB = fixturePlans() as Record<string, Plan>; // another Api call: other objects, same content
    const art = makeArt(
      makeKit(() => plansA),
      () => plansA,
      {},
      false,
    );
    const card = art.city(city);
    expect(card).not.toBeNull();
    const drawn = make.mock.calls.length;
    expect(drawn).toBeGreaterThan(0);
    const page = cityArt(plansB.k1 as Plan, "k1", {}, false);
    expect(page).toBe(card);
    // and a second visit to the Worlds list (a new kit, new plan objects) draws nothing either
    const revisit = makeArt(
      makeKit(() => plansB),
      () => plansB,
      {},
      false,
    ).city(city);
    expect(revisit).toBe(card);
    expect(make.mock.calls.length).toBe(drawn);
  });
});
