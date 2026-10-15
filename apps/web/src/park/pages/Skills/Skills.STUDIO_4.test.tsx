// @vitest-environment happy-dom
// STUDIO-4 Skills (design/studio-v2 "Tilo S Skills", Canvas section 06): the gallery reads the real routes, the
// 3-step Teach wizard (each step a still building going up) posts captures, version and save in that order, "Try it
// once" stays honestly off, Learning now lists what is learning, and a live pause posts the state route and shows
// only what the server answered. Driven through the real live Api and HttpClient over a stubbed fetch.
import { act } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { stubApp } from "../../../../test-support/park/appHarness";
import {
  type Mounted,
  cleanup,
  mount,
  q,
  qa,
} from "../../../../test-support/park/componentsHarness";
import {
  NEXT_EXAMPLE,
  NEXT_REVIEW,
  START,
  clickEl,
  control,
  currentStep,
  isDisabled,
  mountSkills,
  openSkill,
  pageText,
  settle,
  skillsApi,
  typeInto,
} from "../../../../test-support/park/skillsHarness";
import { HttpClient } from "../../../api/http";
import { createLiveApi } from "../../api/liveApi";
import { ParkProvider } from "../../app/context";
import { SkillsPage } from "./SkillsPage";
import { TRY_OFF } from "./TeachWizard";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const BASE = "https://api.example.test";
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

const STEP = {
  text: "Read the invoice mail",
  tool: "gmail",
  action: "read_email",
  verb: "read",
  ask_first: false,
  must_ask: false,
};
const ROW = (over: Record<string, unknown> = {}) => ({
  id: "tsk_L1",
  name: "Match invoices",
  scope: { kind: "just_me", team: null },
  status: "learning",
  paused: false,
  plan: [STEP],
  question: null,
  version: 1,
  ...over,
});

function server(extra: Record<string, (init: RequestInit) => Response> = {}) {
  const table: Record<string, (init: RequestInit) => Response> = {
    "GET /v1/skills?include_builtin=true": () =>
      json({
        skills: [ROW()],
        builtins: [{ id: "web-research", version: "1.0.0", description: "Research." }],
      }),
    "GET /v1/learn?include_builtin=true": () => json({ learning: [ROW()], needs_rating: [] }),
    "POST /v1/skills/captures": () =>
      json({ capture_id: "tsk_C1", captured_steps: [{ text: "Open the mail" }] }, 201),
    "POST /v1/skills/captures/tsk_C1/version": () =>
      json({
        capture_id: "tsk_C1",
        plan_steps: [STEP],
        clarifying_question: null,
        estimates: null,
      }),
    "POST /v1/skills": () => json(ROW({ id: "tsk_N1", name: "Log invoices" }), 201),
    ...extra,
  };
  const fetchSpy = vi.fn(async (url: unknown, init?: RequestInit) => {
    const key = `${init?.method ?? "GET"} ${String(url).replace(BASE, "")}`;
    const hit = table[key];
    if (!hit) throw new Error(`unrouted ${key}`);
    return hit(init ?? {});
  });
  const calls = () =>
    fetchSpy.mock.calls.map((c) => `${c[1]?.method ?? "GET"} ${String(c[0]).replace(BASE, "")}`);
  return { fetch: fetchSpy as unknown as typeof fetch, calls, spy: fetchSpy };
}

async function mountLive(s: ReturnType<typeof server>, withClient = true) {
  const live = createLiveApi({ baseUrl: BASE, fetch: s.fetch });
  // The skills calls are the live Api's; the person and the ledger stay the sample's (no route for them here).
  const api = skillsApi({
    getSkills: live.getSkills,
    getLearn: live.getLearn,
    captureSkill: live.captureSkill,
    proposeVersion: live.proposeVersion,
    saveSkill: live.saveSkill,
  });
  const client = withClient ? new HttpClient({ baseUrl: BASE, fetch: s.fetch }) : null;
  const app = stubApp("skills");
  const m: Mounted = mount(
    <ParkProvider
      api={api}
      worldClient={client}
      schedule={() => () => undefined}
      viewport={{ vw: 1440, vh: 900 }}
    >
      <SkillsPage app={app} />
    </ParkProvider>,
  );
  await settle();
  return { m, el: m.container, app };
}

