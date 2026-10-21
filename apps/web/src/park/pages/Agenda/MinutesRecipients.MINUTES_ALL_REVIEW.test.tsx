// @vitest-environment happy-dom
// MINUTES-ALL security review (21 Oct): the minutes email's To list is shown in full, one address per line, and an
// address that is not an attendee on record or is outside the Owner's own domain carries a note the Owner can see
// before approving. Meet captions give names only, so the send list asks for emails instead of guessing them.
import { act } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, click, mount } from "../../../../test-support/park/componentsHarness";
import { meetingMinutesApi } from "../../api/live/meetingMinutes";
import { recipientNotes } from "../../shared/recipientNotes";
import { MeetingMinutes } from "./MeetingMinutes";
import { SendToEveryone } from "./SendToEveryone";

const signedIn = vi.hoisted(() => ({ email: null as string | null }));
vi.mock("../../../api/sessionAuth", async (original) => ({
  ...(await original<typeof import("../../../api/sessionAuth")>()),
  useSessionAuth: () =>
    signedIn.email
      ? { status: "signedIn", user: { displayName: "Owner", email: signedIn.email } }
      : null,
}));
afterEach(() => {
  cleanup();
  signedIn.email = null;
});

const list = {
  meeting_id: "mt_a",
  transcript: false,
  recipients: [
    { name: "Me", email: "owner@example.com", source: "owner" },
    { name: "Priya", email: "priya@example.com", source: "invited" },
    { name: "Visiting Guest", email: "guest@partner.org", source: "invited" },
    { name: "Bob", email: null, source: "heard" },
  ],
};
const doc = {
  meeting_id: "mt_a",
  summary: [{ text: "Agreed scope" }],
  decisions: [],
  action_items: [],
};
const meeting = {
  id: "mt_a",
  owner: "u_owner",
  minutes_confirmed_by: { user: "u_owner", at: "2026-10-21T00:00:00Z" },
  attendees: [{ user: "u_priya", name: "Priya" }],
};
const card = (to: string[]) => ({
  card_id: "card_all",
  subject: "Minutes: Review",
  body: "Minutes",
  to,
  tier: "T3",
});
const button = (root: HTMLElement, text: string) =>
  Array.from(root.querySelectorAll("button")).find((b) => b.textContent === text);
const press = async (root: HTMLElement, text: string) => {
  const target = button(root, text);
  if (!target) throw new Error(`Missing button: ${text}`);
  await act(async () => click(target));
};
const typeInto = (input: HTMLInputElement, value: string) =>
  act(() => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set?.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
const row = (root: HTMLElement, name: string) =>
  (root.querySelector(`input[aria-label="Email for ${name}"]`) as HTMLInputElement).closest("li");

describe("MINUTES_ALL_REVIEW every To address in full, with a note on any that deserves a second look", () => {
  it("MINUTES_ALL_REVIEW notes an address that is not an attendee on record or is outside the Owner's domain", () => {
    const known = { ownerEmail: "owner@example.com", attendees: new Set(["priya@example.com"]) };
    expect(recipientNotes("priya@example.com", known)).toEqual([]);
    expect(recipientNotes("Priya@Example.com", known)).toEqual([]);
    expect(recipientNotes("new@example.com", known)).toEqual(["Not an attendee on record"]);
    expect(recipientNotes("x@other.org", known)).toEqual([
      "Not an attendee on record",
      "Outside your domain (other.org)",
    ]);
    // no attendee list and no signed-in address: nothing to compare with, so no note is made up
    expect(recipientNotes("x@other.org", { ownerEmail: null })).toEqual([]);
    expect(recipientNotes("x@other.org", { ownerEmail: "me@example.com" })).toEqual([
      "Outside your domain (other.org)",
    ]);
  });

  it("MINUTES_ALL_REVIEW the send list notes each typed or outside address and asks for emails Meet did not give", async () => {
    const h = { getJson: vi.fn(async () => list as never), postJson: vi.fn() };
    const m = mount(
      <SendToEveryone id="mt_a" api={meetingMinutesApi(h)} onCards={() => undefined} />,
    );
    await press(m.container, "Send to everyone who joined");
    expect(row(m.container, "Me")?.textContent).not.toContain("Not an attendee");
    expect(row(m.container, "Priya")?.textContent).not.toContain("Outside your domain");
    expect(row(m.container, "Visiting Guest")?.textContent).toContain(
      "Outside your domain (partner.org)",
    );
    expect(row(m.container, "Visiting Guest")?.textContent).not.toContain("Not an attendee");
    expect(m.container.textContent).toContain("Meet gives Tilo names only, so add");
    typeInto(
      m.container.querySelector('input[aria-label="Email for Bob"]') as HTMLInputElement,
      "bob@elsewhere.net",
    );
    expect(row(m.container, "Bob")?.textContent).toContain("Not an attendee on record");
    expect(row(m.container, "Bob")?.textContent).toContain("Outside your domain (elsewhere.net)");
  });

  it("MINUTES_ALL_REVIEW the drafted card lists every To address in full, one per line, with its notes", async () => {
    const to = [
      "owner@example.com",
      "priya@example.com",
      "guest@partner.org",
      "a.very.long.address.that.is.not.cut@unknown-company.example.net",
    ];
    const h = {
      getJson: vi.fn(async (path: string) =>
        path.endsWith("/minutes")
          ? (doc as never)
          : path.endsWith("/followup-recipients")
            ? (list as never)
            : (meeting as never),
      ),
      postJson: vi.fn(async () => card(to) as never),
    };
    const m = mount(<MeetingMinutes id="mt_a" status="minuted" api={meetingMinutesApi(h)} />);
    await press(m.container, "Review minutes");
    await press(m.container, "Send to everyone who joined");
    await press(m.container, "Draft one email");
    const shown = m.container.querySelector(
      '[aria-label="T3 approval card"] ul[aria-label="To"]',
    ) as HTMLElement;
    const lines = Array.from(shown.querySelectorAll("li"));
    expect(lines).toHaveLength(4);
    lines.forEach((line, i) => expect(line.textContent?.startsWith(to[i] ?? "missing")).toBe(true));
    expect(lines[0]?.querySelector('[role="note"]')).toBeNull();
    expect(lines[1]?.querySelector('[role="note"]')).toBeNull();
    expect(lines[2]?.textContent).toContain("Outside your domain (partner.org)");
    expect(lines[3]?.textContent).toContain("Not an attendee on record");
    expect(lines[3]?.textContent).toContain("Outside your domain (unknown-company.example.net)");
  });

  it("MINUTES_ALL_REVIEW a card drafted from picked people is checked against the signed-in address", async () => {
    signedIn.email = "owner@example.com";
    const h = {
      getJson: vi.fn(async (path: string) =>
        path.endsWith("/minutes") ? (doc as never) : (meeting as never),
      ),
      postJson: vi.fn(async () => card(["priya@example.com", "priya@gmail.com"]) as never),
    };
    const m = mount(<MeetingMinutes id="mt_a" status="minuted" api={meetingMinutesApi(h)} />);
    await press(m.container, "Review minutes");
    await act(async () => click(m.container.querySelector("fieldset input") as Element));
    await press(m.container, "Draft follow-up");
    const lines = Array.from(
      m.container.querySelectorAll('[aria-label="T3 approval card"] ul[aria-label="To"] li'),
    );
    expect(lines.map((l) => l.textContent)).toEqual([
      "priya@example.com",
      "priya@gmail.com Outside your domain (gmail.com)",
    ]);
  });
});
