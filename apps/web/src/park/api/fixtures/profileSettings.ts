// Hand-written from design_handoff_tilo_web_app/design/Tilo App Profile.dc.html, not generated: these
// values are not in tilo-app.js, so scripts/park-fixtures.mjs does not write this file. Lines: quiet
// hours 54-55, plan 101-103, payment 113-114, notification defaults 133, rows 144, sessions 146,
// invoices 164. Money stays a display string, as in the other fixtures. The agent-spend card reads
// the existing ledger fixture (spent, budget); the month label is `plan.spendMonth`.
// Scenario content lives in api/fixtures only.
import type { ProfileSettings } from "../types";

export const profileSettings: ProfileSettings = {
  sessions: [
    {
      id: "mac",
      device: "MacBook Pro · Chrome",
      place: "London",
      lastActive: "active now",
      current: true,
      icon: "laptop",
    },
    {
      id: "ios",
      device: "iPhone 15 · Tilo app",
      place: "London",
      lastActive: "2 hours ago",
      note: "Face ID for approvals",
      icon: "phone",
    },
    {
      id: "ipad",
      device: "iPad · Safari",
      place: "Manchester",
      lastActive: "yesterday",
      icon: "screen",
    },
  ],
  invoices: [
    { id: "2026-09", period: "September 2026", seats: 5, amount: "£245.00", status: "Paid" },
    { id: "2026-08", period: "August 2026", seats: 5, amount: "£245.00", status: "Paid" },
    { id: "2026-07", period: "July 2026", seats: 4, amount: "£196.00", status: "Paid" },
  ],
  payment: { brand: "Visa", last4: "4242", billingEmail: "finance@northwind.co" },
  plan: {
    name: "Team",
    seats: 5,
    perks: "shared boards, two-person approvals",
    renews: "1 October",
    spendMonth: "September",
  },
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
  quiet: { on: true, start: "19:00", end: "08:00", threshold: "£1,000" },
};
