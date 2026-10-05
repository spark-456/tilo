import type { Card } from "@tilo/contracts";
// Values copied from contracts/fixtures/card/valid/*.json (all six) (never imported at runtime). Drift is caught by
// fixtures.drift.test.ts (PRD-18.3 flow). Regenerate by copying the JSON again.

const CONSENT_DRIVE_FOLDER = {
  id: "01J8Z3K4M5N6P7Q8R9S0T1V2W5",
  world_id: "w_01",
  run_id: "r_01J8Z3K4M5",
  header: {
    building: "B1",
    agent: "A_dir",
  },
  add_context: false,
  created_at: "2026-09-29T09:30:00.000Z",
  timeout: 3600,
  gate: null,
  consent: {
    connector: "google_drive",
    scopes: ["Create and edit files in the Tilo folder only"],
  },
  kind: "consent",
  rung: "consent",
  what_happened: "Saving the report needs access to one Drive folder.",
  why_it_matters: "Without it the report stays in Tilo only.",
  options: [
    {
      id: "connect",
      label: "Connect",
      suggested: true,
      reason: "Only the Tilo folder is requested.",
      irreversible: false,
    },
    {
      id: "hold",
      label: "Hold",
      suggested: false,
      irreversible: false,
    },
  ],
  actions: ["show_me", "snooze"],
  answer_channels: ["web", "mobile_web"],
  safe_default: "hold",
} satisfies Card;

const GATE_SAVE_FILE_REVERSIBLE = {
  id: "01J8Z3K4M5N6P7Q8R9S0T1V2W3",
  world_id: "w_01",
  run_id: "r_01J8Z3K4M5",
  header: {
    building: "B2",
    agent: "A_s1",
  },
  add_context: true,
  created_at: "2026-09-29T09:30:00.000Z",
  timeout: 3600,
  gate: {
    id: "G2",
    action: {
      type: "save_file",
      connector: "google_drive",
      exact: "Save the quote summary as a new file in the Tilo folder of your Drive.",
      item: {
        artifact_id: "art_quote_summary",
        version: 1,
        label: "Quote summary",
      },
      destination: "folder-tilo",
    },
    recipients: [],
    irreversible: false,
    risk_tier: "T1",
  },
  consent: null,
  kind: "gate",
  rung: "gate",
  what_happened: "The quote summary is ready to save to your Drive.",
  why_it_matters: "Your policy asks each time before Tilo saves files.",
  options: [
    {
      id: "approve",
      label: "Approve",
      suggested: true,
      reason: "It only adds a new file, and you can delete it.",
      irreversible: false,
    },
    {
      id: "hold",
      label: "Hold",
      suggested: false,
      irreversible: false,
    },
  ],
  actions: ["show_me", "snooze"],
  answer_channels: ["web", "mobile_web"],
  safe_default: "hold",
} satisfies Card;

const GATE_SEND_REPLY = {
  id: "01J8Z3K4M5N6P7Q8R9S0T1V2W3",
  world_id: "w_01",
  run_id: "r_01J8Z3K4M5",
  header: {
    building: "B2",
    agent: "A_s1",
  },
  add_context: true,
  created_at: "2026-09-29T09:30:00.000Z",
  timeout: 3600,
  gate: {
    id: "G1",
    action: {
      type: "send_email",
      connector: "gmail",
      exact: "Send the drafted reply in the thread 'Quote for 500 packs' to orders@example.com.",
      item: {
        artifact_id: "art_reply_draft",
        version: 2,
        label: "Reply draft",
      },
      destination: "thread-quote-500-packs",
    },
    recipients: ["orders@example.com"],
    irreversible: true,
    risk_tier: "T3",
  },
  consent: null,
  kind: "gate",
  rung: "gate",
  what_happened: "The reply to the supplier is drafted and ready to send.",
  why_it_matters: "It confirms the order of 500 packs at the quoted price.",
  options: [
    {
      id: "approve",
      label: "Approve",
      suggested: false,
      irreversible: true,
    },
    {
      id: "edit",
      label: "Edit first",
      suggested: true,
      reason: "It is a new recipient, so check it once.",
      irreversible: false,
    },
    {
      id: "hold",
      label: "Hold",
      suggested: false,
      irreversible: false,
    },
  ],
  actions: ["show_me", "snooze"],
  answer_channels: ["web", "mobile_web"],
  safe_default: "hold",
} satisfies Card;

