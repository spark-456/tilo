// @vitest-environment happy-dom
// QUICK_THINKING (COST-FAST-1; PRD 9.4 honesty): the composer's Quick / Thinking choice. Quick is a direct
// answer (no plan, no world, no event, no agents); Thinking is today's flow, byte for byte. The choice is
// remembered per person in this browser (storage may throw), no number is invented, and a Quick answer on the
// fixture path is plainly a sample. The live reply shapes are services/api/tests/API_COST_FAST_1.md.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  cleanup,
  countPrimary,
  press,
  q,
  qa,
} from "../../../../test-support/park/componentsHarness";
import {
  clickEl,
  control,
  hasControl,
  mountHome,
  pageText,
  settle,
  spiedApi,
  taskInput,
  textOf,
  typeInto,
} from "../../../../test-support/park/homeHarness";
import {
  gate,
  liveAck,
  liveSourced,
  mountLiveHome,
  serverWorld,
} from "../../../../test-support/park/liveHomeHarness";
import { TiloApiError } from "../../../api/http";
import { SAMPLE_QUICK } from "../../api/fixtureApi";
import type { Api } from "../../api/index";
import { QUICK_MAX_CHARS } from "./homeData";

beforeEach(() => {
  window.localStorage.clear();
});
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  window.localStorage.clear();
});

const depth = (root: HTMLElement) => q(root, '[aria-label="Depth"]');
const depthOptions = (root: HTMLElement) => qa(depth(root), '[role="radio"]');
const chosen = (root: HTMLElement): string =>
  textOf(depthOptions(root).find((o) => o.getAttribute("aria-checked") === "true") as Element);
const choose = async (root: HTMLElement, label: string) => {
  clickEl(depthOptions(root).find((o) => textOf(o) === label) as Element);
  await settle();
};
const ask = async (root: HTMLElement, text: string) => {
  typeInto(taskInput(root), text);
  clickEl(control(root, "Ask"));
  await settle();
};
const answerCard = (root: HTMLElement) => root.querySelector('[aria-label="Quick answer"]');
const alertText = (root: HTMLElement): string => qa(root, '[role="alert"]').map(textOf).join(" ");

type Starter = (mode: string, query: string, effort?: string) => Promise<unknown>;
const quickApi = (reply: () => Promise<unknown>, thinking?: Starter): Api =>
  liveSourced({
    startWorld: vi.fn(async (mode: string, query: string, effort?: string) =>
      effort === "quick" ? reply() : (thinking?.(mode, query, effort) ?? reply()),
    ),
  } as unknown as Partial<Api>);
const answered =
  (cost: unknown = null) =>
  async () => ({
    data: { kind: "answered", text: "Paris is the capital of France.", cost },
    source: "live" as const,
  });
const calls = (api: Api): unknown[][] =>
  (api.startWorld as unknown as { mock: { calls: unknown[][] } }).mock.calls;

describe("QUICK_THINKING the control", () => {
  it("QUICK_THINKING_default_is_Thinking_in_a_labelled_radiogroup_with_the_two_words", async () => {
    const { el } = await mountHome();
    expect(depth(el).getAttribute("role")).toBe("radiogroup");
    expect(depthOptions(el).map(textOf)).toEqual(["Quick", "Thinking"]);
    expect(chosen(el)).toBe("Thinking");
    // Thinking is today's flow: the start control and the hint are the size's own.
    expect(hasControl(el, "Start task")).toBe(true);
    expect(pageText(el)).toContain("You see the plan and the cost before any agent starts.");
  });

  it("QUICK_THINKING_keyboard_arrows_move_and_select_and_only_the_selected_item_is_in_the_tab_order", async () => {
    const { el } = await mountHome();
    const [quick, thinking] = depthOptions(el) as [HTMLElement, HTMLElement];
    expect(thinking.tabIndex).toBe(0);
    expect(quick.tabIndex).toBe(-1);
    press(thinking, "ArrowLeft");
    await settle();
    expect(chosen(el)).toBe("Quick");
    press(depthOptions(el)[0] as Element, "ArrowRight");
    await settle();
    expect(chosen(el)).toBe("Thinking");
  });

  it("QUICK_THINKING_words_only_no_number_before_any_answer_and_one_primary_button", async () => {
    const { el } = await mountHome();
    await choose(el, "Quick");
    expect(hasControl(el, "Ask")).toBe(true);
    const composer = q(el, ".park-home-composer");
    expect(textOf(q(composer, ".park-home-hint"))).toBe(
      "A direct answer. No plan is made and no agents start.",
    );
    expect(textOf(composer)).not.toMatch(/[£$₹]|\bpaise\b|\bcredits?\b|\bmin\b/i);
    expect(qa(composer, ".park-home-plan")).toHaveLength(0);
    expect(countPrimary(el)).toBeLessThanOrEqual(1);
  });
});

