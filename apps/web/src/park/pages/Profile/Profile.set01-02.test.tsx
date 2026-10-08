// @vitest-environment happy-dom
// FR-SET-01 / FR-SET-02 on the Profile page (AGY-WEB-4). The honest lines ("kept on this device only", "never
// hidden by quiet hours") are accessible descriptions (aria-description / title) here and, since BQ-SET-2 (user
// approved 8 Oct), visible helper text too (pinned in Profile.BQ_SET_2.test.tsx).
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { makeApp } from "../../../../test-support/park/profileApp";
import type { ApiResult, User } from "../../api/types";
import { clearProfileStore, profileKey } from "./profileStore";
import {
  buttonNamed,
  cleanup,
  clickAndSettle,
  fieldInput,
  openTab,
  renderProfile,
  spyApi,
  switchNamed,
  typeInto,
} from "./testApp";

beforeEach(() => {
  window.localStorage.clear();
  clearProfileStore();
});
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  window.localStorage.clear();
  clearProfileStore();
});

const as = (user: Partial<User>) => {
  const api = spyApi();
  const base = api.getUser;
  api.getUser = vi.fn(async () => {
    const r = (await base()) as ApiResult<User>;
    return { ...r, data: { ...r.data, ...user } };
  });
  return api;
};

describe("FR_SET_01_profile_save_persists_per_user", () => {
  it("test_FR_SET_01_save_toasts_and_the_saved_values_come_back_after_a_remount", async () => {
    const app = makeApp();
    const first = await renderProfile(app);
    await typeInto(fieldInput(first.root, "Full name"), "Ada Lovelace");
    await typeInto(fieldInput(first.root, "Job title"), "Analyst");
    await clickAndSettle(buttonNamed(first.root, "Save changes"));
    expect(app.toast).toHaveBeenCalledWith("Profile saved");
    first.m.unmount();

    const second = await renderProfile(makeApp());
    expect(fieldInput(second.root, "Full name").value).toBe("Ada Lovelace");
    expect(fieldInput(second.root, "Job title").value).toBe("Analyst");
    expect(second.root.querySelector("h1")?.textContent).toBe("Ada Lovelace");
  });

  it("test_FR_SET_01_an_unsaved_edit_does_not_persist", async () => {
    const first = await renderProfile(makeApp());
    await typeInto(fieldInput(first.root, "Full name"), "Never Saved");
    first.m.unmount();
    const second = await renderProfile(makeApp());
    expect(fieldInput(second.root, "Full name").value).toBe("Alex Morgan");
  });

  it("test_FR_SET_01_another_user_does_not_see_the_saved_values", async () => {
    const a = await renderProfile(makeApp(), as({ email: "alex@northwind.co" }));
    await typeInto(fieldInput(a.root, "Full name"), "Ada Lovelace");
    await clickAndSettle(buttonNamed(a.root, "Save changes"));
    a.m.unmount();
    expect(window.localStorage.getItem(profileKey("alex@northwind.co"))).not.toBeNull();

    const b = await renderProfile(makeApp(), as({ email: "sam@northwind.co", name: "Sam Stone" }));
    expect(fieldInput(b.root, "Full name").value).toBe("Sam Stone");
  });

  it("test_FR_SET_01_the_signed_in_identity_keys_the_save_even_when_the_email_field_is_edited", async () => {
    const a = await renderProfile(makeApp());
    await typeInto(fieldInput(a.root, "Work email"), "new@northwind.co");
    await clickAndSettle(buttonNamed(a.root, "Save changes"));
    a.m.unmount();
    const b = await renderProfile(makeApp());
    expect(fieldInput(b.root, "Work email").value).toBe("new@northwind.co");
  });

  it("test_FR_SET_01_cancel_restores_the_last_saved_values", async () => {
    const a = await renderProfile(makeApp());
    await typeInto(fieldInput(a.root, "Full name"), "Ada Lovelace");
    await clickAndSettle(buttonNamed(a.root, "Save changes"));
    await typeInto(fieldInput(a.root, "Full name"), "Scratch");
    await clickAndSettle(buttonNamed(a.root, "Cancel"));
    expect(fieldInput(a.root, "Full name").value).toBe("Ada Lovelace");
  });

  it("test_FR_SET_01_save_still_works_and_persists_for_the_session_when_localStorage_throws", async () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    const app = makeApp();
    const a = await renderProfile(app);
    await typeInto(fieldInput(a.root, "Full name"), "Ada Lovelace");
    await clickAndSettle(buttonNamed(a.root, "Save changes"));
    expect(app.toast).toHaveBeenCalledWith("Profile saved");
    a.m.unmount();
    const b = await renderProfile(makeApp());
    expect(fieldInput(b.root, "Full name").value).toBe("Ada Lovelace");
  });

  it("test_FR_SET_01_save_is_honest_it_is_kept_on_this_device_only_and_calls_no_api", async () => {
    const api = spyApi();
    const a = await renderProfile(makeApp(), api);
    const calls = () => Object.values(api).reduce((n, f) => n + f.mock.calls.length, 0);
    const before = calls();
    const save = buttonNamed(a.root, "Save changes");
    expect(save.getAttribute("aria-description") ?? "").toMatch(/this device only/i);
    await clickAndSettle(save);
    expect(calls(), "Save invents no server call").toBe(before);
  });
});

describe("FR_SET_02_notifications_page", () => {
  const decisions = (root: HTMLElement, c: string) =>
    switchNamed(root, `A decision needs you by ${c}`);

  it("test_FR_SET_02_the_last_decisions_channel_is_marked_unavailable_and_refused_with_copy", async () => {
    const app = makeApp();
    const { root } = await renderProfile(app);
    await openTab(root, "Notifications");
    await clickAndSettle(decisions(root, "Phone"));
    await clickAndSettle(decisions(root, "Email"));
    const slack = decisions(root, "Slack");
    expect(slack.getAttribute("aria-disabled")).toBe("true");
    expect(slack.getAttribute("title")).toBe("Decisions need at least one channel");
    expect(decisions(root, "Phone").getAttribute("aria-disabled")).not.toBe("true");
    await clickAndSettle(slack);
    expect(app.toast).toHaveBeenCalledWith("Decisions need at least one channel");
    expect(slack.getAttribute("aria-checked")).toBe("true");
    await clickAndSettle(decisions(root, "Phone"));
    expect(slack.getAttribute("aria-disabled")).not.toBe("true");
  });

  it("test_FR_SET_02_other_events_never_show_the_unavailable_mark", async () => {
    const { root } = await renderProfile(makeApp());
    await openTab(root, "Notifications");
    await clickAndSettle(switchNamed(root, "Morning digest at 08:00 by Email"));
    for (const s of root.querySelectorAll('[role="switch"]')) {
      if (!(s.getAttribute("aria-label") ?? "").startsWith("A decision")) {
        expect(s.getAttribute("aria-disabled")).not.toBe("true");
      }
    }
  });

  it("test_FR_SET_02_the_quiet_hours_control_says_a_gate_is_never_hidden", async () => {
    const { root } = await renderProfile(makeApp());
    await openTab(root, "Notifications");
    const quiet = switchNamed(root, "Quiet hours");
    expect(quiet.getAttribute("aria-description") ?? "").toMatch(
      /decision.*never hidden.*Needs you/i,
    );
  });
});
