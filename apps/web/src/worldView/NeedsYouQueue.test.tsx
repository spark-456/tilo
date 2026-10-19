// @vitest-environment happy-dom
// AGW-05 S-06 honesty (HR-1, PRD 9.4): what the queue shows follows the recorded events of the
// run, whatever the client would answer. Each case renders the screen on a run that has recorded
// only the first events (a prefix of the village stream).
import { act } from "react";
import { createRoot } from "react-dom/client";
import { describe, expect, it } from "vitest";
import { ClientProvider } from "../api/ClientProvider";
import type { TiloClient } from "../api/client";
import { FixtureClient } from "../api/fixtureClient";
import { EVENTS_VILLAGE_BASIC } from "../api/fixtures/events";
import { NeedsYouView } from "./NeedsYouView";

// OLD-UI-OUT-2: the queue is a Park page now (worldView/NeedsYouView); same behaviour.
const S_06 = () => <NeedsYouView sheet="queue" />;

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

function runUpTo(seq: number): TiloClient {
  const client = new FixtureClient();
  client.subscribeEvents = (_world, onEvent) => {
    for (const e of EVENTS_VILLAGE_BASIC) if (e.seq <= seq) onEvent(e);
    return () => undefined;
  };
  return client;
}

async function render(seq: number) {
  const container = document.createElement("div");
  document.body.append(container);
  await act(async () => {
    createRoot(container).render(
      <ClientProvider client={runUpTo(seq)}>
        <S_06 />
      </ClientProvider>,
    );
  });
  return container;
}

describe("PRD-18.3 AGW-05 S-06 the queue is empty before the request and after the answer", () => {
  const rows = async (seq: number) =>
    (await render(seq)).querySelectorAll('[data-testid="needs-queue"] li').length;
  it("shows 0 rows before seq 34, 1 from the request until the answer, 0 after", async () => {
    expect([
      await rows(33),
      await rows(34),
      await rows(36),
      await rows(37),
      await rows(44),
    ]).toEqual([0, 1, 1, 0, 0]);
  });
  it("says nothing needs you when nothing waits, and names the waiting gate when one does", async () => {
    expect((await render(33)).textContent).toContain("Nothing needs you");
    const page = (await render(34)).textContent ?? "";
    expect(page).toContain("The reply is ready. Sending it needs your approval.");
    expect(page).toContain("Approval gate");
    expect(page).toContain("Specialist 2"); // the agent by name, not A_s2
    expect(page).not.toMatch(/\bA_s2\b|\bG1\b/);
  });
  it("never lists a contract card of another run", async () => {
    const page = (await render(34)).textContent ?? "";
    expect(page).not.toContain("pack sizes");
    expect(page).not.toContain("quote summary");
  });
});
