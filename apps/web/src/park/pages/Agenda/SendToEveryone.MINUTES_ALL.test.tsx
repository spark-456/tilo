// @vitest-environment happy-dom
import { act } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, click, mount } from "../../../../test-support/park/componentsHarness";
import { TiloApiError } from "../../../api/http";
import { type DraftCard, meetingMinutesApi } from "../../api/live/meetingMinutes";
import { SendToEveryone } from "./SendToEveryone";

afterEach(cleanup);

const list = (transcript = true) => ({
  meeting_id: "mt_a",
  transcript,
  recipients: [
    { name: "Me", email: "owner@example.com", source: "owner" },
    { name: "Priya", email: "priya@example.com", source: "invited" },
    { name: "Visiting Guest", email: null, source: "invited" },
    { name: "Bob", email: null, source: "heard" },
  ],
});
const card = {
  card_id: "card_all",
  subject: "Minutes: Review",
  body: "Minutes",
  to: ["owner@example.com"],
  tier: "T3",
};
const http = (transcript = true) => ({
  getJson: vi.fn(async () => list(transcript) as never),
  postJson: vi.fn(async () => card as never),
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
const field = (root: HTMLElement, name: string) =>
  root.querySelector(`input[aria-label="Email for ${name}"]`) as HTMLInputElement;

describe("MINUTES_ALL send to everyone who joined", () => {
  it("MINUTES_ALL shows the list, lets the Owner edit, remove and add, then drafts ONE email to exactly those", async () => {
    const h = http();
    const got: DraftCard[][] = [];
    const m = mount(
      <SendToEveryone id="mt_a" api={meetingMinutesApi(h)} onCards={(c) => got.push(c)} />,
    );
    expect(h.getJson).not.toHaveBeenCalled();
    await press(m.container, "Send to everyone who joined");
    expect(h.getJson).toHaveBeenCalledWith("/v1/meetings/mt_a/followup-recipients");
    expect(field(m.container, "Me").value).toBe("owner@example.com");
    expect(field(m.container, "Bob").placeholder).toBe("no email on file");
    expect(m.container.textContent).toContain("Left out, no email on file: Visiting Guest, Bob.");
    typeInto(field(m.container, "Bob"), " Bob@Example.org ");
    await act(async () =>
      click(m.container.querySelector('button[aria-label="Remove Priya"]') as Element),
    );
    await press(m.container, "Add an address");
    typeInto(field(m.container, "added person"), "new@example.net");
    expect(m.container.textContent).toContain("Left out, no email on file: Visiting Guest.");
    await press(m.container, "Draft one email");
    expect(h.postJson).toHaveBeenCalledTimes(1);
    expect(h.postJson).toHaveBeenCalledWith("/v1/meetings/mt_a/draft-followup", {
      addresses: ["owner@example.com", "bob@example.org", "new@example.net"],
      transcript: true,
    });
    expect(got).toEqual([
      [
        {
          cardId: "card_all",
          subject: "Minutes: Review",
          body: "Minutes",
          recipients: ["owner@example.com"],
        },
      ],
    ]);
  });
  it("MINUTES_ALL an address that is not one mailbox is caught before anything is drafted", async () => {
    const h = http();
    const m = mount(
      <SendToEveryone id="mt_a" api={meetingMinutesApi(h)} onCards={() => undefined} />,
    );
    await press(m.container, "Send to everyone who joined");
    typeInto(field(m.container, "Bob"), "Bob <bob@example.org>");
    await press(m.container, "Draft one email");
    expect(m.container.querySelector('[role="alert"]')?.textContent).toContain(
      "Check the address for Bob",
    );
    expect(h.postJson).not.toHaveBeenCalled();
  });
  it("MINUTES_ALL a transcript that has not passed the safety check cannot be included", async () => {
    const h = http(false);
    const m = mount(
      <SendToEveryone id="mt_a" api={meetingMinutesApi(h)} onCards={() => undefined} />,
    );
    await press(m.container, "Send to everyone who joined");
    const box = m.container.querySelector('input[type="checkbox"]') as HTMLInputElement;
    expect(box.disabled && !box.checked).toBe(true);
    await press(m.container, "Draft one email");
    expect(h.postJson).toHaveBeenCalledWith("/v1/meetings/mt_a/draft-followup", {
      addresses: ["owner@example.com", "priya@example.com"],
      transcript: false,
    });
  });
  it("MINUTES_ALL a refused draft says nothing was sent", async () => {
    const h = http();
    h.postJson.mockRejectedValue(
      new TiloApiError("Conflict", 409, false, true, "version_conflict"),
    );
    const m = mount(
      <SendToEveryone id="mt_a" api={meetingMinutesApi(h)} onCards={() => undefined} />,
    );
    await press(m.container, "Send to everyone who joined");
    await press(m.container, "Draft one email");
    expect(m.container.querySelector('[role="alert"]')?.textContent).toBe(
      "The email could not be drafted. Nothing was sent. Try again.",
    );
  });
});
