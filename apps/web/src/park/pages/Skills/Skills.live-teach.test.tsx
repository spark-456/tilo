// @vitest-environment happy-dom
// SKILLS-5 (FR-SKL-01/02/04, web half; STUDIO-4: through the 3-step Teach wizard): on a live page teaching works against the real API: describe the
// skill -> the captured steps (POST /v1/skills/captures) -> Tilo's version (POST .../{id}/version) -> save
// (POST /v1/skills). Driven through the live Api over a stubbed fetch, so the wire and the page are checked together.
// Pinned: the server sets "Ask me first" (a forced step is locked on), the offer is "Just me" and "When I ask"
// only, the "Saved" toast comes after a 201 and not before, a failed capture or version shows an error and never
// sample steps, one click is one request, and nothing in the live card is a made-up number.
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, q, qa } from "../../../../test-support/park/componentsHarness";
import { CAP, PLAN } from "../../../../test-support/park/skillsCopy";
import {
  NEXT_EXAMPLE,
  NEXT_REVIEW,
  type SkillsRig,
  askStates,
  askSwitches,
  clickEl,
  control,
  currentStep,
  describeField,
  hasControl,
  isDisabled,
  mountSkills,
  openSkill,
  openTeach,
  pageText,
  settle,
  skillsApi,
  teachCard,
  toasts,
  typeInto,
} from "../../../../test-support/park/skillsHarness";
import { createLiveApi } from "../../api/liveApi";
import { TRY_OFF } from "./TeachWizard";

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
// M2-CODES-1 (5b57e7ef): a retryable 5xx on a POST may still have happened, so the page says it is unconfirmed.
const ERR_TRY = "We could not confirm it. Reload before trying again.";
const ERR_UNDERSTOOD = "Check the information and try again.";
// TEACH-COPY (FR-SKL-02): the version call's own 422 sentence tells the person what to change.
const ERR_TEACH_UNDERSTOOD =
  "Tilo could not match your steps to the apps it can use. Name the app and the action in each step, for example Read the new mail in Gmail or Save the summary to Google Drive, then try again.";
const NOT_CONNECTED = ERR_TRY;

type Handler = (init: RequestInit) => Response | Promise<Response>;
interface Server {
  fetch: ReturnType<typeof vi.fn>;
  posts: (path: string) => unknown[];
}

