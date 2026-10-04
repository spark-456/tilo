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

/** The contract meeting card (contracts/fixtures/card/valid/meeting_budget_split.json). */
const MEETING_CARD_ID = "01J8Z3K4M5N6P7Q8R9S0T1V2W3";

const ev = (seq: number, type: string, run_id: string, data: object): Event =>
  ({
    id: `e${seq}`,
    seq,
    type,
    run_id,
    ts: "2026-09-29T10:00:00Z",
    actor: "A_dir",
    target: "B1",
    summary: `summary ${type}`,
    data,
  }) as Event;

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

  it("shows no purpose text from a contract meeting card when this run has no meeting.called", async () => {
    const container = await withEvents([]);
    expect(container.textContent).toContain("No meeting has been requested yet.");
    expect(container.textContent).not.toContain("Research and Finance disagree");
    expect(container.textContent).not.toContain("The decision changes which suppliers");
  });

  it("shows the purpose only from the card named by this run's meeting.called", async () => {
    const called = ev(1, "meeting.called", "r1", { card_id: MEETING_CARD_ID, attendees: [] });
    const container = await withEvents([called]);
    expect(container.textContent).toContain("Research and Finance disagree");
    expect(container.textContent).not.toContain("No meeting has been requested yet.");
  });

  it("shows no purpose when meeting.called names a card the client does not have", async () => {
    const called = ev(1, "meeting.called", "r1", { card_id: "01JB5VQ0000000000000009999" });
    const container = await withEvents([called]);
    expect(container.textContent).not.toContain("Research and Finance disagree");
    expect(container.textContent).toContain("No meeting has been requested yet.");
  });

  it("lists called, started, decision and ended events", async () => {
    const types = ["meeting.called", "meeting.started", "meeting.decision", "meeting.ended"];
    const container = await withEvents(
      types.map((t, i) => ev(i + 1, t, "r1", { card_id: "01JB5VQ0000000000000009999" })),
    );
    for (const t of types) expect(container.textContent).toContain(`summary ${t}`);
  });

  it("ignores meeting events from a different run", async () => {
    const container = await withEvents([
      ev(1, "agent.working", "r1", {}),
      ev(2, "meeting.started", "r2", {}),
    ]);
    expect(container.textContent).not.toContain("summary meeting.started");
    expect(container.textContent).toContain("No meeting has been recorded in this run.");
  });

  it("shows disabled controls properly", async () => {
    const container = await withEvents([]);
    const declineAudio = container.querySelector('[title="Coming soon"]');
    expect(declineAudio).toBeTruthy();
    expect(declineAudio?.getAttribute("aria-disabled")).toBe("true");
  });
});
