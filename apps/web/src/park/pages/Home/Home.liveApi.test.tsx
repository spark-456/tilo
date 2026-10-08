// @vitest-environment happy-dom
// FR-UX-13 acceptance, end to end inside the browser-less page: Home mounted over the REAL live Api
// (`createLiveApi` with a fake fetch standing in for tilo-api). Starting work makes the real intake call
// (POST /intake, the legacy S-01's call), and on the server's reply the world is added, the toast offers Open
// and the legacy `/task/:id/understanding` screen has the brief to show (`rememberIntake`).
//
// The live Api serves the worlds, cards and costs reads today; the user, today and agenda reads are still
// NotBuilt. The composer has to be usable all the same: starting work needs none of them (BQ rows at the end
// of docs/open-questions.md). Where "Open" goes is the builder's choice between the Park world page and the
// task's understanding screen; either way it carries the server's id.
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, mount, press, q } from "../../../../test-support/park/componentsHarness";
import { MODES } from "../../../../test-support/park/homeCopy";
import { clickEl, settle, taskInput } from "../../../../test-support/park/homeHarness";
import {
  confirm,
  confirmButton,
  gate,
  mountLiveHome,
  notices,
  opened,
  pickSize,
  said,
  showsPending,
  toPlan,
} from "../../../../test-support/park/liveHomeHarness";
import { ClientProvider } from "../../../api/ClientProvider";
import { FixtureClient } from "../../../api/fixtureClient";
import { BRIEF_SUPPLIER_COMPARISON } from "../../../api/fixtures/brief";
import { Understanding } from "../../../screens/s02/Understanding";
import type { Api } from "../../api/index";
import { createLiveApi } from "../../api/liveApi";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const BASE = "https://api.example.test";
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
const INTAKE = { task_id: "t_abc123", brief: BRIEF_SUPPLIER_COMPARISON, questions: [], files: [] };

function serverWith(intake: () => Response | Promise<Response>) {
  const fetchSpy = vi.fn(async (url: string | URL | Request, init?: RequestInit) => {
    const path = String(url).replace(BASE, "");
    if (init?.method === "POST" && path === "/intake") return intake();
    if (path.startsWith("/worlds")) return json({ worlds: [], next_cursor: null });
    if (path.startsWith("/cards")) return json({ cards: [], next_cursor: null });
    return json({ detail: "Not Found" }, 404);
  });
  const live = createLiveApi({ baseUrl: BASE, fetch: fetchSpy as unknown as typeof fetch });
  const api: Api = { ...live, getWorlds: vi.fn(live.getWorlds) };
  const intakes = () => fetchSpy.mock.calls.filter(([, init]) => init?.method === "POST");
  return { api, fetchSpy, intakes };
}

describe("FR_UX_13 live composer over the real live Api", () => {
  it("FR_UX_13 live composer: a configured deployment shows the composer although the user, today and agenda reads are not built yet", async () => {
    const { api } = serverWith(() => json(INTAKE));
    const rig = await mountLiveHome(api);
    expect(q(rig.el, 'input[aria-label="Describe your task"]')).not.toBeNull();
  });

  it.each(MODES)(
    "FR_UX_13 live composer: $label posts the brief to /intake once, then adds the world, toasts with Open and hands the brief to S-02",
    async (mode) => {
      const reply = gate<Response>();
      const { api, intakes } = serverWith(() => reply.promise);
      const rig = await mountLiveHome(api);
      await pickSize(rig, mode.label);
      await toPlan(rig, "  Compare three suppliers  ");
      await confirm(rig);

      expect(intakes(), "one POST /intake").toHaveLength(1);
      const body = intakes()[0]?.[1]?.body as FormData;
      expect(body.get("text")).toBe("Compare three suppliers");
      expect(rig.store.getState().added, "nothing is started before the reply").toHaveLength(0);
      expect(rig.store.getState().toast).toBeNull();
      expect(showsPending(rig)).toBe(true);

      reply.resolve(json(INTAKE));
      await settle();
      const state = rig.store.getState();
      expect(state.added.map((w) => w.id)).toEqual(["t_abc123"]);
      expect(state.toast?.actionLabel).toBe("Open");
      const lastWorlds = (
        api.getWorlds as unknown as { mock: { calls: unknown[][] } }
      ).mock.calls.at(-1);
      expect((lastWorlds?.[1] as { id: string }[]).map((w) => w.id)).toContain("t_abc123");

      state.toast?.action?.();
      await settle();
      expect(opened(rig, "t_abc123")).toBe(true);

      // The kept S-02 screen shows the brief the server made, as it does after the legacy S-01.
      const s02 = mount(
        <ClientProvider client={new FixtureClient()}>
          <Understanding taskId="t_abc123" />
        </ClientProvider>,
      );
      expect(s02.container.querySelector('[data-testid="brief-chips"]')).not.toBeNull();
      const goal = s02.container.querySelector<HTMLInputElement>("#brief-goal");
      expect(goal?.value).toBe(BRIEF_SUPPLIER_COMPARISON.goal);
    },
  );

  it("FR_UX_13 live composer: three taps, Enter and a repeat confirm while the POST is in flight send exactly one request", async () => {
    const reply = gate<Response>();
    const { api, intakes } = serverWith(() => reply.promise);
    const rig = await mountLiveHome(api);
    await toPlan(rig, "Compare three suppliers");
    const button = confirmButton(rig);
    clickEl(button);
    clickEl(button);
    clickEl(button);
    press(taskInput(rig.el), "Enter");
    await settle();
    expect(intakes()).toHaveLength(1);
    reply.resolve(json(INTAKE));
    await settle();
    expect(intakes()).toHaveLength(1);
    expect(rig.store.getState().added).toHaveLength(1);
  });

  it("FR_UX_13 live composer: not signed in (401 from /intake) asks to sign in, adds no world, keeps the text and sends one POST", async () => {
    const { api, intakes } = serverWith(() => json({ detail: "Unauthorized" }, 401));
    const rig = await mountLiveHome(api);
    await toPlan(rig, "Compare three suppliers");
    await confirm(rig);
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
      await toPlan(rig, "Compare three suppliers");
      await confirm(rig);
      expect(said(rig)).toContain(sentence);
      expect(said(rig)).not.toContain("10.0.0.7");
      expect(rig.store.getState().added).toHaveLength(0);
      expect(rig.store.getState().toast?.actionLabel).not.toBe("Open");
      expect(taskInput(rig.el).value).toBe("Compare three suppliers");
      expect(intakes()).toHaveLength(1);
    },
  );
});
