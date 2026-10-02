// @vitest-environment happy-dom
import { type ReactElement, act } from "react";
import { type Root, createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ClientProvider } from "../api/ClientProvider";
import type { ApproachesResult, TiloClient } from "../api/client";
import { FixtureClient } from "../api/fixtureClient";
import { FlowShell } from "./FlowShell";
import { PRESS_MS } from "./remote";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const fail = () => Promise.reject(new Error("the network is down"));
const rejectingClient: TiloClient = {
  submitIntake: fail,
  answerQuestions: fail,
  getApproaches: fail,
  approve: fail,
  getLayout: fail,
  subscribeEvents: () => () => undefined,
  listCards: fail,
  answerCard: fail,
  getDelivery: fail,
};

let container: HTMLElement;
let root: Root;
const unhandled: unknown[] = [];
const onUnhandled = (reason: unknown) => unhandled.push(reason);

async function show(path: string, client: TiloClient): Promise<void> {
  window.history.pushState({}, "", path);
  const tree: ReactElement = (
    <ClientProvider client={client}>
      <FlowShell />
    </ClientProvider>
  );
  await act(async () => {
    root.render(tree);
    window.dispatchEvent(new PopStateEvent("popstate")); // a screen already mounted follows the path
  });
}
const settle = (ms = PRESS_MS + 20) =>
  act(async () => void (await new Promise((r) => setTimeout(r, ms))));
/** S-01 starts only with text in the box. */
async function fillTask(text = "Triage my inbox") {
  const box = container.querySelector("textarea");
  const set = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")?.set;
  await act(async () => {
    set?.call(box, text);
    box?.dispatchEvent(new Event("input", { bubbles: true }));
  });
}
const tryAgain = () =>
  [...container.querySelectorAll<HTMLButtonElement>("button.secondary")].find(
    (b) => b.textContent === "Try again",
  );
const button = (cls: string) => container.querySelector<HTMLButtonElement>(`button.${cls}`);

beforeEach(() => {
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  process.on("unhandledRejection", onUnhandled);
});
afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  process.off("unhandledRejection", onUnhandled);
  unhandled.length = 0;
  vi.restoreAllMocks();
});

describe("PRD-18.3 flow: a rejecting client shows the error and a retry, never a console error", () => {
  it("a load that rejects shows what happened, what Tilo did and Try again", async () => {
    const consoleError = vi.spyOn(console, "error");
    const approaches = vi.fn(fail);
    await show("/task/t1/approaches", { ...rejectingClient, getApproaches: approaches });
    await settle(0);
    const alert = container.querySelector('[role="alert"]');
    expect(alert?.textContent).toContain("Could not load the approaches: the network is down.");
    expect(alert?.textContent).toContain("Nothing was changed.");
    expect(button("primary")?.disabled).toBe(true);

    await act(async () => button("secondary")?.click());
    await settle(0);
    expect(approaches).toHaveBeenCalledTimes(2);
    expect(consoleError).not.toHaveBeenCalled();
    expect(unhandled).toEqual([]);
  });

  it("an action that rejects frees the button, shows the error and retries on click", async () => {
    const consoleError = vi.spyOn(console, "error");
    const submit = vi.fn(fail);
    await show("/", { ...rejectingClient, submitIntake: submit });
    await fillTask();
    await act(async () => button("primary")?.click());
    expect(button("primary")?.getAttribute("aria-busy")).toBe("true");
    await settle();
    expect(button("primary")?.getAttribute("aria-busy")).toBeNull();
    expect(container.querySelector('[role="alert"]')?.textContent).toContain(
      "Could not start the task: the network is down.",
    );
    expect(window.location.pathname).toBe("/");

    await act(async () => tryAgain()?.click());
    await settle();
    expect(submit).toHaveBeenCalledTimes(2);
    expect(consoleError).not.toHaveBeenCalled();
    expect(unhandled).toEqual([]);
  });

  it("a client that throws synchronously is handled the same way", async () => {
    const throwing = () => {
      throw new Error("bad state");
    };
    await show("/world/w1/delivery", { ...rejectingClient, getDelivery: throwing });
    await settle(0);
    expect(container.querySelector('[role="alert"]')?.textContent).toContain("bad state");
    expect(unhandled).toEqual([]);
  });
});

