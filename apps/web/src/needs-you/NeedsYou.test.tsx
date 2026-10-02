// @vitest-environment happy-dom
// AGW-05 S-06 card and S-07 gate sheet (FR-HIL-01 UI side, FR-WLD-09, PRD 18.4, 9.4 HR-1, HR-7).
import type { Event } from "@tilo/contracts";
import { act } from "react";
import { type Root, createRoot } from "react-dom/client";
import { afterEach, describe, expect, it } from "vitest";
import {
  GATE_REPLY,
  GATE_SAVE,
  QUESTION,
  ev,
  liveClient,
  requested,
  resolved,
} from "../../test-support/needsYou";
import { ClientProvider } from "../api/ClientProvider";
import { CARDS_VALID } from "../api/fixtures/cards";
import { LAYOUT_VILLAGE_BASIC } from "../api/fixtures/layout";
import { S_06 } from "../screens/S_06";
import { S_07 } from "../screens/S_07";
import { CardView } from "./CardView";
import { GateSheet } from "./GateSheet";
import { gatesOf } from "./gates";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root | null = null;
afterEach(() => {
  act(() => root?.unmount());
  document.body.replaceChildren();
});

async function draw(node: React.ReactElement): Promise<HTMLElement> {
  const container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  await act(async () => root?.render(node));
  return container;
}

const labels = (c: HTMLElement) =>
  [...c.querySelectorAll('[role="radiogroup"] b')].map((b) => b.textContent);
const view = (card = GATE_REPLY, events: Event[] = [requested(1)]) => {
  const record = gatesOf(events)[0];
  if (!record) throw new Error("no gate");
  return <GateSheet record={record} card={card} layout={LAYOUT_VILLAGE_BASIC} answer={null} />;
};

describe("FR-HIL-01 S-06: renders every card fixture in contracts/fixtures/card/valid", () => {
  for (const [i, card] of CARDS_VALID.entries()) {
    it(`card ${i + 1} (${card.rung}) shows header, what happened, why it matters and options`, async () => {
      const c = await draw(<CardView card={card} layout={LAYOUT_VILLAGE_BASIC} answer={null} />);
      expect(c.querySelector(".need-head")?.textContent).toMatch(/\S · \S/); // rung, then building · agent
      expect(c.querySelector(".need-head")?.textContent).not.toMatch(/\bA_[a-z0-9]+\b|\bB\d\b/); // names, not ids
      expect(c.textContent).toContain(card.what_happened);
      expect(c.textContent).toContain(card.why_it_matters);
      expect(labels(c)).toEqual(card.options.map((o) => o.label));
      expect(c.textContent).toContain("Suggested"); // exactly one option is marked
      expect(c.querySelectorAll(".btag[data-tone=suggested]")).toHaveLength(1);
      expect(c.querySelector("button.primary")).toBeNull(); // read-only: nothing to send
    });
  }
});

describe("FR-HIL-01 S-07: the gate sheet names the exact action, the recipient and the irreversibility", () => {
  it("shows the card's exact action, its recipient and that a send can't be unsent", async () => {
    const c = await draw(view());
    expect(c.textContent).toContain(GATE_REPLY.gate?.action.exact);
    expect(c.textContent).toContain("orders@example.com");
    expect(c.textContent).toContain("Once sent, it can't be unsent.");
  });
  it("says a reversible save can be undone and has no recipient", async () => {
    const c = await draw(view(GATE_SAVE, [requested(1, GATE_SAVE)]));
    expect(c.textContent).toContain(GATE_SAVE.gate?.action.exact);
    expect(c.textContent).toContain("Yes, you can undo it afterwards.");
    expect(c.textContent).not.toContain("can't be unsent");
  });
  it("FR-HIL-01 S-07: gate options are exactly Approve, Edit first, Hold", async () => {
    expect(labels(await draw(view()))).toEqual(["Approve", "Edit first", "Hold"]);
  });
  it("suggests one option and never preselects an irreversible approve", async () => {
    const c = await draw(view());
    const chosen = c.querySelector<HTMLInputElement>("input:checked");
    expect(chosen?.value).toBe("edit"); // the suggested one; approve is irreversible here
  });
});

