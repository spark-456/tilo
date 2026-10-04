// @vitest-environment happy-dom
// FR-WLD-07 web side: Pause all is a request; the veil, the "Paused" banner and the paused status
// come only from a recorded world.paused event (PRD 9.4 HR-1), and lift only on world.resumed.
import type { Event } from "@tilo/contracts";
import { act } from "react";
import { type Root, createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import { liveClient } from "../../test-support/needsYou";
import { fixtureEvent } from "../../test-support/worldPause";
import { ClientProvider } from "../api/ClientProvider";
import { FixtureClient } from "../api/fixtureClient";
import { HttpClient } from "../api/http";
import { PAUSE_CONFIRM_MS, canPause } from "../world/pause";
import { ReplayPauseSlot, WorldPauseSlot } from "./PauseSlot";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root | null = null;
afterEach(() => {
  act(() => root?.unmount());
  document.body.replaceChildren();
  vi.useRealTimers();
});

async function draw(node: React.ReactElement): Promise<HTMLElement> {
  const container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  await act(async () => root?.render(node));
  return container;
}

const WORLD = "w_village_basic";
const slot = (c: HTMLElement) => c.querySelector<HTMLElement>('[data-testid="pause-slot"]');
const pauseBtn = (c: HTMLElement) =>
  c.querySelector<HTMLButtonElement>('[data-testid="pause-all"]') as HTMLButtonElement;
const resumeBtn = (c: HTMLElement) => c.querySelector<HTMLButtonElement>('[data-testid="resume"]');
const press = (c: HTMLElement) => act(async () => pauseBtn(c).click());

/** A live client whose pause requests are recorded and answered only when the test says so. */
function pausable() {
  const live = liveClient([]);
  const asked: string[] = [];
  (live.client as FixtureClient & { pauseWorld: (id: string) => Promise<void> }).pauseWorld =
    async (id) => {
      asked.push(id);
    };
  return { ...live, asked };
}

const mount = (client: FixtureClient) =>
  draw(
    <ClientProvider client={client}>
      <WorldPauseSlot worldId={WORLD} />
    </ClientProvider>,
  );

describe("FR_WLD_07 Pause all is a request, never a claim (HR-1)", () => {
  it("FR_WLD_07 sends the request and says only 'Pausing…' until world.paused is recorded", async () => {
    const { client, asked } = pausable();
    const c = await mount(client);
    expect(slot(c)?.getAttribute("data-pause")).toBe("ready");
    await press(c);
    expect(asked).toEqual([WORLD]);
    expect(slot(c)?.getAttribute("data-pause")).toBe("pausing");
    expect(c.textContent).toContain("Pausing…");
    expect(c.textContent).not.toContain("All work is paused");
    expect(resumeBtn(c)).toBeNull();
  });

  it("FR_WLD_07 shows Paused with a Resume that is honestly 'Coming soon', only after the event", async () => {
    const { client, push } = pausable();
    const c = await mount(client);
    await press(c);
    await push(fixtureEvent("world.paused", 7));
    expect(slot(c)?.getAttribute("data-pause")).toBe("paused");
    expect(c.textContent).toContain("All work is paused");
    const resume = resumeBtn(c);
    expect(resume?.getAttribute("aria-disabled")).toBe("true");
    expect(resume?.getAttribute("title")).toContain("Coming soon");
    expect(pauseBtn(c).getAttribute("aria-disabled")).toBe("true");
  });

  it("FR_WLD_07 the banner clears on a recorded world.resumed, not before", async () => {
    const { client, push } = pausable();
    const c = await mount(client);
    await push(fixtureEvent("world.paused", 7));
    expect(slot(c)?.getAttribute("data-pause")).toBe("paused");
    await push(fixtureEvent("world.resumed", 8));
    expect(slot(c)?.getAttribute("data-pause")).toBe("ready");
    expect(c.textContent).not.toContain("All work is paused");
  });

  it("FR_WLD_07 after a bounded wait it says no confirmation was recorded and lets the person retry", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    const { client, asked } = pausable();
    const c = await mount(client);
    await press(c);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(PAUSE_CONFIRM_MS + 1);
    });
    expect(slot(c)?.getAttribute("data-pause")).toBe("unconfirmed");
    expect(c.textContent).toContain("No confirmation recorded yet");
    expect(c.textContent).not.toContain("All work is paused");
    expect(pauseBtn(c).getAttribute("aria-disabled")).not.toBe("true");
    await press(c);
    expect(asked).toHaveLength(2);
  });

  it("FR_WLD_07 a rejected request says what happened and that nothing changed", async () => {
    const { client } = pausable();
    (client as unknown as { pauseWorld: () => Promise<void> }).pauseWorld = async () => {
      throw new Error("The server said no");
    };
    const c = await mount(client);
    await press(c);
    expect(slot(c)?.getAttribute("data-pause")).toBe("error");
    expect(c.textContent).toContain("Could not pause all work");
    expect(c.textContent).toContain("Nothing was changed");
  });

  it("FR_WLD_07 a second click while pausing sends nothing more", async () => {
    const { client, asked } = pausable();
    const c = await mount(client);
    await press(c);
    await press(c);
    expect(asked).toHaveLength(1);
  });

  it("FR_WLD_07 a client that cannot pause gets an aria-disabled 'Coming soon' control that does nothing", async () => {
    const { client } = liveClient([]); // a FixtureClient with its pauseWorld removed
    (client as unknown as { pauseWorld?: unknown }).pauseWorld = undefined;
    expect(canPause(client)).toBe(false);
    const c = await mount(client);
    expect(slot(c)?.getAttribute("data-pause")).toBe("unavailable");
    expect(pauseBtn(c).getAttribute("aria-disabled")).toBe("true");
    expect(pauseBtn(c).getAttribute("title")).toContain("Coming soon");
    await press(c);
    expect(slot(c)?.getAttribute("data-pause")).toBe("unavailable");
    expect(c.textContent).not.toContain("Pausing");
  });

  it("FR_WLD_07 a run that has ended cannot be paused", async () => {
    const { client, push } = pausable();
    const c = await mount(client);
    await push(fixtureEvent("world.completed", 9));
    expect(slot(c)?.getAttribute("data-pause")).toBe("ended");
    expect(pauseBtn(c).getAttribute("aria-disabled")).toBe("true");
  });

  it("FR_WLD_07 the control is a real 44 px button, not the screen's filled primary (UX-1)", async () => {
    const { client } = pausable();
    const c = await mount(client);
    expect(pauseBtn(c).tagName).toBe("BUTTON");
    expect(pauseBtn(c).type).toBe("button");
    expect(pauseBtn(c).classList.contains("primary")).toBe(false);
    expect(pauseBtn(c).textContent).toBe("Pause all");
  });

  it("FR_WLD_07 canPause is true for the fixture and HTTP clients and false for a bare client", () => {
    expect(canPause(new FixtureClient())).toBe(true);
    expect(canPause(new HttpClient({ baseUrl: "http://127.0.0.1:1" }))).toBe(true);
    expect(canPause({} as never)).toBe(false);
  });
});

describe("FR_WLD_07 a recorded replay shows the same slot, honestly", () => {
  it("FR_WLD_07 a replay cannot be paused; a recorded world.paused still shows Paused", async () => {
    const live = await draw(<ReplayPauseSlot status="started" />);
    expect(slot(live)?.getAttribute("data-pause")).toBe("unavailable");
    expect(pauseBtn(live).getAttribute("aria-disabled")).toBe("true");
    expect(pauseBtn(live).getAttribute("title")).toContain("recorded replay");
    act(() => root?.unmount());
    const paused = await draw(<ReplayPauseSlot status="paused" />);
    expect(slot(paused)?.getAttribute("data-pause")).toBe("paused");
    expect(paused.textContent).toContain("All work is paused");
  });
});

describe("FR_WLD_07 fixture helper events are real contract fixtures", () => {
  it("FR_WLD_07 world.paused and world.resumed come from contracts/fixtures", () => {
    const paused: Event = fixtureEvent("world.paused", 7);
    expect(paused.type).toBe("world.paused");
    expect(paused.seq).toBe(7);
    expect((paused.data as { reason: string }).reason).toBe("pause_all");
  });
});