describe("PRD-18.3 flow: loading and empty states", () => {
  it("shows Loading, then the recommendation with the exact budget copy", async () => {
    await show("/task/t1/approaches", new FixtureClient({ delayMs: 50 }));
    expect(container.querySelector("output")?.textContent).toBe("Loading the approaches…");
    expect(button("primary")?.disabled).toBe(true);
    await settle(80);
    expect(container.textContent).toContain("Recommended: Quick scan.");
    expect(container.textContent).toContain(
      "up to 45 credits (about US$0.23). You can pause it any time.",
    );
    expect(button("primary")?.disabled).toBe(false);
  });

  it("states no summary while loading, only once the data is ready", async () => {
    await show("/world/w1/delivery", new FixtureClient({ delayMs: 50 }));
    expect(container.querySelector(".flow-summary")).toBeNull();
    await settle(80);
    expect(container.querySelector(".flow-summary")?.textContent).toContain("Verified");
  });

  it("states no summary after an error", async () => {
    await show("/world/w1/delivery", rejectingClient);
    await settle(0);
    expect(container.querySelector('[role="alert"]')).not.toBeNull();
    expect(container.querySelector(".flow-summary")).toBeNull();
  });

  it("moves focus to the new screen's heading after a route change", async () => {
    await show("/", new FixtureClient());
    await fillTask();
    await act(async () => button("primary")?.click());
    await settle();
    expect(window.location.pathname).toContain("/understanding");
    expect(document.activeElement?.tagName).toBe("H1");
  });

  it("approves the recommended approach with its cap from getApproaches", async () => {
    const approve = vi.fn(async () => ({ world_id: "w9" }));
    const fixture = new FixtureClient();
    await show("/task/t1/approaches", {
      ...rejectingClient,
      getApproaches: (id) => fixture.getApproaches(id),
      approve,
    });
    await settle(0);
    await act(async () => button("primary")?.click());
    await settle();
    expect(approve).toHaveBeenCalledWith("t1", { approach_id: "quick", budget_cap: 45 });
    expect(window.location.pathname).toBe("/world/w9");
  });

  it("an empty approaches list is an empty state with a retry, and nothing to approve", async () => {
    const empty: ApproachesResult = {
      task_id: "t1",
      approaches: [],
      recommended: "",
      credit_usd: 0.005,
    };
    await show("/task/t1/approaches", { ...rejectingClient, getApproaches: async () => empty });
    await settle(0);
    expect(container.querySelector('[role="alert"]')?.textContent).toContain(
      "Nothing came back for the approaches.",
    );
    expect(button("secondary")).not.toBeNull();
    expect(button("primary")?.disabled).toBe(true);
  });

  it("an empty delivery is an empty state with a retry", async () => {
    const fixture = new FixtureClient();
    await show("/world/w1/delivery", {
      ...rejectingClient,
      getDelivery: async (id) => ({ ...(await fixture.getDelivery(id)), artifacts: [] }),
    });
    await settle(0);
    expect(container.querySelector('[role="alert"]')?.textContent).toContain("Nothing came back");
    expect(button("secondary")).not.toBeNull();
  });

  it("every screen has exactly one primary button", async () => {
    const client = new FixtureClient();
    for (const path of [
      "/",
      "/task/t/understanding",
      "/task/t/approaches",
      "/world/w",
      "/world/w/delivery",
    ]) {
      await show(path, client);
      await settle(0);
      expect(container.querySelectorAll("button.primary")).toHaveLength(1);
    }
  });
});