describe("FR-WLD-09 HR-7: a policy-opened gate shows the policy stamp and colour; a person-opened gate does not", () => {
  const policy = ev(
    5,
    "policy.applied",
    {
      policy_id: "pol_autopilot_l2",
      gate_id: "G1",
      action_type: "send_email",
      connector: "gmail",
      risk_tier: "T2",
      level: "L2",
      undo_window_s: 60,
    },
    { authz: { by: "policy", ref: "pol_autopilot_l2", at: "2026-09-29T09:42:16.000Z" } },
  );
  it("shows the stamp, the rule's name, the undo window and a link to the authorisation", async () => {
    const c = await draw(view(GATE_REPLY, [policy]));
    const sheet = c.querySelector('[data-testid="gate-sheet"]');
    expect(sheet?.getAttribute("data-opened-by")).toBe("policy");
    expect(c.querySelector('[data-testid="policy-stamp"]')?.textContent).toContain("Policy");
    expect(c.textContent).toContain("Sent under your rule 'Autopilot L2'. Undo within 60 s.");
    expect(c.querySelector("a")?.getAttribute("href")).toMatch(/\/trace$/);
  });
  it("shows no stamp and no rule line for a gate a person approved, and links the authorisation", async () => {
    const c = await draw(view(GATE_REPLY, [requested(1), resolved(2, "approve")]));
    expect(c.querySelector('[data-testid="gate-sheet"]')?.getAttribute("data-opened-by")).toBe(
      "person",
    );
    expect(c.querySelector('[data-testid="policy-stamp"]')).toBeNull();
    expect(c.textContent).not.toContain("under your rule");
    expect(c.textContent).toContain("Opened. You approved this at");
    expect(c.querySelector("a")?.getAttribute("href")).toMatch(/\/trace$/);
  });
  it("keeps a gate shut for Hold and Edit first", async () => {
    const c = await draw(view(GATE_REPLY, [requested(1), resolved(2, "hold")]));
    expect(c.querySelector('[data-testid="gate-sheet"]')?.getAttribute("data-opened-by")).toBe(
      "none",
    );
    expect(c.textContent).toContain("Kept closed. You chose Hold");
  });
});

describe("FR-WLD-09 HR-1: after Approve, the gate is not shown opened until approval.resolved arrives", () => {
  it("sends the answer, waits for confirmation, and opens only on the recorded event", async () => {
    const { client, sent, push } = liveClient([GATE_REPLY]);
    const c = await draw(
      <ClientProvider client={client}>
        <S_07 />
      </ClientProvider>,
    );
    await push(requested(1));
    const sheet = () => c.querySelector('[data-testid="gate-sheet"]');
    expect(sheet()?.getAttribute("data-gate-state")).toBe("waiting");

    const approve = [...c.querySelectorAll<HTMLInputElement>("input[type=radio]")].find(
      (r) => r.value === "approve",
    );
    await act(async () => approve?.click());
    const send = c.querySelector<HTMLButtonElement>("button.primary");
    expect(send?.textContent).toBe("Approve");
    await act(async () => send?.click());

    expect(sent).toEqual([[GATE_REPLY.id, { option_id: "approve" }]]);
    expect(c.textContent).toContain("Waiting for confirmation…");
    expect(sheet()?.getAttribute("data-gate-state")).toBe("waiting"); // not opened by the click
    expect(sheet()?.getAttribute("data-opened-by")).toBe("none");
    expect(c.textContent).not.toContain("Opened.");
    expect(c.querySelector<HTMLButtonElement>("button.primary")?.disabled).toBe(true);

    await push(resolved(2, "approve"));
    expect(sheet()?.getAttribute("data-gate-state")).toBe("decided");
    expect(sheet()?.getAttribute("data-opened-by")).toBe("person");
    expect(c.textContent).toContain("Opened. You approved this");
    expect(c.textContent).not.toContain("Waiting for confirmation");
  });

  it("frees the button and says what happened when the client rejects the answer", async () => {
    const { client, push } = liveClient([GATE_REPLY]);
    client.answerCard = async () => {
      throw new Error("the service is down");
    };
    const c = await draw(
      <ClientProvider client={client}>
        <S_07 />
      </ClientProvider>,
    );
    await push(requested(1));
    await act(async () => c.querySelector<HTMLButtonElement>("button.primary")?.click());
    expect(c.querySelector('[role="alert"]')?.textContent).toContain("the service is down");
    expect(c.querySelector<HTMLButtonElement>("button.primary")?.disabled).toBe(false);
    expect(c.textContent).not.toContain("Waiting for confirmation…");
  });

  it("closes a question only when question.answered arrives", async () => {
    const { client, sent, push } = liveClient([QUESTION]);
    const c = await draw(
      <ClientProvider client={client}>
        <S_06 />
      </ClientProvider>,
    );
    await push(
      ev(
        1,
        "question.routed",
        { card_id: QUESTION.id, domain: null },
        { actor: "A_s1", target: "u_owner" },
      ),
    );
    await act(async () => c.querySelector<HTMLButtonElement>("button[aria-pressed]")?.click());
    await act(async () => c.querySelector<HTMLButtonElement>("button.primary")?.click());
    expect(sent[0]?.[1]).toEqual({ option_id: "per_kwh" });
    expect(c.textContent).toContain("Waiting for confirmation…");
    expect(c.querySelectorAll('[data-testid="needs-queue"] li')).toHaveLength(1);
    await push(
      ev(2, "question.answered", { answered_by: "person" }, { actor: "u_owner", target: "A_s1" }),
    );
    expect(c.querySelectorAll('[data-testid="needs-queue"] li')).toHaveLength(0);
    expect(c.textContent).not.toContain("Waiting for confirmation");
  });
});
