import { expect, it, vi } from "vitest";
import { createLiveApi } from "./liveApi";
import { withSession } from "./select";
import { fixSkill } from "./skillFixes";
const body = { from_version: 1, step: 1, text: "New", ask_first: true, rating: null };
it("FR_SKL_05_fix_sends_the_displayed_version_once_and_carries_through_session", async () => {
  const row = {
    id: "tsk_a",
    name: "Read",
    scope: { kind: "just_me", team: null },
    status: "learning",
    paused: false,
    plan: [{ text: "New", tool: "gmail", action: "read_email", ask_first: true, rating: null }],
    question: null,
    version: 2,
  };
  const fetch = vi.fn(
    async (_url: RequestInfo | URL, _init?: RequestInit) =>
      new Response(JSON.stringify(row), { status: 200 }),
  );
  const api = withSession(createLiveApi({ baseUrl: "https://api.example.test", fetch }), {
    demo: () => false,
    identity: () => null,
    now: () => new Date(0),
  });
  const result = await fixSkill(api, "tsk_a", body);
  expect(result.steps).toEqual(["New"]);
  expect(fetch).toHaveBeenCalledTimes(1);
  expect(JSON.parse(String(fetch.mock.calls[0]?.[1]?.body))).toEqual(body);
});

it("FR_SKL_05_failed_or_demo_fix_never_acknowledges_or_retries", async () => {
  const fetch = vi.fn(async () => new Response("{}", { status: 409 }));
  const live = createLiveApi({ baseUrl: "https://api.example.test", fetch });
  await expect(fixSkill(live, "tsk_a", body)).rejects.toThrow();
  const demo = withSession(live, {
    demo: () => true,
    identity: () => null,
    now: () => new Date(0),
  });
  await expect(fixSkill(demo, "tsk_a", body)).rejects.toThrow();
  expect(fetch).toHaveBeenCalledTimes(1);
});
