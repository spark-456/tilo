// @vitest-environment happy-dom
// SEC-16 lifetime cap, the kept flow screens (user request, 8 Oct 2026; not in the PRD;
// services/api/tests/API_SPEND_FEEDBACK.md). Where intake errors surface in the old app is the seam every flow call
// goes through (see replayOnly.NFR-22.test.tsx): `useAction` (S-01 "start the task", S-02, S-03 writes) rendered by
// `Primary`, and `useRemote` (S-02, S-03 loads) rendered by `Loaded`, both in FlowShell.tsx. When the call fails with
// the lifetime cap (`isLifetimeCap`: 403 `spend_cap_reached`) the shared `LifetimeCapDialog` replaces the generic
// error, in the same slot; its feedback box sends through `TiloClient.submitFeedback`. Every other failure keeps
// today's message, banner and retry, and shows no dialog.
import { act } from "react";
import { type Root, createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  CAP_BODY,
  COPY,
  SERVER_CAP_SENTENCE,
  areaIn,
  buttonNamed,
  clickButton,
  dialogIn,
  gate,
  nameOf,
  squash,
  typeFeedback,
} from "../../test-support/lifetimeCap";
import { ClientProvider } from "../api/ClientProvider";
import type { TiloClient } from "../api/client";
import { FixtureClient } from "../api/fixtureClient";
import { HttpClient } from "../api/http";
import { FlowShell, Primary } from "./FlowShell";
import { PRESS_MS, useAction } from "./remote";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLElement;
let root: Root;
beforeEach(() => {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});
afterEach(() => {
  act(() => root.unmount());
  container.remove();
  document.body.innerHTML = "";
  vi.restoreAllMocks();
});

const settle = (ms = PRESS_MS + 40) =>
  act(async () => void (await new Promise((r) => setTimeout(r, ms))));
async function until(done: () => boolean) {
  for (let i = 0; i < 60 && !done(); i++) await settle(50);
}

function httpAnswering(status: number, body: unknown): HttpClient {
  const fetchFn = (async () =>
    new Response(JSON.stringify(body), {
      status,
      headers: { "content-type": "application/json" },
    })) as typeof fetch;
  return new HttpClient({ baseUrl: "http://api.test", fetch: fetchFn });
}
async function rejectionOf(call: Promise<unknown>): Promise<unknown> {
  try {
    await call;
  } catch (error) {
    return error;
  }
  throw new Error("the call should have failed");
}

type Feedback = (text: string) => Promise<void>;
/** The fixture client with a spied `submitFeedback` (the method is the builder's to add to TiloClient). */
function clientWith(over: Record<string, unknown> = {}) {
  const submitFeedback = vi.fn<Feedback>(async () => undefined);
  const client = Object.assign(
    new FixtureClient(),
    { submitFeedback },
    over,
  ) as unknown as TiloClient;
  return { client, submitFeedback };
}

function Start({ http }: { http: HttpClient }) {
  const action = useAction("start the task", () =>
    http.submitIntake("Prepare the weekly summary.", []).then(() => "/x"),
  );
  return <Primary label="Start task" action={action} />;
}
async function startWith(http: HttpClient, client: TiloClient) {
  await act(async () =>
    root.render(
      <ClientProvider client={client}>
        <Start http={http} />
      </ClientProvider>,
    ),
  );
  await act(async () => container.querySelector<HTMLButtonElement>("button.primary")?.click());
  await settle();
}
const startButton = () => container.querySelector<HTMLButtonElement>("button.primary");
const dialog = () => dialogIn(container);

describe("SEC-16 the start path: a lifetime cap opens the dialog instead of the generic error", () => {
  it("SEC_16_FEEDBACK an intake refused at the lifetime cap shows the dialog with the user's three sentences", async () => {
    await startWith(httpAnswering(403, CAP_BODY), clientWith().client);

    const el = dialog();
    expect(el, "role=dialog").not.toBeNull();
    expect(nameOf(el as HTMLElement)).toBe(COPY.title);
    const text = squash(el?.textContent);
    expect(text).toContain(COPY.allowance);
    expect(text).toContain(COPY.later);
    expect(text).toContain(COPY.ask);
  });

  it("SEC_16_FEEDBACK the dialog replaces the generic error: no alert, no 'Could not start', no server sentence", async () => {
    await startWith(httpAnswering(403, CAP_BODY), clientWith().client);

    expect(container.querySelector('[role="alert"]')).toBeNull();
    expect(container.textContent).not.toContain("Could not start the task");
    expect(container.textContent).not.toContain("We could not confirm it");
    expect(container.textContent).not.toContain(SERVER_CAP_SENTENCE);
    expect(container.querySelector('[data-testid="replay-banner"]')).toBeNull();
  });

  it("SEC_16_FEEDBACK after the dialog the Start button is usable again (no stuck busy)", async () => {
    await startWith(httpAnswering(403, CAP_BODY), clientWith().client);
    expect(startButton()?.disabled).toBe(false);
    expect(startButton()?.getAttribute("aria-busy")).toBeNull();
  });

  it("SEC_16_FEEDBACK Close hides the dialog; starting again at the cap shows it again", async () => {
    await startWith(httpAnswering(403, CAP_BODY), clientWith().client);

    clickButton(buttonNamed(container, COPY.close) as HTMLElement);
    expect(dialog(), "closed").toBeNull();

    await act(async () => startButton()?.click());
    await settle();
    expect(dialog(), "the cap is still the cap").not.toBeNull();
  });
});

