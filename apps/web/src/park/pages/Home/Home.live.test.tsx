// @vitest-environment happy-dom
// FR-UX-13 acceptance (docs/prd-supplement-design-2026-10-06.md section 1.6, row FR-UX-13: "Home extras. City
// map pins and the composer's quick, routine and workspace flow." Done when: "Starting work adds the world and
// toasts with Open."), on the LIVE path: the composer's confirm control (README "Home": idle -> drafting ->
// plan -> start; starting calls addWorld and toasts with Open) goes to the server, and a world is added only
// after the server's successful reply (HR-1: nothing is shown as started before that; PRD 9.4).
//
// The page is mounted with the real store inside ParkProvider and an injected Api whose results say
// source "live" (the same switch WIRE-3's `decide` uses). Errors are the shared TiloApiError of src/api/http.ts.
// Where it is shown (page text or toast) is the builder's choice: `said()` reads both.
//
// Defaults taken (BQ rows at the end of docs/open-questions.md):
//   - the POST is made when the person confirms the plan ("Start now" / "Schedule it" / "Draft the city"),
//     because the existing composer starts nothing before that (Home.composer.test.tsx); the first tap on the
//     start control only drafts the plan card.
//   - the 401 test uses a fake Api that throws TiloApiError(401); no auth code is involved.
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, press } from "../../../../test-support/park/componentsHarness";
import { MODES } from "../../../../test-support/park/homeCopy";
import { clickEl, settle, taskInput } from "../../../../test-support/park/homeHarness";
import {
  type LiveRig,
  confirm,
  confirmButton,
  gate,
  hasConfirm,
  liveAck,
  liveSourced,
  mountLiveHome,
  notices,
  opened,
  pickSize,
  said,
  serverWorld,
  showsPending,
  toPlan,
} from "../../../../test-support/park/liveHomeHarness";
import { TiloApiError } from "../../../api/http";
import type { Api } from "../../api/index";
import { NotBuilt } from "../../api/liveApi";
import type { TierKey, World } from "../../api/types";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

type Start = ReturnType<typeof vi.fn<(mode: TierKey, query: string) => Promise<unknown>>>;
const withStart = (startWorld: Start): Api => liveSourced({ startWorld } as Partial<Api>);
const worldsSeen = (rig: LiveRig): World[] => {
  const calls = (rig.api.getWorlds as unknown as { mock?: { calls: unknown[][] } }).mock?.calls;
  return (calls?.at(-1)?.[1] as World[] | undefined) ?? [];
};
const spyWorlds = (api: Api): Api => ({ ...api, getWorlds: vi.fn(api.getWorlds) });

describe("FR_UX_13 live composer: a world is added only after the server's reply", () => {
  it.each(MODES)(
    "FR_UX_13 live composer: $label sends one start with its size and the trimmed text, adds nothing until the reply, then adds the world and toasts with Open",
    async (mode) => {
      const reply = gate<unknown>();
      const startWorld: Start = vi.fn(() => reply.promise);
      const rig = await mountLiveHome(spyWorlds(withStart(startWorld)));
      await pickSize(rig, mode.label);
      await toPlan(rig, "  Plan the offsite  ");
      expect(startWorld, "nothing is sent before the person confirms").not.toHaveBeenCalled();

      await confirm(rig);
      expect(startWorld).toHaveBeenCalledTimes(1);
      expect(startWorld).toHaveBeenCalledWith(mode.key, "Plan the offsite");
      // The request is on its way and nothing is shown as started (HR-1).
      expect(rig.store.getState().added, "no world before the reply").toHaveLength(0);
      expect(rig.store.getState().toast, "no toast before the reply").toBeNull();
      expect(worldsSeen(rig)).toHaveLength(0);
      expect(showsPending(rig), "the start control shows it is waiting").toBe(true);

      const world = serverWorld(mode.key, "Plan the offsite", "t_abc123");
      reply.resolve(liveAck(world));
      await settle();

      const state = rig.store.getState();
      expect(state.added.map((w) => w.id)).toEqual(["t_abc123"]);
      // SIMPLE-RUN-1: the old Understanding screen is retired, so the toast offers no Open to it.
      expect(state.toast?.actionLabel).toBeUndefined();
      expect(state.toast?.message ?? "").toContain(world.short);
      expect(
        worldsSeen(rig).map((w) => w.id),
        "the worlds list gets it",
      ).toContain("t_abc123");
      expect(taskInput(rig.el).value, "the brief is cleared once started").toBe("");
      expect(hasConfirm(rig), "the plan card closes").toBe(false);

      expect(startWorld).toHaveBeenCalledTimes(1);
    },
  );

  it("FR_UX_13 live composer: a second tap, the Enter key or a repeat confirm while the first is in flight sends nothing more", async () => {
    const reply = gate<unknown>();
    const startWorld: Start = vi.fn(() => reply.promise);
    const rig = await mountLiveHome(withStart(startWorld));
    await toPlan(rig, "Compare three suppliers");
    const button = confirmButton(rig);
    clickEl(button);
    clickEl(button);
    clickEl(button);
    press(taskInput(rig.el), "Enter");
    await settle();
    expect(startWorld, "one POST for one decision to start").toHaveBeenCalledTimes(1);
    expect(rig.store.getState().added, "still nothing started while it waits").toHaveLength(0);
    reply.resolve(liveAck(serverWorld("quick", "Compare three suppliers", "t_one")));
    await settle();
    expect(rig.store.getState().added).toHaveLength(1);
    expect(startWorld).toHaveBeenCalledTimes(1);
  });
});

