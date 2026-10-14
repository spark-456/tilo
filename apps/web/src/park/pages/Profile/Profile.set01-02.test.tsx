// @vitest-environment happy-dom
// FR-SET-01 / FR-SET-02 on the Profile page (ADR-0039): the Profile form, the notification matrix and quiet hours
// are the person's own UserSettings document, read and saved through the Api. A save is shown only after the server
// answered; every failure keeps the form and says nothing was saved. Fake settings server: testApp.withFakeSettings.
import { afterEach, describe, expect, it } from "vitest";
import { makeApp } from "../../../../test-support/park/profileApp";
import { TiloApiError } from "../../../api/http";
import { createFixtureApi } from "../../api/fixtureApi";
import { userSettings } from "../../api/fixtures";
import {
  buttonNamed,
  cleanup,
  clickAndSettle,
  fieldInput,
  openTab,
  renderProfile,
  settle,
  spyApi,
  switchNamed,
  text,
  typeInto,
  withFakeSettings,
} from "./testApp";

afterEach(cleanup);

const boom = new TiloApiError("Tilo had a problem on its side.", 500, true, true);
// M2-CODES-1 (5b57e7ef): a failed WRITE reads "could not confirm"; a failed READ (not a write) keeps the plain trouble line.
const readBoom = new TiloApiError("Tilo had a problem on its side.", 500, true);
const stale = new TiloApiError(
  "That cannot be done right now.",
  409,
  false,
  true,
  "version_conflict",
);
const alertText = (root: HTMLElement) => text(root.querySelector('[role="alert"]'));
const save = (root: HTMLElement) => buttonNamed(root, "Save changes");
const named = (root: HTMLElement, label: string) => fieldInput(root, label).value;

