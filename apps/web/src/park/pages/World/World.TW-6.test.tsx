import type { Event, Layout } from "@tilo/contracts";
// @vitest-environment happy-dom
// TW-6 acceptance: Needs-you on the stage (CX-SUP after TW-1)
// - approval.requested: agent hand up, amber "Needs you" chip with ping ring,
//   now-line turns amber with Review button -> approval card at top of Story
//   (exact action, plain-words risk, cost, Approve / Edit / Decline);
// - stops on approval.resolved.
import { act } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, click } from "../../../../test-support/park/componentsHarness";
import { liveWorldsApi, mountWorld, textOf } from "../../../../test-support/park/worldHarness";
import { villageBasicLayout } from "../../../../test-support/worldFixtures";
import { HttpClient } from "../../../api/http";
import { frameOf } from "../../../world/frame";
import { applyEvent, createInitialState } from "../../../world/reducer";
import { MapToast, latestLine } from "./MapChrome";
import { RunStory, activeApprovalOf } from "./Panels";
import type { RunEvent } from "./useRunEvents";

vi.mock("../../../worldView/LiveStageEmbed", () => ({
  default: ({ onReview }: { onReview?: () => void }) => (
    <div data-testid="live-stage-stub">
      <button
        type="button"
        data-testid="world-needs-chip"
        className="tw-needs-chip"
        onClick={onReview}
      >
        <span className="tw-needs-ping" />
        Needs you
      </button>
    </div>
  ),
  LiveChat: () => <div data-testid="live-chat-stub">Live chat</div>,
}));

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

let seq = 0;
const ev = (
  type: string,
  summary: string,
  data: unknown = {},
  extra: Partial<RunEvent> = {},
): RunEvent => ({
  seq: ++seq,
  type,
  ts: `2026-10-15T09:${String(seq).padStart(2, "0")}:00.000Z`,
  credits: 0,
  summary,
  data,
  ...extra,
});

function liveFeed() {
  const client = new HttpClient({
    baseUrl: "http://localhost:0",
    fetch: async () => new Response("{}", { status: 404 }),
  });
  let push: ((e: never) => void) | null = null;
  client.subscribeEvents = (_world, onEvent) => {
    push = onEvent as unknown as (e: never) => void;
    return () => undefined;
  };
  const emit = async (...events: RunEvent[]) => {
    await act(async () => {
      for (const e of events) push?.(e as never);
    });
  };
  return { client, emit };
}

describe("TW_6: Agent hand up in world reducer & frame", () => {
  const layout = villageBasicLayout() as unknown as Layout;

  it("TW_6_reducer_raises_hand_on_approval_requested_and_drops_on_approval_resolved", () => {
    let state = createInitialState(layout);
    // Spawn agent A_s1
    state = applyEvent(
      state,
      {
        id: "e1",
        world_id: "w_village_basic",
        seq: 1,
        type: "agent.spawned",
        ts: "2026-10-15T09:00:00.000Z",
        credits: 0,
        target: "A_s1",
        summary: "Specialist arrived.",
        data: {},
      } as unknown as Event,
      layout,
    );
    // Assign to Mail Room B1
    state = applyEvent(
      state,
      {
        id: "e1b",
        world_id: "w_village_basic",
        seq: 2,
        type: "agent.assigned",
        ts: "2026-10-15T09:00:30.000Z",
        credits: 0,
        actor: "A_s1",
        target: "B1",
        summary: "Specialist assigned to Mail Room.",
        data: {},
      } as unknown as Event,
      layout,
    );
    expect(state.agents.A_s1?.hand).toBe(false);

    // approval.requested raises hand
    state = applyEvent(
      state,
      {
        id: "e2",
        world_id: "w_village_basic",
        seq: 3,
        type: "approval.requested",
        ts: "2026-10-15T09:01:00.000Z",
        credits: 0,
        actor: "A_s1",
        summary: "Specialist needs your yes to send email.",
        data: { gate_id: "G1" },
      } as unknown as Event,
      layout,
    );
    expect(state.agents.A_s1?.hand).toBe(true);

    // frameOf reflects hand: true
    const frame1 = frameOf(layout, state);
    const frameAgent1 = frame1.agents.find((a) => a.id === "A_s1");
    expect(frameAgent1?.hand).toBe(true);

    // approval.resolved drops hand
    state = applyEvent(
      state,
      {
        id: "e3",
        world_id: "w_village_basic",
        seq: 4,
        type: "approval.resolved",
        ts: "2026-10-15T09:02:00.000Z",
        credits: 0,
        actor: "A_s1",
        summary: "Email approved.",
        data: { gate_id: "G1" },
      } as unknown as Event,
      layout,
    );
    expect(state.agents.A_s1?.hand).toBe(false);

    const frame2 = frameOf(layout, state);
    const frameAgent2 = frame2.agents.find((a) => a.id === "A_s1");
    expect(frameAgent2?.hand).toBe(false);
  });
});