const MEETING_BUDGET_SPLIT = {
  id: "01J8Z3K4M5N6P7Q8R9S0T1V2W3",
  world_id: "w_01",
  run_id: "r_01J8Z3K4M5",
  header: {
    building: "B1",
    agent: "A_dir",
  },
  add_context: true,
  created_at: "2026-09-29T09:30:00.000Z",
  timeout: 3600,
  gate: null,
  consent: null,
  kind: "meeting",
  rung: "meeting",
  what_happened: "Research and Finance disagree on the budget split.",
  why_it_matters: "The decision changes which suppliers get a deep review.",
  options: [
    {
      id: "research",
      label: "More for research",
      suggested: false,
      irreversible: false,
    },
    {
      id: "even",
      label: "Split evenly",
      suggested: true,
      reason: "Both leads can finish on time.",
      irreversible: false,
    },
  ],
  actions: ["show_me", "snooze", "delegate"],
  answer_channels: ["web"],
  safe_default: "even",
} satisfies Card;

const NEEDS_YOU_BLOCKED = {
  id: "01J8Z3K4M5N6P7Q8R9S0T1V2W4",
  world_id: "w_01",
  run_id: "r_01J8Z3K4M5",
  header: {
    building: "B2",
    agent: "A_s1",
  },
  add_context: true,
  created_at: "2026-09-29T09:30:00.000Z",
  timeout: 3600,
  gate: null,
  consent: null,
  kind: "needs_you",
  rung: "blocked",
  what_happened: "Two quotes use different pack sizes.",
  why_it_matters: "Comparing them per pack would favour the larger pack.",
  options: [
    {
      id: "per_kwh",
      label: "Compare per kWh",
      suggested: true,
      reason: "It is fair across pack sizes.",
      irreversible: false,
    },
    {
      id: "per_pack",
      label: "Compare per pack",
      suggested: false,
      irreversible: false,
    },
  ],
  actions: ["show_me", "snooze", "delegate"],
  answer_channels: ["web", "mobile_web", "email"],
  safe_default: "per_kwh",
} satisfies Card;

const NEEDS_YOU_COMPARE_BASIS = {
  id: "01J8Z3K4M5N6P7Q8R9S0T1V2W4",
  world_id: "w_01",
  run_id: "r_01J8Z3K4M5",
  header: {
    building: "B2",
    agent: "A_s1",
  },
  add_context: true,
  created_at: "2026-09-29T09:30:00.000Z",
  timeout: 3600,
  gate: null,
  consent: null,
  kind: "needs_you",
  rung: "needs_you",
  what_happened: "Two quotes use different pack sizes.",
  why_it_matters: "Comparing them per pack would favour the larger pack.",
  options: [
    {
      id: "per_kwh",
      label: "Compare per kWh",
      suggested: true,
      reason: "It is fair across pack sizes.",
      irreversible: false,
    },
    {
      id: "per_pack",
      label: "Compare per pack",
      suggested: false,
      irreversible: false,
    },
  ],
  actions: ["show_me", "snooze", "delegate"],
  answer_channels: ["web", "mobile_web", "email"],
  safe_default: "per_kwh",
} satisfies Card;

export const CARDS_VALID = [
  CONSENT_DRIVE_FOLDER,
  GATE_SAVE_FILE_REVERSIBLE,
  GATE_SEND_REPLY,
  MEETING_BUDGET_SPLIT,
  NEEDS_YOU_BLOCKED,
  NEEDS_YOU_COMPARE_BASIS,
] satisfies readonly Card[];
