// SKILLS-3 (FR-SKL-04, web half): getSkills reads GET /v1/skills, getLearn GET /v1/learn and saveSkill posts
// POST /v1/skills (services/api skills_routes.py). Nothing is invented: a skill's runs, rate, last run and
// improvement are not served, so they read as 0, null and "" ; a failed answer rejects (the page shows its
// unavailable state) and a save that did not happen is never an Ack.
import { describe, expect, it, vi } from "vitest";
import { TiloApiError } from "../../api/http";
import { createLiveApi } from "./liveApi";
import type { Skill } from "./types";

const BASE = "https://api.example.test";
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
const asFetch = (f: unknown) => f as typeof fetch;

const STEP = {
  text: "Read the new invoice mail",
  tool: "gmail",
  action: "read_email",
  verb: "read",
  ask_first: false,
  must_ask: false,
};
const SEND = {
  text: "Send the summary",
  tool: "gmail",
  action: "send_email",
  verb: "send",
  ask_first: true,
  must_ask: true,
};
const row = (over: Record<string, unknown> = {}) => ({
  id: "tsk_A1",
  org_id: "org_1",
  owner: "usr_1",
  name: "Match invoices",
  scope: { kind: "just_me", team: null },
  status: "learning",
  paused: false,
  method: "describe",
  captured: [],
  plan: [STEP, SEND],
  question: { text: "Link or PDF?", options: ["Open the link", "Skip"], answer: null },
  trigger: { kind: "on_demand", schedule_id: null, event: null },
  estimates: null,
  tool_access: {},
  good_runs: 0,
  version: 1,
  created_at: "2026-10-10T08:00:00Z",
  updated_at: "2026-10-10T08:00:00Z",
  ...over,
});
const live = (spy: ReturnType<typeof vi.fn>) =>
  createLiveApi({ baseUrl: BASE, fetch: asFetch(spy) });
const failure = (p: Promise<unknown>) =>
  p.then(
    (v) => ({ resolved: v }),
    (e: unknown) => e,
  );

describe("SKILLS_3_getSkills: GET /v1/skills as the Skills library", () => {
  it("SKILLS_3_getSkills_maps_a_record_to_a_Skill_and_says_live", async () => {
    const spy = vi.fn(async () => json({ skills: [row()] }));
    const r = await live(spy).getSkills();
    expect(String(spy.mock.calls[0]?.[0])).toBe(`${BASE}/v1/skills`);
    expect(r.source).toBe("live");
    const s = r.data[0] as Skill;
    expect(s).toMatchObject({
      id: "tsk_A1",
      name: "Match invoices",
      owner: "You",
      team: "",
      status: "live",
      st: "learning",
      steps: ["Read the new invoice mail", "Send the summary"],
      ask: { q: "Link or PDF?", a: ["Open the link", "Skip"] },
    });
    expect(s.tools).toEqual([
      ["gmail", 1],
      ["gmail", 2],
    ]);
  });

  it("SKILLS_3_getSkills_invents_no_numbers", async () => {
    const r = await live(vi.fn(async () => json({ skills: [row()] }))).getSkills();
    const s = r.data[0] as Skill;
    expect([s.runs, s.rate, s.last, s.improved, s.from]).toEqual([0, null, "", "", ""]);
    expect(s.first).toBeUndefined();
    expect(s.now).toBeUndefined();
    expect(s.used).toEqual([]);
  });

  it("SKILLS_3_getSkills_status_and_pause_set_st_and_status", async () => {
    const rows = [
      row({ id: "tsk_T", status: "trusted" }),
      row({ id: "tsk_P", paused: true }),
      row({ id: "tsk_D", status: "draft" }),
    ];
    const r = await live(vi.fn(async () => json({ skills: rows }))).getSkills();
    expect(r.data.map((s) => [s.id, s.st, s.status])).toEqual([
      ["tsk_T", "trusted", "live"],
      ["tsk_P", "review", "live"],
      ["tsk_D", "draft", "draft"],
    ]);
  });

  it("SKILLS_3_getSkills_a_team_skill_names_its_team_and_not_a_made_up_owner", async () => {
    const team = row({ scope: { kind: "team", team: "finance" } });
    const s = (await live(vi.fn(async () => json({ skills: [team] }))).getSkills()).data[0];
    expect(s?.team).toBe("finance");
    expect(s?.owner).toBe("");
  });

  it("SKILLS_3_getSkills_an_answered_question_is_not_asked_again", async () => {
    const answered = row({ question: { text: "Q?", options: ["a"], answer: "a" } });
    const s = (await live(vi.fn(async () => json({ skills: [answered] }))).getSkills()).data[0];
    expect(s?.ask).toBeUndefined();
  });

  it("SKILLS_3_getSkills_an_empty_list_is_an_empty_library", async () => {
    const r = await live(vi.fn(async () => json({ skills: [] }))).getSkills();
    expect(r).toEqual({ data: [], source: "live" });
  });

  it("SKILLS_3_getSkills_a_malformed_row_is_left_out_not_a_crash", async () => {
    const bad = [{ id: 3 }, null, row({ plan: "x" }), row({ status: "weird", id: "tsk_W" }), row()];
    const r = await live(vi.fn(async () => json({ skills: bad }))).getSkills();
    expect(r.data.map((s) => s.id)).toEqual(["tsk_A1"]);
  });

  it("SKILLS_3_getSkills_a_body_without_skills_is_an_unreadable_reply", async () => {
    const err = await failure(live(vi.fn(async () => json({ nope: 1 }))).getSkills());
    expect(err).toBeInstanceOf(TiloApiError);
  });

  it.each([401, 500, 503])("SKILLS_3_getSkills_http_%i_rejects_TiloApiError", async (status) => {
    const err = await failure(live(vi.fn(async () => json({ detail: "x" }, status))).getSkills());
    expect(err).toBeInstanceOf(TiloApiError);
    expect((err as TiloApiError).status).toBe(status);
  });
});

