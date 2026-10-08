// Hand-written fixture for the World page's Lovable build-handoff card (FR-CON-16; not in tilo-app.js,
// not generated). Holds the demo world's build-handoff prompt, granted files that would leave Tilo,
// decision key and contract size limits from config/build_partners.yaml (50,000 prompt chars, 32,000 URL chars).
import type { BuildHandoff } from "../types";

export const buildHandoffs: BuildHandoff[] = [
  {
    world: "k1",
    decisionKey: "mail",
    approveLabel: "Approve Lovable handoff",
    doneLabel: "Approved · ready to open in Lovable",
    prompt: [
      "Goal: Build the K1 supplier quote intake and prototype tolerance dashboard.",
      "Audience: Hardware procurement leads and 3 invited battery pack suppliers.",
      "Data model: SupplierQuote (supplier_id, cell_chemistry, unit_price_gbp, lead_time_weeks, ip_rating) and PrototypeLot (lot_id, cycle_count, pass_rate).",
      "Acceptance criteria: Responsive intake form with CSV upload, side-by-side quote comparison table, and pass/fail tolerance badges.",
    ].join("\n"),
    files: [
      {
        path: "briefs/k1-supplier-portal.md",
        summary: "Supplier portal brief and comparison layout (4.2 KB)",
      },
      {
        path: "specs/battery-rfq-schema.json",
        summary: "Quote fields and validation rules (1.8 KB)",
      },
      {
        path: "data/approved-tolerances.csv",
        summary: "Sanitised cell test thresholds for Level 3 gate (2.1 KB)",
      },
    ],
    maxPromptChars: 50_000,
    maxUrlLength: 32_000,
  },
];
