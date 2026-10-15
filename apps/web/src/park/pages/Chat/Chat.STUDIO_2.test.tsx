// @vitest-environment happy-dom
// UI-STUDIO-2 Chat (design/studio-v2 "Tilo S Chat"): a direct question goes to the real Quick answer path once, the
// helper's pose follows the request state only (reading in flight, talking while a new answer shows, done after),
// a fixture answer is labelled a sample, nothing is listed that the server did not keep, and the scene is display
// state that survives blocked storage.
import { act } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fakeScheduler, stubApp } from "../../../../test-support/park/appHarness";
import { fakeApi } from "../../../../test-support/park/appHarness";
import { cleanup, mount, q, qa } from "../../../../test-support/park/componentsHarness";
import { settle, textOf } from "../../../../test-support/park/homeHarness";
import { gate, liveSourced } from "../../../../test-support/park/liveHomeHarness";
import { TiloApiError } from "../../../api/http";
import { SAMPLE_QUICK } from "../../api/fixtureApi";
import type { Api } from "../../api/index";
import type { AppCtx } from "../../app/AppCtx";
import { ParkProvider } from "../../app/context";
import { takeDraft } from "../../chat/handoff";
import { moodOf, talkMs } from "../../chat/useQuickChat";
import { ChatPage } from "./ChatPage";

beforeEach(() => window.localStorage.clear());
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  window.localStorage.clear();
  takeDraft();
});

type Reply = () => Promise<unknown>;
const quickApi = (reply: Reply): Api =>
  liveSourced({
    startWorld: vi.fn(async (_m: string, _q: string, effort?: string) =>
      effort === "quick" ? reply() : Promise.reject(new Error("not quick")),
    ),
  } as unknown as Partial<Api>);
const calls = (api: Api): unknown[][] =>
  (api.startWorld as unknown as { mock: { calls: unknown[][] } }).mock.calls;

async function mountChat(api: Api, over: Partial<AppCtx> = {}) {
  const sch = fakeScheduler();
  const app = stubApp("chat", over);
  const m = mount(
    <ParkProvider
      api={api}
      navigate={vi.fn()}
      schedule={sch.schedule}
      viewport={{ vw: 1440, vh: 900 }}
    >
      <ChatPage app={app} />
    </ParkProvider>,
  );
  await settle();
  return { el: m.container, sch, app };
}

const input = (el: HTMLElement) => q<HTMLInputElement>(el, "input");
const mood = (el: HTMLElement) => q(el, ".park-buddy").getAttribute("data-mood");
const status = (el: HTMLElement) => textOf(q(el, '[role="status"]'));
function type(el: HTMLInputElement, value: string) {
  act(() => {
    const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
    set?.call(el, value);
    el.dispatchEvent(new Event("input", { bubbles: true }));
  });
}
async function send(el: HTMLElement, text: string) {
  type(input(el), text);
  act(() => {
    q<HTMLButtonElement>(el, 'button[aria-label="Send"]').click();
  });
  await settle();
}