describe("QUICK_THINKING the choice is remembered", () => {
  it("QUICK_THINKING_persists_across_remounts", async () => {
    const first = await mountHome();
    await choose(first.el, "Quick");
    cleanup();
    const second = await mountHome();
    expect(chosen(second.el)).toBe("Quick");
    expect(hasControl(second.el, "Ask")).toBe(true);
  });

  it("QUICK_THINKING_is_kept_per_signed_in_email_not_shared", async () => {
    const first = await mountHome();
    await choose(first.el, "Quick");
    const keys = Object.keys(window.localStorage).filter((k) => k.includes("effort"));
    expect(keys).toHaveLength(1);
    // LIVE-HOME (BQ-SIGNIN-4): the key is per person but never holds the address itself.
    expect(keys[0]).not.toContain("@");
    expect(keys[0]).not.toMatch(/alex|northwind/i);
  });

  it("QUICK_THINKING_survives_storage_throwing_and_keeps_the_choice_in_memory", async () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    const first = await mountHome();
    expect(chosen(first.el)).toBe("Thinking");
    await choose(first.el, "Quick");
    expect(chosen(first.el)).toBe("Quick");
    cleanup();
    const second = await mountHome();
    expect(chosen(second.el)).toBe("Quick");
  });
});

describe("QUICK_THINKING on the fixture path", () => {
  it("QUICK_THINKING_quick_asks_with_the_effort_makes_no_world_and_shows_a_labelled_sample", async () => {
    const api = spiedApi();
    const rig = await mountHome({ api });
    await choose(rig.el, "Quick");
    await ask(rig.el, "What is the capital of France?");
    const sent = (api.startWorld as unknown as { mock: { calls: unknown[][] } }).mock.calls;
    expect(sent).toEqual([["quick", "What is the capital of France?", "quick"]]);
    expect(rig.app.addWorld).not.toHaveBeenCalled();
    const card = answerCard(rig.el) as Element;
    expect(textOf(card)).toContain(SAMPLE_QUICK);
    expect(textOf(card)).toContain("Sample answer");
    // honest: no plan card, no drafting line, no agents, no cost, no progress
    expect(hasControl(rig.el, "Start now")).toBe(false);
    expect(pageText(rig.el)).not.toMatch(/Tilo is drafting|Director|Agents/);
    expect(textOf(card)).not.toMatch(/credit|£|\d/);
    expect(qa(rig.el, '[role="progressbar"]')).toHaveLength(0);
  });

  it("QUICK_THINKING_thinking_sends_exactly_what_it_sent_before_and_the_plan_card_still_opens", async () => {
    const api = spiedApi();
    const rig = await mountHome({ api });
    typeInto(taskInput(rig.el), "Plan the offsite");
    clickEl(control(rig.el, "Start task"));
    await settle();
    for (const t of rig.sch.live().filter((x) => x.ms === 900)) rig.sch.fire(t);
    await settle();
    clickEl(control(rig.el, "Start now"));
    await settle();
    expect(rig.app.addWorld).toHaveBeenCalledWith("quick", "Plan the offsite");
    expect((api.startWorld as unknown as { mock: { calls: unknown[][] } }).mock.calls).toEqual([]);
  });

  it("QUICK_THINKING_an_empty_question_is_not_sent_and_says_so", async () => {
    const api = spiedApi();
    const rig = await mountHome({ api });
    await choose(rig.el, "Quick");
    clickEl(control(rig.el, "Ask"));
    await settle();
    expect(alertText(rig.el)).toBe("Type your question first.");
    expect((api.startWorld as unknown as { mock: { calls: unknown[][] } }).mock.calls).toEqual([]);
  });

  it("QUICK_THINKING_a_question_over_500_characters_is_refused_in_plain_words_and_never_cut", async () => {
    const api = spiedApi();
    const rig = await mountHome({ api });
    await choose(rig.el, "Quick");
    const long = "a".repeat(QUICK_MAX_CHARS + 1);
    await ask(rig.el, long);
    expect(alertText(rig.el)).toContain("500 characters");
    expect(alertText(rig.el)).toContain("501");
    expect((api.startWorld as unknown as { mock: { calls: unknown[][] } }).mock.calls).toEqual([]);
    expect(taskInput(rig.el).value).toBe(long);
    // exactly 500 is allowed
    typeInto(taskInput(rig.el), "b".repeat(QUICK_MAX_CHARS));
    clickEl(control(rig.el, "Ask"));
    await settle();
    expect((api.startWorld as unknown as { mock: { calls: unknown[][] } }).mock.calls).toHaveLength(
      1,
    );
  });
});

