// @vitest-environment happy-dom
// PPL-40b / FR-PB-01, FR-PB-08, FR-CAL-01: S-28 Pinboards and S-29 Calendar on contract-shaped
// fixtures. Who sees what is code (ADR-0016): a teammate's personal pin and entry, a proposal that is
// not yours and a removed pin are never rendered; of a teammate only the display name and free/busy.
import fc from "fast-check";
import { type ReactElement, act } from "react";
import { createRoot } from "react-dom/client";
import { describe, expect, it } from "vitest";
import { S_28 } from "../screens/S_28";
import { S_29 } from "../screens/S_29";
import { addDays, agendaOf, barsOn, ownEntries, weekOf } from "./calendar";
import { AGENDA_ROWS, CAL_ENTRIES, FREE_BUSY, MENTIONS, PINS } from "./data";
import { personalBoard, sortPins, taggedOn, teamBoard } from "./pins";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

async function render(ui: ReactElement) {
  const box = document.createElement("div");
  document.body.append(box);
  await act(async () => createRoot(box).render(ui));
  return box;
}
const click = (el: Element | null | undefined) =>
  act(async () => {
    (el as HTMLElement).click();
  });
const titles = (box: Element, id: string) =>
  [...box.querySelectorAll(`[data-testid="${id}"] [data-testid="pin-row"] b`)].map(
    (b) => b.textContent,
  );
const button = (box: Element, name: string) =>
  [...box.querySelectorAll("button")].find((b) => b.getAttribute("aria-label")?.startsWith(name));
const radio = (box: Element, value: string) =>
  box.querySelector(`input[type="radio"][value="${value}"]`);
const rowTitles = (box: Element) =>
  [...box.querySelectorAll('[data-testid="agenda-row"] b')].map((b) => b.textContent);

describe("PPL-40b pins as pure functions (FR-PB-01, -02, -04, -07)", () => {
  it("FR-PB-01 the team board holds active pins and your own proposals, never a teammate's or a removed one", () => {
    const ids = teamBoard(PINS).map((p) => p.id);
    expect(ids).toContain("pb_rate_sheet");
    expect(ids).toContain("pb_rollout_plan"); // proposed, and set up by you
    expect(ids).not.toContain("pb_priya_draft"); // proposed by a teammate
    expect(ids).not.toContain("pb_old_removed");
  });

  it("FR-PB-02 the personal board is the signed-in person's own active pins only", () => {
    const ids = personalBoard(PINS).map((p) => p.id);
    expect(ids.sort()).toEqual(["pb_owner_followup", "pb_owner_note"]);
    expect(personalBoard(PINS, "u_priya").map((p) => p.id)).toEqual(["pb_priya_note"]);
  });

  it("FR-PB-04 a removed tag is gone and a personal pin takes none", () => {
    const pin = (id: string) => PINS.find((p) => p.id === id) as (typeof PINS)[number];
    expect(taggedOn(pin("pb_rate_sheet"), MENTIONS)).toEqual(["u_priya"]);
    expect(taggedOn(pin("pb_brief_link"), MENTIONS)).toEqual([]);
    expect(taggedOn(pin("pb_owner_followup"), MENTIONS)).toEqual([]);
  });

  it("FR-PB-01 sorting puts a missing due date last either way and is the same whatever order pins arrive in", () => {
    const team = teamBoard(PINS);
    for (const dir of [1, -1] as const)
      expect(sortPins(team, { key: "due", dir }).at(-1)?.due).toBeNull();
    const ids = (xs: typeof team) => sortPins(xs, { key: "updated", dir: -1 }).map((p) => p.id);
    fc.assert(
      fc.property(fc.shuffledSubarray(team, { minLength: team.length }), (xs) => {
        expect(ids(xs)).toEqual(ids(team));
      }),
    );
  });
});

