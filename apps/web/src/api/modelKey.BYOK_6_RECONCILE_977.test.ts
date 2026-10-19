// ADR-0041 BYOK-6 (BQ-BYOKC-6), SECURITY-FLAGGED, INERT: the web flow reads what contracts/org_model_key.schema.json
// says. The contract's own fixtures are the oracle, so the client is held to the same files the API's tests judge:
// every valid `owner_view`, `member_view` and `error` is read as the schema means it, and the one PUT body the client
// sends has only the fields of `put_request`. No network: a fake `fetch` over the real `HttpClient`.
import { readFileSync, readdirSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { HttpClient } from "./http";
import { createModelKeyFlow } from "./modelKey";

const FIXTURES = path.join(import.meta.dirname, "../../../../contracts/fixtures");
const CONTRACTS = path.join(FIXTURES, "..");
const KEY = ["byok", "Zq81XyN0pQ3rT7vW9aB2cD4eF6gH"].join("_"); // assembled at runtime: no secret in the file

function fixtures(name: string, kind = "valid"): [string, Record<string, unknown>][] {
  const dir = path.join(FIXTURES, `org_model_key.${name}`, kind);
  return readdirSync(dir)
    .filter((f) => f.endsWith(".json"))
    .sort()
    .map((f) => [f.replace(/\.json$/, ""), JSON.parse(readFileSync(path.join(dir, f), "utf8"))]);
}

type Reply = { status: number; body: unknown };
function client(replies: Reply[]) {
  const bodies: (string | null)[] = [];
  let i = 0;
  const fetchFn = (async (_url: string, init: RequestInit = {}) => {
    bodies.push((init.body as string | undefined) ?? null);
    const r = replies[Math.min(i++, replies.length - 1)] as Reply;
    return new Response(JSON.stringify(r.body), {
      status: r.status,
      headers: { "content-type": "application/json" },
    });
  }) as unknown as typeof fetch;
  return {
    flow: createModelKeyFlow(new HttpClient({ baseUrl: "http://api.test", fetch: fetchFn })),
    bodies,
  };
}

describe("ADR-0041 BYOK-6 the client reads the contract's answers", () => {
  it("BYOK_6_every_valid_owner_view_is_read_as_the_schema_means_it", async () => {
    const all = fixtures("owner_view");
    expect(all.length).toBeGreaterThanOrEqual(6);
    for (const [name, fx] of all) {
      const r = await client([{ status: 200, body: fx }]).flow.read();
      expect(r.ok, name).toBe(true);
      if (!r.ok) continue;
      expect(r.view, name).toMatchObject({
        owner: true,
        active: fx.active,
        label: fx.label,
        state: fx.state,
        // the config's current version, the one this page's text must match (never the stored one)
        consentVersion: fx.consent_version,
        version: fx.secret_version ?? null,
        dayCapCredits: fx.day_cap_credits ?? null,
        lastError: fx.last_error ?? null,
      });
    }
  });

  it("BYOK_6_every_valid_member_view_is_read_only_with_no_state_and_no_version", async () => {
    const all = fixtures("member_view");
    expect(all.length).toBeGreaterThanOrEqual(1);
    for (const [name, fx] of all) {
      const r = await client([{ status: 200, body: fx }]).flow.read();
      expect(r, name).toMatchObject({
        ok: true,
        view: {
          owner: false,
          active: fx.active,
          label: fx.label,
          state: null,
          consentVersion: null,
        },
      });
    }
  });

  it("BYOK_6_every_valid_error_is_named_by_status_and_word_and_a_403_is_always_owner_only", async () => {
    const status: Record<string, number> = {
      owner_only: 403,
      reauth_required: 401,
      confirm_required: 422,
      key_refused: 422,
      invalid_body: 422,
      rate_limited: 429,
      not_configured: 503,
      unavailable: 503,
    };
    const problem: Record<string, string> = {
      owner_only: "owner_only",
      reauth_required: "reauth",
      confirm_required: "confirm",
      key_refused: "key_refused",
      invalid_body: "invalid",
      rate_limited: "rate_limited",
      not_configured: "not_configured",
      unavailable: "unavailable",
    };
    const all = fixtures("error");
    expect(all.map(([n]) => n).sort()).toEqual(Object.keys(status).sort());
    for (const [name, fx] of all) {
      const detail = String(fx.detail);
      const r = await client([{ status: status[detail] ?? 500, body: fx }]).flow.read();
      expect(r, name).toEqual({ ok: false, problem: problem[detail] });
    }
    // An API built before the contract said `forbidden` for a person with no directory record: the status decides.
    for (const body of [{ detail: "forbidden" }, { detail: "owner_only" }, {}]) {
      const r = await client([{ status: 403, body }]).flow.read();
      expect(r, JSON.stringify(body)).toEqual({ ok: false, problem: "owner_only" });
    }
  });
});

describe("ADR-0041 BYOK-6 the client writes only what put_request allows", () => {
  it("BYOK_6_the_put_body_has_only_put_request_fields_and_all_the_required_ones", async () => {
    const schema = JSON.parse(
      readFileSync(path.join(CONTRACTS, "org_model_key.schema.json"), "utf8"),
    ) as { $defs: { put_request: { properties: object; required: string[] } } };
    const { properties, required } = schema.$defs.put_request;
    const owner = fixtures("owner_view").find(([n]) => n === "active")?.[1];
    const { flow, bodies } = client([
      { status: 200, body: { state: "active", secret_version: 2, validated: true } },
      { status: 200, body: owner },
    ]);
    const r = await flow.save({
      bundleId: "openai-compat-example",
      key: KEY,
      projectId: null,
      dayCapCredits: 500,
      fallbackToTilo: true,
      consentVersion: 1,
    });
    expect(r.ok).toBe(true);
    const sent = JSON.parse(bodies[0] ?? "{}") as Record<string, unknown>;
    expect(Object.keys(sent).filter((k) => !(k in properties))).toEqual([]);
    expect(required.filter((k) => !(k in sent))).toEqual([]);
    expect(sent.confirm).toBe(true);
  });

  it("BYOK_6_every_valid_put_answer_is_accepted_and_confirmed_by_a_reread", async () => {
    const owners = new Map(fixtures("owner_view").map(([n, fx]) => [n, fx]));
    const all = fixtures("put_answer");
    expect(all.length).toBeGreaterThanOrEqual(1);
    for (const [name, fx] of all) {
      const view = owners.get(fx.state === "active" ? "active" : "unverified_first_set");
      const { flow } = client([
        { status: 200, body: fx },
        { status: 200, body: view },
      ]);
      const r = await flow.save({
        bundleId: "openai-compat-example",
        key: KEY,
        projectId: null,
        dayCapCredits: 500,
        fallbackToTilo: false,
        consentVersion: 1,
      });
      expect(r, name).toMatchObject({ ok: true, view: { state: fx.state } });
    }
  });
});