describe("SEC-16 the dialog's feedback goes through the client, and Thanks waits for the server", () => {
  it("SEC_16_FEEDBACK Send calls TiloClient.submitFeedback once with the text; Thanks only after it resolves", async () => {
    const reply = gate<void>();
    const { client, submitFeedback } = clientWith();
    submitFeedback.mockImplementation(() => reply.promise);
    await startWith(httpAnswering(403, CAP_BODY), client);

    typeFeedback(areaIn(container) as HTMLTextAreaElement, "The approval step was hard to find.");
    clickButton(buttonNamed(container, COPY.send) as HTMLElement);
    await settle(0);

    expect(submitFeedback).toHaveBeenCalledTimes(1);
    expect(submitFeedback).toHaveBeenCalledWith("The approval step was hard to find.");
    expect(container.textContent).not.toMatch(/thanks/i);

    await act(async () => reply.resolve());
    await settle(0);
    expect(squash(container.textContent)).toContain(COPY.thanks);
  });

  it("SEC_16_FEEDBACK a failed send (4xx, 5xx or network) shows the error, no Thanks, and keeps the text", async () => {
    const { client, submitFeedback } = clientWith();
    submitFeedback.mockRejectedValue(new Error("boom"));
    await startWith(httpAnswering(403, CAP_BODY), client);

    typeFeedback(areaIn(container) as HTMLTextAreaElement, "Keep these words");
    clickButton(buttonNamed(container, COPY.send) as HTMLElement);
    await settle(0);

    expect(container.textContent).not.toMatch(/thanks/i);
    expect(squash(container.querySelector('[role="alert"]')?.textContent)).toBe(COPY.failed);
    expect(areaIn(container)?.value).toBe("Keep these words");
  });
});

describe("SEC-16 every other failure keeps today's behaviour and shows no dialog", () => {
  it.each([
    [
      "a visitor's 403 under_construction",
      403,
      { detail: "Tilo is still under construction.", code: "under_construction" },
    ],
    [
      "an undeclared 403 declaration_required",
      403,
      { detail: "Tell Tilo who you are.", code: "declaration_required" },
    ],
    ["a role 403 with no code", 403, { detail: "Forbidden" }],
    ["a 429 rate limit", 429, { detail: "Too many requests.", code: "rate_limited" }],
    ["a 409", 409, { detail: "That cannot be done right now." }],
    ["a 500", 500, { detail: "boom" }],
  ])("SEC_16_FEEDBACK %s: the generic error, no dialog", async (_name, status, body) => {
    await startWith(httpAnswering(status, body), clientWith().client);

    expect(dialog()).toBeNull();
    expect(container.querySelector('[role="alert"]'), "today's alert").not.toBeNull();
    expect(container.textContent).toMatch(/start the task/i);
  });

  it("SEC_16_FEEDBACK the daily replay-only 503 shows the replay banner, never the dialog", async () => {
    await startWith(
      httpAnswering(503, { detail: "replay-only right now", replay_only: true }),
      clientWith().client,
    );

    expect(dialog()).toBeNull();
    expect(container.querySelector('[data-testid="replay-banner"]')).not.toBeNull();
  });
});

describe("SEC-16 the approaches screen (S-03) shows the dialog at the lifetime cap", () => {
  async function openApproaches(failure: unknown) {
    const getApproaches = vi.fn(async () => {
      throw failure;
    });
    const { client, submitFeedback } = clientWith({ getApproaches });
    window.history.pushState({}, "", "/task/t1/approaches");
    await act(async () => {
      root.render(
        <ClientProvider client={client}>
          <FlowShell />
        </ClientProvider>,
      );
      window.dispatchEvent(new PopStateEvent("popstate"));
    });
    return { getApproaches, submitFeedback };
  }

  it("SEC_16_FEEDBACK GET /tasks/{id}/approaches refused at the cap: the dialog, not 'Could not load the approaches'", async () => {
    const failure = await rejectionOf(httpAnswering(403, CAP_BODY).getApproaches("t1"));
    await openApproaches(failure);
    await until(() => dialog() !== null);

    expect(dialog(), "S-03 mounts the dialog").not.toBeNull();
    expect(container.textContent).not.toContain("Could not load the approaches");
    expect(container.textContent).not.toContain(SERVER_CAP_SENTENCE);
    expect(squash(dialog()?.textContent)).toContain(COPY.later);
  });

  it("SEC_16_FEEDBACK the dialog on S-03 sends feedback through the client too", async () => {
    const failure = await rejectionOf(httpAnswering(403, CAP_BODY).getApproaches("t1"));
    const { submitFeedback } = await openApproaches(failure);
    await until(() => dialog() !== null);

    typeFeedback(areaIn(container) as HTMLTextAreaElement, "Clear screen, slow model.");
    clickButton(buttonNamed(container, COPY.send) as HTMLElement);
    await settle(0);

    expect(submitFeedback).toHaveBeenCalledWith("Clear screen, slow model.");
    expect(squash(container.textContent)).toContain(COPY.thanks);
  });

  it("SEC_16_FEEDBACK any other approaches failure keeps its message and its Try again, with no dialog", async () => {
    const failure = await rejectionOf(httpAnswering(500, { detail: "boom" }).getApproaches("t1"));
    await openApproaches(failure);
    await until(() => container.querySelector('[role="alert"]') !== null);

    expect(dialog()).toBeNull();
    expect(container.querySelector('[role="alert"]')?.textContent).toContain(
      "Could not load the approaches",
    );
    expect(buttonNamed(container, "Try again")).not.toBeNull();
  });
});