describe("STUDIO_2 Chat: the helper's mood follows the real request", () => {
  it("STUDIO_2 chat mood is idle, then reading while the call is out, talking when the answer lands, done after", async () => {
    const reply = gate<unknown>();
    const api = quickApi(() => reply.promise);
    const { el, sch } = await mountChat(api);
    expect(mood(el)).toBe("idle");
    expect(status(el)).toBe("Ready when you are");
    await send(el, "What is the capital of France?");
    expect(calls(api)).toEqual([["quick", "What is the capital of France?", "quick"]]);
    expect(mood(el)).toBe("reading");
    expect(status(el)).toBe("Tilo is reading your question");
    expect(sch.live()).toHaveLength(0); // nothing is timed while the call is out: reading lasts exactly as long
    reply.resolve({
      data: { kind: "answered", text: "Paris.", cost: { credits: 0.02 } },
      source: "live",
    });
    await settle();
    expect(mood(el)).toBe("talking");
    expect(textOf(q(el, '[role="log"]'))).toContain("Paris.");
    expect(textOf(q(el, '[role="log"]'))).toContain("COST 0.02 CREDITS");
    expect(sch.live()).toHaveLength(1);
    expect(sch.live()[0]?.ms).toBe(talkMs("Paris."));
    sch.fire(sch.live()[0]);
    expect(mood(el)).toBe("done");
    expect(textOf(el)).not.toContain("Sample answer");
  });

  it("STUDIO_2 chat a failed ask leaves the helper idle with the reason and no answer", async () => {
    const api = quickApi(() =>
      Promise.reject(new TiloApiError("Too many asks.", 429, false, false)),
    );
    const { el, sch } = await mountChat(api);
    await send(el, "Hello?");
    expect(mood(el)).toBe("idle");
    expect(textOf(q(el, '[role="log"]'))).toMatch(/limited right now/);
    expect(sch.live()).toHaveLength(0);
  });

  it("STUDIO_2 chat a second send while one is out sends nothing more", async () => {
    const reply = gate<unknown>();
    const api = quickApi(() => reply.promise);
    const { el } = await mountChat(api);
    await send(el, "One");
    await send(el, "Two");
    expect(calls(api)).toHaveLength(1);
    expect(input(el).value).toBe("Two"); // kept, not sent
  });

  it("STUDIO_2 chat an empty or over-long question is not sent and says why", async () => {
    const api = quickApi(async () => ({
      data: { kind: "answered", text: "x", cost: null },
      source: "live",
    }));
    const { el } = await mountChat(api);
    await send(el, "   ");
    expect(textOf(q(el, '[role="alert"]'))).toBe("Type your question first.");
    await send(el, "a".repeat(501));
    expect(textOf(q(el, '[role="alert"]'))).toMatch(/up to 500 characters; this one is 501/);
    expect(calls(api)).toHaveLength(0);
  });

  it("STUDIO_2 chat moodOf is a pure reading of the last turn", () => {
    expect(moodOf(undefined, null)).toBe("idle");
    expect(moodOf({ id: 1, question: "q", state: "asking" }, null)).toBe("reading");
    const a = {
      id: 2,
      question: "q",
      state: "answered",
      text: "t",
      cost: null,
      sample: false,
      seconds: 1,
    } as const;
    expect(moodOf(a, 2)).toBe("talking");
    expect(moodOf(a, null)).toBe("done");
    expect(moodOf({ id: 3, question: "q", state: "error", message: "m" }, 3)).toBe("idle");
  });
});

describe("STUDIO_2 Chat: honest data", () => {
  it("STUDIO_2 chat on the fixture Api the answer is labelled a sample and shows no cost", async () => {
    const { el } = await mountChat(fakeApi());
    await send(el, "Anything");
    const log = textOf(q(el, '[role="log"]'));
    expect(log).toContain(SAMPLE_QUICK);
    expect(log).toContain("Sample answer");
    expect(log).not.toMatch(/credit/i);
  });

  it("STUDIO_2 chat starts empty with no listed past chats", async () => {
    const { el } = await mountChat(fakeApi());
    expect(qa(el, ".park-chat-pair")).toHaveLength(0);
    expect(textOf(q(el, '[role="log"]'))).toContain("Past chats are not kept");
    expect(qa(el, "h1")).toHaveLength(1);
    expect(qa(el, "main")).toHaveLength(0);
  });

  it("STUDIO_2 chat Make it a world hands the question to Home without the address", async () => {
    const api = quickApi(async () => ({
      data: { kind: "answered", text: "Pack light.", cost: null },
      source: "live",
    }));
    const go = vi.fn();
    const { el } = await mountChat(api, { go });
    await send(el, "Plan a road trip to Gokarna");
    act(() => {
      (
        qa<HTMLButtonElement>(el, "button").find(
          (b) => textOf(b) === "Make it a world →",
        ) as HTMLButtonElement
      ).click();
    });
    expect(go).toHaveBeenCalledWith("home");
    expect(takeDraft()).toBe("Plan a road trip to Gokarna");
    expect(window.location.search).not.toContain("Gokarna");
  });

  it("STUDIO_2 chat a switch offer says why in words and offers Make it a world", async () => {
    const api = quickApi(async () => ({
      data: { kind: "switch", reason: "side_effect" },
      source: "live",
    }));
    const { el } = await mountChat(api);
    await send(el, "Email my suppliers");
    expect(textOf(q(el, '[role="log"]'))).toContain("This needs a world.");
    expect(mood(el)).toBe("idle");
  });
});

describe("STUDIO_2 Chat: the scene is display state", () => {
  it("STUDIO_2 chat the chosen scene is remembered and a blocked storage falls back to the office", async () => {
    const { el } = await mountChat(fakeApi());
    const beach = qa(el, '[role="radio"]').find((r) => textOf(r) === "Beach") as HTMLElement;
    act(() => beach.click());
    expect(window.localStorage.getItem("tilo.chat.scene")).toBe("beach");
    expect(q(el, 'section[aria-label="Your helper"]').className).toContain(
      "park-chat-scene--beach",
    );
    cleanup();
    vi.spyOn(window, "localStorage", "get").mockImplementation(() => {
      throw new Error("blocked");
    });
    const again = await mountChat(fakeApi());
    expect(q(again.el, 'section[aria-label="Your helper"]').className).toContain(
      "park-chat-scene--office",
    );
  });
});
