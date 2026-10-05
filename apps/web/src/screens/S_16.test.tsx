// @vitest-environment happy-dom
// CH-RM (SD-01, docs/prd-supplement-2026-10-05.md): WhatsApp is out of scope, so S-16 is email,
// notification preferences and the connected Google accounts. `whatsapp` stays a valid enum value in
// the contracts, but the screen never offers, names or lists it, even when a recorded run holds it.
import { act } from "react";
import { createRoot } from "react-dom/client";
import { describe, expect, it } from "vitest";
import { ClientProvider } from "../api/ClientProvider";
import { FixtureClient } from "../api/fixtureClient";
import { EVENTS_VILLAGE_BASIC } from "../api/fixtures/events";
import { S_16 } from "./S_16";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

async function render() {
  const client = new FixtureClient();
  client.subscribeEvents = (_world, onEvent) => {
    for (const e of EVENTS_VILLAGE_BASIC) onEvent(e); // the village run, WhatsApp messages included
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
  await act(async () => {
    await new Promise((r) => setTimeout(r, 50));
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
    expect(page.textContent).toContain("No email or in-app message has been recorded yet.");
  });
});
