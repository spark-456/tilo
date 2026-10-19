import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const here = dirname(fileURLToPath(import.meta.url));
const css = readFileSync(join(here, "Agenda.studio.css"), "utf8");
const host = readFileSync(join(here, "MeetingHost.tsx"), "utf8");
const schedule = readFileSync(join(here, "ScheduleWithOthersDialog.tsx"), "utf8");
const minutes = readFileSync(join(here, "MeetingMinutes.tsx"), "utf8");

describe("UX_POLISH_AGENDA", () => {
  it("UX_POLISH_AGENDA_replaces_browser_select_arrows_in_meeting_forms", () => {
    expect(host).toContain('className="park-agenda-hostselect"');
    expect(schedule).toContain('className="park-agenda-hostselect"');
    expect(css).toMatch(/\.park-agenda-hostselect select \{[^}]*appearance: none/s);
    expect(css).toMatch(/\.park-agenda-hostselect::after \{[^}]*content: "⌄"/s);
  });

  it("UX_POLISH_AGENDA_uses_labelled_custom_checkboxes_for_invites_and_minutes", () => {
    expect(css).toContain('.park-agenda-hostnotice input[type="checkbox"],');
    expect(minutes).toContain('className="park-agenda-minutes"');
    expect(css).toMatch(/\.park-agenda-minutes input\[type="checkbox"\] \{[^}]*appearance: none/s);
  });
});
