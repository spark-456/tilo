// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { describe, expect, it } from "vitest";
import { ClientProvider } from "../../api/ClientProvider";
import { FixtureClient } from "../../api/fixtureClient";
import { EVENTS_VILLAGE_BASIC } from "../../api/fixtures/events";
import { HomeBrief, greeting } from "./HomeBrief";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

async function brief(upTo: number): Promise<HTMLElement> {
  const client = new FixtureClient();
  client.subscribeEvents = (_world, onEvent) => {
    for (const e of EVENTS_VILLAGE_BASIC.filter((x) => x.seq <= upTo)) onEvent(e);
    return () => undefined;
  };
  const container = document.createElement("div");
  document.body.append(container);
  await act(async () => {
    createRoot(container).render(
      <ClientProvider client={client}>
        <HomeBrief />
      </ClientProvider>,
    );
  });
  return container;
}

describe("PRD-18.3 S-01 top line: a greeting, or the decisions the queue lists (HR-1)", () => {
  it("greets by the time of day and never names a person", () => {
    expect(greeting(6)).toBe("Good morning.");
    expect(greeting(13)).toBe("Good afternoon.");
    expect(greeting(21)).toBe("Good evening.");
  });

  it("shows the greeting when nothing waits", async () => {
    const el = (await brief(20)).querySelector('[data-testid="home-brief"]');
    expect(el?.getAttribute("data-tone")).toBe("calm");
    expect(el?.textContent).toMatch(/^Good (morning|afternoon|evening)\.$/);
  });

  it("shows the waiting decision, its words and a link to Needs you", async () => {
    const el = (await brief(34)).querySelector('[data-testid="home-brief"]');
    expect(el?.getAttribute("data-tone")).toBe("needs");
    expect(el?.textContent).toContain("1 decision is waiting in Triage my inbox");
    expect(el?.textContent).toContain("The reply is ready. Sending it needs your approval.");
    expect(el?.querySelector("a")?.getAttribute("href")).toContain("/needs-you");
  });
});
