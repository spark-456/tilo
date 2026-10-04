// @vitest-environment happy-dom
import type { Event } from "@tilo/contracts";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { describe, expect, it } from "vitest";
import { ClientProvider } from "../api/ClientProvider";
import { FixtureClient } from "../api/fixtureClient";
import { S_08 } from "./S_08";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

/** The contract consent card (contracts/fixtures/card/valid/consent_drive_folder.json). */
const CONSENT_CARD_ID = "01J8Z3K4M5N6P7Q8R9S0T1V2W5";
const UNKNOWN_CARD_ID = "01J8Z3K4M5N6P7Q8R9S0T1V2W9";

/** A contract-valid connection.requested / .consented event: data is only connector and card_id. */
const connection = (
  seq: number,
  type: "connection.requested" | "connection.consented",
  cardId: string,
  runId = "r_village_1",
): Event =>
  ({
    v: "1.0",
    id: `evt_consent_${seq}`,
    seq,
    ts: "2026-09-29T09:30:00.000Z",
    world_id: "w_village_basic",
    run_id: runId,
    type,
    actor: "A_s1",
    target: "w_village_basic",
    level: "L1",
    district: "D1",
    item: null,
    severity: "needs_you",
    credits: 0,
    summary: "Saving the report needs access to one Drive folder.",
    cause: null,
    vis: "all",
    authz: null,
    data: { connector: "google_drive", card_id: cardId },
    trace: {
      model_role: null,
      profile: null,
      tokens_in: null,
      tokens_out: null,
      tool: null,
      latency_ms: null,
      archive_ref: null,
    },
  }) as Event;

async function render(events: Event[]) {
  const client = new FixtureClient();
  const answers: Array<{ cardId: string; optionId: string }> = [];
  client.answerCard = async (cardId, answer) => {
    answers.push({ cardId, optionId: answer.option_id });
  };
  client.subscribeEvents = (_world, onEvent) => {
    for (const e of events) onEvent(e);
    return () => undefined;
  };
  const container = document.createElement("div");
  document.body.append(container);
  await act(async () => {
    createRoot(container).render(
      <ClientProvider client={client}>
        <S_08 />
      </ClientProvider>,
    );
  });
  return { container, answers };
}

const buttons = (c: HTMLElement) => [...c.querySelectorAll("button")].map((b) => b.textContent);

describe("AGW-06 S-08 Connection consent sheet", () => {
  it("renders the empty state when no request is waiting", async () => {
    const { container } = await render([]);
    expect(container.textContent).toContain("No connection is asking for consent right now.");
    expect(container.querySelector("h1")?.textContent).toBe("Connection consent");
  });

  it("takes scopes and options from the consent card a contract-valid event names", async () => {
    const { container } = await render([connection(1, "connection.requested", CONSENT_CARD_ID)]);
    expect(container.textContent).toContain("Connect Google Drive");
    expect(container.textContent).toContain("Create and edit files in the Tilo folder only");
    expect(container.textContent).not.toContain("No specific scopes");
    expect(container.querySelector("h1")?.textContent).toBe("Connection consent");
    expect(container.querySelector("dl.gate-facts")).toBeTruthy();
  });

  it("offers exactly the contract options, Connect and Hold (CR-13)", async () => {
    const { container } = await render([connection(1, "connection.requested", CONSENT_CARD_ID)]);
    expect(buttons(container)).toEqual(["Connect", "Hold"]);
    expect(container.textContent).not.toContain("Allow");
    expect(container.textContent).not.toContain("Not now");
  });

  it("sends the option id the card names, and nothing before a click", async () => {
    const { container, answers } = await render([
      connection(1, "connection.requested", CONSENT_CARD_ID),
    ]);
    expect(answers).toEqual([]);
    const connect = [...container.querySelectorAll("button")].find(
      (b) => b.textContent === "Connect",
    );
    await act(async () => {
      connect?.click();
    });
    expect(answers).toEqual([{ cardId: CONSENT_CARD_ID, optionId: "connect" }]);
  });

  it("says scopes are not available, and offers no answer, when the card is missing", async () => {
    const { container } = await render([connection(1, "connection.requested", UNKNOWN_CARD_ID)]);
    expect(container.textContent).toContain("Scopes are not available.");
    expect(container.textContent).not.toContain("No specific scopes");
    expect(container.querySelector("[data-testid=consent-no-card]")).toBeTruthy();
    expect(buttons(container)).toEqual([]);
  });

  it("shows the empty state again after consent is granted", async () => {
    const { container } = await render([
      connection(1, "connection.requested", CONSENT_CARD_ID),
      connection(2, "connection.consented", CONSENT_CARD_ID),
    ]);
    expect(container.textContent).toContain("No connection is asking for consent right now.");
  });

  it("ignores a request recorded in a different run", async () => {
    const { container } = await render([
      { ...connection(1, "connection.consented", UNKNOWN_CARD_ID), run_id: "r_village_1" } as Event,
      connection(2, "connection.requested", CONSENT_CARD_ID, "r_other_run"),
    ]);
    expect(container.textContent).toContain("No connection is asking for consent right now.");
  });
});
