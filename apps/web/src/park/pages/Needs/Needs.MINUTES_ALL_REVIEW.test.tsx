// @vitest-environment happy-dom
// MINUTES-ALL security review (21 Oct): the Needs you card the person approves lists every To address in full, and
// an address outside the signed-in person's own domain carries a note beside it. Display only: the server decides.
import type { Card } from "@tilo/contracts";
import { afterEach, describe, expect, it, vi } from "vitest";
import { stubApp } from "../../../../test-support/park/appHarness";
import { cleanup, mount, q, qa } from "../../../../test-support/park/componentsHarness";
import { settle } from "../../../../test-support/park/skillsHarness";
import { createLiveApi } from "../../api/liveApi";
import type { AppCtx } from "../../app/AppCtx";
import { ParkProvider } from "../../app/context";
import { NeedsPage } from "./NeedsPage";

const signedIn = vi.hoisted(() => ({ email: null as string | null }));
vi.mock("../../../api/sessionAuth", async (original) => ({
  ...(await original<typeof import("../../../api/sessionAuth")>()),
  useSessionAuth: () =>
    signedIn.email
      ? { status: "signedIn", user: { displayName: "Owner", email: signedIn.email } }
      : null,
}));
afterEach(() => {
  cleanup();
  signedIn.email = null;
  vi.restoreAllMocks();
});

const BASE = "https://api.example.test";
const TO = ["owner@example.com", "priya@example.com", "guest@partner.org"];
const GATE = {
  id: "01J8Z3K4M5N6P7Q8R9S0T1V2W3",
  world_id: "w_01",
  run_id: "r_01J8Z3K4M5",
  header: { building: "B2", agent: "A_s1" },
  add_context: true,
  created_at: "2026-10-21T09:30:00.000Z",
  timeout: 3600,
  gate: {
    id: "G1",
    action: {
      type: "send_email",
      connector: "gmail",
      exact: "Send the minutes email to everyone who joined.",
      item: { artifact_id: "art_minutes", version: 1, label: "Minutes email" },
      destination: "new",
    },
    recipients: TO,
    irreversible: true,
    risk_tier: "T3",
  },
  consent: null,
  kind: "gate",
  rung: "gate",
  what_happened: "The minutes email is drafted.",
  why_it_matters: "It goes to everyone on the list.",
  options: [{ id: "approve", label: "Approve", suggested: false, irreversible: true }],
  actions: ["show_me"],
  answer_channels: ["web", "mobile_web"],
  safe_default: "hold",
} as unknown as Card;

async function mountNeeds() {
  const fetchSpy = vi.fn(async (url: unknown) => {
    const path = String(url).replace(BASE, "");
    const body = path.startsWith("/cards")
      ? { cards: [{ world_id: "w_01", card_id: GATE.id, card: GATE }], count: 1, next_cursor: null }
      : { worlds: [], next_cursor: null };
    return new Response(JSON.stringify(body), { headers: { "content-type": "application/json" } });
  });
  const api = createLiveApi({ baseUrl: BASE, fetch: fetchSpy as unknown as typeof fetch });
  const app = stubApp("needs" as AppCtx["page"], { decide: vi.fn() });
  const m = mount(
    <ParkProvider
      api={api}
      schedule={() => () => undefined}
      viewport={{ vw: 1440, vh: 900 }}
      fields={null}
    >
      <NeedsPage app={app} />
    </ParkProvider>,
  );
  await settle();
  return q(m.container, 'section[aria-label="Exactly what will be sent"]');
}
const words = (el: Element) => (el.textContent ?? "").replace(/\s+/g, " ").trim();

describe("MINUTES_ALL_REVIEW Needs you: the approved email's To list", () => {
  it("MINUTES_ALL_REVIEW lists every To address in full and notes the one outside the person's domain", async () => {
    signedIn.email = "owner@example.com";
    const sent = await mountNeeds();
    expect(qa(sent, ".park-needs__person").map(words)).toEqual(TO);
    expect(qa(sent, '[role="note"]').map(words)).toEqual([
      "guest@partner.org: Outside your domain (partner.org)",
    ]);
  });

  it("MINUTES_ALL_REVIEW with no signed-in address there is nothing to compare, so no note is made up", async () => {
    const sent = await mountNeeds();
    expect(qa(sent, ".park-needs__person").map(words)).toEqual(TO);
    expect(qa(sent, '[role="note"]')).toHaveLength(0);
  });
});
