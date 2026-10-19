// @vitest-environment happy-dom
// SEC-16 lifetime cap, the Park app (user request, 8 Oct 2026; not in the PRD; services/api/tests/API_SPEND_FEEDBACK.md).
// Park Home's live composer starts a world through `store.startWorld` (FR-UX-13): the Api's `startWorld` rejects with the
// shared TiloApiError. When that is the lifetime cap (`isLifetimeCap`: 403 `spend_cap_reached`) the shell shows the shared
// `LifetimeCapDialog` (src/components) instead of a toast with the server's sentence; `store.startWorld` still resolves
// false, so the composer keeps the person's text and adds nothing (HR-1). Every other failure keeps its toast and shows
// no dialog (per-run and daily limits have their own honest messages and never the lifetime code).
//
// The dialog's feedback box sends through the Park `Api`: a new method `submitFeedback(text): R<Ack>` in API_METHODS
// (live: `HttpClient.submitFeedback`, fixture: a call that is not a server confirmation). "Thanks" appears only when the
// Api answered with source "live" (HR-1: a fixture answer is not the server confirming); a rejection or any other source
// shows the error and keeps the text.
import { act } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  CAP_BODY,
  COPY,
  SERVER_CAP_SENTENCE,
  areaIn,
  buttonNamed,
  clickButton,
  dialogIn,
  flush,
  gate,
  nameOf,
  squash,
  typeFeedback,
} from "../../../test-support/lifetimeCap";
import { cleanup } from "../../../test-support/park/componentsHarness";
import { taskInput } from "../../../test-support/park/homeHarness";
import {
  confirm,
  hasConfirm,
  liveSourced,
  mountLiveHome,
  showsPending,
  toPlan,
} from "../../../test-support/park/liveHomeHarness";
import { liveApi, mountApp, seen } from "../../../test-support/park/shellHarness";
import { TiloApiError } from "../../api/http";
import type { Api } from "../api/index";

vi.mock("../engines/park", async () =>
  (await import("../../../test-support/park/shellEngine")).parkMock(),
);

afterEach(() => {
  cleanup();
  window.history.pushState({}, "", "/");
  vi.restoreAllMocks();
});

const capError = () => new TiloApiError(CAP_BODY.detail, 403, false, true, "spend_cap_reached");
type Send = (text: string) => Promise<unknown>;

function apiWith(startWorld: () => Promise<unknown>, submitFeedback?: Send): Api {
  const feedback =
    submitFeedback ?? vi.fn<Send>(async () => ({ data: { ok: true }, source: "live" }));
  return { ...liveApi(), startWorld, submitFeedback: feedback } as unknown as Api;
}

async function start(api: Api): Promise<boolean> {
  await mountApp({ api });
  let ok = true;
  await act(async () => {
    ok = await seen.store.startWorld("quick", "Plan the offsite");
  });
  await flush();
  return ok;
}
const dialog = () => dialogIn(document.body);
const toastText = () => seen.store.getState().toast?.message ?? "";

describe("SEC-16 Park: the lifetime cap opens the dialog", () => {
  it("SEC_16_FEEDBACK a start refused at the lifetime cap shows the dialog with the user's three sentences", async () => {
    const ok = await start(apiWith(() => Promise.reject(capError())));

    expect(ok, "nothing was started").toBe(false);
    const el = dialog();
    expect(el, "role=dialog").not.toBeNull();
    expect(nameOf(el as HTMLElement)).toBe(COPY.title);
    const text = squash(el?.textContent);
    expect(text).toContain(COPY.allowance);
    expect(text).toContain(COPY.later);
    expect(text).toContain(COPY.ask);
  });

  it("SEC_16_FEEDBACK the dialog replaces the toast: the server's sentence is shown nowhere, and no world is added", async () => {
    await start(apiWith(() => Promise.reject(capError())));

    expect(toastText()).not.toContain(SERVER_CAP_SENTENCE);
    expect(toastText()).toBe("");
    expect(squash(document.body.textContent)).not.toContain(SERVER_CAP_SENTENCE);
    expect(seen.store.getState().added).toHaveLength(0);
  });

  it("SEC_16_FEEDBACK Close hides it; the next start at the cap shows it again", async () => {
    await start(apiWith(() => Promise.reject(capError())));

    clickButton(buttonNamed(document.body, COPY.close) as HTMLElement);
    expect(dialog(), "closed").toBeNull();

    await act(async () => {
      await seen.store.startWorld("quick", "Plan the offsite");
    });
    await flush();
    expect(dialog(), "the cap is still the cap").not.toBeNull();
  });

  it.each([
    ["a 401", new TiloApiError("You need to sign in to do this.", 401, false, true)],
    [
      "a visitor's 403",
      new TiloApiError("Not open to the public.", 403, false, true, "under_construction"),
    ],
    [
      "a role 403 with no code",
      new TiloApiError("You do not have access to this.", 403, false, true),
    ],
    [
      "the daily replay-only 503",
      new TiloApiError("Live models are unavailable right now.", 503, false, true, null, true),
    ],
    ["a rate limit", new TiloApiError("Too many requests.", 429, false, true, "rate_limited")],
    ["a 5xx", new TiloApiError("Tilo had a problem on its side.", 500, true, true)],
    ["an error that is not the server's", new Error("ECONNREFUSED 10.0.0.7")],
  ])("SEC_16_FEEDBACK %s keeps its toast and shows no dialog", async (_name, error) => {
    const ok = await start(apiWith(() => Promise.reject(error)));

    expect(ok).toBe(false);
    expect(dialog()).toBeNull();
    expect(toastText().length, "a short sentence is said").toBeGreaterThan(10);
  });
});

