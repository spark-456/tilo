// @vitest-environment happy-dom
// SEC-15 / SIGNIN + FR-CON-03 (S-08 connection consent): the OAuth consent screen of the Google project is "In production"
// WITHOUT Google verification of the restricted Gmail scopes (user decision, 7 Oct; infra/ACCESS.md section 11, BQ-SIGNIN-1).
// So Google puts an "unverified app" warning in front of every Gmail consent. Before Tilo sends the person to Google, the
// consent sheet says so in plain words, so the warning is expected and not alarming. Behaviour pinned here:
//   - the consent card is for the `gmail` connector: the sheet shows ONE note, `[data-testid="consent-unverified-note"]`,
//     whose text is exactly UNVERIFIED_NOTE below (also written in services/api/tests/API_SIGNIN.md; a repo test keeps
//     the two equal), and it comes before the Connect and Hold buttons in the document, so it is read before the answer;
//   - any other connector (Google Drive here: a non-sensitive scope) shows no such note;
//   - the existing S-08 rules hold: exactly Connect and Hold, nothing sent before a click.
// Neutral wording, no new brand copy; the look is the design's.
import type { Card, Event } from "@tilo/contracts";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { describe, expect, it } from "vitest";
import { ClientProvider } from "../api/ClientProvider";
import { FixtureClient } from "../api/fixtureClient";
import { NeedsYouView } from "./NeedsYouView";

// OLD-UI-OUT-2: the consent sheet is a Park page now (worldView/NeedsYouView); same behaviour.
const S_08 = () => <NeedsYouView sheet="consent" />;

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

/** The exact sentence the builder must show (services/api/tests/API_SIGNIN.md). */
const UNVERIFIED_NOTE =
  "Google will show a warning that this app is not verified, because Google has not finished reviewing Tilo's access to Gmail. Tilo asks only for the access listed above. To continue, choose Advanced on Google's page, then continue to Tilo.";

const GMAIL_CARD_ID = "01J8Z3K4M5N6P7Q8R9S0T1V2G1";
const DRIVE_CARD_ID = "01J8Z3K4M5N6P7Q8R9S0T1V2D1";

const consentCard = (id: string, connector: string, scopes: string[]): Card =>
  ({
    id,
    world_id: "w_village_basic",
    run_id: "r_village_1",
    header: { building: "B1", agent: "A_dir" },
    add_context: false,
    created_at: "2026-09-29T09:30:00.000Z",
    timeout: 3600,
    gate: null,
    consent: { connector, scopes },
    kind: "consent",
    rung: "consent",
    what_happened: "The run needs access to an account.",
    why_it_matters: "Without it that part of the work cannot be done.",
    options: [
      { id: "connect", label: "Connect", suggested: true, irreversible: false },
      { id: "hold", label: "Hold", suggested: false, irreversible: false },
    ],
    actions: ["show_me", "snooze"],
    answer_channels: ["web", "mobile_web"],
    safe_default: "hold",
  }) as unknown as Card;

const requested = (cardId: string, connector: string): Event =>
  ({
    v: "1.0",
    id: `evt_consent_${connector}`,
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
    summary: "The run needs access to an account.",
    cause: null,
    vis: "all",
    authz: null,
    data: { connector, card_id: cardId },
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

async function show(connector: "gmail" | "google_drive") {
  const cardId = connector === "gmail" ? GMAIL_CARD_ID : DRIVE_CARD_ID;
  const scopes =
    connector === "gmail"
      ? ["Read, search and draft email", "Send email you approve"]
      : ["Create and edit files in the Tilo folder only"];
  const client = new FixtureClient();
  const answers: string[] = [];
  client.listCards = async () => [consentCard(cardId, connector, scopes)];
  client.answerCard = async (_card, answer) => {
    answers.push(answer.option_id);
  };
  client.subscribeEvents = (_world, onEvent) => {
    onEvent(requested(cardId, connector));
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

const normal = (s: string | null | undefined) => (s ?? "").replace(/\s+/g, " ").trim();

describe("SEC-15 SIGNIN the Gmail consent sheet explains Google's unverified-app warning before the redirect", () => {
  it("SEC-15 SIGNIN a Gmail consent card shows the exact unverified-app sentence once, in the note element", async () => {
    const { container } = await show("gmail");
    const notes = container.querySelectorAll('[data-testid="consent-unverified-note"]');
    expect(notes).toHaveLength(1);
    expect(normal(notes[0]?.textContent)).toBe(UNVERIFIED_NOTE);
  });

  it("SEC-15 SIGNIN the note comes before the Connect and Hold buttons, so it is read before the answer", async () => {
    const { container } = await show("gmail");
    const note = container.querySelector('[data-testid="consent-unverified-note"]') as Element;
    expect(note).not.toBeNull();
    const connect = [...container.querySelectorAll("button")].find(
      (b) => b.textContent === "Connect",
    ) as Element;
    expect(connect).toBeDefined();
    // DOCUMENT_POSITION_FOLLOWING (4): `connect` follows `note`
    expect(note.compareDocumentPosition(connect) & 4).toBe(4);
  });

  it("SEC-15 SIGNIN nothing is sent to Google, or answered, by showing the note: only a click answers", async () => {
    const { container, answers } = await show("gmail");
    expect(answers).toEqual([]);
    expect([...container.querySelectorAll("button")].map((b) => b.textContent)).toEqual([
      "Connect",
      "Hold",
    ]);
  });

  it("SEC-15 SIGNIN a connector whose scopes Google does not flag (Drive's own-files scope) shows no such note", async () => {
    const { container } = await show("google_drive");
    expect(container.querySelector('[data-testid="consent-unverified-note"]')).toBeNull();
    expect(container.textContent).not.toMatch(/not verified|unverified/i);
  });

  it("SEC-15 SIGNIN the note says nothing that sounds like an instruction to skip checks or a promise Tilo cannot keep", async () => {
    const { container } = await show("gmail");
    const text = normal(
      container.querySelector('[data-testid="consent-unverified-note"]')?.textContent,
    );
    expect(text).not.toMatch(/\b(safe|secure|guarantee|certified|approved by google)\b/i);
    expect(text).not.toMatch(/password/i);
  });
});
