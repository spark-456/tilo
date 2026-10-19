// @vitest-environment happy-dom
// SIMPLE-RUN-1 acceptance: Home mounted over the REAL live Api (fake fetch for tilo-api). Start on a task makes the
// intake, skips every question and lands on ONE confirm card; the person's click on its Start approves the cap and
// opens the run's world. Nothing sends the person to the old Understanding or Approaches screens.
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, q } from "../../../../test-support/park/componentsHarness";
import { MODES } from "../../../../test-support/park/homeCopy";
import {
  clickEl,
  control,
  hasControl,
  pageText,
  settle as settleOnce,
  taskInput,
  typeInto,
} from "../../../../test-support/park/homeHarness";
import {
  type LiveRig,
  gate,
  mountLiveHome,
  opened,
} from "../../../../test-support/park/liveHomeHarness";
import { BRIEF_SUPPLIER_COMPARISON } from "../../../api/fixtures/brief";
import { createLiveApi } from "../../api/liveApi";
import { pendingWorld } from "../../app/PendingWorldRoute";
import { handDraft } from "../../chat/handoff";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

// The one-step start is three chained calls: more ticks than the harness's three.
const settle = async (): Promise<void> => {
  for (let i = 0; i < 4; i++) await settleOnce();
};

const BASE = "https://api.example.test";
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
const APPROACH = {
  id: "a_balanced",
  label: "Balanced",
  summary: "Read the sources, then write.",
  dimensions: {
    depth: "standard",
    sources: "web",
    parallelism: "single",
    verification: "light",
    output_format: "document",
  },
  time: { min_s: 120, max_s: 300 },
  credits: { min: 8, max: 20 },
  risks: [],
  skips: [],
};
const BRIEF = {
  ...BRIEF_SUPPLIER_COMPARISON,
  assumptions: [{ question: "Who is it for?", assumed: "The team" }],
};

function serverWith(over: Record<string, () => Response | Promise<Response>> = {}) {
  const posts: string[] = [];
  const fetchSpy = vi.fn(async (url: string | URL | Request, init?: RequestInit) => {
    const path = String(url).replace(BASE, "");
    const key = `${init?.method ?? "GET"} ${path}`;
    if (init?.method === "POST") posts.push(path);
    if (over[key]) return over[key]();
    if (key === "POST /intake")
      return json({
        task_id: "t_1",
        brief: BRIEF_SUPPLIER_COMPARISON,
        questions: [{ field: "audience", text: "Who is it for?", suggested_answers: ["The team"] }],
        files: [],
      });
    if (key === "POST /tasks/t_1/answers") return json({ brief: BRIEF });
    if (key === "GET /tasks/t_1/approaches")
      return json({
        task_id: "t_1",
        approaches: [APPROACH],
        recommended: "a_balanced",
        credit_usd: 0.05,
      });
    if (key === "POST /tasks/t_1/approve") return json({ world_id: "w_1" });
    if (path.startsWith("/worlds")) return json({ worlds: [], next_cursor: null });
    if (path.startsWith("/cards")) return json({ cards: [], next_cursor: null });
    return json({ detail: "Not Found" }, 404);
  });
  const api = createLiveApi({ baseUrl: BASE, fetch: fetchSpy as unknown as typeof fetch });
  return { api, posts };
}

async function start(rig: LiveRig, text: string): Promise<void> {
  typeInto(taskInput(rig.el), text);
  const label = MODES.map((m) => m.start).find((l) => hasControl(rig.el, l)) ?? "";
  clickEl(control(rig.el, label));
  await settle();
}
const cardOrNull = (rig: LiveRig) => rig.el.querySelector('[data-testid="run-card"]');
const card = (rig: LiveRig) => q(rig.el, '[data-testid="run-card"]');
const cardStart = (rig: LiveRig): HTMLElement => q(card(rig), "button.park-home-confirm");

