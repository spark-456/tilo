// @vitest-environment happy-dom
// FR-UX-13 acceptance, end to end inside the browser-less page: Home mounted over the REAL live Api
// (`createLiveApi` with a fake fetch standing in for tilo-api). Starting work makes the real intake call
// (POST /intake, the legacy S-01's call), and on the server's reply the world is added, the toast offers Open
// and the person lands on the one confirm card (SIMPLE-RUN-1); the old Understanding screen is gone.
//
// The live Api serves the worlds, cards and costs reads today; the user, today and agenda reads are still
// NotBuilt. The composer has to be usable all the same: starting work needs none of them (BQ rows at the end
// of docs/open-questions.md). Where "Open" goes is the builder's choice between the Park world page and the
// task's understanding screen; either way it carries the server's id.
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, mount, press, q } from "../../../../test-support/park/componentsHarness";
import { MODES } from "../../../../test-support/park/homeCopy";
import {
  clickEl,
  control,
  hasControl,
  settle,
  taskInput,
  typeInto,
} from "../../../../test-support/park/homeHarness";
import {
  gate,
  mountLiveHome,
  notices,
  opened,
  pickSize,
  said,
  showsPending,
} from "../../../../test-support/park/liveHomeHarness";
import { BRIEF_SUPPLIER_COMPARISON } from "../../../api/fixtures/brief";
import type { Api } from "../../api/index";
import { createLiveApi } from "../../api/liveApi";
import { carryOneStep } from "../../api/oneStep";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const BASE = "https://api.example.test";
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
const INTAKE = { task_id: "t_abc123", brief: BRIEF_SUPPLIER_COMPARISON, questions: [], files: [] };

/** SIMPLE-RUN-1: Start on a live Thinking task goes straight to the one POST /intake. */
async function startTask(rig: Awaited<ReturnType<typeof mountLiveHome>>, text: string) {
  typeInto(taskInput(rig.el), text);
  clickEl(control(rig.el, MODES.map((m) => m.start).find((l) => hasControl(rig.el, l)) ?? ""));
  await settle();
}

function serverWith(intake: () => Response | Promise<Response>) {
  const fetchSpy = vi.fn(async (url: string | URL | Request, init?: RequestInit) => {
    const path = String(url).replace(BASE, "");
    if (init?.method === "POST" && path === "/intake") return intake();
    if (init?.method === "POST" && path === "/tasks/t_abc123/answers")
      return json({ brief: BRIEF_SUPPLIER_COMPARISON });
    if (path === "/tasks/t_abc123/approaches")
      return json({
        task_id: "t_abc123",
        approaches: [
          {
            id: "a1",
            label: "Balanced",
            summary: "s",
            dimensions: {
              depth: "standard",
              sources: "web",
              parallelism: "single",
              verification: "light",
              output_format: "document",
            },
            time: { min_s: 60, max_s: 120 },
            credits: { min: 4, max: 9 },
            risks: [],
            skips: [],
          },
        ],
        recommended: "a1",
        credit_usd: 0.05,
      });
    if (path.startsWith("/worlds")) return json({ worlds: [], next_cursor: null });
    if (path.startsWith("/cards")) return json({ cards: [], next_cursor: null });
    return json({ detail: "Not Found" }, 404);
  });
  const live = createLiveApi({ baseUrl: BASE, fetch: fetchSpy as unknown as typeof fetch });
  // a spread drops the one-step start (it travels by identity), so it is carried over explicitly
  const api: Api = carryOneStep(live, { ...live, getWorlds: vi.fn(live.getWorlds) });
  const intakes = () =>
    fetchSpy.mock.calls.filter(
      ([url, init]) => init?.method === "POST" && String(url).endsWith("/intake"),
    );
  return { api, fetchSpy, intakes };
}

