// @vitest-environment happy-dom
// FR-UX-17 acceptance tests on the Worlds page: Share to Slack opens a dialog (channel from the Slack connector
// fixture, optional length-capped note, "Ask for approval") that creates one pending approval card in Spotlight
// ("Waiting for approval", plus "sample" in sample mode), never "Shared"; disabled with an explanation when Slack
// is not connected; traps focus, closes on Escape, and returns focus to the trigger.
import { act } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, click, q, qa } from "../../../../test-support/park/componentsHarness";
import {
  buttons,
  leaf,
  renderWorlds,
  worldsApi,
} from "../../../../test-support/park/worldsHarness";

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

describe("FR_UX_17 Worlds page: Share to Slack through the approval card", () => {
  it("test_FR_UX_17_worlds_share_to_slack_creates_one_pending_approval_and_never_shared_state", async () => {
    const r = await renderWorlds({ dec: { depot: true, mail: true } });
    expect(leaf(r.c, "You’re all caught up")).not.toBeNull();

    const trigger = must(buttons(r.c, "Share to Slack")[0], "Share to Slack button");
    click(trigger);

    const dialog = q(r.c, '[role="dialog"]');
    expect(dialog.textContent ?? "").toContain("northwind.slack.com");
    const selects = qa<HTMLSelectElement>(dialog, "select");
    const channelSelect = must(selects[selects.length - 1], "channel select");
    const options = qa<HTMLOptionElement>(channelSelect, "option").map((o) => o.value);
    expect(options.length).toBeGreaterThanOrEqual(2);
    expect(options[0]).toMatch(/^#/);

    setFieldValue(channelSelect, options[1] ?? options[0] ?? "#ops");
    const noteInput = must(
      dialog.querySelector<HTMLInputElement | HTMLTextAreaElement>("textarea, input"),
      "note input",
    );
    setFieldValue(noteInput, "Share weekly world status");

    click(must(buttons(dialog, "Ask for approval")[0], "Ask for approval button"));

    expect(r.c.querySelector('[role="dialog"]')).toBeNull();
    expect(leaf(r.c, "WAITING FOR YOU")).not.toBeNull();
    expect(r.c.textContent ?? "").toContain("Waiting for approval · sample");
    expect(r.c.textContent ?? "").toContain("Share weekly world status");
    expect(r.c.textContent ?? "").not.toMatch(/\bshared\b/i);

    // Repeating for the same world keeps one pending Slack share approval card.
    click(must(buttons(r.c, "Share to Slack")[0], "Share to Slack button"));
    click(
      must(buttons(q(r.c, '[role="dialog"]'), "Ask for approval")[0], "Ask for approval button"),
    );
    expect(
      qa(r.c, "*").filter((e) => e.textContent?.trim() === "Waiting for approval · sample"),
    ).toHaveLength(1);
  });

  it("test_FR_UX_17_worlds_without_connected_slack_connector_action_is_disabled_and_explains_why", async () => {
    const api = worldsApi();
    const baseGetConnectors = api.getConnectors.bind(api);
    api.getConnectors = vi.fn(async () => {
      const res = await baseGetConnectors();
      return {
        ...res,
        data: res.data.map((c) => (c.id === "slack" ? { ...c, st: "available" as const } : c)),
      };
    });

    const r = await renderWorlds({ api });
    const trigger = must(buttons(r.c, "Share to Slack")[0], "Share to Slack button");
    expect(trigger.disabled || trigger.getAttribute("aria-disabled") === "true").toBe(true);

    const describedById = trigger.getAttribute("aria-describedby");
    const descText = describedById
      ? (r.c.querySelector(`#${describedById}`)?.textContent ?? "")
      : "";
    const explanation = `${trigger.getAttribute("title") ?? ""} ${descText}`;
    expect(explanation).toMatch(/slack/i);
    expect(explanation).toMatch(/connect/i);

    click(trigger);
    expect(r.c.querySelector('[role="dialog"]')).toBeNull();
  });

  it("test_FR_UX_17_worlds_note_is_length_capped_and_rendered_as_text_never_html", async () => {
    const r = await renderWorlds();
    click(must(buttons(r.c, "Share to Slack")[0], "Share to Slack button"));

    const dialog = q(r.c, '[role="dialog"]');
    const noteInput = must(
      dialog.querySelector<HTMLInputElement | HTMLTextAreaElement>("textarea, input"),
      "note input",
    );
    const rawHtml = `<script>window.__xss=2</script><b>urgent</b>${"y".repeat(260)}`;
    setFieldValue(noteInput, rawHtml);
    expect(noteInput.value.length).toBeLessThanOrEqual(240);

    click(must(buttons(dialog, "Ask for approval")[0], "Ask for approval button"));

    expect(r.c.querySelector("script")).toBeNull();
    expect(r.c.textContent ?? "").toContain("<script>window.__xss=2</script><b>urgent</b>");
    expect(r.c.textContent ?? "").toContain(rawHtml.slice(0, 240));
    expect(r.c.textContent ?? "").not.toContain(rawHtml);
  });

  it("test_FR_UX_17_worlds_dialog_traps_focus_escape_closes_and_returns_focus_to_trigger", async () => {
    const r = await renderWorlds();
    const trigger = must(buttons(r.c, "Share to Slack")[0], "Share to Slack button");
    trigger.focus();
    expect(document.activeElement).toBe(trigger);

    click(trigger);
    const dialog = q(r.c, '[role="dialog"]');
    const focusables = qa<HTMLElement>(
      dialog,
      'select, textarea, input, button:not([disabled]), [tabindex]:not([tabindex="-1"])',
    );
    expect(focusables.length).toBeGreaterThanOrEqual(3);
    expect(dialog.contains(document.activeElement)).toBe(true);

    const first = must(focusables[0], "first focusable");
    const last = must(focusables[focusables.length - 1], "last focusable");
    last.focus();
    pressKey(last, "Tab", false);
    expect(document.activeElement).toBe(first);

    first.focus();
    pressKey(first, "Tab", true);
    expect(document.activeElement).toBe(last);

    pressKey(dialog, "Escape");
    expect(r.c.querySelector('[role="dialog"]')).toBeNull();
    expect(document.activeElement).toBe(trigger);
  });
});
