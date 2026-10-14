// @vitest-environment happy-dom
// FR-UX-17 acceptance tests on the World page: Share to Slack opens a dialog (channel from the Slack connector
// fixture, optional length-capped note, "Ask for approval") that adds one pending approval card ("Waiting for
// approval", plus "sample" in sample mode), never "Shared"; disabled with an explanation when Slack is not
// connected; traps focus, closes on Escape, and returns focus to the trigger.
import { act } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, click, q, qa } from "../../../../test-support/park/componentsHarness";
import {
  control,
  liveWorldsApi,
  mountWorld,
  pageText,
  spiedApi,
  textOf,
  toastCalls,
} from "../../../../test-support/park/worldHarness";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function must<T>(val: T | null | undefined, label = "element"): T {
  if (val === null || val === undefined) throw new Error(`missing ${label}`);
  return val;
}

function setFieldValue(
  el: HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement,
  value: string,
): void {
  act(() => {
    const proto =
      el instanceof HTMLSelectElement
        ? HTMLSelectElement.prototype
        : el instanceof HTMLTextAreaElement
          ? HTMLTextAreaElement.prototype
          : HTMLInputElement.prototype;
    const set = Object.getOwnPropertyDescriptor(proto, "value")?.set;
    set?.call(el, value);
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
  });
}

function pressKey(target: Element, key: string, shiftKey = false): boolean {
  let defaultPrevented = false;
  act(() => {
    const ev = new KeyboardEvent("keydown", {
      key,
      shiftKey,
      bubbles: true,
      cancelable: true,
    });
    target.dispatchEvent(ev);
    defaultPrevented = ev.defaultPrevented;
  });
  return defaultPrevented;
}

