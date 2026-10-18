// @vitest-environment happy-dom
// FT-SUP-2: visible streamed steps during Home prepareRun
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, q } from "../../../../test-support/park/componentsHarness";
import { MODES } from "../../../../test-support/park/homeCopy";
import {
  clickEl,
  control,
  hasControl,
  settle as settleOnce,
  taskInput,
  typeInto,
} from "../../../../test-support/park/homeHarness";
import { type LiveRig, mountLiveHome } from "../../../../test-support/park/liveHomeHarness";
import { BRIEF_SUPPLIER_COMPARISON } from "../../../api/fixtures/brief";
import { createLiveApi } from "../../api/liveApi";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

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

describe("FT-SUP-2 visible streamed steps on Home", () => {
  it("shows visible streamed step immediately upon Start click, then confirms", async () => {
    let resolveIntake!: (res: Response) => void;
    const intakePromise = new Promise<Response>((done) => {
      resolveIntake = done;
    });

    const fetchSpy = vi.fn(async (url: string | URL | Request, init?: RequestInit) => {
      const path = String(url).replace(BASE, "");
      const key = `${init?.method ?? "GET"} ${path}`;
      if (key === "POST /intake") {
        return intakePromise;
      }
      if (key === "GET /tasks/t_1/approaches") {
        return json({
          task_id: "t_1",
          approaches: [APPROACH],
          recommended: "a_balanced",
          credit_usd: 0.05,
        });
      }
      if (path.startsWith("/worlds")) return json({ worlds: [], next_cursor: null });
      if (path.startsWith("/cards")) return json({ cards: [], next_cursor: null });
      return json({ detail: "Not Found" }, 404);
    });

    const api = createLiveApi({ baseUrl: BASE, fetch: fetchSpy as unknown as typeof fetch });
    const rig = await mountLiveHome(api);

    typeInto(taskInput(rig.el), "Research AI competitors");
    const label = MODES.map((m) => m.start).find((l) => hasControl(rig.el, l)) ?? "";
    clickEl(control(rig.el, label));

    // First answer within 0 s: immediate visual progress feedback
    await settleOnce();
    const draftingEl = rig.el.querySelector(".park-home-drafting__text");
    expect(draftingEl).not.toBeNull();
    expect(draftingEl?.textContent).toBe("Reading your task...");

    // Resolve intake
    resolveIntake(
      json({
        task_id: "t_1",
        brief: BRIEF_SUPPLIER_COMPARISON,
        questions: [],
        files: [],
      }),
    );
    await settle();

    // Confirm card is shown
    expect(rig.el.querySelector('[data-testid="run-card"]')).not.toBeNull();
  });
});
