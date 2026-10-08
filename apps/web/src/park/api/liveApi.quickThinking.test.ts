// QUICK_THINKING at the Api: `POST /intake` with the optional `mode=quick|thinking` form field (COST-FAST-1,
// services/api/tests/API_COST_FAST_1.md). Thinking and the legacy call stay as they were (no `mode` field when
// none is chosen); a Quick reply is read strictly into a QuickReply; Quick makes no world and remembers no
// intake; the fixture answers with a labelled sample.
import { describe, expect, it } from "vitest";
import { TiloApiError } from "../../api/http";
import { intakes } from "../../api/intakes";
import { SAMPLE_QUICK, createFixtureApi } from "./fixtureApi";
import { askQuick } from "./index";
import { createLiveApi } from "./liveApi";

const BASE = "https://api.example.test";
const BRIEF = { goal: "g" };
const THINKING_201 = {
  mode: "thinking",
  task_id: "t_think1",
  brief: BRIEF,
  questions: [],
  files: [],
};

interface Seen {
  url: string;
  form: FormData;
}
function rig(status: number, body: unknown) {
  const seen: Seen[] = [];
  const fetchFn = (async (url: string, init?: RequestInit) => {
    seen.push({ url, form: init?.body as FormData });
    return new Response(JSON.stringify(body), {
      status,
      headers: { "content-type": "application/json" },
    });
  }) as unknown as typeof fetch;
  return { seen, api: createLiveApi({ baseUrl: BASE, fetch: fetchFn }) };
}

describe("QUICK_THINKING_http: the mode field", () => {
  it("QUICK_THINKING_http_legacy_and_thinking_calls_send_no_quick_field", async () => {
    const r = rig(201, THINKING_201);
    const ack = await r.api.startWorld("quick", "Plan the offsite");
    expect(ack.data.world.id).toBe("t_think1");
    expect(r.seen[0]?.url).toBe(`${BASE}/intake`);
    expect(r.seen[0]?.form.get("text")).toBe("Plan the offsite");
    expect(r.seen[0]?.form.has("mode")).toBe(false); // absent means Thinking on the server
  });

  it("QUICK_THINKING_http_quick_sends_mode_quick_and_reads_the_answer_with_its_cost", async () => {
    const r = rig(200, {
      mode: "quick",
      outcome: "answered",
      text: "Paris.",
      cost: { model_calls: 1, credits: 0.04, saved_credits: 0.3 },
    });
    const known = intakes.size;
    const res = await askQuick(r.api, "quick", "Capital of France?");
    expect(r.seen[0]?.form.get("mode")).toBe("quick");
    expect(res.source).toBe("live");
    expect(res.data).toEqual({
      kind: "answered",
      text: "Paris.",
      cost: { credits: 0.04, savedCredits: 0.3 },
    });
    // a Quick answer makes no task: nothing is remembered as an intake
    expect(intakes.size).toBe(known);
  });

  it("QUICK_THINKING_http_an_answer_without_cost_has_cost_null_never_a_made_up_figure", async () => {
    const r = rig(200, { mode: "quick", outcome: "answered", text: "Paris." });
    const res = await askQuick(r.api, "quick", "q");
    expect(res.data).toEqual({ kind: "answered", text: "Paris.", cost: null });
  });

  it("QUICK_THINKING_http_a_switch_offer_carries_its_reason", async () => {
    const r = rig(200, { mode: "quick", outcome: "switch_to_thinking", reason: "needs_tools" });
    const res = await askQuick(r.api, "quick", "q");
    expect(res.data).toEqual({ kind: "switch", reason: "needs_tools" });
  });

  it.each([
    ["a task-shaped body (an old server that ignored mode)", THINKING_201],
    ["an unknown reason", { mode: "quick", outcome: "switch_to_thinking", reason: "because" }],
    ["an empty answer", { mode: "quick", outcome: "answered", text: "" }],
    ["a missing outcome", { mode: "quick", text: "Paris." }],
    ["a non-object", "Paris."],
  ])("QUICK_THINKING_http_%s is a reply this page cannot read", async (_name, body) => {
    const r = rig(200, body);
    await expect(askQuick(r.api, "quick", "q")).rejects.toBeInstanceOf(TiloApiError);
  });

  it.each([422, 429, 403, 503, 502])(
    "QUICK_THINKING_http_status_%i_rejects_typed",
    async (status) => {
      const r = rig(status, { error: "No." });
      await expect(askQuick(r.api, "quick", "q")).rejects.toMatchObject({ status });
    },
  );
});

describe("QUICK_THINKING_fixture: Quick on the fixture", () => {
  it("QUICK_THINKING_fixture_quick_is_a_sample_answer_from_the_fixture_with_no_world_and_no_cost", async () => {
    const res = await askQuick(createFixtureApi(), "quick", "anything");
    expect(res.source).toBe("fixture");
    expect(res.data).toEqual({ kind: "answered", text: SAMPLE_QUICK, cost: null });
  });

  it("QUICK_THINKING_fixture_thinking_still_makes_the_world", async () => {
    const res = await createFixtureApi().startWorld("quick", "Plan it");
    expect(res.data.world.short.length).toBeGreaterThan(0);
  });
});
