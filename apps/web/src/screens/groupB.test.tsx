// @vitest-environment happy-dom
// AGW-08 group B honesty (HR-1, PRD 9.4): what S-13, S-17, S-18 and S-19 show follows the
// recorded events of the run, whatever the client would answer. Each case renders the screen on a
// run that has recorded only the first events (a prefix of the village stream), so the moments
// between events are tested exactly, not by timing.
import { act } from "react";
import { createRoot } from "react-dom/client";
import { describe, expect, it } from "vitest";
import { ClientProvider } from "../api/ClientProvider";
import type { TiloClient } from "../api/client";
import { FixtureClient } from "../api/fixtureClient";
import { EVENTS_VILLAGE_BASIC } from "../api/fixtures/events";
import { S_13 } from "./S_13";
import { S_17 } from "./S_17";
import { S_18 } from "./S_18";
import { S_19 } from "./S_19";
import { S_23 } from "./S_23";
import type { ScreenProps } from "./routes";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

/** A client whose run has recorded events up to and including `seq`, all at once. */
function runUpTo(seq: number): TiloClient {
  const client = new FixtureClient();
  client.subscribeEvents = (_world, onEvent) => {
    for (const e of EVENTS_VILLAGE_BASIC) if (e.seq <= seq) onEvent(e);
    return () => undefined;
  };
  return client;
}

async function text(Screen: (p: ScreenProps) => React.ReactElement, seq: number) {
  const container = document.createElement("div");
  document.body.append(container);
  await act(async () => {
    createRoot(container).render(
      <ClientProvider client={runUpTo(seq)}>
        <Screen params={[]} />
      </ClientProvider>,
    );
  });
  return container;
}

describe("AGW-08 S-18 questions waiting follow approval.requested and approval.resolved", () => {
  const waiting = async (seq: number) =>
    (await text(S_18, seq)).querySelectorAll('[data-testid="lead-queue"] li').length;
  it("is 0 before seq 34, 1 from the request until the answer, 0 after", async () => {
    expect(await waiting(33)).toBe(0);
    expect(await waiting(34)).toBe(1);
    expect(await waiting(36)).toBe(1);
    expect(await waiting(37)).toBe(0);
    expect(await waiting(44)).toBe(0);
  });
  it("never lists a card of another run", async () => {
    const page = await text(S_18, 44);
    expect(page.textContent).not.toContain("pack sizes");
    expect(page.textContent).toContain("No question is waiting.");
  });
});

describe("AGW-08 S-19 consent requests come only from connection.requested events", () => {
  it("says none is waiting when the run recorded no consent request", async () => {
    expect((await text(S_19, 44)).textContent).toContain("No access request is waiting.");
  });
});

describe("AGW-08 S-13 the library follows artifact.delivered", () => {
  it("is empty before seq 41 and lists the deliverable from seq 41", async () => {
    expect((await text(S_13, 40)).textContent).toContain("Nothing has been delivered yet.");
    const after = await text(S_13, 41);
    expect(after.querySelector('[data-testid="library-rows"]')?.textContent).toContain(
      "Triage list",
    );
  });
});

describe("AGW-08 S-17 lists are told apart by registered fields, not by fixture ids", () => {
  it("shows the draft once its send is asked about, and the sent reply once sent", async () => {
    const before = (await text(S_17, 33)).textContent ?? "";
    expect(before).toContain("Nothing has been sent yet.");
    expect(before).toContain("No draft has been written yet.");
    const after = (await text(S_17, 38)).textContent ?? "";
    expect(after).toContain("The reply went to the supplier in the same thread.");
    expect(after).toContain("Thursday 3pm works");
  });
  it("shows the time saved only once world.completed is recorded", async () => {
    expect((await text(S_17, 43)).textContent).toContain("No time-saved estimate yet.");
    expect((await text(S_17, 44)).textContent).toContain("About 8 to 18 min saved (estimate)");
  });
});

describe("AGW-08 S-23 the estimate example follows world.completed", () => {
  it("shows the figure only once the run has finished", async () => {
    expect((await text(S_23, 43)).textContent).not.toContain("min saved");
    expect((await text(S_23, 43)).textContent).toContain(
      "The example appears when the recorded run finishes.",
    );
    expect((await text(S_23, 44)).textContent).toContain("About 8 to 18 min saved (estimate)");
  });
});
