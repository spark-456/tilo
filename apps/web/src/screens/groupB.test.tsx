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

describe("AGW-08 S-13 the library follows artifact.delivered", () => {
  it("is empty before seq 41 and lists the deliverable from seq 41", async () => {
    expect((await text(S_13, 40)).textContent).toContain("Nothing delivered yet");
    const after = await text(S_13, 41);
    expect(after.querySelector('[data-testid="library-rows"]')?.textContent).toContain(
      "Triage list",
    );
  });
});
