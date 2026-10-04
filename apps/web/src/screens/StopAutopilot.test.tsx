// @vitest-environment happy-dom
// FR-HIL-07 S-15 Stop all autopilot: it asks first with nothing chosen, sends once on a deliberate
// second press, and the page then says only what the API answered (HR-1).
import { act } from "react";
import { type Root, createRoot } from "react-dom/client";
import { afterEach, describe, expect, it } from "vitest";
import { ClientProvider } from "../api/ClientProvider";
import type { TiloClient } from "../api/client";
import { FixtureClient } from "../api/fixtureClient";
import type { StopResult } from "../api/stop";
import { StopAutopilot } from "./StopAutopilot";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root | null = null;
afterEach(() => {
  act(() => root?.unmount());
  document.body.replaceChildren();
});

async function draw(client: TiloClient, world = "w1"): Promise<HTMLElement> {
  const container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  await act(async () =>
    root?.render(
      <ClientProvider client={client}>
        <StopAutopilot worldId={world} />
      </ClientProvider>,
    ),
  );
  return container;
}

const button = (c: HTMLElement, name: string) =>
  [...c.querySelectorAll("button")].find((b) => b.textContent === name) as HTMLButtonElement;
const note = (c: HTMLElement) => c.querySelector('[data-testid="stop-result"]')?.textContent ?? "";

/** A fixture client whose stop is answered only when the test says so. */
function held() {
  const client = new FixtureClient();
  const calls: string[] = [];
  let answer: (r: StopResult) => void = () => undefined;
  let fail: (e: Error) => void = () => undefined;
  client.stopAutopilot = (id: string) =>
    new Promise<StopResult>((resolve, reject) => {
      calls.push(id);
      answer = resolve;
      fail = reject;
    });
  return { client, calls, answer: (r: StopResult) => answer(r), fail: (e: Error) => fail(e) };
}

describe("FR-HIL-07 S-15 Stop all autopilot", () => {
  it("asks first: nothing is sent and no button has focus when the question opens", async () => {
    const h = held();
    const c = await draw(h.client);
    await act(async () => button(c, "Stop all autopilot").click());
    expect(c.querySelector("h3")?.textContent).toBe("Stop all autopilot?");
    expect(document.activeElement?.tagName).toBe("H3"); // nothing preselected
    expect(h.calls).toEqual([]);
    await act(async () => button(c, "Keep autopilot as it is").click());
    expect(c.querySelector("h3")).toBeNull();
    expect(h.calls).toEqual([]);
  });

  it("sends once on the second press and says only what the answer says", async () => {
    const h = held();
    const c = await draw(h.client, "w9");
    await act(async () => button(c, "Stop all autopilot").click());
    await act(async () => button(c, "Stop all autopilot").click());
    await act(async () => button(c, "Stopping…").click()); // a second press while sending does nothing
    expect(h.calls).toEqual(["w9"]);
    expect(note(c)).toBe(""); // nothing is claimed before the answer
    await act(async () =>
      h.answer({ stopped: 2, already_l1: 0, confirmations: [{ channel: "whatsapp" }], pending: 0 }),
    );
    expect(note(c)).toContain("Stopped 2 rules");
    expect(note(c)).toContain("Confirmations go to: WhatsApp.");
    expect(c.querySelector("h3")).toBeNull();
  });

  it("shows the failure in words and lets the person try again, claiming nothing stopped", async () => {
    const h = held();
    const c = await draw(h.client);
    await act(async () => button(c, "Stop all autopilot").click());
    await act(async () => button(c, "Stop all autopilot").click());
    await act(async () => h.fail(new Error("You do not have access to this.")));
    expect(note(c)).toContain("Could not stop all autopilot: You do not have access to this");
    expect(note(c)).not.toContain("Stopped");
    expect(button(c, "Stop all autopilot")).toBeTruthy(); // back to the control
  });

  it("an unreadable answer is an error, never a result", async () => {
    const h = held();
    const c = await draw(h.client);
    await act(async () => button(c, "Stop all autopilot").click());
    await act(async () => button(c, "Stop all autopilot").click());
    await act(async () => h.answer({ stopped: "many" } as unknown as StopResult));
    expect(note(c)).toContain("could not read");
    expect(note(c)).not.toContain("Stopped");
  });

  it("a client that cannot send it shows the control disabled, never a live no-op", async () => {
    const c = await draw({} as TiloClient);
    const b = button(c, "Stop all autopilot");
    expect(b.getAttribute("aria-disabled")).toBe("true");
    expect(b.title).toBe("Coming soon");
    await act(async () => b.click());
    expect(c.querySelector("h3")).toBeNull();
  });
});
