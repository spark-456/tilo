// @vitest-environment happy-dom
// SKILLS-5 (FR-SKL-01/02/04, web half): on a live page the Teach card works against the real API: describe the
// skill -> the captured steps (POST /v1/skills/captures) -> Tilo's version (POST .../{id}/version) -> save
// (POST /v1/skills). Driven through the live Api over a stubbed fetch, so the wire and the page are checked together.
// Pinned: the server sets "Ask me first" (a forced step is locked on), the offer is "Just me" and "When I ask"
// only, the "Saved" toast comes after a 201 and not before, a failed capture or version shows an error and never
// sample steps, one click is one request, and nothing in the live card is a made-up number.
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, qa } from "../../../../test-support/park/componentsHarness";
import { CAP, PLAN } from "../../../../test-support/park/skillsCopy";
import {
  type SkillsRig,
  askStates,
  askSwitches,
  clickEl,
  control,
  describeField,
  hasControl,
  isDisabled,
  mountSkills,
  pageText,
  settle,
  skillsApi,
  teachCard,
  toasts,
  typeInto,
} from "../../../../test-support/park/skillsHarness";
import { createLiveApi } from "../../api/liveApi";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const BASE = "https://api.example.test";
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

const READ = {
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
const CAPTURED = {
  capture_id: "tsk_C1",
  captured_steps: [{ text: "Open the invoice mail" }, { text: "Note the total" }],
};
const VERSION = {
  capture_id: "tsk_C1",
  plan_steps: [READ, SEND],
  clarifying_question: { text: "Link or PDF?", options: ["Open the link", "Skip"] },
  estimates: {
    credits_per_run: 6,
    seconds_per_run: 40,
    asks_per_run: 1,
    source: "prior",
    prices_as_of: "2026-10-01",
  },
};
const SAVED = {
  id: "tsk_N1",
  name: "Match invoices",
  scope: { kind: "just_me", team: null },
  status: "learning",
  paused: false,
  plan: [READ, SEND],
  question: null,
};

// the strings this ticket adds (flagged in the PR body)
const SAVED_TOAST = "Saved “Match invoices”. It starts as Learning";
const ERR_TRY = "Tilo couldn’t read that just now. Try again.";
const ERR_UNDERSTOOD = "Tilo couldn’t make a skill from that. Try describing it differently.";
const NOT_CONNECTED = "Not connected yet";

type Handler = (init: RequestInit) => Response | Promise<Response>;
interface Server {
  fetch: ReturnType<typeof vi.fn>;
  posts: (path: string) => unknown[];
}

function rig(routes: Record<string, Handler> = {}): { server: Server; mount: () => Promise<SkillsRig> } {
  const table: Record<string, Handler> = {
    "GET /v1/skills": () => json({ skills: [] }),
    "GET /v1/learn": () => json({ learning: [], needs_rating: [] }),
    "POST /v1/skills/captures": () => json(CAPTURED, 201),
    "POST /v1/skills/captures/tsk_C1/version": () => json(VERSION),
    "POST /v1/skills": () => json(SAVED, 201),
    ...routes,
  };
  const fetchSpy = vi.fn(async (url: unknown, init?: RequestInit) => {
    const key = `${init?.method ?? "GET"} ${String(url).replace(BASE, "")}`;
    const hit = table[key];
    if (!hit) throw new Error(`unrouted ${key}`);
    return hit(init ?? {});
  });
  const server: Server = {
    fetch: fetchSpy,
    posts: (path) =>
      fetchSpy.mock.calls
        .filter((c) => c[1]?.method === "POST" && String(c[0]) === `${BASE}${path}`)
        .map((c) => JSON.parse(String(c[1]?.body))),
  };
  const live = createLiveApi({ baseUrl: BASE, fetch: fetchSpy as unknown as typeof fetch });
  const api = skillsApi({
    getSkills: live.getSkills,
    getLearn: live.getLearn,
    captureSkill: live.captureSkill,
    proposeVersion: live.proposeVersion,
    saveSkill: live.saveSkill,
  });
  return { server, mount: () => mountSkills({ api }) };
}

const text = (r: SkillsRig) => pageText(teachCard(r.el));
const describe_ = async (r: SkillsRig, words = "Check the invoice mail and log the total") => {
  typeInto(describeField(r.el), words);
  clickEl(control(r.el, "Read my description"));
  await settle();
};
const toVersion = async (r: SkillsRig) => {
  await describe_(r);
  clickEl(control(r.el, "Show me Tilo’s version"));
  await settle();
};
const toSave = async (r: SkillsRig) => {
  await toVersion(r);
  clickEl(control(r.el, "Looks right"));
  await settle();
};
const name = (r: SkillsRig, v: string) => {
  const field = qa<HTMLInputElement>(teachCard(r.el), "input").find((i) => i.value !== undefined);
  typeInto(field as HTMLInputElement, v);
};
const gate = () => {
  let release: (r: Response) => void = () => undefined;
  const waiting = new Promise<Response>((res) => {
    release = res;
  });
  return { waiting, release };
};

describe("SKILLS_5_live_teach: describe it (step 1)", () => {
  it("SKILLS_5_live_teach_the_first_step_is_an_empty_describe_box_and_no_sample_content", async () => {
    const r = await rig().mount();
    expect(describeField(r.el).value).toBe("");
    expect(hasControl(r.el, "Read my description")).toBe(true);
    for (const m of ["Record my screen", "Guided walkthrough", "Upload an example"])
      expect(text(r), m).not.toContain(m);
    expect(text(r)).not.toContain("Connect to start teaching");
    expect(text(r)).not.toContain("Sample run");
    for (const line of [...CAP.describe, PLAN[0].text]) expect(text(r)).not.toContain(line);
  });

  it("SKILLS_5_live_teach_nothing_is_sent_for_an_empty_description", async () => {
    const { server, mount } = rig();
    const r = await mount();
    expect(isDisabled(control(r.el, "Read my description"))).toBe(true);
    clickEl(control(r.el, "Read my description"));
    await settle();
    expect(server.posts("/v1/skills/captures")).toEqual([]);
  });

  it("SKILLS_5_live_teach_reading_posts_the_text_and_shows_the_servers_captured_steps", async () => {
    const { server, mount } = rig();
    const r = await mount();
    await describe_(r, "  Check the invoice mail and log the total ");
    expect(server.posts("/v1/skills/captures")).toEqual([
      { method: "describe", text: "Check the invoice mail and log the total" },
    ]);
    expect(text(r)).toContain("Open the invoice mail");
    expect(text(r)).toContain("Note the total");
    expect(text(r)).toContain("2 of 2");
  });

  it("SKILLS_5_live_teach_two_clicks_before_the_answer_make_one_request", async () => {
    const g = gate();
    const { server, mount } = rig({ "POST /v1/skills/captures": () => g.waiting });
    const r = await mount();
    typeInto(describeField(r.el), "Check the mail");
    clickEl(control(r.el, "Read my description"));
    clickEl(control(r.el, "Read my description"));
    await settle();
    expect(server.posts("/v1/skills/captures")).toHaveLength(1);
    g.release(json(CAPTURED, 201));
    await settle();
    expect(text(r)).toContain("Note the total");
  });
});

describe("SKILLS_5_live_teach: a capture the server cannot make", () => {
  it.each([
    [503, NOT_CONNECTED],
    [502, ERR_TRY],
    [422, ERR_UNDERSTOOD],
  ])("SKILLS_5_live_teach_capture_http_%i_says_so_and_shows_no_steps", async (status, line) => {
    const r = await rig({ "POST /v1/skills/captures": () => json({ detail: "x" }, status) }).mount();
    await describe_(r);
    expect(pageText(r.el.querySelector('[data-testid="skills-teach-error"]') as Element)).toBe(line);
    expect(text(r)).toContain("0 of 0");
    for (const l of CAP.describe) expect(text(r)).not.toContain(l);
    expect(isDisabled(control(r.el, "Show me Tilo’s version"))).toBe(true);
  });

  it.each([{ oops: 1 }, { capture_id: "tsk_C1", captured_steps: [] }])(
    "SKILLS_5_live_teach_an_unreadable_201_is_an_error_not_steps_%#",
    async (body) => {
      const r = await rig({ "POST /v1/skills/captures": () => json(body, 201) }).mount();
      await describe_(r);
      expect(r.el.querySelector('[data-testid="skills-teach-error"]')).not.toBeNull();
      expect(isDisabled(control(r.el, "Show me Tilo’s version"))).toBe(true);
    },
  );

  it("SKILLS_5_live_teach_a_second_try_after_an_error_clears_it", async () => {
    let n = 0;
    const r = await rig({
      "POST /v1/skills/captures": () => (++n === 1 ? json({ detail: "x" }, 502) : json(CAPTURED, 201)),
    }).mount();
    await describe_(r);
    expect(r.el.querySelector('[data-testid="skills-teach-error"]')).not.toBeNull();
    clickEl(control(r.el, "Read my description"));
    await settle();
    expect(r.el.querySelector('[data-testid="skills-teach-error"]')).toBeNull();
    expect(text(r)).toContain("Note the total");
  });
});

describe("SKILLS_5_live_teach: Tilo's version (step 2)", () => {
  it("SKILLS_5_live_teach_version_posts_once_and_shows_the_steps_the_question_and_labelled_estimates", async () => {
    const { server, mount } = rig();
    const r = await mount();
    await toVersion(r);
    expect(server.posts("/v1/skills/captures/tsk_C1/version")).toHaveLength(1);
    for (const l of [READ.text, SEND.text, "Link or PDF?"]) expect(text(r)).toContain(l);
    expect(text(r)).toContain("Each run (estimate)6 credits");
    expect(text(r)).toContain("Time (estimate)40 s");
    expect(text(r)).toContain("Stops to ask1 step");
    expect(text(r)).not.toMatch(/[£$€₹]|~/);
    for (const l of PLAN.map((p) => p.text)) expect(text(r)).not.toContain(l);
  });

  it("SKILLS_5_live_teach_the_servers_ask_first_shows_and_a_forced_step_cannot_be_switched_off", async () => {
    const r = await rig().mount();
    await toVersion(r);
    expect(askStates(r.el)).toEqual([false, true]);
    const [free, forced] = askSwitches(r.el) as [HTMLElement, HTMLElement];
    expect(isDisabled(forced)).toBe(true);
    clickEl(forced);
    expect(askStates(r.el)).toEqual([false, true]);
    expect(isDisabled(free)).toBe(false);
    clickEl(free);
    expect(askStates(r.el)).toEqual([true, true]);
  });

  it("SKILLS_5_live_teach_two_clicks_on_Tilos_version_make_one_request", async () => {
    const g = gate();
    const { server, mount } = rig({ "POST /v1/skills/captures/tsk_C1/version": () => g.waiting });
    const r = await mount();
    await describe_(r);
    clickEl(control(r.el, "Show me Tilo’s version"));
    clickEl(control(r.el, "Show me Tilo’s version"));
    await settle();
    expect(server.posts("/v1/skills/captures/tsk_C1/version")).toHaveLength(1);
    g.release(json(VERSION));
    await settle();
    expect(text(r)).toContain(SEND.text);
  });

  it("SKILLS_5_live_teach_no_estimates_from_the_server_print_dashes_not_numbers", async () => {
    const r = await rig({
      "POST /v1/skills/captures/tsk_C1/version": () => json({ ...VERSION, estimates: null }),
    }).mount();
    await toVersion(r);
    expect(text(r)).toContain("Each run (estimate)—");
    expect(text(r)).toContain("Time (estimate)—");
  });

  it("SKILLS_5_live_teach_no_question_from_the_server_shows_none", async () => {
    const r = await rig({
      "POST /v1/skills/captures/tsk_C1/version": () => json({ ...VERSION, clarifying_question: null }),
    }).mount();
    await toVersion(r);
    expect(text(r)).not.toContain("Link or PDF?");
  });

  it.each([
    [503, NOT_CONNECTED],
    [502, ERR_TRY],
    [422, ERR_UNDERSTOOD],
  ])("SKILLS_5_live_teach_version_http_%i_says_so_and_stays_on_step_1", async (status, line) => {
    const r = await rig({
      "POST /v1/skills/captures/tsk_C1/version": () => json({ detail: "x" }, status),
    }).mount();
    await toVersion(r);
    expect(pageText(r.el.querySelector('[data-testid="skills-teach-error"]') as Element)).toBe(line);
    expect(text(r)).toContain("Note the total");
    expect(askSwitches(r.el)).toHaveLength(0);
    for (const l of PLAN.map((p) => p.text)) expect(text(r)).not.toContain(l);
  });

  it("SKILLS_5_live_teach_a_malformed_version_is_an_error_and_does_not_crash", async () => {
    const r = await rig({
      "POST /v1/skills/captures/tsk_C1/version": () => json({ plan_steps: "nope" }),
    }).mount();
    await toVersion(r);
    expect(r.el.querySelector('[data-testid="skills-teach-error"]')).not.toBeNull();
    expect(askSwitches(r.el)).toHaveLength(0);
  });

  it("SKILLS_5_live_teach_there_is_no_practice_run_to_start_live", async () => {
    const r = await rig().mount();
    await toVersion(r);
    expect(hasControl(r.el, "Let Tilo try it")).toBe(false);
    expect(hasControl(r.el, "Looks right")).toBe(true);
  });
});

describe("SKILLS_5_live_teach: save (step 4)", () => {
  it("SKILLS_5_live_teach_save_offers_just_me_and_when_I_ask_only", async () => {
    const r = await rig().mount();
    await toSave(r);
    expect(hasControl(r.el, "Save skill")).toBe(true);
    const picks = qa(teachCard(r.el), ".park-skills-pick").map((e) => pageText(e));
    expect(picks).toEqual(["Just me", "When I ask"]);
  });

  it("SKILLS_5_live_teach_save_posts_the_servers_steps_and_shows_Saved_only_after_a_201", async () => {
    const g = gate();
    const { server, mount } = rig({ "POST /v1/skills": () => g.waiting });
    const r = await mount();
    await toSave(r);
    name(r, "Match invoices");
    clickEl(control(r.el, "Save skill"));
    await settle();
    expect(toasts(r.app)).toEqual([]);
    expect(text(r)).not.toContain("is now a skill");
    expect(r.el.textContent).not.toContain("Match invoices");
    g.release(json(SAVED, 201));
    await settle();
    expect(toasts(r.app)).toEqual([[SAVED_TOAST]]);
    expect(text(r)).toContain("“Match invoices” is now a skill");
    expect(text(r)).toContain("starts as Learning");
    const [body] = server.posts("/v1/skills") as Record<string, unknown>[];
    expect(body).toEqual({
      name: "Match invoices",
      scope: { kind: "just_me", team: null },
      trigger: { kind: "on_demand" },
      plan_steps: [
        { text: READ.text, tool: "gmail", action: "read_email", verb: "read", ask_first: false },
        { text: SEND.text, tool: "gmail", action: "send_email", verb: "send", ask_first: true },
      ],
      captured_steps: [{ text: "Open the invoice mail" }, { text: "Note the total" }],
      clarifying_question: { text: "Link or PDF?", options: ["Open the link", "Skip"] },
    });
  });

  it("SKILLS_5_live_teach_a_step_the_person_switched_to_ask_first_is_posted_as_asked", async () => {
    const { server, mount } = rig();
    const r = await mount();
    await toVersion(r);
    clickEl(askSwitches(r.el)[0] as HTMLElement);
    clickEl(control(r.el, "Looks right"));
    await settle();
    name(r, "Match invoices");
    clickEl(control(r.el, "Save skill"));
    await settle();
    const [body] = server.posts("/v1/skills") as { plan_steps: { ask_first: boolean }[] }[];
    expect(body?.plan_steps.map((s) => s.ask_first)).toEqual([true, true]);
  });

  it("SKILLS_5_live_teach_two_clicks_on_Save_make_one_request", async () => {
    const g = gate();
    const { server, mount } = rig({ "POST /v1/skills": () => g.waiting });
    const r = await mount();
    await toSave(r);
    name(r, "Match invoices");
    clickEl(control(r.el, "Save skill"));
    clickEl(control(r.el, "Save skill"));
    await settle();
    expect(server.posts("/v1/skills")).toHaveLength(1);
    g.release(json(SAVED, 201));
    await settle();
    expect(toasts(r.app)).toHaveLength(1);
  });

  it("SKILLS_5_live_teach_the_saved_skill_is_in_the_library_as_Learning_with_runs_shown_as_a_dash", async () => {
    const r = await rig().mount();
    await toSave(r);
    name(r, "Match invoices");
    clickEl(control(r.el, "Save skill"));
    await settle();
    const lib = pageText(r.el);
    expect(lib).toContain("Match invoices");
    expect(lib).toMatch(/Learning/);
    const runs = qa(r.el, "*").find((e) => pageText(e) === "Runs");
    expect(pageText(runs?.nextElementSibling as Element)).toBe("—");
  });

  it.each([
    ["unknown_action", "Couldn’t save “Match invoices” (unknown_action). Try again"],
    ["ask_first_required", "Couldn’t save “Match invoices” (ask_first_required). Try again"],
    ["some words the server made up", "Couldn’t save “Match invoices”. Try again"],
  ])("SKILLS_5_live_teach_a_422_%s_says_Couldnt_save_and_nothing_is_saved", async (detail, toast) => {
    const r = await rig({ "POST /v1/skills": () => json({ detail }, 422) }).mount();
    await toSave(r);
    name(r, "Match invoices");
    clickEl(control(r.el, "Save skill"));
    await settle();
    expect(toasts(r.app)).toEqual([[toast]]);
    expect(text(r)).not.toContain("is now a skill");
    expect(hasControl(r.el, "Save skill")).toBe(true);
  });

  it("SKILLS_5_live_teach_a_500_says_Couldnt_save_and_the_button_works_again", async () => {
    let n = 0;
    const { server, mount } = rig({
      "POST /v1/skills": () => (++n === 1 ? json({ detail: "x" }, 500) : json(SAVED, 201)),
    });
    const r = await mount();
    await toSave(r);
    name(r, "Match invoices");
    clickEl(control(r.el, "Save skill"));
    await settle();
    expect(toasts(r.app)).toEqual([["Couldn’t save “Match invoices”. Try again"]]);
    clickEl(control(r.el, "Save skill"));
    await settle();
    expect(server.posts("/v1/skills")).toHaveLength(2);
    expect(toasts(r.app)[1]).toEqual([SAVED_TOAST]);
  });

  it("SKILLS_5_live_teach_a_201_the_page_cannot_read_is_not_saved", async () => {
    const r = await rig({ "POST /v1/skills": () => json({ oops: 1 }, 201) }).mount();
    await toSave(r);
    name(r, "Match invoices");
    clickEl(control(r.el, "Save skill"));
    await settle();
    expect(toasts(r.app)[0]?.[0]).toMatch(/^Couldn’t save/);
    expect(text(r)).not.toContain("is now a skill");
  });
});