function rig(routes: Record<string, Handler> = {}): {
  server: Server;
  mount: () => Promise<SkillsRig>;
} {
  const table: Record<string, Handler> = {
    "GET /v1/skills": () => json({ skills: [] }),
    "GET /v1/learn": () => json({ learning: [], needs_rating: [] }),
    "POST /v1/skills/captures": () => json(CAPTURED, 201),
    "POST /v1/skills/captures/tsk_C1/version": () => json(VERSION),
    "POST /v1/skills": () => json(SAVED, 201),
    ...routes,
  };
  const fetchSpy = vi.fn(async (url: unknown, init?: RequestInit) => {
    // LIVE-SKILLS (FR-SKL-04, 4480648d): the library and Learn reads ask for the built-in catalogue, so the
    // route key ignores that one query flag; the flag itself is pinned in liveApi.LIVE-SKILLS.test.ts.
    const key = `${init?.method ?? "GET"} ${String(url)
      .replace(BASE, "")
      .replace(/\?include_builtin=true$/, "")}`;
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
  return {
    server,
    mount: async () => {
      const r = await mountSkills({ api });
      openTeach(r); // STUDIO-4: the wizard opens from the page's one primary button
      return r;
    },
  };
}

const text = (r: SkillsRig) => pageText(teachCard(r.el));
const describe_ = async (r: SkillsRig, words = "Check the invoice mail and log the total") => {
  typeInto(describeField(r.el), words);
  clickEl(control(r.el, NEXT_EXAMPLE));
  await settle();
};
const toVersion = async (r: SkillsRig) => {
  await describe_(r);
  clickEl(control(r.el, NEXT_REVIEW));
  await settle();
};
// STUDIO-4: Save sits on step 3 (Review the steps), with Tilo's version.
const toSave = toVersion;
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
  it("FR_SKL_01_W11_describing_announces_loading_until_the_capture_finishes", async () => {
    const g = gate();
    const { mount } = rig({ "POST /v1/skills/captures": () => g.waiting });
    const r = await mount();
    typeInto(describeField(r.el), "Check the mail");
    clickEl(control(r.el, NEXT_EXAMPLE));
    await settle();
    const pending = r.el.querySelector("output");
    expect(pending).not.toBeNull();
    expect(pending?.textContent).toBe("Reading your description…");
    expect(isDisabled(control(r.el, NEXT_EXAMPLE))).toBe(true);
    g.release(json(CAPTURED, 201));
    await settle();
    expect(r.el.querySelector("output")).toBeNull();
    expect(text(r)).toContain("Note the total");
  });

  it("SKILLS_5_live_teach_the_first_step_is_an_empty_describe_box_and_no_sample_content", async () => {
    const r = await rig().mount();
    expect(describeField(r.el).value).toBe("");
    expect(hasControl(r.el, NEXT_EXAMPLE)).toBe(true);
    for (const m of ["Record my screen", "Guided walkthrough", "Upload an example"])
      expect(text(r), m).not.toContain(m);
    expect(text(r)).not.toContain("Connect to start teaching");
    expect(text(r)).not.toContain("Sample run");
    for (const line of [...CAP.describe, PLAN[0].text]) expect(text(r)).not.toContain(line);
  });

  it("SKILLS_5_live_teach_nothing_is_sent_for_an_empty_description", async () => {
    const { server, mount } = rig();
    const r = await mount();
    expect(isDisabled(control(r.el, NEXT_EXAMPLE))).toBe(true);
    // W10: an empty box says what is missing instead of a silent, unexplained off button.
    expect(text(r)).toContain("Write a sentence about the work first");
    typeInto(describeField(r.el), "Check the invoice mail");
    expect(text(r)).not.toContain("Write a sentence about the work first");
    typeInto(describeField(r.el), "");
    clickEl(control(r.el, NEXT_EXAMPLE));
    await settle();
    expect(server.posts("/v1/skills/captures")).toEqual([]);
  });

  // STUDIO-4: a live page pauses through POST /v1/skills/{id}/state; a session with no signed-in client cannot, and
  // the sheet says so (no step editor button: a live owned skill's steps are fixed in FixSkill).
  it("W10_FR_SKL_05_signed_in_library_without_a_client_disables_pause_and_says_why", async () => {
    const { mount } = rig({ "GET /v1/skills": () => json({ skills: [SAVED] }) });
    const r = await mount();
    clickEl(control(r.el, "← Back to skills"));
    const sheet = openSkill(r.el, "Match invoices");
    const why = "Pausing is not available in this session.";
    expect(isDisabled(control(sheet, "Pause"))).toBe(true);
    expect(isDisabled(control(sheet, "Test run"))).toBe(true);
    expect(pageText(sheet)).toContain(why);
    clickEl(control(sheet, "Pause"));
    expect(hasControl(sheet, "Edit steps")).toBe(false);
    expect(toasts(r.app)).toEqual([]);
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
    expect(currentStep(r.el)).toBe("Show an example"); // STUDIO-4: the read steps are step 2
  });

  it("SKILLS_5_live_teach_two_clicks_before_the_answer_make_one_request", async () => {
    const g = gate();
    const { server, mount } = rig({ "POST /v1/skills/captures": () => g.waiting });
    const r = await mount();
    typeInto(describeField(r.el), "Check the mail");
    clickEl(control(r.el, NEXT_EXAMPLE));
    clickEl(control(r.el, NEXT_EXAMPLE));
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
    const r = await rig({
      "POST /v1/skills/captures": () => json({ detail: "x" }, status),
    }).mount();
    await describe_(r);
    expect(pageText(r.el.querySelector('[data-testid="skills-teach-error"] p') as Element)).toBe(
      line,
    );
    for (const l of CAP.describe) expect(text(r)).not.toContain(l);
    expect(currentStep(r.el)).toBe("Describe it"); // STUDIO-4: no steps read, so no way on to step 2
    expect(hasControl(r.el, NEXT_REVIEW)).toBe(false);
  });

  it.each([{ oops: 1 }, { capture_id: "tsk_C1", captured_steps: [] }])(
    "SKILLS_5_live_teach_an_unreadable_201_is_an_error_not_steps_%#",
    async (body) => {
      const r = await rig({ "POST /v1/skills/captures": () => json(body, 201) }).mount();
      await describe_(r);
      expect(r.el.querySelector('[data-testid="skills-teach-error"]')).not.toBeNull();
      expect(hasControl(r.el, NEXT_REVIEW)).toBe(false);
    },
  );

  it("SKILLS_5_live_teach_a_second_try_after_an_error_clears_it", async () => {
    let n = 0;
    const r = await rig({
      "POST /v1/skills/captures": () =>
        ++n === 1 ? json({ detail: "x" }, 502) : json(CAPTURED, 201),
    }).mount();
    await describe_(r);
    expect(r.el.querySelector('[data-testid="skills-teach-error"]')).not.toBeNull();
    clickEl(control(r.el, NEXT_EXAMPLE));
    await settle();
    expect(r.el.querySelector('[data-testid="skills-teach-error"]')).toBeNull();
    expect(text(r)).toContain("Note the total");
  });
});