describe("PPL-40b S-28 Pinboards", () => {
  it("FR-PB-01 shows the preview note, the team entries a member may read, and none of the hidden ones", async () => {
    const box = await render(<S_28 />);
    expect(box.querySelector('[data-testid="people-preview"]')?.textContent).toContain(
      "Preview, not connected",
    );
    const team = titles(box, "team-pins");
    expect(team).toContain("Rate sheet goes to Acme by 9 Oct");
    expect(team).toContain("Agree the rollout plan with Acme"); // your own proposal
    expect(box.textContent).toContain("Proposed, only you see it");
    expect(box.textContent).not.toContain("Draft the press note for launch"); // a teammate's proposal
    expect(box.textContent).not.toContain("Old agenda for the offsite"); // removed
    expect(box.textContent).not.toContain("Ask Dev about the venue"); // a teammate's personal pin
  });

  it("FR-PB-02 the personal board lists only your own pins, with no responsible person and no tags", async () => {
    const box = await render(<S_28 />);
    expect(titles(box, "personal-pins").sort()).toEqual([
      "Ask Dev about the rate sheet",
      "Follow up on the rate sheet",
    ]);
    const mine = box.querySelector('[data-testid="personal-pins"]');
    expect(mine?.textContent).not.toMatch(/Responsible|Tagged|Unowned/);
    expect(mine?.textContent).toContain("Added by Tilo from a meeting");
  });

  it("FR-PB-07 the Unowned lane lists exactly the entries with no owner, and every other entry has one", async () => {
    const box = await render(<S_28 />);
    expect(titles(box, "pins-unowned").sort()).toEqual([
      "Agree the rollout plan with Acme",
      "Offsite venue still to be chosen",
    ]);
    const lane = box.querySelector('[data-testid="pins-unowned"]');
    expect(lane?.textContent).toContain("Unowned");
    for (const row of box.querySelectorAll('[data-testid="team-pins"] tbody:not([data-testid]) tr'))
      expect(row.textContent).not.toContain("Unowned");
  });

  it("FR-PB-04 a tagged person is shown by display name, and a removed tag is not", async () => {
    const box = await render(<S_28 />);
    const rows = [...box.querySelectorAll('[data-testid="team-pins"] [data-testid="pin-row"]')];
    const row = (t: string) => rows.find((r) => r.textContent?.includes(t));
    const tags = (t: string) => row(t)?.querySelector(".pb-tags")?.textContent;
    expect(tags("Rate sheet goes to Acme")).toContain("Priya Nair");
    expect(tags("Launch is 17 October")).toContain("You");
    expect(tags("Launch brief")).toBeUndefined();
  });

  it("FR-PB-03 Get in touch drafts to the set-up person by name and says nothing is sent", async () => {
    const box = await render(<S_28 />);
    expect(button(box, "Get in touch with Asha Rao")).toBeUndefined(); // never to yourself
    await click(button(box, "Get in touch with Priya Nair about Launch is 17 October"));
    const draft = box.querySelector('[data-testid="pin-draft"]');
    expect(draft?.textContent).toContain("Draft to Priya Nair");
    expect(draft?.textContent).toContain("Nothing is sent from this preview");
    expect((draft?.querySelector("textarea") as HTMLTextAreaElement).value).toContain(
      "Launch is 17 October",
    );
    expect(draft?.querySelector("button[aria-disabled='true']")?.getAttribute("title")).toBe(
      "Coming soon",
    );
    expect(box.textContent).not.toMatch(/@example\.com|Asia\/Kolkata|email|WhatsApp/);
  });

  it("FR-PB-03 the draft opens in the row right under the entry it is about, and Escape closes it and returns focus", async () => {
    const box = await render(<S_28 />);
    const opener = button(box, "Get in touch with Priya Nair about Launch is 17 October");
    await click(opener);
    const draft = box.querySelector('[data-testid="pin-draft"]');
    const row = draft?.closest("tr")?.previousElementSibling;
    expect(row?.getAttribute("data-testid")).toBe("pin-row");
    expect(row?.textContent).toContain("Launch is 17 October");
    expect(row?.contains(opener ?? null)).toBe(true);
    await act(async () => {
      draft?.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    });
    expect(box.querySelector('[data-testid="pin-draft"]')).toBeNull();
    expect(document.activeElement).toBe(opener);
  });

  it("FR-PB-05 edit is offered only on entries you set up, and does nothing yet", async () => {
    const box = await render(<S_28 />);
    const edits = [...box.querySelectorAll("button")].filter((b) =>
      b.getAttribute("aria-label")?.startsWith("Edit:"),
    );
    const mineOnTeam = teamBoard(PINS).filter((p) => p.set_up_by === "u_owner").length;
    expect(edits).toHaveLength(mineOnTeam + personalBoard(PINS).length);
    for (const b of edits) {
      expect(b.getAttribute("aria-disabled")).toBe("true");
      expect(b.getAttribute("title")).toBe("Coming soon");
    }
    expect(button(box, "Edit: Launch is 17 October")).toBeUndefined(); // Priya's entry
    expect(button(box, "Edit: Rate sheet goes to Acme by 9 Oct")).toBeDefined();
  });

  it("FR-PB-01 sorts by a column and filters by kind, with an empty state when nothing is left", async () => {
    const box = await render(<S_28 />);
    await click(box.querySelector('[data-testid="team-pins"] thead .pb-sort'));
    const entry = box.querySelector('[data-testid="team-pins"] thead th[aria-sort]');
    expect(entry?.textContent).toContain("Entry");
    expect(entry?.getAttribute("aria-sort")).toBe("ascending");
    await click(radio(box, "deadline"));
    expect(titles(box, "team-pins")).toEqual(["Acme rate hold runs out"]);
    expect(box.querySelector('[data-testid="personal-empty"]')).not.toBeNull();
    await click(radio(box, "all"));
    expect(box.querySelector('[data-testid="personal-empty"]')).toBeNull();
  });

  it("FR-PB-08 two tabs switch the board, and the page has no filled primary button", async () => {
    const box = await render(<S_28 />);
    const board = (id: string) =>
      box.querySelector(`[data-testid="${id}"]`)?.getAttribute("data-shown");
    expect([board("team-board"), board("personal-board")]).toEqual(["true", "false"]);
    await click(radio(box, "personal"));
    expect([board("team-board"), board("personal-board")]).toEqual(["false", "true"]);
    expect(box.querySelectorAll("button.primary")).toHaveLength(0);
  });
});

