import type { Event } from "@tilo/contracts";
// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { describe, expect, it } from "vitest";
import { ClientProvider } from "../api/ClientProvider";
import { FixtureClient } from "../api/fixtureClient";
import { S_08 } from "./S_08";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const consentRequest: Event = {
  v: "1.0",
  id: "evt_consent_1",
  seq: 1,
  ts: "2026-09-29T09:30:00.000Z",
  world_id: "w_village_basic",
  run_id: "r_village_1",
  type: "connection.requested",
  actor: "A_s1",
  target: "w_village_basic",
  level: "L1",
  district: "D1",
  item: null,
  severity: "needs_you",
  credits: 0,
  summary: "Triage my inbox",
  cause: null,
  vis: "all",
  authz: null,
  data: {
    connector: "gmail",
    card_id: "card_consent_1",
    scopes: ["Read email", "Send email"],
    write_actions: ["Send email"],
  },
  trace: {
    model_role: null,
    profile: null,
    tokens_in: null,
    tokens_out: null,
    tool: null,
    latency_ms: null,
    archive_ref: null,
  },
};

const consentGranted: Event = {
  ...consentRequest,
  id: "evt_consent_2",
  seq: 2,
  type: "connection.consented",
};

async function render(events: Event[]) {
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
        <S_08 />
      </ClientProvider>,
    );
  });
  return container;
}

describe("S-08 Connection consent sheet", () => {
  it("renders empty state when no request is waiting", async () => {
    const container = await render([]);
    expect(container.textContent).toContain("No connection is asking for consent right now.");
  });

  it("shows consent request details when one is waiting", async () => {
    const container = await render([consentRequest]);
    expect(container.textContent).toContain("Connect Gmail");
    expect(container.textContent).toContain("Read email, Send email");
  });

  it("shows empty state again after consent is granted", async () => {
    const container = await render([consentRequest, consentGranted]);
    expect(container.textContent).toContain("No connection is asking for consent right now.");
  });
});