describe("SKILLS_5_live_teach: Tilo's version (step 2)", () => {
  it("test_FR_SKL_02_S1w_reviews_inputs_hosts_setup_and_unavailable_steps_from_the_version", async () => {
    const expanded = {
      ...VERSION,
      inputs: [{ name: "invoice", label: "Invoice file", kind: "file", required: true }],
      hosts: ["example.com"],
      cannot: [{ text: "Buy the item", reason: "unavailable_action" }],
      needs_setup: [{ tool: "gmail", reason: "not_connected" }],
    };
    const { server, mount } = rig({
      "POST /v1/skills/captures/tsk_C1/version": () => json(expanded),
    });
    const r = await mount();
    await toVersion(r);
    expect(text(r)).toContain("Invoice file");
    expect(text(r)).toContain("example.com");
    expect(text(r)).toContain("Tilo can't do this yet");
    expect(text(r)).toContain("Buy the item");
    expect(text(r)).toContain("Gmail needs setup");
    expect(q(r.el, 'a[href="/connectors"]')).not.toBeNull();
    clickEl(q(r.el, 'button[aria-label="Remove example.com"]'));
    name(r, "Match invoices");
    clickEl(control(r.el, "Save skill"));
    await settle();
    const [body] = server.posts("/v1/skills") as Record<string, unknown>[];
    expect(body?.inputs).toEqual(expanded.inputs);
    expect(body?.hosts).toBeUndefined();
  });

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
    clickEl(control(r.el, NEXT_REVIEW));
    clickEl(control(r.el, NEXT_REVIEW));
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
      "POST /v1/skills/captures/tsk_C1/version": () =>
        json({ ...VERSION, clarifying_question: null }),
    }).mount();
    await toVersion(r);
    expect(text(r)).not.toContain("Link or PDF?");
  });

  it.each([
    [503, NOT_CONNECTED],
    [502, ERR_TRY],
    [422, ERR_TEACH_UNDERSTOOD],
  ])("SKILLS_5_live_teach_version_http_%i_says_so_and_stays_on_step_1", async (status, line) => {
    const r = await rig({
      "POST /v1/skills/captures/tsk_C1/version": () => json({ detail: "x" }, status),
    }).mount();
    await toVersion(r);
    expect(pageText(r.el.querySelector('[data-testid="skills-teach-error"] p') as Element)).toBe(
      line,
    );
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
    // STUDIO-4: Try it once has no route yet, so it is off and says so; nothing pretends to run.
    expect(isDisabled(control(r.el, "Try it once"))).toBe(true);
    expect(text(r)).toContain(TRY_OFF);
    expect(hasControl(r.el, "Save skill")).toBe(true);
  });
});

