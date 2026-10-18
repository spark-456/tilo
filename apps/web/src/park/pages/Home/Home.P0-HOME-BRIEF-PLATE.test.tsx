// @vitest-environment happy-dom
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, mount } from "../../../../test-support/park/componentsHarness";
import { settle } from "../../../../test-support/park/homeHarness";
import type { MorningBrief, MorningBriefApi } from "../../api/live/morningBrief";
import { MorningBriefCard } from "./MorningBriefCard";
import { homeTarget } from "./homeTargets";

afterEach(cleanup);

const source = (
  kind: "calendar_event" | "mail" | "work_item" | "pinboard_item" | "world",
  id: string,
) => ({ kind, id });

const brief: MorningBrief = {
  v: "1.0",
  owner: "u_owner",
  local_date: "2026-10-18",
  time_zone: "Asia/Kolkata",
  generated_at: "2026-10-18T02:00:00Z",
  trigger: "on_demand",
  model: "used",
  meetings: {
    status: "ok",
    items: [
      { title: "Planning call", start: "09:00", source: source("calendar_event", "ce_plan") },
    ],
  },
  mail_needing_reply: {
    status: "ok",
    items: [
      {
        from_name: "Priya",
        subject: "Private mail",
        received_at: null,
        source: source("mail", "m_1"),
      },
    ],
  },
  deadlines: {
    status: "ok",
    items: [{ title: "Approve quote", due: "today", source: source("work_item", "wi_quote") }],
  },
  suggestions: [
    { text: "Open the launch world", cites: [source("world", "w_launch"), source("mail", "m_1")] },
  ],
  todo_suggestions: [],
};

const api: MorningBriefApi = {
  read: vi.fn(async () => brief),
  make: vi.fn(async () => brief),
  settings: vi.fn(),
  saveSettings: vi.fn(),
  addTodo: vi.fn(),
};

it("P0_HOME_BRIEF_PLATE routes every supported Home brief target and leaves no-target sources as plain text", async () => {
  expect(homeTarget({ kind: "world", id: "w_launch" })).toEqual({
    page: "world",
    params: { id: "w_launch" },
  });
  expect(homeTarget({ kind: "decision", id: "d_quote" })).toEqual({
    page: "needs",
    params: { id: "d_quote" },
  });
  expect(homeTarget({ kind: "work_item", id: "wi_quote" })).toEqual({
    page: "agenda",
    params: { item: "work_item:wi_quote" },
  });
  expect(homeTarget({ kind: "calendar_event", id: "ce_plan" })).toEqual({
    page: "agenda",
    params: { item: "calendar_entry:ce_plan" },
  });
  expect(homeTarget({ kind: "meeting", id: "mt_plan" })).toEqual({
    page: "agenda",
    params: { item: "meeting:mt_plan" },
  });
  expect(homeTarget({ kind: "mail", id: "m_1" })).toBeNull();

  const opened: string[] = [];
  const m = mount(
    <MorningBriefCard
      api={api}
      canOpenSource={(item) => homeTarget(item) !== null}
      onOpenSource={(item) => opened.push(`${item.kind}:${item.id}`)}
    />,
  );
  await settle();
  const buttons = [...m.container.querySelectorAll("button")];
  const click = (label: string) =>
    buttons.find((button) => button.textContent?.includes(label))?.click();
  click("Planning call");
  click("Approve quote");
  click("world · w_launch");
  expect(opened).toEqual(["calendar_event:ce_plan", "work_item:wi_quote", "world:w_launch"]);
  expect(buttons.some((button) => button.textContent?.includes("mail · m_1"))).toBe(false);
  expect(m.container.querySelectorAll('a[href=""], a[href="#"]').length).toBe(0);

  const compact = mount(
    <MorningBriefCard
      api={api}
      compact
      canOpenSource={(item) => homeTarget(item) !== null}
      onOpenSource={(item) => opened.push(`${item.kind}:${item.id}`)}
    />,
  );
  await settle();
  const compactLink = [...compact.container.querySelectorAll("button")].find((button) =>
    button.textContent?.includes("Open the launch world"),
  );
  expect(compactLink).toBeTruthy();
  compactLink?.click();
  expect(opened.at(-1)).toBe("world:w_launch");
});