describe("SKILLS_3_getLearn: GET /v1/learn as the Learn data", () => {
  it("SKILLS_3_getLearn_has_no_ratings_reviews_helpers_or_tools_to_show", async () => {
    const spy = vi.fn(async () => json({ learning: [row()], needs_rating: [], helpers: null }));
    const r = await live(spy).getLearn();
    expect(String(spy.mock.calls[0]?.[0])).toBe(`${BASE}/v1/learn`);
    expect(r).toEqual({
      data: { rates: [], reviews: [], helpers: [], tools: [] },
      source: "live",
    });
  });

  it("SKILLS_3_getLearn_a_body_the_page_cannot_read_is_an_error", async () => {
    const err = await failure(live(vi.fn(async () => json({ other: 1 }))).getLearn());
    expect(err).toBeInstanceOf(TiloApiError);
  });

  it("SKILLS_3_getLearn_http_503_rejects_TiloApiError", async () => {
    const err = await failure(live(vi.fn(async () => json({ detail: "x" }, 503))).getLearn());
    expect((err as TiloApiError).status).toBe(503);
  });
});

const draft = (over: Partial<Skill> = {}): Skill => ({
  id: "taught",
  name: "Match invoices",
  team: "",
  owner: "Alex",
  role: "builder",
  runs: 0,
  rate: null,
  last: "Not run yet",
  improved: "Draft",
  status: "draft",
  st: "draft",
  from: "taught by you",
  tools: [],
  used: [],
  steps: ["Read the new invoice mail", "Send the summary"],
  draft: {
    scope: "me",
    trigger: "ask",
    plan: [
      { text: "Read the new invoice mail", tool: "Gmail · Read", ask: false },
      { text: "Send the summary", tool: "Gmail · Act", ask: true },
    ],
  },
  ...over,
});

describe("SKILLS_3_saveSkill: POST /v1/skills", () => {
  it("SKILLS_3_saveSkill_posts_the_draft_as_plan_steps_and_acks_on_201", async () => {
    const spy = vi.fn(async (_u: unknown, _i?: RequestInit) => json(row(), 201));
    const r = await live(spy).saveSkill(draft());
    expect(r).toEqual({ data: { ok: true }, source: "live" });
    expect(String(spy.mock.calls[0]?.[0])).toBe(`${BASE}/v1/skills`);
    expect(spy.mock.calls[0]?.[1]?.method).toBe("POST");
    const body = JSON.parse(String(spy.mock.calls[0]?.[1]?.body));
    expect(body.name).toBe("Match invoices");
    expect(body.scope).toEqual({ kind: "just_me", team: null });
    expect(body.trigger).toEqual({ kind: "on_demand" });
    expect(body.plan_steps).toHaveLength(2);
    expect(body.plan_steps[0]).toEqual({
      text: "Read the new invoice mail",
      tool: "gmail",
      action: "read_email",
      verb: "read",
      ask_first: false,
    });
    expect(Object.keys(body).sort()).toEqual(["name", "plan_steps", "scope", "trigger"]);
  });

  it.each([422, 403, 503])(
    "SKILLS_3_saveSkill_http_%i_rejects_so_nothing_shows_as_saved",
    async (status) => {
      const err = await failure(
        live(vi.fn(async () => json({ detail: "x" }, status))).saveSkill(draft()),
      );
      expect(err).toBeInstanceOf(TiloApiError);
      expect((err as TiloApiError).status).toBe(status);
      expect((err as TiloApiError).write).toBe(true);
    },
  );

  it("SKILLS_3_saveSkill_a_201_the_page_cannot_read_is_not_an_ack", async () => {
    const err = await failure(live(vi.fn(async () => json({ oops: 1 }, 201))).saveSkill(draft()));
    expect(err).toBeInstanceOf(TiloApiError);
  });

  it("SKILLS_3_saveSkill_a_team_or_timed_draft_is_refused_without_a_request", async () => {
    const spy = vi.fn(async () => json(row(), 201));
    const base = draft().draft as NonNullable<Skill["draft"]>;
    for (const d of [
      { ...base, scope: "team" as const },
      { ...base, trigger: "weekday" as const },
      { ...base, trigger: "arrive" as const },
    ]) {
      const err = await failure(live(spy).saveSkill(draft({ draft: d })));
      expect(err).toBeInstanceOf(TiloApiError);
      expect((err as TiloApiError).status).toBe(422);
    }
    expect(spy).not.toHaveBeenCalled();
  });

  it("SKILLS_3_saveSkill_without_a_draft_to_send_is_refused_without_a_request", async () => {
    const spy = vi.fn(async () => json(row(), 201));
    const err = await failure(live(spy).saveSkill(draft({ draft: undefined })));
    expect(err).toBeInstanceOf(TiloApiError);
    expect(spy).not.toHaveBeenCalled();
  });
});