describe("STUDIO_4 Skills gallery", () => {
  it("STUDIO_4_skills_gallery_reads_the_real_routes_and_shows_the_banner_cards_and_learning_now", async () => {
    const s = server();
    const { el } = await mountLive(s);
    expect(s.calls()).toEqual(
      expect.arrayContaining([
        "GET /v1/skills?include_builtin=true",
        "GET /v1/learn?include_builtin=true",
      ]),
    );
    expect(q(el, 'section[aria-label="Teach Tilo a skill"]')).toBeTruthy();
    const gallery = pageText(q(el, 'section[aria-label="All skills"]'));
    expect(gallery).toContain("Web Research");
    expect(gallery).toContain("Match invoices");
    expect(gallery).toContain("No runs recorded"); // the server serves no run count: none is made up
    const learning = pageText(q(el, 'section[aria-label="Learning now"]'));
    expect(learning).toContain("Match invoices");
    expect(learning).toContain("No practice runs recorded yet.");
    expect(qa(el, ".park-btn--primary")).toHaveLength(1); // UX-1
  });

  it("STUDIO_4_skills_a_live_pause_posts_the_state_route_and_shows_the_servers_answer", async () => {
    const s = server({ "POST /v1/skills/tsk_L1/state": () => json(ROW({ paused: true })) });
    const { el, app } = await mountLive(s);
    const sheet = openSkill(el, "Match invoices");
    clickEl(control(sheet, "Pause"));
    await settle();
    const [post] = s.spy.mock.calls.filter((c) => String(c[0]).endsWith("/state"));
    expect(JSON.parse(String(post?.[1]?.body))).toEqual({ change: "paused" });
    expect(pageText(q(el, '[role="dialog"]'))).toContain("Paused");
    expect(control(q(el, '[role="dialog"]'), "Resume")).toBeTruthy();
    expect((app.toast as unknown as ReturnType<typeof vi.fn>).mock.calls).toContainEqual([
      "“Match invoices” is paused.",
    ]);
  });

  it("STUDIO_4_skills_a_refused_pause_changes_nothing_and_says_so", async () => {
    const s = server({ "POST /v1/skills/tsk_L1/state": () => json({ detail: "not_found" }, 404) });
    const { el, app } = await mountLive(s);
    const sheet = openSkill(el, "Match invoices");
    clickEl(control(sheet, "Pause"));
    await settle();
    expect(control(q(el, '[role="dialog"]'), "Pause")).toBeTruthy();
    const toasts = (app.toast as unknown as ReturnType<typeof vi.fn>).mock.calls.map((c) =>
      String(c[0]),
    );
    expect(toasts.some((t) => t.startsWith("Couldn’t pause “Match invoices”."))).toBe(true);
  });

  it("STUDIO_4_skills_the_sheet_closes_on_Escape", async () => {
    const { el } = await mountSkills();
    openSkill(el, "Match invoices to purchase orders");
    act(() => {
      document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
    });
    await settle();
    expect(el.querySelector('[role="dialog"]')).toBeNull();
  });
});

describe("STUDIO_4 Teach wizard", () => {
  it("STUDIO_4_wizard_steps_call_the_real_routes_in_order_and_each_step_is_a_still_building", async () => {
    const s = server();
    const { el } = await mountLive(s);
    clickEl(control(el, START));
    const strip = q(el, 'ol[aria-label="Steps"]');
    expect(qa(strip, "li")).toHaveLength(3);
    expect(qa(strip, "li img")).toHaveLength(3); // one still building per step
    expect(currentStep(el)).toBe("Describe it");

    typeInto(
      q<HTMLTextAreaElement>(el, '[data-testid="skills-teach"] textarea'),
      "Log each invoice",
    );
    clickEl(control(el, NEXT_EXAMPLE));
    await settle();
    expect(currentStep(el)).toBe("Show an example");
    expect(pageText(el)).toContain("Open the mail");

    clickEl(control(el, NEXT_REVIEW));
    await settle();
    expect(currentStep(el)).toBe("Review the steps");
    expect(pageText(el)).toContain(STEP.text);

    typeInto(q<HTMLInputElement>(el, '[data-testid="skills-teach"] input'), "Log invoices");
    clickEl(control(el, "Save skill"));
    await settle();
    expect(s.calls().filter((c) => c.startsWith("POST"))).toEqual([
      "POST /v1/skills/captures",
      "POST /v1/skills/captures/tsk_C1/version",
      "POST /v1/skills",
    ]);
    expect(pageText(el)).toContain("“Log invoices” is now a skill");
  });

  it("STUDIO_4_wizard_try_it_once_is_disabled_and_says_not_available_yet", async () => {
    const s = server();
    const { el } = await mountLive(s);
    clickEl(control(el, START));
    typeInto(
      q<HTMLTextAreaElement>(el, '[data-testid="skills-teach"] textarea'),
      "Log each invoice",
    );
    clickEl(control(el, NEXT_EXAMPLE));
    await settle();
    clickEl(control(el, NEXT_REVIEW));
    await settle();
    const tryIt = control(el, "Try it once");
    expect(isDisabled(tryIt)).toBe(true);
    expect(pageText(el)).toContain(TRY_OFF);
    clickEl(tryIt);
    await settle();
    expect(s.calls().filter((c) => c.includes("run"))).toEqual([]);
  });

  it("STUDIO_4_wizard_has_one_primary_button_on_every_step_and_back_to_skills_returns_to_the_gallery", async () => {
    const { el } = await mountSkills();
    clickEl(control(el, START));
    for (const next of [NEXT_EXAMPLE, NEXT_REVIEW]) {
      expect(qa(el, ".park-btn--primary")).toHaveLength(1);
      clickEl(control(el, next));
    }
    expect(qa(el, ".park-btn--primary")).toHaveLength(1);
    expect(qa(el, "h1").map((h) => pageText(h))).toEqual(["Teach Tilo a skill"]);
    clickEl(control(el, "← Back to skills"));
    expect(qa(el, "h1").map((h) => pageText(h))).toEqual(["Skills"]);
  });
});