describe("TW_6: MapToast (now-line) turns amber with Review button", () => {
  it("TW_6_latestLine_detects_active_approval_and_returns_needs_kind", () => {
    const events: RunEvent[] = [
      ev("world.started", "Run started."),
      ev(
        "approval.requested",
        "Juno needs your yes to book flights.",
        {
          question: "Book 3 economy seats on TAP Air Portugal?",
          exact: "POST https://api.flytap.com/v1/bookings",
          risk: "High. Non-refundable ticket purchase of €450.",
          cost: "2 credits",
          gate_id: "g_flight",
        },
        { actor: "Juno" },
      ),
    ];

    const line = latestLine(events, undefined);
    expect(line).not.toBeNull();
    expect(line?.kind).toBe("needs");
    expect(line?.text).toBe("Book 3 economy seats on TAP Air Portugal?");
    expect(line?.meta).toContain("Needs you");
  });

  it("TW_6_latestLine_reverts_after_approval_resolved", () => {
    const events: RunEvent[] = [
      ev("world.started", "Run started."),
      ev(
        "approval.requested",
        "Juno needs your yes to book flights.",
        { gate_id: "g_flight" },
        { actor: "Juno" },
      ),
      ev("approval.resolved", "Flights booked.", { gate_id: "g_flight" }, { actor: "Juno" }),
    ];

    const line = latestLine(events, undefined);
    expect(line).not.toBeNull();
    expect(line?.kind).toBe("info");
  });

  it("TW_6_MapToast_renders_Review_button_when_kind_is_needs", () => {
    const onReview = vi.fn();
    const line = {
      text: "Juno needs your yes",
      meta: "Needs you · 09:05 UTC",
      kind: "needs" as const,
    };
    const div = document.createElement("div");
    act(() => {
      // Mount MapToast
      const { createRoot } = require("react-dom/client");
      const root = createRoot(div);
      root.render(<MapToast line={line} onReview={onReview} />);
    });

    const toast = div.querySelector(".park-world-toast");
    expect(toast?.getAttribute("data-kind")).toBe("needs");

    const btn = div.querySelector("button.park-world-toast__act") as HTMLButtonElement | null;
    expect(btn).not.toBeNull();
    expect(textOf(btn as Element)).toBe("Review");

    click(btn as HTMLButtonElement);
    expect(onReview).toHaveBeenCalledTimes(1);
  });
});