describe("FR_UX_17 World page: Share to Slack through the approval card", () => {
  it("test_FR_UX_17_share_to_slack_creates_one_pending_approval_and_never_shared_state", async () => {
    const rig = await mountWorld({ id: "hires" });
    expect(pageText(rig.el)).not.toContain("WAITING FOR YOU");

    const trigger = control(rig.el, "Share to Slack");
    click(trigger);

    const dialog = q(rig.el, '[role="dialog"]');
    expect(textOf(dialog)).toContain("northwind.slack.com");
    const select = q<HTMLSelectElement>(dialog, "select");
    const options = qa<HTMLOptionElement>(select, "option").map((o) => o.value);
    expect(options).toEqual(["#ops", "#k1-firmware"]);

    setFieldValue(select, options[1] ?? options[0] ?? "");
    const noteInput = must(
      dialog.querySelector<HTMLInputElement | HTMLTextAreaElement>("textarea, input"),
      "note input",
    );
    setFieldValue(noteInput, "Please review the hiring progress");

    click(control(dialog, "Ask for approval"));

    expect(rig.el.querySelector('[role="dialog"]')).toBeNull();
    expect(pageText(rig.el)).toContain("WAITING FOR YOU");
    expect(pageText(rig.el)).toContain("Waiting for approval · sample");
    expect(pageText(rig.el)).toContain("Please review the hiring progress");
    expect(pageText(rig.el)).not.toMatch(/\bshared\b/i);
    for (const call of toastCalls(rig.app)) {
      expect(String(call[0] ?? "")).not.toMatch(/\bshared\b/i);
    }

    // Submitting a second time for the same world keeps at most one pending Slack share approval card.
    click(control(rig.el, "Share to Slack"));
    click(control(q(rig.el, '[role="dialog"]'), "Ask for approval"));
    const pendingBadges = qa(rig.el, "*").filter(
      (e) => textOf(e) === "Waiting for approval · sample",
    );
    expect(pendingBadges).toHaveLength(1);

    cleanup();
    const liveRig = await mountWorld({ id: "hires", api: liveWorldsApi() });
    click(control(liveRig.el, "Share to Slack"));
    click(control(q(liveRig.el, '[role="dialog"]'), "Ask for approval"));
    expect(pageText(liveRig.el)).toContain("Waiting for approval");
    expect(pageText(liveRig.el)).not.toContain("Waiting for approval · sample");
    expect(pageText(liveRig.el)).not.toMatch(/\bshared\b/i);
  });

  it("UI_10_B7_the_dialog_of_a_sample_world_says_sample_and_that_nothing_is_sent", async () => {
    const rig = await mountWorld({ id: "hires" });
    click(control(rig.el, "Share to Slack"));
    const dialog = q(rig.el, '[role="dialog"]');
    expect(textOf(dialog)).toContain("Sample");
    expect(textOf(dialog)).toContain("Nothing is sent to Slack");
    cleanup();
    const live = await mountWorld({ id: "hires", api: liveWorldsApi() });
    click(control(live.el, "Share to Slack"));
    expect(textOf(q(live.el, '[role="dialog"]'))).not.toContain("Nothing is sent to Slack");
  });

  it("UI_10_B7_the_note_has_a_live_character_counter_to_the_240_limit", async () => {
    const rig = await mountWorld({ id: "hires" });
    click(control(rig.el, "Share to Slack"));
    const dialog = q(rig.el, '[role="dialog"]');
    expect(textOf(dialog)).toContain("0 / 240");
    setFieldValue(q<HTMLTextAreaElement>(dialog, "textarea"), "hello");
    expect(textOf(q(rig.el, '[role="dialog"]'))).toContain("5 / 240");
    setFieldValue(q<HTMLTextAreaElement>(dialog, "textarea"), "x".repeat(300));
    expect(textOf(q(rig.el, '[role="dialog"]'))).toContain("240 / 240");
  });

  it("UI_10_B7_a_click_on_the_backdrop_closes_the_dialog_and_a_click_inside_does_not", async () => {
    const rig = await mountWorld({ id: "hires" });
    click(control(rig.el, "Share to Slack"));
    click(q(rig.el, '[role="dialog"] .park-world-slacktitle'));
    expect(rig.el.querySelector('[role="dialog"]')).not.toBeNull();
    click(q(rig.el, ".park-world-slackbackdrop"));
    expect(rig.el.querySelector('[role="dialog"]')).toBeNull();
    // nothing was asked for: no pending approval card
    expect(pageText(rig.el)).not.toContain("Waiting for approval");
  });

  it("test_FR_UX_17_without_connected_slack_connector_action_is_disabled_and_explains_why", async () => {
    const api = spiedApi();
    const baseGetConnectors = api.getConnectors;
    api.getConnectors = vi.fn(async () => {
      const res = await baseGetConnectors();
      return {
        ...res,
        data: res.data.map((c) => (c.id === "slack" ? { ...c, st: "available" as const } : c)),
      };
    });

    const rig = await mountWorld({ id: "k1", api });
    const trigger = control(rig.el, "Share to Slack") as HTMLButtonElement;
    expect(trigger.disabled || trigger.getAttribute("aria-disabled") === "true").toBe(true);

    const describedById = trigger.getAttribute("aria-describedby");
    const descText = describedById
      ? (rig.el.querySelector(`#${describedById}`)?.textContent ?? "")
      : "";
    const explanation = `${trigger.getAttribute("title") ?? ""} ${descText}`;
    expect(explanation).toMatch(/slack/i);
    expect(explanation).toMatch(/connect/i);

    click(trigger);
    expect(rig.el.querySelector('[role="dialog"]')).toBeNull();

    // Also when Slack is connected but has no channels configured, the action is disabled with a reason.
    cleanup();
    const noChannelsApi = spiedApi();
    const baseNoChannels = noChannelsApi.getConnectors;
    noChannelsApi.getConnectors = vi.fn(async () => {
      const res = await baseNoChannels();
      return {
        ...res,
        data: res.data.map((c) => (c.id === "slack" ? { ...c, channels: [] } : c)),
      };
    });
    const noChRig = await mountWorld({ id: "k1", api: noChannelsApi });
    const noChTrigger = control(noChRig.el, "Share to Slack") as HTMLButtonElement;
    expect(noChTrigger.disabled || noChTrigger.getAttribute("aria-disabled") === "true").toBe(true);
    const noChDescId = noChTrigger.getAttribute("aria-describedby");
    const noChDesc = noChDescId
      ? (noChRig.el.querySelector(`#${noChDescId}`)?.textContent ?? "")
      : "";
    const noChReason = `${noChTrigger.getAttribute("title") ?? ""} ${noChDesc}`;
    expect(noChReason).toMatch(/channel/i);
    click(noChTrigger);
    expect(noChRig.el.querySelector('[role="dialog"]')).toBeNull();
  });

  it("test_FR_UX_17_note_is_length_capped_and_rendered_as_text_never_html", async () => {
    const rig = await mountWorld({ id: "hires" });
    click(control(rig.el, "Share to Slack"));

    const dialog = q(rig.el, '[role="dialog"]');
    const noteInput = must(
      dialog.querySelector<HTMLInputElement | HTMLTextAreaElement>("textarea, input"),
      "note input",
    );
    const rawHtml = `<script>window.__xss=1</script><img src=x onerror=alert(1)><b>bold</b>${"z".repeat(260)}`;
    setFieldValue(noteInput, rawHtml);
    expect(noteInput.value.length).toBeLessThanOrEqual(240);

    click(control(dialog, "Ask for approval"));

    expect(rig.el.querySelector("script")).toBeNull();
    expect(rig.el.querySelector('img[src="x"]')).toBeNull();
    expect(pageText(rig.el)).toContain("<script>window.__xss=1</script>");
    const cappedNote = rawHtml.slice(0, 240);
    expect(pageText(rig.el)).toContain(cappedNote);
    expect(pageText(rig.el)).not.toContain(rawHtml);
  });

  it("test_FR_UX_17_dialog_traps_focus_escape_closes_and_returns_focus_to_trigger", async () => {
    const rig = await mountWorld({ id: "k1" });
    const trigger = control(rig.el, "Share to Slack");
    trigger.focus();
    expect(document.activeElement).toBe(trigger);

    click(trigger);
    const dialog = q(rig.el, '[role="dialog"]');
    const focusables = qa<HTMLElement>(
      dialog,
      'select, textarea, input, button:not([disabled]), [tabindex]:not([tabindex="-1"])',
    );
    expect(focusables.length).toBeGreaterThanOrEqual(3);
    expect(dialog.contains(document.activeElement)).toBe(true);

    const first = must(focusables[0], "first focusable");
    const last = must(focusables[focusables.length - 1], "last focusable");
    last.focus();
    expect(document.activeElement).toBe(last);
    pressKey(last, "Tab", false);
    expect(document.activeElement).toBe(first);

    first.focus();
    pressKey(first, "Tab", true);
    expect(document.activeElement).toBe(last);

    pressKey(dialog, "Escape");
    expect(rig.el.querySelector('[role="dialog"]')).toBeNull();
    expect(document.activeElement).toBe(trigger);
  });
});
