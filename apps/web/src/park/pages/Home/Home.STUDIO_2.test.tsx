// @vitest-environment happy-dom
// UI-STUDIO-2 Home (design/studio-v2 "Tilo S Home"): one ask box whose switch picks Quick answer (the real Quick path,
// no world) or Make a world (the intake -> plan -> approve flow), the helper in the box follows the request only,
// Chat history is an honest empty state (the server keeps no Quick answers), and a question handed over from the
// Chat page lands in the box set to Make a world.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, q, qa } from "../../../../test-support/park/componentsHarness";
import {
  clickEl,
  control,
  hasControl,
  mountHome,
  settle,
  spiedApi,
  taskInput,
  textOf,
  typeInto,
} from "../../../../test-support/park/homeHarness";
import { gate, liveSourced, mountLiveHome } from "../../../../test-support/park/liveHomeHarness";
import type { Api } from "../../api/index";
import { handDraft } from "../../chat/handoff";

beforeEach(() => window.localStorage.clear());
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  window.localStorage.clear();
});

const switchOf = (el: HTMLElement) => q(el, '[aria-label="Quick answer or world"]');
const pick = async (el: HTMLElement, label: string) => {
  clickEl(qa(switchOf(el), '[role="radio"]').find((r) => textOf(r) === label) as Element);
  await settle();
};
const helper = (el: HTMLElement) => q(el, ".park-home-panel .park-buddy").getAttribute("data-mood");
const calls = (api: Api): unknown[][] =>
  (api.startWorld as unknown as { mock: { calls: unknown[][] } }).mock.calls;

describe("STUDIO_2 Home: the ask box switch", () => {
  it("STUDIO_2 home switch Make a world is the planned flow with the size behind Options", async () => {
    const rig = await mountHome();
    expect(qa(switchOf(rig.el), '[role="radio"]').map(textOf)).toEqual([
      "Quick answer",
      "Make a world",
    ]);
    expect(hasControl(rig.el, "Start task")).toBe(true);
    expect(rig.el.querySelector("details.park-home-options")).not.toBeNull();
    typeInto(taskInput(rig.el), "Plan the offsite");
    clickEl(control(rig.el, "Start task"));
    await settle();
    for (const t of rig.sch.live().filter((x) => x.ms === 900)) rig.sch.fire(t);
    await settle();
    clickEl(control(rig.el, "Start now"));
    await settle();
    expect(rig.app.addWorld).toHaveBeenCalledWith("quick", "Plan the offsite");
  });

  it("STUDIO_2 home switch Quick answer asks once over Quick, makes no world and hides the size", async () => {
    const api = spiedApi();
    const rig = await mountHome({ api });
    await pick(rig.el, "Quick answer");
    expect(hasControl(rig.el, "Ask")).toBe(true);
    expect(rig.el.querySelector("details.park-home-options")).toBeNull();
    expect(taskInput(rig.el).placeholder).toBe("Ask a quick question");
    typeInto(taskInput(rig.el), "What is the capital of France?");
    clickEl(control(rig.el, "Ask"));
    await settle();
    expect(calls(api)).toEqual([["quick", "What is the capital of France?", "quick"]]);
    expect(rig.app.addWorld).not.toHaveBeenCalled();
    expect(textOf(q(rig.el, '[aria-label="Quick answer"]'))).toContain("Sample answer");
  });

  it("STUDIO_2 home the helper in the ask box reads while the call is out and is done once answered", async () => {
    const reply = gate<unknown>();
    const api = liveSourced({
      startWorld: vi.fn(async () => reply.promise),
    } as unknown as Partial<Api>);
    const rig = await mountLiveHome(api);
    expect(helper(rig.el)).toBe("idle");
    await pick(rig.el, "Quick answer");
    typeInto(taskInput(rig.el), "Capital of France?");
    clickEl(control(rig.el, "Ask"));
    await settle();
    expect(helper(rig.el)).toBe("reading");
    reply.resolve({ data: { kind: "answered", text: "Paris.", cost: null }, source: "live" });
    await settle();
    expect(helper(rig.el)).toBe("done");
  });
});

describe("STUDIO_2 Home: Chat history is honest", () => {
  it("STUDIO_2 home empty history says nothing is kept, lists no sample chat and links to Chat", async () => {
    const rig = await mountHome();
    const history = q(rig.el, 'section[aria-label="Chat history"]');
    expect(textOf(history)).toContain("No saved chats yet");
    expect(textOf(history)).toContain("not kept");
    expect(textOf(history)).not.toMatch(/Gokarna|Brightcell|hotel/i); // the artboard's sample chats never show
    const link = control(history, "Open chat");
    expect(link.getAttribute("href")).toBe("/chat");
    clickEl(link);
    expect(rig.app.go).toHaveBeenLastCalledWith("chat");
  });

  it("STUDIO_2 home live history is the same honest empty state", async () => {
    const rig = await mountLiveHome(liveSourced());
    expect(textOf(q(rig.el, 'section[aria-label="Chat history"]'))).toContain("No saved chats yet");
  });
});

describe("STUDIO_2 Home: a question handed over from Chat", () => {
  it("STUDIO_2 home a handed question fills the box once, set to Make a world", async () => {
    window.localStorage.clear();
    const first = await mountHome();
    await pick(first.el, "Quick answer");
    cleanup();
    handDraft("Plan a road trip to Gokarna");
    const rig = await mountHome();
    expect(taskInput(rig.el).value).toBe("Plan a road trip to Gokarna");
    const chosen = qa(switchOf(rig.el), '[role="radio"]').find(
      (r) => r.getAttribute("aria-checked") === "true",
    );
    expect(textOf(chosen as Element)).toBe("Make a world");
    cleanup();
    const again = await mountHome();
    expect(taskInput(again.el).value).toBe(""); // once only
  });
});
