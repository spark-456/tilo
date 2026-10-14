// @vitest-environment happy-dom
// CH-RM (SD-01, docs/prd-supplement-2026-10-05.md): WhatsApp is out of scope, so S-16 is email,
// notification preferences and the connected Google accounts. `whatsapp` stays a valid enum value in
// the contracts, but the screen never offers, names or lists it, even when a recorded run holds it.
import type { Event } from "@tilo/contracts";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { describe, expect, it, vi } from "vitest";
import { ClientProvider } from "../../../api/ClientProvider";
import { FixtureClient } from "../../../api/fixtureClient";
import { EVENTS_VILLAGE_BASIC } from "../../../api/fixtures/events";
import { ChannelsSection as S_16 } from "./RunSections";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

// The village run now carries no WhatsApp message (its seq 35 and 36 went by email), so one is
// built here from seq 35: a recorded run may still hold the value, and the screen must not list it.
const [CARD_OUT] = EVENTS_VILLAGE_BASIC.filter((e) => e.seq === 35);
const RETIRED_CHANNEL_MESSAGE: Event = {
  ...(CARD_OUT as Event),
  id: "01JB5VQ0000000000000000099",
  seq: 99,
  summary: "A message went by the retired channel.",
  data: { ...(CARD_OUT?.data as object), channel: "whatsapp" } as Event["data"],
};

async function render() {
  const client = new FixtureClient();
  client.subscribeEvents = (_world, onEvent) => {
    for (const e of [...EVENTS_VILLAGE_BASIC, RETIRED_CHANNEL_MESSAGE]) onEvent(e);
    return () => undefined;
  };
  const container = document.createElement("div");
  document.body.append(container);
  await act(async () => {
    createRoot(container).render(
      <ClientProvider client={client}>
        <S_16 />
      </ClientProvider>,
    );
  });
  // The layout arrives after the first render (the fixture client imports it).
  await vi.waitFor(async () => {
    await act(async () => undefined);
    expect(container.querySelector('[data-testid="connected-accounts"]')).not.toBeNull();
  });
  return container;
}

describe("CH-RM S-16 Channels without WhatsApp", () => {
  it("never says WhatsApp, in any heading, note, row, chip or button", async () => {
    const page = await render();
    expect(page.textContent ?? "").not.toMatch(/whatsapp/i);
    expect([...page.querySelectorAll("button")].map((b) => b.textContent)).not.toContain(
      "Bind a WhatsApp number",
    );
  });

  it("is email, notification preferences and the connected Google accounts", async () => {
    const page = await render();
    const headings = [...page.querySelectorAll("h2")].map((h) => h.textContent);
    expect(headings).toEqual(
      expect.arrayContaining(["Connected Google accounts", "Email", "Notification preferences"]),
    );
    // The accounts come from the world's own connections, not a channel island.
    const rows = page.querySelector('[data-testid="connected-accounts"]');
    expect(rows?.textContent).toContain("Gmail");
    expect(rows?.textContent).toContain("Connected");
  });

  it("lists only the messages that went by email or in the app", async () => {
    const page = await render();
    const text = page.textContent ?? "";
    expect(text).toContain("Tilo sent the approval card to your inbox.");
    expect(text).toContain("Your answer arrived.");
    expect(text).not.toContain("A message went by the retired channel.");
    expect(text).not.toContain("No email or in-app message has been recorded yet.");
  });
});
