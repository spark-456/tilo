import type { ProfileSettings } from "../types";

/** Page choices only (BQ-SET-3), never evidence of delivery, billing or signed-in devices. */
export function profileDefaults(): ProfileSettings {
  return {
    sessions: null,
    invoices: null,
    payment: null,
    plan: null,
    notifications: [
      {
        id: "decisions",
        label: "A decision needs you",
        description: "Budget sign-offs, gates and anything outside the company",
        phone: true,
        email: true,
        slack: true,
      },
      {
        id: "spend",
        label: "Spend goes over a limit",
        description: "A world or district passes its budget",
        phone: true,
        email: true,
        slack: false,
      },
      {
        id: "finished",
        label: "Work is ready",
        description: "Quick tasks and routine runs finish",
        phone: true,
        email: false,
        slack: true,
      },
      {
        id: "digest",
        label: "Morning digest at 08:00",
        description: "What happened overnight and what’s next",
        phone: false,
        email: true,
        slack: false,
      },
      {
        id: "weekly",
        label: "Weekly ledger summary",
        description: "Every Monday, spend and hours saved",
        phone: false,
        email: true,
        slack: true,
      },
    ],
    quiet: { on: true, start: "19:00", end: "08:00", threshold: "" },
  };
}