describe("QUICK_THINKING on the live path", () => {
  it("QUICK_THINKING_live_answer_shows_the_served_cost_makes_no_world_and_no_toast", async () => {
    const api = quickApi(answered({ credits: 0.04, savedCredits: 0.3 }));
    const rig = await mountLiveHome(api);
    await choose(rig.el, "Quick");
    await ask(rig.el, "What is the capital of France?");
    expect(calls(api)).toEqual([["quick", "What is the capital of France?", "quick"]]);
    const card = textOf(answerCard(rig.el) as Element);
    expect(card).toContain("Paris is the capital of France.");
    expect(card).toContain("Cost 0.04 credits");
    expect(card).toContain("Saved 0.3 credits");
    expect(card).not.toContain("Sample");
    const state = rig.store.getState();
    expect(state.added).toHaveLength(0);
    expect(state.toast).toBeNull();
  });

  it("QUICK_THINKING_live_answer_without_a_cost_shows_no_cost_and_no_number", async () => {
    const rig = await mountLiveHome(quickApi(answered(null)));
    await choose(rig.el, "Quick");
    await ask(rig.el, "Capital of France?");
    const card = textOf(answerCard(rig.el) as Element);
    expect(card).not.toMatch(/credit|Cost|Saved|\d/);
  });

  it("QUICK_THINKING_asking_shows_a_plain_status_and_locks_the_text_until_the_reply", async () => {
    const reply = gate<unknown>();
    const rig = await mountLiveHome(quickApi(() => reply.promise));
    await choose(rig.el, "Quick");
    await ask(rig.el, "Capital of France?");
    expect(qa(rig.el, '[role="status"]').map(textOf)).toContain("Asking Tilo");
    expect(qa(rig.el, ".park-home-spin")).toHaveLength(0); // nothing animates
    typeInto(taskInput(rig.el), "something else");
    expect(taskInput(rig.el).value).toBe("Capital of France?");
    reply.resolve({
      data: { kind: "answered", text: "Paris.", cost: null },
      source: "live",
    });
    await settle();
    expect(textOf(answerCard(rig.el) as Element)).toContain("Paris.");
  });

  it("QUICK_THINKING_a_switch_offer_gives_the_reason_in_words_and_one_click_resends_as_thinking", async () => {
    const world = serverWorld("quick", "Make a 12 slide deck", "t_sw1");
    const api = quickApi(
      async () => ({ data: { kind: "switch", reason: "deliverable" }, source: "live" }),
      async () => liveAck(world),
    );
    const rig = await mountLiveHome(api);
    await choose(rig.el, "Quick");
    await ask(rig.el, "Make a 12 slide deck");
    const offer = textOf(answerCard(rig.el) as Element);
    expect(offer).toContain("This needs Thinking.");
    expect(offer).toContain("It asks for a document, deck or sheet to be made.");
    expect(offer).not.toContain("deliverable"); // the code is not for people
    expect(rig.store.getState().added).toHaveLength(0);

    clickEl(control(rig.el, "Switch to Thinking"));
    await settle();
    // the same text, as Thinking: the two-argument call of today, no effort
    expect(calls(api)).toEqual([
      ["quick", "Make a 12 slide deck", "quick"],
      ["quick", "Make a 12 slide deck"],
    ]);
    expect(rig.store.getState().added.map((w) => w.id)).toEqual(["t_sw1"]);
    expect(chosen(rig.el)).toBe("Thinking");
    expect(answerCard(rig.el)).toBeNull();
  });

  it.each([
    [429, null, /limited right now/],
    [403, "spend_cap_reached", /spending limit/],
    [503, null, /unavailable right now/],
    [502, null, /problem on its side/],
  ] as const)(
    "QUICK_THINKING_error_%i_is_one_honest_sentence_and_the_typed_text_stays",
    async (status, code, sentence) => {
      const rig = await mountLiveHome(
        quickApi(async () => {
          throw new TiloApiError("raw server text", status, status >= 500, true, code);
        }),
      );
      await choose(rig.el, "Quick");
      await ask(rig.el, "Capital of France?");
      expect(alertText(rig.el)).toMatch(sentence);
      expect(alertText(rig.el)).not.toContain("raw server text");
      expect(taskInput(rig.el).value).toBe("Capital of France?");
      expect(answerCard(rig.el)).toBeNull();
      expect(rig.store.getState().added).toHaveLength(0);
    },
  );

  it("QUICK_THINKING_a_422_shows_the_servers_own_short_sentence", async () => {
    const rig = await mountLiveHome(
      quickApi(async () => {
        throw new TiloApiError("That question was flagged by the safety check.", 422, false, true);
      }),
    );
    await choose(rig.el, "Quick");
    await ask(rig.el, "x");
    expect(alertText(rig.el)).toBe("That question was flagged by the safety check.");
  });
});