describe("SKILLS_5_live_teach: save (step 4)", () => {
  it("test_FR_SKL_04_S1w_saves_to_a_current_team_selected_by_its_id", async () => {
    const { server, mount } = rig({
      "GET /v1/teams": () =>
        json({
          teams: [
            { team: "tm_ops", lead: false, state: "member", invited_by: null },
            { team: "tm_old", lead: false, state: "lapsed", invited_by: null },
          ],
          you: "u_me",
        }),
    });
    const r = await mount();
    await toSave(r);
    clickEl(control(r.el, "Share with my team"));
    await settle();
    expect(hasControl(r.el, "Team tm_old")).toBe(false);
    clickEl(control(r.el, "Team tm_ops"));
    name(r, "Match invoices");
    clickEl(control(r.el, "Save skill"));
    await settle();
    const [body] = server.posts("/v1/skills") as { scope: unknown }[];
    expect(body?.scope).toEqual({ kind: "team", team: "tm_ops" });
  });

  it("SKILLS_5_live_teach_save_offers_just_me_and_when_I_ask_only", async () => {
    const r = await rig().mount();
    const chips = () => qa(teachCard(r.el), "fieldset button").map((e) => pageText(e));
    expect(chips()).toEqual(["When I ask"]); // STUDIO-4: when it runs is asked on step 1
    await toSave(r);
    expect(hasControl(r.el, "Save skill")).toBe(true);
    expect(chips()).toEqual(["Just me", "Share with my team"]); // team choices load only on request
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
    expect(text(r)).toContain("“Match invoices” is now a skill");
    clickEl(control(r.el, "View in skills")); // STUDIO-4: back to the gallery, its sheet open
    const sheet = q(r.el, '[role="dialog"]');
    const lib = pageText(sheet);
    expect(lib).toContain("Match invoices");
    expect(lib).toMatch(/Learning/);
    const runs = qa(sheet, "*").find((e) => pageText(e) === "Runs");
    expect(pageText(runs?.nextElementSibling as Element)).toBe("—");
  });

  it.each([
    // X-APIERR-2 (dcaff4b8): a known refusal code gets its own plain sentence; an unknown word keeps the generic one.
    ["unknown_action", "Couldn’t save “Match invoices”. This action is not available here."],
    [
      "ask_first_required",
      "Couldn’t save “Match invoices”. Ask for approval before making this change.",
    ],
    [
      "some words the server made up",
      "Couldn’t save “Match invoices”. Check the information and try again.",
    ],
  ])(
    "SKILLS_5_live_teach_a_422_%s_says_Couldnt_save_and_nothing_is_saved",
    async (detail, toast) => {
      const r = await rig({ "POST /v1/skills": () => json({ detail }, 422) }).mount();
      await toSave(r);
      name(r, "Match invoices");
      clickEl(control(r.el, "Save skill"));
      await settle();
      expect(toasts(r.app)).toEqual([[toast]]);
      expect(text(r)).not.toContain("is now a skill");
      expect(hasControl(r.el, "Save skill")).toBe(true);
    },
  );

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
    expect(toasts(r.app)).toEqual([
      ["Couldn’t save “Match invoices”. We could not confirm it. Reload before trying again."],
    ]);
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

it.each(["capture", "version", "save"])(
  "NFR22 Skills %s failure reserves space and Retry only refreshes reads",
  async (action) => {
    const path =
      action === "capture"
        ? "/v1/skills/captures"
        : action === "version"
          ? "/v1/skills/captures/tsk_C1/version"
          : "/v1/skills";
    const { server, mount } = rig({
      [`POST ${path}`]: () => json({ detail: "rate_limited" }, 429),
    });
    const r = await mount();
    const before = r.el.querySelector<HTMLElement>("[data-skills-action-state]");
    expect(before?.style.blockSize).toBe("176px");
    if (action === "capture") await describe_(r);
    if (action === "version") await toVersion(r);
    if (action === "save") {
      await toSave(r);
      name(r, "Match invoices");
      clickEl(control(r.el, "Save skill"));
      await settle();
    }
    const box = r.el.querySelector<HTMLElement>("[data-skills-action-state]");
    expect(box?.style.blockSize).toBe("176px");
    expect(box?.textContent).toContain("Too many requests. Wait a moment and try again.");
    const posts = server.posts(path).length;
    const reads = server.fetch.mock.calls.filter((c) => c[1]?.method !== "POST").length;
    clickEl(control(box as HTMLElement, "Retry"));
    await settle();
    expect(server.posts(path)).toHaveLength(posts);
    expect(server.fetch.mock.calls.filter((c) => c[1]?.method !== "POST").length).toBeGreaterThan(
      reads,
    );
    expect(text(r)).not.toContain("is now a skill");
    expect(r.el.querySelector("[role=alert]")).toBeNull();
  },
);