describe("PPL-40b calendar as pure functions (FR-CAL-01)", () => {
  it("FR-CAL-01 a week runs Monday to Sunday and days step by whole days", () => {
    expect(weekOf("2026-10-07")).toEqual([
      "2026-10-05",
      "2026-10-06",
      "2026-10-07",
      "2026-10-08",
      "2026-10-09",
      "2026-10-10",
      "2026-10-11",
    ]);
    expect(weekOf("2026-10-11")[0]).toBe("2026-10-05");
    expect(addDays("2026-10-31", 1)).toBe("2026-11-01");
  });

  it("FR-CAL-06 only your own live entries are on the agenda: not a teammate's, not a cancelled one", () => {
    const titles = ownEntries(CAL_ENTRIES).map((e) => e.title);
    expect(titles).not.toContain("Vendor call");
    expect(ownEntries(CAL_ENTRIES).every((e) => e.owner === "u_owner")).toBe(true);
    expect(agendaOf(CAL_ENTRIES, AGENDA_ROWS).filter((r) => r.title === "Dentist")).toHaveLength(1);
  });

  it("FR-CAL-06 a teammate's free/busy is bars and times, in the person's own day", () => {
    const [fb] = FREE_BUSY;
    expect(fb && barsOn(fb, "2026-10-07").map((b) => b.label)).toEqual(["Busy 15:00 to 15:30"]);
    expect(fb && barsOn(fb, "2026-10-06")).toEqual([]);
    expect(JSON.stringify(fb && barsOn(fb, "2026-10-07"))).not.toMatch(/Dentist/);
  });
});

