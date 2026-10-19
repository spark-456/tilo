// ADR-0041 BYOK-5 (BQ-BYOK-WEB-3), SECURITY-FLAGGED: the framework-free flow of `/v1/org/model-key` over the real
// `HttpClient` and a fake `fetch` that answers exactly as `services/api/.../byok_routes.py` does (a `detail` token, and
// a `code` on the coded refusals). Nothing is "saved" or "removed" without a re-read; no refusal carries input back.
import { describe, expect, it } from "vitest";
import { HttpClient } from "./http";
import { MODEL_KEY_PATH, createModelKeyFlow } from "./modelKey";

const KEY = ["byok", "Zq81XyN0pQ3rT7vW9aB2cD4eF6gH"].join("_"); // assembled at runtime: no secret in the file
const OWNER = {
  active: true,
  label: "Example endpoint",
  state: "active",
  secret_version: 2,
  consent_version: 1,
};
const NONE = { active: false, label: null, state: "none", consent_version: 1 };

interface Seen {
  method: string;
  url: string;
  body: string | null;
}
type Reply = { status: number; body: unknown } | "network";

/** One scripted reply per request, in order; the last repeats. */
function client(replies: Reply[]) {
  const seen: Seen[] = [];
  let i = 0;
  const fetchFn = (async (url: string, init: RequestInit = {}) => {
    seen.push({
      method: init.method ?? "GET",
      url,
      body: (init.body as string | undefined) ?? null,
    });
    const r = replies[Math.min(i++, replies.length - 1)] as Reply;
    if (r === "network") throw new TypeError("Failed to fetch");
    return new Response(JSON.stringify(r.body), {
      status: r.status,
      headers: { "content-type": "application/json" },
    });
  }) as unknown as typeof fetch;
  return {
    flow: createModelKeyFlow(new HttpClient({ baseUrl: "http://api.test", fetch: fetchFn })),
    seen,
  };
}
const SAVE = {
  bundleId: "ex",
  key: KEY,
  projectId: null,
  dayCapCredits: 500,
  fallbackToTilo: false,
  consentVersion: 1,
};

describe("ADR-0041 BQ-BYOK-WEB-3 read", () => {
  it("BYOK_WEB_ADR_0041_flow_reads_an_owner_a_member_and_nothing_else", async () => {
    const owner = await client([{ status: 200, body: OWNER }]).flow.read();
    expect(owner).toMatchObject({
      ok: true,
      view: { owner: true, active: true, state: "active", version: 2 },
    });
    const member = await client([
      { status: 200, body: { active: false, label: null } },
    ]).flow.read();
    expect(member).toMatchObject({ ok: true, view: { owner: false, state: null } });
    const junk = await client([{ status: 200, body: { state: "active" } }]).flow.read();
    expect(junk).toEqual({ ok: false, problem: "unavailable" });
  });

  it("BYOK_WEB_ADR_0041_flow_names_each_refusal_by_status_and_code_never_by_text", async () => {
    const cases: [number, unknown, string][] = [
      [503, { detail: "not_configured" }, "not_configured"],
      [503, { detail: "unavailable" }, "unavailable"],
      [401, { detail: "Unauthorized" }, "sign_in"],
      [401, { detail: "reauth_required", code: "reauth_required" }, "reauth"],
      [403, { detail: "owner_only" }, "owner_only"],
      [422, { detail: "key_refused", code: "key_refused" }, "key_refused"],
      [422, { detail: "confirm_required", code: "confirm_required" }, "confirm"],
      [422, { detail: "invalid_body", code: "invalid_body" }, "invalid"],
      [429, { detail: "rate_limited", code: "rate_limited" }, "rate_limited"],
      [500, {}, "unavailable"],
    ];
    for (const [status, body, problem] of cases) {
      const r = await client([{ status, body }]).flow.read();
      expect(r, `${status} ${JSON.stringify(body)}`).toEqual({ ok: false, problem });
    }
    expect(await client(["network"]).flow.read()).toEqual({ ok: false, problem: "unavailable" });
  });
});

