// @vitest-environment happy-dom
import { act } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, mount } from "../../../../test-support/park/componentsHarness";
import { settle } from "../../../../test-support/park/homeHarness";
import type { BriefSettings, MorningBriefApi } from "../../api/live/morningBrief";
import { BriefSettingsPanel } from "./BriefSettingsPanel";

afterEach(cleanup);
const settings: BriefSettings = {
  owner_id: "u_a",
  org_id: "org_a",
  enabled: false,
  time: "07:30",
  time_zone: "UTC",
  email_copy: false,
  email_rule_ready: false,
  updated_at: null,
};
function api(over: Partial<MorningBriefApi> = {}): MorningBriefApi {
  return {
    read: vi.fn(),
    make: vi.fn(),
    settings: vi.fn(async () => settings),
    saveSettings: vi.fn(async (next) => ({
      ...settings,
      ...next,
      updated_at: "2026-10-16T02:00:05.000Z",
    })),
    addTodo: vi.fn(),
    ...over,
  };
}
const button = (root: HTMLElement, label: string) => {
  const found = [...root.querySelectorAll("button")].find((el) => el.textContent?.includes(label));
  if (!found) throw new Error(`Missing button ${label}`);
  return found;
};

describe("MO-02 brief settings", () => {
  it("test_MO_02_default_is_off_and_email_rule_note_is_honest", async () => {
    const m = mount(<BriefSettingsPanel api={api()} />);
    await settle();
    expect((m.container.querySelector('input[name="enabled"]') as HTMLInputElement).checked).toBe(
      false,
    );
    expect((m.container.querySelector('input[name="time"]') as HTMLInputElement).value).toBe(
      "07:30",
    );
    expect(m.container.textContent).toContain("Email copy needs your own standing send rule");
  });

  it("test_MO_02_save_uses_whole_settings_body_and_waits_for_committed_reply", async () => {
    let resolve!: (value: BriefSettings) => void;
    const client = api({
      saveSettings: vi.fn(
        () =>
          new Promise<BriefSettings>((r) => {
            resolve = r;
          }),
      ),
    });
    const m = mount(<BriefSettingsPanel api={client} />);
    await settle();
    await act(async () => {
      (m.container.querySelector('input[name="enabled"]') as HTMLInputElement).click();
    });
    await act(async () => {
      button(m.container, "Save brief settings").click();
    });
    expect(m.container.textContent).not.toContain("Saved brief settings");
    expect(client.saveSettings).toHaveBeenCalledWith({
      enabled: true,
      time: "07:30",
      time_zone: "UTC",
      email_copy: false,
    });
    await act(async () => {
      resolve({ ...settings, enabled: true, updated_at: "2026-10-16T02:00:05.000Z" });
    });
    expect(m.container.textContent).toContain("Saved brief settings");
  });
});