describe("PPL-40b S-29 Calendar", () => {
  it("FR-CAL-01 the day view merges entries and agenda rows in time order, each citing its source", async () => {
    const box = await render(<S_29 />);
    expect(rowTitles(box)).toEqual([
      "Design review",
      "Launch sync",
      "Budget review",
      "Prepare the rate sheet for Acme",
    ]);
    const rows = [...box.querySelectorAll('[data-testid="agenda-row"]')];
    for (const r of rows) expect(r.textContent).toContain("Source:");
    expect(box.querySelector('[data-testid="people-preview"]')?.textContent).toContain(
      "Preview, not connected",
    );
    expect(box.textContent).toContain("Shared with your team");
  });

  it("FR-CAL-06 a teammate's entry title and a cancelled entry are never rendered, in any view", async () => {
    const box = await render(<S_29 />);
    expect(box.textContent).not.toContain("Dentist"); // Priya's, 7 Oct
    await click(radio(box, "week"));
    expect(rowTitles(box).filter((t) => t === "Dentist")).toHaveLength(1); // yours, 9 Oct
    expect(box.textContent).not.toContain("Vendor call");
  });

  it("FR-CAL-03 a Tilo proposal is marked private to you, and Accept and Decline are coming soon", async () => {
    const box = await render(<S_29 />);
    const row = [...box.querySelectorAll('[data-testid="agenda-row"]')].find((r) =>
      r.textContent?.includes("Prepare the rate sheet for Acme"),
    );
    expect(row?.textContent).toContain("Proposed, private to you");
    const soon = [...(row?.querySelectorAll("button") ?? [])];
    expect(soon.map((b) => b.textContent)).toEqual(["Accept", "Decline"]);
    for (const b of soon) {
      expect(b.getAttribute("aria-disabled")).toBe("true");
      expect(b.getAttribute("title")).toBe("Coming soon");
    }
    expect(box.querySelectorAll("button.primary")).toHaveLength(0);
  });

  it("FR-CAL-06 a teammate's availability is a bar and busy times with their display name, no titles", async () => {
    const box = await render(<S_29 />);
    const free = box.querySelector('[data-testid="free-busy"]');
    expect(free?.textContent).toContain("Priya Nair");
    expect(free?.textContent).toContain("Busy 15:00 to 15:30");
    expect(free?.querySelectorAll(".cal-busy")).toHaveLength(1);
    expect(box.textContent).not.toMatch(/@example\.com|Asia\/Kolkata\)/);
  });

  it("FR-CAL-01 the week view lists seven days, from Monday, with every row citing its source", async () => {
    const box = await render(<S_29 />);
    await click(radio(box, "week"));
    const days = [...box.querySelectorAll('[data-testid^="day-"]')].map((d) =>
      d.getAttribute("data-testid"),
    );
    expect(days).toEqual(weekOf("2026-10-07").map((d) => `day-${d}`));
    expect(box.textContent).toContain("Wednesday 7 Oct (today)");
    const rows = [...box.querySelectorAll('[data-testid="agenda-row"]')];
    expect(rows.length).toBeGreaterThan(8);
    for (const r of rows) expect(r.textContent).toContain("Source:");
    expect(box.querySelectorAll('[data-testid="free-busy"] li')).toHaveLength(7);
  });

  it("FR-CAL-01 day and week are real radio buttons, and Earlier and Later move by their own step", async () => {
    const box = await render(<S_29 />);
    expect(box.querySelectorAll('[data-testid="cal-view"] input[type="radio"]')).toHaveLength(2);
    const nav = (t: string) =>
      [...box.querySelectorAll(".cal-nav button")].find((b) => b.textContent === t);
    await click(nav("Later"));
    expect(box.textContent).toContain("Thursday 8 Oct");
    await click(nav("Today"));
    expect(box.textContent).toContain("Wednesday 7 Oct");
  });

  it("FR-CAL-05 opening a meeting row shows its prep from records: agenda, related work and pins, previous minutes", async () => {
    const box = await render(<S_29 />);
    await click(
      [...box.querySelectorAll(".cal-nav button")].find((b) => b.textContent === "Later"),
    );
    await click(
      [...box.querySelectorAll("button")].find((b) => b.textContent === "Prepare for Q4 planning"),
    );
    const prep = box.querySelector('[data-testid="prep"]');
    expect(prep?.textContent).toContain("Launch date");
    expect(prep?.textContent).toContain("(15 min)");
    expect(box.querySelector('[data-testid="prep-items"]')?.textContent).toContain(
      "Confirm the rate hold in writing",
    );
    expect(box.querySelector('[data-testid="prep-pins"]')?.textContent).toContain(
      "Rate sheet goes to Acme by 9 Oct",
    );
    expect(box.querySelector('[data-testid="prep-pins"]')?.textContent).not.toContain("press note");
    const minutes = box.querySelector('[data-testid="prep-minutes"]');
    expect(minutes?.textContent).toContain("Q4 planning");
    expect(minutes?.querySelector("a")?.getAttribute("href")).toBe("/meetings/mt_q4_plan");
  });

  it("FR-CAL-05 a meeting with no series says there are no earlier minutes", async () => {
    const box = await render(<S_29 />);
    await click(
      [...box.querySelectorAll("button")].find(
        (b) => b.textContent === "Prepare for Design review",
      ),
    );
    expect(box.querySelector('[data-testid="prep-minutes"]')?.textContent).toContain(
      "No earlier minutes in this series.",
    );
  });
});