describe("ADR-0041 BQ-BYOK-WEB-3 write", () => {
  it("BYOK_WEB_ADR_0041_save_is_one_put_with_the_documented_body_then_a_reread", async () => {
    const { flow, seen } = client([
      { status: 200, body: { state: "active", secret_version: 2, validated: true } },
      { status: 200, body: OWNER },
    ]);
    const r = await flow.save(SAVE);
    expect(r).toMatchObject({ ok: true, view: { state: "active" } });
    expect(seen.map((s) => `${s.method} ${s.url}`)).toEqual([
      `PUT http://api.test${MODEL_KEY_PATH}`,
      `GET http://api.test${MODEL_KEY_PATH}`,
    ]);
    expect(JSON.parse(seen[0]?.body ?? "{}")).toEqual({
      confirm: true,
      consent_version: 1,
      bundle_id: "ex",
      day_cap_credits: 500,
      fallback_to_tilo: false,
      key: KEY,
    });
    expect(seen[1]?.body).toBeNull();
    expect(seen.some((s) => s.url.includes(KEY))).toBe(false);
  });

  it("BYOK_WEB_ADR_0041_a_vertex_project_sends_project_id_and_no_key", async () => {
    const { flow, seen } = client([
      { status: 200, body: { state: "unverified", secret_version: 1, validated: false } },
      { status: 200, body: { ...OWNER, state: "unverified" } },
    ]);
    await flow.save({ ...SAVE, key: null, projectId: "my-vertex-project" });
    const body = JSON.parse(seen[0]?.body ?? "{}");
    expect(body.project_id).toBe("my-vertex-project");
    expect("key" in body).toBe(false);
  });

  it("BYOK_WEB_ADR_0041_a_malformed_answer_or_an_unconfirming_reread_is_not_saved", async () => {
    const bad = await client([{ status: 200, body: { ok: true } }]).flow.save(SAVE);
    expect(bad).toEqual({ ok: false, problem: "unavailable" });
    const empty = await client([
      { status: 200, body: { state: "active", secret_version: 1, validated: true } },
      { status: 200, body: NONE },
    ]).flow.save(SAVE);
    expect(empty).toEqual({ ok: false, problem: "unconfirmed" });
    const unread = await client([
      { status: 200, body: { state: "active", secret_version: 1, validated: true } },
      { status: 503, body: { detail: "unavailable" } },
    ]).flow.save(SAVE);
    expect(unread).toEqual({ ok: false, problem: "unconfirmed" });
  });

  it("BYOK_WEB_ADR_0041_a_refused_save_makes_no_reread_and_its_problem_carries_no_input", async () => {
    const { flow, seen } = client([
      { status: 422, body: { detail: "key_refused", code: "key_refused", echo: KEY } },
    ]);
    const r = await flow.save(SAVE);
    expect(r).toEqual({ ok: false, problem: "key_refused" });
    expect(JSON.stringify(r)).not.toContain(KEY);
    expect(seen).toHaveLength(1);
  });

  it("BYOK_WEB_ADR_0041_remove_is_a_delete_then_a_reread_that_shows_no_key", async () => {
    const { flow, seen } = client([
      { status: 200, body: { removed: true } },
      { status: 200, body: NONE },
    ]);
    expect(await flow.remove()).toMatchObject({ ok: true, view: { state: "none" } });
    expect(seen.map((s) => s.method)).toEqual(["DELETE", "GET"]);
    const still = await client([
      { status: 200, body: { removed: true } },
      { status: 200, body: OWNER },
    ]).flow.remove();
    expect(still).toEqual({ ok: false, problem: "unconfirmed" });
    const nope = await client([{ status: 200, body: {} }]).flow.remove();
    expect(nope).toEqual({ ok: false, problem: "unavailable" });
  });
});
