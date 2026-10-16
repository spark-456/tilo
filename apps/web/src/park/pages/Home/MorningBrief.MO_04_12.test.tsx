import { act } from "react";
// @vitest-environment happy-dom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, mount } from "../../../../test-support/park/componentsHarness";
import { settle } from "../../../../test-support/park/homeHarness";
import { TiloApiError } from "../../../api/http";
import type { MorningBrief, MorningBriefApi } from "../../api/live/morningBrief";
import { MorningBriefCard } from "./MorningBriefCard";

afterEach(cleanup);
const source = { kind: "mail" as const, id: "msg_1" };
const mail = { from_name: "Priya", subject: "Budget", received_at: null, source };
const brief = {
  v: "1.0" as const,
  owner: "u_alex",
  local_date: "2026-10-16",
  time_zone: "Asia/Kolkata",
  generated_at: "2026-10-16T02:00:05.000Z",
  trigger: "on_demand" as const,
  model: "used" as const,
  meetings: { status: "not_connected" as const, items: [] },
  mail_needing_reply: { status: "unsorted" as const, items: [mail] },
  deadlines: { status: "unavailable" as const, items: [] },
  suggestions: [{ text: "Review the budget", cites: [source] }],
  todo_suggestions: [{ title: "Review budget", due_text: "tomorrow", mail }],
};
const settings = {
  owner_id: "u_alex",
  org_id: "org_a",
  enabled: true,
  time: "07:30",
  time_zone: "Asia/Kolkata",
  email_copy: false,
  email_rule_ready: false,
  updated_at: null,
};
function api(over: Partial<MorningBriefApi> = {}): MorningBriefApi {
  return {
    read: vi.fn(async () => brief),
    make: vi.fn(async () => brief),
    settings: vi.fn(async () => settings),
    saveSettings: vi.fn(async () => settings),
    addTodo: vi.fn(async () => ({ id: "wi_1", title: "Review budget" })),
    ...over,
  };
}
const text = (el: HTMLElement) => el.textContent ?? "";
const button = (el: HTMLElement, label: string) => {
  const found = [...el.querySelectorAll("button")].find((b) => b.textContent?.includes(label));
  if (!found) throw new Error(`Missing button: ${label}`);
  return found;
};

describe("MO-04/12 morning brief card", () => {
  it("test_MO_12_not_ready_shows_arrival_time_and_never_claims_mail_needs_a_reply", async () => {
    const client = api({
      read: vi.fn(async () => {
        throw new TiloApiError("not_ready", 404, false);
      }),
    });
    const m = mount(<MorningBriefCard api={client} />);
    await settle();
    expect(text(m.container)).toContain("Your brief arrives at 07:30");
    expect(text(m.container)).not.toContain("needs a reply");
  });

  it("test_MO_12_sections_keep_unavailable_and_unsorted_distinct_and_show_source", async () => {
    const m = mount(<MorningBriefCard api={api()} />);
    await settle();
    expect(text(m.container)).toContain("Connect your calendar");
    expect(text(m.container)).toContain("Unread mail");
    expect(text(m.container)).toContain("Could not read deadlines today");
    expect(text(m.container)).toContain("Priya");
    expect(text(m.container)).toContain("Generated");
    expect(text(m.container)).toContain("Review the budget");
    expect(text(m.container)).toContain("Budget");
  });

  it("test_MO_04_make_it_now_waits_for_the_server_and_updates_from_its_reply", async () => {
    let resolve!: (value: MorningBrief) => void;
    const client = api({
      make: vi.fn(
        () =>
          new Promise<MorningBrief>((r) => {
            resolve = r;
          }),
      ),
    });
    const m = mount(<MorningBriefCard api={client} />);
    await settle();
    await act(async () => {
      button(m.container, "Make it now").click();
    });
    expect(button(m.container, "Making your brief").hasAttribute("disabled")).toBe(true);
    await act(async () => {
      resolve(brief);
    });
    expect(text(m.container)).toContain("Review the budget");
    expect(client.make).toHaveBeenCalledTimes(1);
  });

  it("test_MO_11_todo_is_only_added_after_person_confirms_and_write_commits", async () => {
    let resolve!: (value: { id: string; title: string }) => void;
    const client = api({
      addTodo: vi.fn(
        () =>
          new Promise<{ id: string; title: string }>((r) => {
            resolve = r;
          }),
      ),
    });
    const m = mount(<MorningBriefCard api={client} />);
    await settle();
    expect(client.addTodo).not.toHaveBeenCalled();
    await act(async () => {
      button(m.container, "Add to-do").click();
    });
    expect(text(m.container)).not.toContain("Added to your work items");
    await act(async () => {
      resolve({ id: "wi_1", title: "Review budget" });
    });
    expect(client.addTodo).toHaveBeenCalledWith(brief.todo_suggestions[0]);
    expect(text(m.container)).toContain("Added to your work items");
  });
});