describe("FR_UX_13 live composer: honest error states (HR rules, PRD 9.4)", () => {
  async function failWith(error: unknown, text = "Compare three suppliers") {
    const startWorld: Start = vi.fn(() => Promise.reject(error));
    const rig = await mountLiveHome(spyWorlds(withStart(startWorld)));
    await toPlan(rig, text);
    await confirm(rig);
    return { rig, startWorld, text };
  }
  const nothingStarted = (rig: LiveRig) => {
    expect(rig.store.getState().added, "no world is added").toHaveLength(0);
    expect(worldsSeen(rig)).toHaveLength(0);
    expect(rig.store.getState().toast?.actionLabel, "no Open for work that did not start").not.toBe(
      "Open",
    );
    expect(said(rig)).not.toMatch(/Started|Starting now/);
  };

  it("FR_UX_13 live composer: not signed in (TiloApiError 401) asks the person to sign in, adds no world and keeps the text", async () => {
    const { rig, text } = await failWith(
      new TiloApiError("You need to sign in to do this.", 401, false, true),
    );
    nothingStarted(rig);
    expect(said(rig)).toMatch(/sign in/i);
    expect(taskInput(rig.el).value, "what was typed stays").toBe(text);
  });

  it("FR_UX_13 live composer: the API not configured says so in one honest sentence, adds no world and keeps the text", async () => {
    const { rig, text } = await failWith(new NotBuilt("startWorld"));
    nothingStarted(rig);
    const words = said(rig);
    expect(words).toMatch(/not connected|not available|isn.t connected|can.?t be started/i);
    expect(words, "no method name or error class on screen").not.toMatch(
      /NotBuilt|not_built|startWorld/,
    );
    expect(taskInput(rig.el).value).toBe(text);
  });

  it.each([
    ["a 5xx", new TiloApiError("Tilo had a problem on its side.", 503, true, true)],
    [
      "a network failure",
      new TiloApiError(
        "Tilo could not be reached. Check your connection and try again.",
        null,
        true,
        true,
      ),
    ],
    [
      "an intake limit (the server's own short sentence)",
      new TiloApiError("The task text is over the 4,000 character limit.", 422, false, true),
    ],
  ])(
    "FR_UX_13 live composer: %s shows the server's sentence, adds no world and keeps the text",
    async (_name, error) => {
      const { rig, text } = await failWith(error);
      nothingStarted(rig);
      expect(said(rig)).toContain(error.message);
      expect(taskInput(rig.el).value).toBe(text);
    },
  );

  it("FR_UX_13 live composer: an error that is not the server's gets a plain fallback, never its own text", async () => {
    const { rig, text } = await failWith(new Error("ECONNREFUSED 10.0.0.7:8080 secret-4471"));
    nothingStarted(rig);
    expect(said(rig)).not.toMatch(/ECONNREFUSED|10\.0\.0\.7|secret-4471/);
    expect(notices(rig).join(" ").trim().length, "a short sentence is announced").toBeGreaterThan(
      10,
    );
    expect(taskInput(rig.el).value).toBe(text);
  });

  it("FR_UX_13 live composer: after a failure the card stays open and the person can try again, once", async () => {
    const first = gate<unknown>();
    const second = gate<unknown>();
    const replies = [first, second];
    const startWorld: Start = vi.fn(() => (replies.shift() as ReturnType<typeof gate>).promise);
    const rig = await mountLiveHome(withStart(startWorld));
    await toPlan(rig, "Compare three suppliers");
    await confirm(rig);
    first.reject(new TiloApiError("Tilo had a problem on its side.", 503, true, true));
    await settle();
    expect(rig.store.getState().added).toHaveLength(0);
    expect(showsPending(rig), "not stuck waiting after a failure").toBe(false);
    expect(hasConfirm(rig), "the plan card stays open").toBe(true);

    await confirm(rig);
    expect(startWorld, "a new tap is a new attempt").toHaveBeenCalledTimes(2);
    second.resolve(liveAck(serverWorld("quick", "Compare three suppliers", "t_retry")));
    await settle();
    expect(rig.store.getState().added.map((w) => w.id)).toEqual(["t_retry"]);
  });
});

describe("FR_UX_13 fixture path is unchanged", () => {
  it("FR_UX_13 fixture path: with no live Api the world is added and the toast offers Open at once, without waiting for the Api", async () => {
    const { fakeApi } = await import("../../../../test-support/park/appHarness");
    const api = fakeApi();
    api.startWorld.mockImplementation(() => new Promise(() => undefined)); // never replies
    const rig = await mountLiveHome(api);
    await toPlan(rig, "Compare three suppliers");
    await confirm(rig);
    const state = rig.store.getState();
    expect(state.added).toHaveLength(1);
    expect(state.toast?.actionLabel).toBe("Open");
    expect(api.startWorld).toHaveBeenCalledWith("quick", "Compare three suppliers");
    expect(taskInput(rig.el).value).toBe("");
  });
});