describe("FR_UX_13 live composer over the real live Api", () => {
  it("FR_UX_13 live composer: a configured deployment shows the composer although the user, today and agenda reads are not built yet", async () => {
    const { api } = serverWith(() => json(INTAKE));
    const rig = await mountLiveHome(api);
    expect(q(rig.el, 'input[aria-label="Describe your task"]')).not.toBeNull();
  });

  it.each(MODES)(
    "FR_UX_13 live composer: $label posts the brief to /intake once and shows the one confirm card only after the reply (SIMPLE-RUN-1)",
    async (mode) => {
      const reply = gate<Response>();
      const { api, intakes } = serverWith(() => reply.promise);
      const rig = await mountLiveHome(api);
      await pickSize(rig, mode.label);
      typeInto(taskInput(rig.el), "  Compare three suppliers  ");
      clickEl(control(rig.el, MODES.find((m) => m.key === mode.key)?.start ?? mode.start));
      await settle();

      expect(intakes(), "one POST /intake").toHaveLength(1);
      const body = intakes()[0]?.[1]?.body as FormData;
      expect(body.get("text")).toBe("Compare three suppliers");
      expect(rig.store.getState().added, "nothing is started before the reply").toHaveLength(0);
      expect(rig.store.getState().toast).toBeNull();
      expect(
        rig.el.querySelector('[data-testid="run-card"]'),
        "no card before the reply",
      ).toBeNull();

      reply.resolve(json(INTAKE));
      for (let i = 0; i < 4; i++) await settle();
      expect(
        rig.el.querySelector('[data-testid="run-card"]'),
        "the one confirm card",
      ).not.toBeNull();
      expect(rig.navigate.mock.calls.some((c) => /understanding/.test(String(c[0])))).toBe(false);
    },
  );

  it("FR_UX_13 live composer: three taps and Enter while the POST is in flight send exactly one request", async () => {
    const reply = gate<Response>();
    const { api, intakes } = serverWith(() => reply.promise);
    const rig = await mountLiveHome(api);
    typeInto(taskInput(rig.el), "Compare three suppliers");
    const start = control(
      rig.el,
      MODES.map((m) => m.start).find((l) => hasControl(rig.el, l)) ?? "",
    );
    clickEl(start);
    clickEl(start);
    clickEl(start);
    press(taskInput(rig.el), "Enter");
    await settle();
    expect(intakes()).toHaveLength(1);
    reply.resolve(json(INTAKE));
    for (let i = 0; i < 4; i++) await settle();
    expect(intakes()).toHaveLength(1);
  });

  it("FR_UX_13 live composer: not signed in (401 from /intake) asks to sign in, adds no world, keeps the text and sends one POST", async () => {
    const { api, intakes } = serverWith(() => json({ detail: "Unauthorized" }, 401));
    const rig = await mountLiveHome(api);
    await startTask(rig, "Compare three suppliers");
    expect(said(rig)).toMatch(/sign in/i);
    expect(notices(rig).join(" ")).toMatch(/sign in/i);
    expect(rig.store.getState().added).toHaveLength(0);
    expect(rig.store.getState().toast?.actionLabel).not.toBe("Open");
    expect(taskInput(rig.el).value).toBe("Compare three suppliers");
    expect(intakes(), "a write is never retried by itself").toHaveLength(1);
  });

  it.each([
    ["a 5xx", () => json({ detail: "boom" }, 503), "Tilo had a problem on its side."],
    [
      "an intake limit",
      () => json({ error: "The task text is over the 4,000 character limit." }, 422),
      "The task text is over the 4,000 character limit.",
    ],
    [
      "a network failure",
      () => {
        throw new TypeError("connect ECONNREFUSED 10.0.0.7:8080");
      },
      "Tilo could not be reached. Check your connection and try again.",
    ],
  ])(
    "FR_UX_13 live composer: %s from /intake shows the sentence, adds no world, keeps the text and sends one POST",
    async (_name, reply, sentence) => {
      const { api, intakes } = serverWith(reply);
      const rig = await mountLiveHome(api);
      await startTask(rig, "Compare three suppliers");
      expect(said(rig)).toContain(sentence);
      expect(said(rig)).not.toContain("10.0.0.7");
      expect(rig.store.getState().added).toHaveLength(0);
      expect(rig.store.getState().toast?.actionLabel).not.toBe("Open");
      expect(taskInput(rig.el).value).toBe("Compare three suppliers");
      expect(intakes()).toHaveLength(1);
    },
  );
});
