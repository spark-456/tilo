import type { Brief } from "@tilo/contracts";
// Values copied from contracts/fixtures/brief/valid/supplier_comparison.json (never imported at runtime). Drift is caught by
// fixtures.drift.test.ts (PRD-18.3 flow). Regenerate by copying the JSON again.

export const BRIEF_SUPPLIER_COMPARISON = {
  goal: "Compare three suppliers' quotes for 500 scooter battery packs and recommend one.",
  deliverables: [
    {
      title: "Supplier comparison",
      format: "pdf",
    },
  ],
  audience: "Operations lead and finance reviewer",
  deadline: "2026-10-09",
  constraints: ["Use only quotes received this month", "Keep it to two pages"],
  sources: [
    {
      kind: "file",
      ref: "art_quote_a",
      label: "Quote A",
    },
    {
      kind: "connector",
      ref: "gmail",
      label: "Supplier threads",
    },
    {
      kind: "web",
      ref: "battery pack 48V 15Ah supplier reviews",
    },
  ],
  sensitivity: "business",
  assumptions: [
    {
      question: "Should shipping costs be included?",
      assumed: "Shipping is included in each total",
    },
  ],
  applied_preferences: [
    {
      field: "deliverables",
      value: "PDF output",
      citation: {
        kind: "preference",
        ref: "mem_output_format",
        recorded_at: "2026-09-29T09:30:00.000Z",
      },
    },
  ],
} satisfies Brief;
