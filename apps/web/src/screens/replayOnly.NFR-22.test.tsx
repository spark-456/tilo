// @vitest-environment happy-dom
// NFR-22 (PRD 17.2), integration at the seam the start path really uses: when intake or approaches reject with the
// replay-only failure (http.NFR-22.test.ts), the flow shows the shared ReplayBanner instead of the generic error.
//
// Seam, not route (BQ-NFR22-3): every flow call goes through `useRemote` (loads: S-02, S-03) and `useAction` (writes:
// S-01 "start the task", S-02, S-03), and renders through `Loaded` and `Primary` (FlowShell.tsx). Those carry a
// `replayOnly` flag next to their message and mount the banner. The intake call itself (S-01 Start, its `useAction`)
// is pinned through `useAction` + `Primary` with a real HttpClient, so these tests do not depend on which path "/"
// serves after the Park cutover. The approaches screen is also pinned whole, at /task/t1/approaches (S-03 survives).
// Park Home's composer is fixture-only today (no live intake call), so no Park test is pinned here; it must mount the
// banner when it is wired live (BQ-NFR22-4).
import { act } from "react";
import { type Root, createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ClientProvider } from "../api/ClientProvider";
import type { TiloClient } from "../api/client";
import { FixtureClient } from "../api/fixtureClient";
import { HttpClient } from "../api/http";
// FlowShell first: StartScreen and FlowShell import each other (as in the other flow tests).
import { FlowShell, Primary } from "./FlowShell";
import { PRESS_MS, useAction, useRemote } from "./remote";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const GENERIC_5XX = "Tilo had a problem on its side.";
const MODEL_UNAVAILABLE_BODY = {
  detail:
    "The model is unavailable right now (quota or outage), so nothing new was started; finished runs can still be replayed.",
  replay_only: true,
  code: "model_unavailable",
};

let container: HTMLElement;
let root: Root;
const q = <T extends Element = HTMLElement>(s: string) => container.querySelector<T>(s);
const settle = (ms = PRESS_MS + 40) =>
  act(async () => void (await new Promise((r) => setTimeout(r, ms))));
/** Lets lazy screens and rejected promises settle: up to ~3 s, until `done` is true. */
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

beforeEach(() => {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});
afterEach(() => {
  act(() => root.unmount());
  container.remove();
  vi.restoreAllMocks();
});

const banner = () => q('[data-testid="replay-banner"]');

describe("NFR-22 useRemote and useAction carry the replay-only flag", () => {
  function RemoteProbe({ load }: { load: () => Promise<unknown> }) {
    const [state] = useRemote("load the approaches", load);
    return <pre data-testid="probe">{JSON.stringify(state)}</pre>;
  }
  const probe = () => JSON.parse(q("[data-testid=probe]")?.textContent ?? "{}");

  it("NFR_22 a replay-only rejection becomes an error state with replayOnly true", async () => {
    const http = httpAnswering(503, MODEL_UNAVAILABLE_BODY);
    await act(async () => root.render(<RemoteProbe load={() => http.getApproaches("t1")} />));
    await until(() => probe().status === "error");
    expect(probe().status).toBe("error");
    expect(probe().replayOnly).toBe(true);
  });

  it("NFR_22 any other rejection keeps its message and is not replay-only", async () => {
    const http = httpAnswering(500, { detail: "boom" });
    await act(async () => root.render(<RemoteProbe load={() => http.getApproaches("t1")} />));
    await until(() => probe().status === "error");
    expect(probe().replayOnly).toBeFalsy();
    expect(probe().message).toBe(
      `Could not load the approaches: ${GENERIC_5XX.replace(/\.$/, "")}. Nothing was changed. You can try again.`,
    );
  });

  function ActionProbe({ run, flag }: { run: () => Promise<string>; flag?: boolean }) {
    const action = useAction("start the task", run) as ReturnType<typeof useAction> & {
      replayOnly?: boolean;
    };
    return (
      <>
        {flag && <i data-testid="flag">{String(action.replayOnly)}</i>}
        <Primary label="Start task" action={action} />
      </>
    );
  }
  const press = async () => {
    await act(async () => q<HTMLButtonElement>("button.primary")?.click());
    await settle();
  };

  it("NFR_22 start path: an intake that fails replay-only sets action.replayOnly and shows the banner, not the generic error", async () => {
    const http = httpAnswering(503, MODEL_UNAVAILABLE_BODY);
    await act(async () =>
      root.render(
        <ActionProbe
          flag
          run={() => http.submitIntake("Prepare the weekly summary.", []).then(() => "/x")}
        />,
      ),
    );
    await press();
    expect(q("[data-testid=flag]")?.textContent).toBe("true");
    const el = banner();
    expect(el, "the banner replaces the generic error").not.toBeNull();
    expect(el?.textContent).toMatch(/live models are unavailable/i);
    expect(container.textContent).not.toContain(GENERIC_5XX);
    expect(container.textContent).not.toContain("We could not confirm it"); // the server started nothing
    const link = el?.querySelector<HTMLAnchorElement>("a[href]");
    expect(link?.getAttribute("href")).toBe("/worlds");
  });

  it("NFR_22 start path: after the banner the Start button is usable again (nothing was started, no stuck busy)", async () => {
    const http = httpAnswering(503, MODEL_UNAVAILABLE_BODY);
    await act(async () =>
      root.render(<ActionProbe run={() => http.submitIntake("x", []).then(() => "/x")} />),
    );
    await press();
    const button = q<HTMLButtonElement>("button.primary");
    expect(button?.disabled).toBe(false);
    expect(button?.getAttribute("aria-busy")).toBeNull();
  });

  it("NFR_22 no regression: any other failed start keeps today's alert copy and shows no banner", async () => {
    const http = httpAnswering(500, { detail: "boom" });
    await act(async () =>
      root.render(<ActionProbe flag run={() => http.submitIntake("x", []).then(() => "/x")} />),
    );
    await press();
    expect(banner()).toBeNull();
    expect(q("[data-testid=flag]")?.textContent).not.toBe("true");
    expect(q('[role="alert"]')?.textContent).toContain(
      "Something went wrong while trying to start the task. We could not confirm it. Check before trying again.",
    );
  });

  it("NFR_22 no regression: a 4xx start failure keeps its reason and 'Nothing was changed'", async () => {
    const http = httpAnswering(409, { detail: "That cannot be done right now." });
    await act(async () =>
      root.render(<ActionProbe run={() => http.submitIntake("x", []).then(() => "/x")} />),
    );
    await press();
    expect(banner()).toBeNull();
    expect(q('[role="alert"]')?.textContent).toContain(
      "Could not start the task: That cannot be done right now. Nothing was changed. You can try again.",
    );
  });
});

