// @vitest-environment happy-dom
import type { Event } from "@tilo/contracts";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { describe, expect, it } from "vitest";
import { ClientProvider } from "../api/ClientProvider";
import { FixtureClient } from "../api/fixtureClient";
import { S_09 } from "./S_09";
import type { ScreenProps } from "./routes";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const withEvents = async (events: Event[]) => {
  const client = new FixtureClient();
  client.subscribeEvents = (_world, onEvent) => {
    for (const e of events) onEvent(e);
    return () => undefined;
  };
  const container = document.createElement("div");
  document.body.append(container);
  await act(async () => {
    createRoot(container).render(
      <ClientProvider client={client}>
        <S_09 />
      </ClientProvider>,
    );
  });
  return container;
};

describe("AGW-07 S-09 Meeting screen", () => {
  it("renders empty state when there are no meeting events", async () => {
    const container = await withEvents([]);
    expect(container.textContent).toContain("No meeting has been recorded in this run.");
  });

  it("lists meeting events when they arrive", async () => {
    const meetingEvent = {
      id: "e1",
      seq: 1,
      type: "meeting.started",
      ts: "2026-09-29T10:00:00Z",
      actor: "A_dir",
      target: "B1",
      summary: "The meeting at B1 started.",
      data: {},
    } as Event;
    const container = await withEvents([meetingEvent]);
    expect(container.textContent).not.toContain("No meeting has been recorded in this run.");
    expect(container.textContent).toContain("The meeting at B1 started.");
  });

  it("shows disabled controls properly", async () => {
    const container = await withEvents([]);
    const declineAudio = container.querySelector('[title="Coming soon"]');
    expect(declineAudio).toBeTruthy();
    expect(declineAudio?.getAttribute("aria-disabled")).toBe("true");
  });
});