describe("SIMPLE-RUN-1 Home starts a run in one step", () => {
  it("test_FR_INT_01_run_opens_world_from_a_chat_handoff", async () => {
    const { api, posts } = serverWith();
    handDraft("Plan a road trip to Gokarna");
    const rig = await mountLiveHome(api);
    expect(taskInput(rig.el).value).toBe("Plan a road trip to Gokarna");
    const label = MODES.map((m) => m.start).find((text) => hasControl(rig.el, text)) ?? "";
    clickEl(control(rig.el, label));
    await settle();
    clickEl(cardStart(rig));
    await settle();
    expect(posts.at(-1)).toBe("/tasks/t_1/approve");
    expect(opened(rig, "w_1")).toBe(true);
    expect(pendingWorld("w_1")).toBe(true);
  });

  it("test_FR_INT_01_run_opens_world_after_approval", async () => {
    const { api, posts } = serverWith();
    const rig = await mountLiveHome(api);
    await start(rig, "Plan the offsite");

    expect(posts, "intake, then every question skipped in one call; nothing approved yet").toEqual([
      "/intake",
      "/tasks/t_1/answers",
    ]);
    const text = pageText(card(rig));
    expect(text).toContain(BRIEF_SUPPLIER_COMPARISON.goal);
    expect(text).toContain("Assumed: The team");
    expect(
      text,
      "the 20-credit estimate is shown at the 60-credit floor (BQ-BUDGET-FLOOR-1)",
    ).toMatch(/60 credits/);
    expect(pageText(rig.el)).not.toMatch(/Example only|drafting/i);
    expect(cardStart(rig).textContent).toBe("Start");

    clickEl(cardStart(rig));
    await settle();
    expect(posts.at(-1)).toBe("/tasks/t_1/approve");
    expect(opened(rig, "w_1"), "the run's own world").toBe(true);
    expect(pendingWorld("w_1"), "the world route waits for a recorded plan or start").toBe(true);
    expect(
      rig.navigate.mock.calls.some((c) => /understanding|approaches/.test(String(c[0]))),
      "no navigation to the old screens",
    ).toBe(false);
  });

  it("SIMPLE-RUN-1 Home: a double tap on the card's Start approves once", async () => {
    const approve = gate<Response>();
    const { api, posts } = serverWith({ "POST /tasks/t_1/approve": () => approve.promise });
    const rig = await mountLiveHome(api);
    await start(rig, "Plan the offsite");
    const button = cardStart(rig);
    clickEl(button);
    clickEl(button);
    await settle();
    approve.resolve(json({ world_id: "w_1" }));
    await settle();
    expect(posts.filter((p) => p.endsWith("/approve"))).toHaveLength(1);
  });

  it("SIMPLE-RUN-1 Home: a refusal at approve says why on the card and Try again approves again", async () => {
    let calls = 0;
    const { api, posts } = serverWith({
      "POST /tasks/t_1/approve": () =>
        ++calls === 1
          ? json({ detail: "One run may use at most 300 credits." }, 422)
          : json({ world_id: "w_1" }),
    });
    const rig = await mountLiveHome(api);
    await start(rig, "Plan the offsite");
    clickEl(cardStart(rig));
    await settle();
    expect(pageText(card(rig))).toContain("One run may use at most 300 credits.");
    expect(cardStart(rig).textContent).toBe("Try again");
    clickEl(cardStart(rig));
    await settle();
    expect(posts.filter((p) => p.endsWith("/approve"))).toHaveLength(2);
    expect(opened(rig, "w_1")).toBe(true);
  });

  it("SIMPLE-RUN-1 Home: an intake refusal shows the server's words with one Try again, never the stock sentence", async () => {
    const { api, posts } = serverWith({
      "POST /intake": () => json({ detail: "The Director could not draft a brief." }, 502),
    });
    const rig = await mountLiveHome(api);
    await start(rig, "Plan the offsite");
    const text = pageText(rig.el);
    expect(text).toContain("The Director could not draft a brief.");
    expect(text).not.toContain("could not accept that");
    expect(cardOrNull(rig)).toBeNull();
    expect(taskInput(rig.el).value, "the words stay").toBe("Plan the offsite");
    expect(posts).toEqual(["/intake"]);
  });

  it("SIMPLE-RUN-1 Home: changing an assumed line answers it and prices the plan again", async () => {
    const { api, posts } = serverWith();
    const rig = await mountLiveHome(api);
    await start(rig, "Plan the offsite");
    clickEl(q(card(rig), "button.park-home-run__link"));
    await settle();
    const input = q<HTMLInputElement>(card(rig), "input");
    typeInto(input, "The board");
    clickEl(q(card(rig), 'form button[type="submit"]'));
    await settle();
    expect(posts.slice(-1)).toEqual(["/tasks/t_1/answers"]);
    expect(posts.filter((p) => p.endsWith("/approve"))).toHaveLength(0);
  });
});
