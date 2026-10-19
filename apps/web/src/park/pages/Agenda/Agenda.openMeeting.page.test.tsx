// @vitest-environment happy-dom
// Agenda: "Open meeting page" on an upcoming event Tilo joins. ADR-0024 am4: the agenda data carries no Meet
// URL; the Tilo meeting page fetches the transient join link. The Park shell has no meeting page yet, so the
// button says so in words, opens nothing and fetches nothing (HR-1..HR-7).
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, renderAgenda } from "../../../../test-support/park/agendaHarness";
import { click, q, qa } from "../../../../test-support/park/componentsHarness";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

const detail = (root: ParentNode) => q(root, '[aria-label="Event detail"]');
const open = (root: ParentNode) =>
  qa<HTMLElement>(detail(root), "button").find(
    (b) => (b.textContent ?? "").trim() === "Open meeting page",
  );

describe("AGENDA_OPEN_MEETING the meeting button never opens a Meet link", () => {
  it("AGENDA_OPEN_MEETING shows on an upcoming joined event and only toasts, no navigation, no window", async () => {
    const openSpy = vi.fn();
    vi.stubGlobal("open", openSpy);
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);
    const { container, toast } = await renderAgenda();
    const btn = open(container);
    expect(btn).toBeTruthy();
    if (btn) click(btn);
    expect(toast()).toContain("is not connected yet");
    expect(openSpy).not.toHaveBeenCalled();
    expect(fetchSpy).not.toHaveBeenCalled();
    expect(detail(container).innerHTML).not.toContain("meet.google.com");
  });
});