describe("FR_SET_01_profile_saved_per_person", () => {
  it("test_FR_SET_01_saved_is_said_only_after_the_server_answers_and_the_values_survive_a_new_session", async () => {
    const { api, server } = withFakeSettings();
    const app = makeApp();
    const a = await renderProfile(app, spyApi(api));
    await typeInto(fieldInput(a.root, "Full name"), "Ada Lovelace");
    const release = server.hold();
    await clickAndSettle(save(a.root));
    expect(app.toast, "no Profile saved before the answer").not.toHaveBeenCalled();
    expect(text(a.root)).toContain("Saving…");
    release();
    await settle();
    expect(app.toast).toHaveBeenCalledWith("Profile saved");
    expect(server.stored().profile.name).toBe("Ada Lovelace");
    a.m.unmount();
    const b = await renderProfile(makeApp(), spyApi(api));
    expect(named(b.root, "Full name")).toBe("Ada Lovelace");
  });

  it("test_FR_SET_01_the_write_carries_the_version_it_read_and_no_owner_org_or_time", async () => {
    const { api, server } = withFakeSettings();
    const a = await renderProfile(makeApp(), spyApi(api));
    await typeInto(fieldInput(a.root, "Job title"), "Analyst");
    await clickAndSettle(save(a.root));
    const [put] = server.puts;
    expect(Object.keys(put ?? {}).sort()).toEqual([
      "notifications",
      "profile",
      "quiet_hours",
      "version",
    ]);
    expect(put?.version).toBe(userSettings.version);
    expect(put?.profile.title).toBe("Analyst");
    expect(put?.profile.language).toBe("en-GB");
    expect(put?.profile.working_hours).toEqual(userSettings.profile.working_hours);
  });

  it("test_FR_SET_01_a_failed_save_keeps_the_form_says_nothing_was_saved_and_a_retry_works", async () => {
    const { api, server } = withFakeSettings();
    const app = makeApp();
    const a = await renderProfile(app, spyApi(api));
    await typeInto(fieldInput(a.root, "Full name"), "Ada Lovelace");
    server.failNext(boom);
    await clickAndSettle(save(a.root));
    expect(alertText(a.root)).toMatch(/Nothing was saved/);
    expect(named(a.root, "Full name")).toBe("Ada Lovelace");
    expect(app.toast).not.toHaveBeenCalled();
    expect(server.stored().profile.name).toBe("Alex Morgan");
    await clickAndSettle(save(a.root));
    expect(app.toast).toHaveBeenCalledWith("Profile saved");
    expect(a.root.querySelector('[role="alert"]')).toBeNull();
  });

  it("test_FR_SET_01_a_stale_version_is_refused_and_reload_shows_the_stored_document", async () => {
    const { api, server } = withFakeSettings();
    const a = await renderProfile(makeApp(), spyApi(api));
    await typeInto(fieldInput(a.root, "Full name"), "Ada Lovelace");
    server.failNext(stale);
    await clickAndSettle(save(a.root));
    expect(alertText(a.root)).toMatch(/changed on another device. Nothing was saved/);
    await clickAndSettle(buttonNamed(a.root, "Reload settings"));
    expect(named(a.root, "Full name")).toBe("Alex Morgan");
    expect(a.root.querySelector('[role="alert"]')).toBeNull();
  });

  it("test_FR_SET_01_unreadable_working_hours_are_not_sent_and_say_how_to_write_them", async () => {
    const { api, server } = withFakeSettings();
    const a = await renderProfile(makeApp(), spyApi(api));
    await typeInto(fieldInput(a.root, "Working hours"), "whenever");
    await clickAndSettle(save(a.root));
    expect(server.puts).toEqual([]);
    expect(alertText(a.root)).toMatch(/08:30 – 17:30, Monday to Friday/);
  });

  it("test_FR_SET_01_nothing_saved_yet_starts_from_who_signed_in_not_the_server_placeholder", async () => {
    const profile = {
      ...userSettings.profile,
      name: "Tilo user",
      email: "not-set@example.invalid",
    };
    const unsaved = { ...userSettings, version: 0, updated_at: null, profile };
    const { api, server } = withFakeSettings(createFixtureApi(), unsaved);
    const a = await renderProfile(makeApp(), spyApi(api));
    expect(named(a.root, "Full name")).toBe("Alex Morgan");
    expect(named(a.root, "Work email")).toBe("alex@northwind.co");
    await clickAndSettle(save(a.root));
    expect(server.puts[0]?.version).toBe(0);
    expect(server.puts[0]?.profile.name).toBe("Alex Morgan");
    expect(server.stored().version).toBe(1);
  });

  it("test_FR_SET_01_loading_failed_and_signed_out_are_honest_states_with_a_retry", async () => {
    const { api } = withFakeSettings();
    let calls = 0;
    const signedOut = new TiloApiError("You need to sign in to do this.", 401, false);
    const flaky = spyApi({
      ...api,
      getUserSettings: async () => {
        calls += 1;
        if (calls === 1) throw readBoom;
        if (calls === 2) throw signedOut;
        return api.getUserSettings();
      },
    });
    const a = await renderProfile(makeApp(), flaky);
    expect(a.root.querySelectorAll("input")).toHaveLength(0);
    expect(alertText(a.root)).toBe("Tilo had a problem on its side.");
    await clickAndSettle(buttonNamed(a.root, "Try again"));
    expect(alertText(a.root)).toBe("Sign in to see and save your settings.");
    await clickAndSettle(buttonNamed(a.root, "Try again"));
    expect(named(a.root, "Full name")).toBe("Alex Morgan");
  });

  it("test_FR_SET_01_a_demo_session_is_never_shown_as_saved", async () => {
    const app = makeApp();
    const a = await renderProfile(app, spyApi(createFixtureApi()));
    await typeInto(fieldInput(a.root, "Full name"), "Ada Lovelace");
    await clickAndSettle(save(a.root));
    expect(alertText(a.root)).toMatch(/demo, so nothing was saved/);
    expect(app.toast).not.toHaveBeenCalled();
  });

  it("test_FR_SET_01_cancel_returns_to_the_stored_values_and_an_unsaved_edit_does_not_persist", async () => {
    const { api } = withFakeSettings();
    const a = await renderProfile(makeApp(), spyApi(api));
    await typeInto(fieldInput(a.root, "Full name"), "Scratch");
    await clickAndSettle(buttonNamed(a.root, "Cancel"));
    expect(named(a.root, "Full name")).toBe("Alex Morgan");
    await typeInto(fieldInput(a.root, "Full name"), "Never Saved");
    a.m.unmount();
    const b = await renderProfile(makeApp(), spyApi(api));
    expect(named(b.root, "Full name")).toBe("Alex Morgan");
  });
});

