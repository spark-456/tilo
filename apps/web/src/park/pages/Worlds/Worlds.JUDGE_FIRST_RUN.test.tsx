// @vitest-environment happy-dom
// JUDGE-FIRST-RUN F5: no broken sentence when nothing names a world, and "1 world", not "1 worlds".
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, q } from "../../../../test-support/park/componentsHarness";
import { flush, renderWorlds, worldsApi } from "../../../../test-support/park/worldsHarness";

afterEach(cleanup);

it("JUDGE_FIRST_RUN_F5_all_caught_up_never_starts_a_sentence_with_a_missing_world_name", async () => {
  const api = worldsApi();
  api.getDecisions = vi.fn(async () => ({ data: [], source: "live" as const }));
  const { c } = await renderWorlds({ api, dec: { depot: true, mail: true } });
  await flush();
  const clear = q(c, ".park-worlds-clear__body");
  const text = clear.textContent?.trim() ?? "";
  expect(text.length).toBeGreaterThan(0);
  expect(text).not.toMatch(/^(is|are)\b/i);
  expect(text.startsWith(" ")).toBe(false);
  expect(text).toBe("Nothing needs you right now. Tilo will ask if anything does.");
});

it("JUDGE_FIRST_RUN_F5_the_total_says_world_for_one_and_worlds_otherwise", async () => {
  const api = worldsApi();
  const all = (await api.getWorlds({}, [])).data;
  api.getWorlds = vi.fn(async () => ({ data: all.slice(0, 1), source: "live" as const }));
  const one = await renderWorlds({ api });
  await flush();
  expect(q(one.c, ".park-worlds-total").textContent).toBe("1 world");
  cleanup();
  const many = await renderWorlds({ api: worldsApi() });
  await flush();
  expect(q(many.c, ".park-worlds-total").textContent).toMatch(/^\d+ worlds$/);
  expect(q(many.c, ".park-worlds-total").textContent).not.toBe("1 worlds");
});
