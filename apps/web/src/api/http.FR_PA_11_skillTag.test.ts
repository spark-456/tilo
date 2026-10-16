import { expect, it, vi } from "vitest";
import { HttpClient } from "./http";

it("FR_PA_11 sends the typed skill ref with Quick and Thinking and keeps it on replay", async () => {
  const forms: FormData[] = [];
  const fetch = vi.fn(async (_url: unknown, init?: RequestInit) => {
    forms.push(init?.body as FormData);
    const quick = (init?.body as FormData).get("mode") === "quick";
    return new Response(
      JSON.stringify(
        quick
          ? { mode: "quick", outcome: "switch_to_thinking", reason: "refs" }
          : { task_id: "t1", brief: { goal: "Plan" }, questions: [], files: [] },
      ),
      {
        status: quick ? 200 : 201,
        headers: { "content-type": "application/json" },
      },
    );
  });
  const client = new HttpClient({
    baseUrl: "https://api.test",
    fetch: fetch as typeof globalThis.fetch,
  });
  const refs = [{ kind: "taught_skill" as const, id: "tsk_1" }];
  const quick = await client.submitIntake("Plan", [], "quick", refs);
  expect(quick).toMatchObject({ kind: "switch", reason: "refs" });
  await client.submitIntake("Plan", [], undefined, refs);
  expect(forms.map((form) => form.get("refs"))).toEqual([
    JSON.stringify(refs),
    JSON.stringify(refs),
  ]);
  expect(forms[0]?.get("mode")).toBe("quick");
  expect(forms[1]?.has("mode")).toBe(false);
});
