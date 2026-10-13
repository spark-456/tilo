// @vitest-environment happy-dom
// QA-DEMO-1 (agy-bridge/reports/QA-DEMO-1.md), PR A: a demo session never shows progress, approvals or account
// facts that have no recorded event behind them (HR-1). B1 the composer's Start now, M3 Approve, M4 the Profile
// security and billing rows, m6 the notification rows.
import { act } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { fakeApi } from "../../../test-support/park/appHarness";
import { cleanup, click, q, qa } from "../../../test-support/park/componentsHarness";
import { mountApp, mountShell, seen, settle } from "../../../test-support/park/shellHarness";
import { HomePage } from "../pages/Home/HomePage";
import { ProfilePage } from "../pages/Profile/ProfilePage";
import { useApp } from "./context";
import { DEMO_DECIDE, DEMO_START } from "./store";

vi.mock("../engines/park", async () =>
  (await import("../../../test-support/park/shellEngine")).parkMock(),
);

afterEach(() => {
  cleanup();
  window.history.pushState({}, "", "/");
});

function Home() {
  return <HomePage app={useApp()} />;
}
function Profile() {
  return <ProfilePage app={useApp()} />;
}

const typeInto = (input: HTMLInputElement, value: string): void => {
  act(() => {
    const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
    set?.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
};
const text = (el: Element | null): string => (el?.textContent ?? "").replace(/\s+/g, " ").trim();

describe("QA_DEMO_1_B1 the composer in a demo session", () => {
  it("QA_DEMO_1_B1_start_now_starts_no_world_and_says_so_plainly", async () => {
    const api = fakeApi();
    const rig = mountShell(<Home />, { api, demo: true, path: "/" });
    await settle();
    typeInto(
      q<HTMLInputElement>(rig.m.container, 'input[aria-label="Describe your task"]'),
      "Summarise this week's customer feedback",
    );
    click(q(rig.m.container, ".park-home-start"));
    act(() => rig.sch.fire(rig.sch.live().find((t) => t.ms === 900)));
    await settle();
    // the plan is labelled a sample, and the confirm control no longer claims to start anything
    const plan = q(rig.m.container, ".park-home-plan");
    expect(text(plan)).toContain(
      "Sample plan. Demo sessions replay a recorded run; sign in to start your own.",
    );
    expect(text(q(plan, ".park-home-confirm"))).toBe("Open the sample world");
    expect(text(plan)).not.toContain("Start now");
    click(q(plan, ".park-home-confirm"));
    await settle();
    expect(api.startWorld).not.toHaveBeenCalled();
    expect(seen.store.getState().added).toHaveLength(0);
    expect(seen.store.getState().toast?.message).toBe(DEMO_START);
    // it opens an existing sample world (never "new1"), so nothing is left "Starting 4%"
    const target = String(rig.navigate.mock.calls.at(-1)?.[0] ?? "");
    expect(target).toMatch(/^\/world\/(?!new)/);
  });

  it("QA_DEMO_1_B1_the_drafting_line_does_not_claim_a_model_is_drafting", async () => {
    const rig = mountShell(<Home />, { api: fakeApi(), demo: true, path: "/" });
    await settle();
    click(q(rig.m.container, ".park-home-start"));
    await settle();
    const line = text(q(rig.m.container, ".park-home-drafting"));
    expect(line).toContain("Showing a sample plan");
    expect(line).not.toContain("Tilo is drafting");
  });

  it("QA_DEMO_1_B1_a_non_demo_fixture_session_keeps_the_designed_start", async () => {
    const api = fakeApi();
    const rig = mountShell(<Home />, { api, path: "/" });
    await settle();
    click(q(rig.m.container, ".park-home-start"));
    act(() => rig.sch.fire(rig.sch.live().find((t) => t.ms === 900)));
    await settle();
    expect(text(q(rig.m.container, ".park-home-confirm"))).not.toBe("Open the sample world");
  });
});

describe("QA_DEMO_1_M3 approving in a demo session", () => {
  it("QA_DEMO_1_M3_approve_records_nothing_and_is_explained_as_sample", async () => {
    const api = fakeApi();
    mountShell(<div />, { api, demo: true });
    await settle();
    act(() => seen.app.decide("depot"));
    expect(api.decide).not.toHaveBeenCalled();
    expect(seen.store.getState().dec).toEqual({});
    expect(seen.store.getState().toast?.message).toBe(DEMO_DECIDE);
    expect(seen.store.getState().needsLeft).toBe(2);
  });

  it("QA_DEMO_1_M3_a_non_demo_fixture_session_still_takes_the_decision", async () => {
    mountShell(<div />, { api: fakeApi() });
    await settle();
    act(() => seen.app.decide("depot"));
    await settle();
    expect(seen.store.getState().dec).toEqual({ depot: true });
  });
});

describe("QA_DEMO_1_M4 Profile in a demo session", () => {
  const open = async (tab: string) => {
    const rig = mountShell(<Profile />, { api: fakeApi(), demo: true, path: "/profile" });
    await settle();
    const t = qa<HTMLButtonElement>(rig.m.container, "nav button").find((b) => text(b) === tab);
    click(t as HTMLButtonElement);
    await settle();
    return rig.m.container;
  };

  it("QA_DEMO_1_M4_security_has_no_face_id_or_phone_app_claim_and_is_labelled_sample", async () => {
    const root = await open("Security");
    const all = text(root);
    expect(all).not.toMatch(/face id/i);
    expect(all).not.toContain("iPhone");
    expect(all).not.toContain("Tilo app");
    expect(text(q(root, "h2"))).toContain("Sample");
    expect(all).toContain("Sample account: these are not your account's details.");
  });

  it("QA_DEMO_1_M4_plan_and_billing_say_sample_data", async () => {
    const root = await open("Plan and billing");
    expect(text(root)).toContain("Sample account: these are not your account's details.");
  });

  it("QA_DEMO_1_M4_the_face_id_row_is_gone_in_every_session", async () => {
    const rig = mountShell(<Profile />, { api: fakeApi(), path: "/profile" });
    await settle();
    click(
      qa<HTMLButtonElement>(rig.m.container, "nav button").find(
        (b) => text(b) === "Security",
      ) as HTMLButtonElement,
    );
    await settle();
    expect(text(rig.m.container)).not.toMatch(/Confirm approvals with Face ID/);
  });
});

describe("QA_DEMO_1_m6 notifications in a demo session", () => {
  it("QA_DEMO_1_m6_every_row_carries_the_sample_label", async () => {
    await mountApp({ api: fakeApi(), demo: true });
    click(q(document.body, 'button[aria-label="Notifications"]'));
    await settle();
    const rows = qa(
      q(document.body, '[role="dialog"][aria-label="Notifications"]'),
      "button[data-kind]",
    );
    expect(rows.length).toBeGreaterThan(0);
    for (const r of rows) expect(text(r)).toContain("Sample");
  });

  it("QA_DEMO_1_m6_a_non_demo_session_adds_no_label", async () => {
    await mountApp({ api: fakeApi() });
    click(q(document.body, 'button[aria-label="Notifications"]'));
    await settle();
    const rows = qa(
      q(document.body, '[role="dialog"][aria-label="Notifications"]'),
      "button[data-kind]",
    );
    for (const r of rows) expect(text(r)).not.toContain("Sample");
  });
});
