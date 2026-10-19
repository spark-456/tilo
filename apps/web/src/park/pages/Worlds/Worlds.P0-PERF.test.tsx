// @vitest-environment happy-dom
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, click, q } from "../../../../test-support/park/componentsHarness";
import { renderWorlds } from "../../../../test-support/park/worldsHarness";
import { countFor, visibleWorlds } from "./model";

vi.mock("./model", async (importOriginal) => {
  const original = await importOriginal<typeof import("./model")>();
  return {
    ...original,
    countFor: vi.fn(original.countFor),
    visibleWorlds: vi.fn(original.visibleWorlds),
  };
});

afterEach(cleanup);

it("P0_PERF_worlds_filter_does_not_repeat_for_an_unrelated_share_dialog", async () => {
  const { c } = await renderWorlds();
  const calls = vi.mocked(visibleWorlds).mock.calls.length;
  const counts = vi.mocked(countFor).mock.calls.length;
  click(q(c, "button.park-worlds-slack"));
  expect(q(c, '[role="dialog"][aria-label="Share to Slack"]')).not.toBeNull();
  expect(vi.mocked(visibleWorlds).mock.calls.length).toBe(calls);
  expect(vi.mocked(countFor).mock.calls.length).toBe(counts);
});