describe("NFR-22 the approaches screen (S-03) shows the banner when the model is unavailable", () => {
  async function openApproaches(failure: Promise<unknown>) {
    const getApproaches = vi.fn(async () => {
      throw await failure;
    });
    const client: TiloClient = Object.assign(new FixtureClient(), { getApproaches });
    window.history.pushState({}, "", "/task/t1/approaches");
    await act(async () => {
      root.render(
        <ClientProvider client={client}>
          <FlowShell />
        </ClientProvider>,
      );
      window.dispatchEvent(new PopStateEvent("popstate"));
    });
    return getApproaches;
  }

  it("NFR_22 GET /tasks/{id}/approaches failing replay-only: the labelled banner and the replay link, not the generic notice", async () => {
    const failure = rejectionOf(httpAnswering(503, MODEL_UNAVAILABLE_BODY).getApproaches("t1"));
    await openApproaches(failure);
    await until(() => banner() !== null);
    const el = banner();
    expect(el, "S-03 mounts the banner").not.toBeNull();
    expect(el?.textContent).toMatch(/live models are unavailable/i);
    expect(el?.querySelector("a[href]")?.getAttribute("href")).toBe("/worlds");
    expect(container.textContent).not.toContain(GENERIC_5XX);
    expect(container.textContent).not.toContain("Could not load the approaches");
  });

  it("NFR_22 the banner sits inside the screen's reserved slot, so it moves nothing below it (UX-1, CLS)", async () => {
    const failure = rejectionOf(httpAnswering(503, MODEL_UNAVAILABLE_BODY).getApproaches("t1"));
    await openApproaches(failure);
    await until(() => banner() !== null);
    expect(banner()?.closest(".flow-slot")).not.toBeNull();
  });

  it("NFR_22 no regression: any other approaches failure keeps its message, retry and no banner", async () => {
    const failure = rejectionOf(httpAnswering(500, { detail: "boom" }).getApproaches("t1"));
    const getApproaches = await openApproaches(failure);
    await until(() => q('[role="alert"]') !== null);
    expect(banner()).toBeNull();
    expect(q('[role="alert"]')?.textContent).toContain(
      "Could not load the approaches: Tilo had a problem on its side. Nothing was changed. You can try again.",
    );
    const retry = [...container.querySelectorAll("button")].find(
      (b) => b.textContent === "Try again",
    );
    expect(retry, "Try again stays").toBeDefined();
    await act(async () => retry?.click());
    await settle(0);
    expect(getApproaches).toHaveBeenCalledTimes(2);
  });

  it("NFR_22 no regression: a screen that loaded fine shows no banner", async () => {
    window.history.pushState({}, "", "/task/t1/approaches");
    await act(async () => {
      root.render(
        <ClientProvider client={new FixtureClient()}>
          <FlowShell />
        </ClientProvider>,
      );
      window.dispatchEvent(new PopStateEvent("popstate"));
    });
    await until(() => q(".s03-approaches") !== null);
    expect(banner()).toBeNull();
  });
});
