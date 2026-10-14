// @vitest-environment happy-dom
// AGW-08 group B honesty (HR-1, PRD 9.4): what S-13, S-17, S-18 and S-19 show follows the
// recorded events of the run, whatever the client would answer. Each case renders the screen on a
// run that has recorded only the first events (a prefix of the village stream), so the moments
// between events are tested exactly, not by timing.
import { act } from "react";
import { createRoot } from "react-dom/client";
import { describe, expect, it } from "vitest";
import { ClientProvider } from "../../../api/ClientProvider";
import type { TiloClient } from "../../../api/client";
import { FixtureClient } from "../../../api/fixtureClient";
import { EVENTS_VILLAGE_BASIC } from "../../../api/fixtures/events";
import { EstimateSection as S_23 } from "./RunSections";
type ScreenProps = { params: readonly string[] };

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

describe("AGW-08 S-23 the estimate example follows world.completed", () => {
  it("shows the figure only once the run has finished", async () => {
    expect((await text(S_23, 43)).textContent).not.toContain("min saved");
    expect((await text(S_23, 43)).textContent).toContain(
      "The example appears when the recorded run finishes.",
    );
    expect((await text(S_23, 44)).textContent).toContain("About 8 to 18 min saved (estimate)");
  });
});