describe("SEC-16 Park: feedback goes through the Api and Thanks waits for the server", () => {
  async function openWith(send: Send) {
    await start(apiWith(() => Promise.reject(capError()), send));
    typeFeedback(
      areaIn(document.body) as HTMLTextAreaElement,
      "More guidance on the first run, please.",
    );
  }
  const sendIt = async () => {
    clickButton(buttonNamed(document.body, COPY.send) as HTMLElement);
    await flush();
  };

  it("SEC_16_FEEDBACK Send calls Api.submitFeedback once with the text; no Thanks until the live answer", async () => {
    const reply = gate<unknown>();
    const send = vi.fn<Send>(() => reply.promise);
    await openWith(send);

    await sendIt();
    expect(send).toHaveBeenCalledTimes(1);
    expect(send).toHaveBeenCalledWith("More guidance on the first run, please.");
    expect(document.body.textContent).not.toMatch(/thanks/i);

    await act(async () => reply.resolve({ data: { ok: true }, source: "live" }));
    await flush();
    expect(squash(document.body.textContent)).toContain(COPY.thanks);
  });

  it("SEC_16_FEEDBACK an answer whose source is not live is not a server confirmation: error, no Thanks", async () => {
    await openWith(async () => ({ data: { ok: true }, source: "fixture" }));

    await sendIt();

    expect(document.body.textContent).not.toMatch(/thanks/i);
    expect(squash(document.body.querySelector('[role="alert"]')?.textContent)).toBe(COPY.failed);
    expect(areaIn(document.body)?.value).toBe("More guidance on the first run, please.");
  });

  it.each([
    ["a 422", new TiloApiError("Write a few words first.", 422, false, true)],
    ["a 429", new TiloApiError("Too much feedback.", 429, false, true, "rate_limited")],
    ["a 5xx", new TiloApiError("Tilo had a problem on its side.", 500, true, true)],
    ["a network failure", new TiloApiError("Tilo could not be reached.", null, true, true)],
  ])(
    "SEC_16_FEEDBACK %s: error shown, no Thanks, text kept, a second tap sends again",
    async (_n, failure) => {
      const send = vi.fn<Send>().mockRejectedValueOnce(failure);
      send.mockResolvedValue({ data: { ok: true }, source: "live" });
      await openWith(send);

      await sendIt();
      expect(document.body.textContent).not.toMatch(/thanks/i);
      expect(squash(document.body.querySelector('[role="alert"]')?.textContent)).toBe(COPY.failed);
      expect(areaIn(document.body)?.value).toBe("More guidance on the first run, please.");

      await sendIt();
      expect(send).toHaveBeenCalledTimes(2);
      expect(squash(document.body.textContent)).toContain(COPY.thanks);
    },
  );

  it("SEC_16_FEEDBACK a double tap while the request is in flight sends once", async () => {
    const reply = gate<unknown>();
    const send = vi.fn<Send>(() => reply.promise);
    await openWith(send);
    const button = buttonNamed(document.body, COPY.send) as HTMLElement;

    clickButton(button);
    clickButton(button);
    await flush();

    expect(send).toHaveBeenCalledTimes(1);
    await act(async () => reply.resolve({ data: { ok: true }, source: "live" }));
    await flush();
  });
});

describe("SEC-16 Park Home: the composer is left as it was", () => {
  it("SEC_16_FEEDBACK a start refused at the cap adds no world, offers no Open, keeps the text and the plan card, and stops waiting", async () => {
    const startWorld = vi.fn(() => Promise.reject(capError()));
    const rig = await mountLiveHome(liveSourced({ startWorld } as Partial<Api>));
    await toPlan(rig, "Compare three suppliers");

    await confirm(rig);

    expect(startWorld).toHaveBeenCalledTimes(1);
    expect(rig.store.getState().added, "no world is added").toHaveLength(0);
    expect(rig.store.getState().toast?.actionLabel, "no Open for work that did not start").not.toBe(
      "Open",
    );
    expect(taskInput(rig.el).value, "what was typed stays").toBe("Compare three suppliers");
    expect(hasConfirm(rig), "the plan card stays open").toBe(true);
    expect(showsPending(rig), "no stuck waiting state").toBe(false);
  });
});
