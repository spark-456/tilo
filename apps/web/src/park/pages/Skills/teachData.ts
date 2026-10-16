// The copy and the sample flow data of the Skills page and its Teach wizard (STUDIO-4, design/studio-v2 "Tilo S
// Skills"; the sample plan and question come from the earlier design_handoff_tilo_web_app "Tilo App Skills"). The Api
// serves none of the sample: a live page shows only what the server answered. Nothing here names the person, the
// company or a skill of the sample data: those come from the Api.
import type { Ledger, Skill } from "../../api/types";
import { type CurrencyCode, STEP_LEDGER_PRICES, runMoney } from "../../app/ledgerKpis";
import { SKILL_TRUST_CONFIG } from "./skillConfig";

export { STEP_LEDGER_PRICES };

/** STUDIO-4 (design/studio-v2 "Tilo S Skills"), without the design's "Use one in a task" (no such action yet). */
export const INTRO =
  "Things Tilo knows how to do. They grow with you.";

/** One captured step / one run step every 900 ms (README Skills 2). */
/** Sample data: the four steps read from the sample description. */
export const CAPTURE_STEPS = 4;
export const CAP = {
  describe: [
    "Watch the Accounts inbox for invoice emails",
    "Open the attached PDF",
    "Copy supplier, amount and due date into “Invoices 2026”",
    "Label the email “Logged”",
  ],
} as const;

export const DEFAULT_DESC =
  "When an invoice email arrives in the Accounts inbox, open the PDF, copy the supplier, amount and due date into the “Invoices 2026” sheet, then label the email “Logged”.";
/** No API session (a demo): Tilo cannot read the description, so the steps are a sample and say so (HR-1). */
export const DESCRIBE_SAMPLE =
  "Sample only: the steps below are an example, not read from your description. Real steps need sign-in.";

export const PLAN = [
  {
    text: "Check the Accounts inbox for new supplier invoices",
    tool: "Gmail · Read",
    icon: "mail",
  },
  {
    text: "Read supplier, invoice number, amount and due date from the PDF",
    tool: "Files · Read",
    icon: "doc",
  },
  { text: "Add a row to “Invoices 2026”", tool: "Google Sheets · Act", icon: "chart" },
  { text: "Label the email “Logged”", tool: "Gmail · Act", icon: "tag" },
] as const;
/** Step 3 asks first by default. */
export const DEFAULT_ASK: readonly boolean[] = [false, false, true, false];

export const QUESTION = {
  eyebrow: "ONE QUESTION",
  text: "Some invoices arrive as a link, not a PDF. What should I do?",
  answers: ["Open the link", "Ask me each time", "Skip and flag it"],
} as const;
export const SAVE = {
  nameLabel: "Skill name",
  who: "Who can use it",
  when: "When it runs",
  note: `I’ll ask before adding rows until we’ve had ${SKILL_TRUST_CONFIG.minGoodRunsForTrust} good runs together, then you can mark it trusted.`,
} as const;

export type Scope = "me" | "team";
export type Trigger = "ask" | "weekday" | "arrive";
export const TRIGGERS: readonly { key: Trigger; label: string; runs: string }[] = [
  { key: "ask", label: "When I ask", runs: "runs when you ask" },
  { key: "weekday", label: "Weekdays 09:00", runs: "runs every weekday at 09:00" },
  { key: "arrive", label: "When an invoice arrives", runs: "runs when an invoice arrives" },
];

/** The saved banner's second line: who it is shared with, when it runs, and that it starts as Learning. */
export const savedLine = (who: string, t: Trigger): string =>
  `${who} · ${TRIGGERS.find((x) => x.key === t)?.runs ?? ""} · starts as Learning`;
export const sharedWith = (scope: Scope, org: string): string =>
  scope === "team" ? `Shared with ${org}` : "Just for you";

export const STEP_SECONDS = 15;

export const stopsToAsk = (asks: readonly boolean[]): string => {
  const n = asks.filter(Boolean).length;
  return n === 0 ? "Never" : `${n} ${n === 1 ? "step" : "steps"}`;
};

export function estimateSkillPlan(
  steps: readonly { readonly tool: string }[],
  asks: readonly boolean[],
  currency: CurrencyCode | Pick<Ledger, "currency"> = "GBP",
): { run: string; time: string; stops: string } {
  const cost = steps.reduce((sum, s) => {
    if (s.tool.endsWith("Act")) return sum + STEP_LEDGER_PRICES.Act;
    if (s.tool.endsWith("Draft")) return sum + STEP_LEDGER_PRICES.Draft;
    return sum + STEP_LEDGER_PRICES.Read;
  }, 0);
  const mins = Math.max(1, Math.round((steps.length * STEP_SECONDS) / 60));
  return {
    run: `~${runMoney(cost, currency)}`,
    time: `~${mins} min`,
    stops: stopsToAsk(asks),
  };
}

/** What "Save skill" sets on the draft skill (the design's `S.live` override). */
export const savedOverride = (owner: string): Partial<Skill> => ({
  st: "learning",
  status: "live",
  runs: 1,
  rate: 100,
  last: "Just now",
  first: 0.38,
  now: 0.38,
  from: "taught by you",
  owner,
});

/** SKILLS-3: what a saved skill shows on a live page: it has not run, so no count, rate or time is made up. */
export const liveSavedOverride = (owner: string): Partial<Skill> => ({
  st: "learning",
  status: "live",
  runs: null,
  rate: null,
  last: "",
  improved: "",
  from: "",
  owner,
});

/** SKILLS-5: the words of the live teach flow (new strings are flagged in the PR). */
export const LIVE_TEACH = {
  saved: (name: string) => `Saved “${name}”. It starts as Learning`,
} as const;

/** A new skill for a person whose data holds no draft to start from. */
export const blankSkill = (owner: string): Skill => ({
  id: "taught",
  name: "",
  team: "",
  owner,
  role: "builder",
  runs: 0,
  rate: null,
  last: "Not run yet",
  improved: "Draft",
  status: "draft",
  st: "draft",
  from: "taught by you",
  tools: [],
  used: [],
  steps: PLAN.map((p) => p.text),
});

export const pillTotal = (n: number): string => `${n} ${n === 1 ? "skill" : "skills"}`;
