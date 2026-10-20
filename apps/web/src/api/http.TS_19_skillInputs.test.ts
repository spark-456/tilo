import { expect, it, vi } from "vitest";
import { HttpClient } from "./http";

function client(forms: FormData[]) {
  const fetch = vi.fn(async (_url: unknown, init?: RequestInit) => {
    forms.push(init?.body as FormData);
    return new Response(
      JSON.stringify({ task_id: "t1", brief: { goal: "Run" }, questions: [], files: [] }),
      { status: 201, headers: { "content-type": "application/json" } },
    );
  });
  return new HttpClient({ baseUrl: "https://api.test", fetch: fetch as typeof globalThis.fetch });
}

it("TS_19 sends a skill run form's values as the inputs field beside the skill ref", async () => {
  const forms: FormData[] = [];
  const http = client(forms);
  const refs = [{ kind: "taught_skill" as const, id: "tsk_1" }];
  const inputs = { supplier: "Globex", period: "" };
  await http.submitIntake("Run the Invoice digest skill.", [], undefined, refs, inputs);
  expect(forms[0]?.get("inputs")).toBe(JSON.stringify(inputs));
  expect(forms[0]?.get("refs")).toBe(JSON.stringify(refs));
});

it("TS_19 sends no inputs field without a skill ref or without values, and other values are a new request", async () => {
  const forms: FormData[] = [];
  const http = client(forms);
  await http.submitIntake("Plan a trip", [], undefined, [], { supplier: "Globex" });
  await http.submitIntake("Run it", [], undefined, [{ kind: "taught_skill", id: "tsk_1" }]);
  expect(forms.map((form) => form.has("inputs"))).toEqual([false, false]);
  const refs = [{ kind: "taught_skill" as const, id: "tsk_2" }];
  await http.submitIntake("Run it", [], undefined, refs, { supplier: "Acme" });
  await http.submitIntake("Run it", [], undefined, refs, { supplier: "Initech" });
  expect(forms.slice(2).map((form) => form.get("inputs"))).toEqual([
    JSON.stringify({ supplier: "Acme" }),
    JSON.stringify({ supplier: "Initech" }),
  ]);
});