describe("TW_6: RunStory approval card", () => {
  it("TW_6_activeApprovalOf_extracts_approval_details", () => {
    const events: RunEvent[] = [
      ev(
        "approval.requested",
        "Juno needs your yes",
        {
          question: "Send invitation emails to 12 participants?",
          exact: "Send 12 emails via Gmail connector",
          risk: "Medium. Recipients will see it immediately.",
          cost: "1 credit",
          gate_id: "g_invite",
        },
        { actor: "Juno", credits: 1 },
      ),
    ];

    const apr = activeApprovalOf(events);
    expect(apr).not.toBeNull();
    expect(apr?.who).toBe("Juno");
    expect(apr?.question).toBe("Send invitation emails to 12 participants?");
    expect(apr?.exact).toBe("Send 12 emails via Gmail connector");
    expect(apr?.risk).toBe("Medium. Recipients will see it immediately.");
    expect(apr?.cost).toBe("1 credit");
    expect(apr?.gateId).toBe("g_invite");
  });

  it("TW_6_RunStory_renders_approval_card_with_actions", () => {
    const onApprove = vi.fn();
    const onDecline = vi.fn();
    const onEdit = vi.fn();
    const events: RunEvent[] = [
      ev(
        "approval.requested",
        "Wren needs your yes",
        {
          question: "Deploy the new landing page?",
          exact: "Deploy to production hosting",
          risk: "Low. Instant rollback supported.",
          cost: "2 credits",
          gate_id: "g_deploy",
        },
        { actor: "Wren" },
      ),
    ];

    const div = document.createElement("div");
    act(() => {
      const { createRoot } = require("react-dom/client");
      const root = createRoot(div);
      root.render(
        <RunStory events={events} onApprove={onApprove} onDecline={onDecline} onEdit={onEdit} />,
      );
    });

    const card = div.querySelector('[aria-label="Needs you"]');
    expect(card).not.toBeNull();

    const who = card?.querySelector(".park-world-approval-who");
    expect(textOf(who as Element)).toBe("Wren needs your yes");

    const q = card?.querySelector(".park-world-approval-q");
    expect(textOf(q as Element)).toBe("Deploy the new landing page?");

    const exact = card?.querySelector(".park-world-approval-exacttxt");
    expect(textOf(exact as Element)).toBe("Deploy to production hosting");

    const approveBtn = card?.querySelector(
      ".park-world-approval-btn--approve",
    ) as HTMLButtonElement | null;
    const editBtn = card?.querySelector(
      ".park-world-approval-btn--edit",
    ) as HTMLButtonElement | null;
    const declineBtn = card?.querySelector(
      ".park-world-approval-btn--decline",
    ) as HTMLButtonElement | null;

    expect(approveBtn).not.toBeNull();
    expect(editBtn).not.toBeNull();
    expect(declineBtn).not.toBeNull();

    click(approveBtn as HTMLButtonElement);
    expect(onApprove).toHaveBeenCalledTimes(1);

    // Card shows local confirmation
    const done = card?.querySelector(".park-world-approval-done");
    expect(done).not.toBeNull();
    expect(textOf(done as Element)).toContain("Approved. Wren is continuing.");
  });

  it("TW_6_RunStory_removes_approval_card_when_approval_resolved", () => {
    const events: RunEvent[] = [
      ev("approval.requested", "Wren needs your yes", { gate_id: "g_deploy" }, { actor: "Wren" }),
      ev("approval.resolved", "Deployment approved.", { gate_id: "g_deploy" }, { actor: "Wren" }),
    ];

    const apr = activeApprovalOf(events);
    expect(apr).toBeNull();

    const div = document.createElement("div");
    act(() => {
      const { createRoot } = require("react-dom/client");
      const root = createRoot(div);
      root.render(<RunStory events={events} />);
    });

    const card = div.querySelector('[aria-label="Needs you"]');
    expect(card).toBeNull();
  });
});

describe("TW_6: Full WorldPage integration", () => {
  it("TW_6_approval_requested_shows_needs_toast_and_clicking_review_navigates_to_story", async () => {
    const { client, emit } = liveFeed();
    const { el } = await mountWorld({ id: "hires", api: liveWorldsApi(), client });

    await emit(
      ev("world.started", "Run started."),
      ev(
        "approval.requested",
        "Alex needs your yes",
        {
          question: "Confirm supplier booking?",
          exact: "Book order #482",
          risk: "Medium.",
          cost: "1 credit",
          gate_id: "g_book",
        },
        { actor: "Alex" },
      ),
    );

    // Toast is rendered with data-kind="needs" and Review button
    const toast = el.querySelector(".park-world-toast[data-kind='needs']");
    expect(toast).not.toBeNull();

    const reviewBtn = toast?.querySelector(".park-world-toast__act") as HTMLButtonElement | null;
    expect(reviewBtn).not.toBeNull();

    // Clicking Review opens Story tab
    click(reviewBtn as HTMLButtonElement);

    // Story tab has approval card
    const approvalCard = el.querySelector('[aria-label="Needs you"]');
    expect(approvalCard).not.toBeNull();
    expect(textOf(approvalCard as Element)).toContain("Alex needs your yes");
    expect(textOf(approvalCard as Element)).toContain("Confirm supplier booking?");

    // Resolving approval clears the approval card and reverts toast
    await emit(
      ev(
        "approval.resolved",
        "Supplier booking confirmed.",
        { gate_id: "g_book" },
        { actor: "Alex" },
      ),
    );

    const revertedToast = el.querySelector(".park-world-toast[data-kind='needs']");
    expect(revertedToast).toBeNull();

    const clearedCard = el.querySelector('[aria-label="Needs you"]');
    expect(clearedCard).toBeNull();
  });
});
