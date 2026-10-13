// FR-SET-01/02 sample document: the fixture user's profile and the design's notification defaults, in the
// UserSettings contract's shape (packages/contracts-ts). Hand-written from user.ts and profileSettings.ts, so the
// two never drift. `threshold` is typed money, as the contract has it; nothing delivers by it (USET-05).
import type { UserSettings } from "@tilo/contracts";
import { profileSettings } from "./profileSettings";
import { user } from "./user";

const row = (id: string) => {
  const r = profileSettings.notifications.find((n) => n.id === id);
  return { phone: r?.phone ?? false, email: r?.email ?? false, slack: r?.slack ?? false };
};
const { quiet } = profileSettings;

export const userSettings: UserSettings = {
  owner_id: "u_alex",
  org_id: "org_northwind",
  version: 1,
  profile: {
    name: user.name,
    email: user.email,
    title: user.title,
    time_zone: "Europe/London",
    language: "en-GB",
    working_hours: { days: ["mon", "tue", "wed", "thu", "fri"], start: "08:30", end: "17:30" },
  },
  notifications: {
    decisions: row("decisions"),
    spend: row("spend"),
    finished: row("finished"),
    digest: row("digest"),
    weekly: row("weekly"),
  },
  quiet_hours: {
    enabled: quiet.on,
    start: quiet.start,
    end: quiet.end,
    timezone: "Europe/London",
    threshold: { amount_minor: 100000, currency: "GBP" },
  },
  updated_at: "2026-09-24T09:12:00Z",
};
