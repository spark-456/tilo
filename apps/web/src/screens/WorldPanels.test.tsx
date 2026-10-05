// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { describe, expect, it } from "vitest";
import { ClientProvider } from "../api/ClientProvider";
import type { TiloClient } from "../api/client";
import { FixtureClient } from "../api/fixtureClient";
import { EVENTS_VILLAGE_BASIC } from "../api/fixtures/events";
import { HudGlance, WorldPanels } from "./WorldPanels";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

async function render(client: TiloClient): Promise<HTMLElement> {
  const container = document.createElement("div");
  document.body.append(container);
  await act(async () => {
    createRoot(container).render(
      <ClientProvider client={client}>
        <WorldPanels worldId="w_village_basic" />
      </ClientProvider>,
    );
  });
  return container;
}

describe("PRD-18.3 S-04 HUD: figures appear only once recorded events exist (HR-1, UX-3)", () => {
  it("shows no figure while the run has no event", async () => {
    const silent = new FixtureClient();
    silent.subscribeEvents = () => () => undefined; // a run that has not recorded anything yet
    const meter = (await render(silent)).querySelector('[data-testid="hud-meter"]');
    expect(meter?.textContent).toBe("Nothing yet. This fills in once a run starts.");
  });

  it("derives status and credits from the events that have arrived", async () => {
    const instant = new FixtureClient(); // the whole recorded stream at once, no timers
    instant.subscribeEvents = (_world, onEvent) => {
      for (const event of EVENTS_VILLAGE_BASIC) onEvent(event);
      return () => undefined;
    };
    const meter = (await render(instant)).querySelector('[data-testid="hud-meter"]');
    expect(meter?.textContent).toContain("Done");
    expect(meter?.textContent).toContain("credits of 40 approved");
    expect(meter?.textContent).toContain("13");
    expect(meter?.querySelector('[data-testid="memory-saved"]')?.textContent).toContain(
      "saved by memory",
    );
  });
});

describe("PRD-18.3 S-04 HUD in fixture mode: the panels read the replay on the stage (HR-1)", () => {
  it("shows the replayed run's status and credits though the client's own log has not started", async () => {
    const silent = new FixtureClient();
    silent.subscribeEvents = () => () => undefined; // the client's own run: nothing recorded
    const container = document.createElement("div");
    document.body.append(container);
    await act(async () => {
      createRoot(container).render(
        <ClientProvider client={silent}>
          <WorldPanels worldId="w_village_basic" replayed={EVENTS_VILLAGE_BASIC} />
          <HudGlance worldId="w_village_basic" replayed={EVENTS_VILLAGE_BASIC.slice(0, 20)} />
        </ClientProvider>,
      );
    });
    const meter = container.querySelector('[data-testid="hud-meter"]');
    expect(meter?.textContent).toContain("Done");
    expect(meter?.textContent).not.toContain("has not started");
    expect(container.querySelector('[data-testid="hud-glance"]')?.textContent).toContain("Working");
  });
});