describe("FR_SET_02_notifications_saved_per_person", () => {
  const decisions = (root: HTMLElement, c: string) =>
    switchNamed(root, `A decision needs you by ${c}`);
  const on = (root: HTMLElement, label: string) =>
    switchNamed(root, label).getAttribute("aria-checked");

  it("test_FR_SET_02_a_changed_row_and_quiet_hours_are_saved_whole_and_come_back", async () => {
    const { api, server } = withFakeSettings();
    const app = makeApp();
    const a = await renderProfile(app, spyApi(api));
    await openTab(a.root, "Notifications");
    await clickAndSettle(switchNamed(a.root, "Spend goes over a limit by Email"));
    await clickAndSettle(switchNamed(a.root, "Quiet hours"));
    expect(server.puts).toEqual([]);
    await clickAndSettle(save(a.root));
    expect(app.toast).toHaveBeenCalledWith("Notification settings saved");
    expect(server.stored().notifications.spend.email).toBe(false);
    expect(server.stored().quiet_hours.enabled).toBe(false);
    a.m.unmount();
    const b = await renderProfile(makeApp(), spyApi(api));
    await openTab(b.root, "Notifications");
    expect(on(b.root, "Spend goes over a limit by Email")).toBe("false");
    expect(on(b.root, "Quiet hours")).toBe("false");
  });

  it("test_FR_SET_02_a_failed_save_keeps_the_toggles_and_claims_nothing", async () => {
    const { api, server } = withFakeSettings();
    const app = makeApp();
    const a = await renderProfile(app, spyApi(api));
    await openTab(a.root, "Notifications");
    await clickAndSettle(switchNamed(a.root, "Work is ready by Phone"));
    server.failNext(boom);
    await clickAndSettle(save(a.root));
    expect(alertText(a.root)).toMatch(/Nothing was saved/);
    expect(on(a.root, "Work is ready by Phone")).toBe("false");
    expect(app.toast).not.toHaveBeenCalled();
    expect(server.stored().notifications.finished.phone).toBe(true);
  });

  it("test_FR_SET_02_the_last_decisions_channel_is_refused_and_never_sent_all_off", async () => {
    const { api, server } = withFakeSettings();
    const app = makeApp();
    const a = await renderProfile(app, spyApi(api));
    await openTab(a.root, "Notifications");
    await clickAndSettle(decisions(a.root, "Phone"));
    await clickAndSettle(decisions(a.root, "Email"));
    const slack = decisions(a.root, "Slack");
    expect(slack.getAttribute("aria-disabled")).toBe("true");
    await clickAndSettle(slack);
    expect(app.toast).toHaveBeenCalledWith("Decisions need at least one channel");
    await clickAndSettle(save(a.root));
    expect(server.puts[0]?.notifications.decisions).toEqual({
      phone: false,
      email: false,
      slack: true,
    });
  });

  it("test_FR_SET_02_a_profile_edit_not_yet_saved_is_not_sent_with_the_notifications", async () => {
    const { api, server } = withFakeSettings();
    const a = await renderProfile(makeApp(), spyApi(api));
    await typeInto(fieldInput(a.root, "Full name"), "Not Saved Here");
    await openTab(a.root, "Notifications");
    await clickAndSettle(switchNamed(a.root, "Morning digest at 08:00 by Phone"));
    await clickAndSettle(save(a.root));
    expect(server.puts[0]?.profile.name).toBe("Alex Morgan");
    expect(server.stored().notifications.digest.phone).toBe(true);
  });

  it("test_FR_SET_02_quiet_hours_note_stays_and_a_saved_threshold_is_never_promised_as_a_push_rule", async () => {
    const { api } = withFakeSettings();
    const a = await renderProfile(makeApp(), spyApi(api));
    await openTab(a.root, "Notifications");
    expect(text(a.root)).toMatch(/never hidden by quiet hours: it waits in Needs you/);
    expect(text(a.root)).not.toMatch(/except decisions over/);
    expect(text(a.root)).toContain("Quiet hours · 19:00 to 08:00");
  });
});
