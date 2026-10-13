// Hand-written fixture for the World page's Lovable build-handoff card (FR-CON-16; not in tilo-app.js,
// not generated). Holds the demo world's build-handoff prompt, source-file references (not uploaded by the link),
// decision key and contract size limits from config/build_partners.yaml (50,000 prompt chars, 32,000 URL chars).
import type { BuildHandoff, Decision } from "../types";
import { decisionFacts } from "./additive";

export const buildHandoffs: BuildHandoff[] = [
  {
    world: "k1",
    decisionKey: "lovable",
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

/** Separate approval; this never resolves the supplier-mail decision. */
export const buildHandoffDecisions: Decision[] = buildHandoffs.map((h) => ({
  k: h.decisionKey,
  world: h.world,
  title: "Lovable build handoff",
  body: `${h.prompt}\n\nThe link carries this prompt only. No files are uploaded.`,
  yes: h.approveLabel,
  icon: "arrowR",
  done: h.doneLabel,
  toast: "Lovable handoff approved",
  approvedTitle: "You approved the Lovable handoff",
  facts: decisionFacts[h.decisionKey],
}));
