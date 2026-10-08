// The copy and the flow data of the Skills page's header and its "Teach Tilo something new" card, taken from
// design_handoff_tilo_web_app/design/Tilo App Skills.dc.html (the markup and `renderVals`). The Api serves none
// of it (a teaching session has no endpoint yet), so it is page-local, as the Home composer's copy is. Nothing
// here names the person, the company or a skill of the sample data: those come from the Api.
import type { Skill } from "../../api/types";
import { type CurrencyCode, STEP_LEDGER_PRICES, runMoney } from "../../app/ledgerKpis";
import { SKILL_TRUST_CONFIG } from "./skillConfig";

export { STEP_LEDGER_PRICES };

export const INTRO =
  "Teach your agents new work, help them get better, and choose which tools they may touch. Every repeat of a skill gets faster and cheaper.";

/** One captured step / one run step every 900 ms (README Skills 2). */
export const STEP_MS = 900;
export const CAPTURE_STEPS = 4;

export const STEP_LABELS = ["Show it", "Tilo’s version", "Try run", "Save"] as const;

export type MethodKey = "record" | "guided" | "describe" | "upload";
export interface Method {
  key: MethodKey;
  name: string;
  desc: string;
  icon: string;
}
export const METHODS: readonly Method[] = [
  {
    key: "record",
    name: "Record my screen",
    desc: "Do it once while Tilo watches",
    icon: "screen",
  },
  {
    key: "guided",
    name: "Guided walkthrough",
    desc: "Click through it in Tilo’s browser",
    icon: "eye",
  },
  { key: "describe", name: "Describe it", desc: "Explain in words, Tilo tries it", icon: "pen" },
  {
    key: "upload",
    name: "Upload an example",
    desc: "A finished doc, video or sheet",
    icon: "upload",
  },
];

/** What the mock browser says for the two screen methods (the record address is built from the person's mail domain). */
export const GUIDED = {
  url: "Tilo browser · Accounts inbox",
  hint: "Tilo highlights what it sees and asks as you go.",
  start: "Start walkthrough",
} as const;
export const RECORD = {
  hint: "Do the task as normal. Tilo notes each step.",
  start: "Start recording",
} as const;
export const CAPTURED_HINT = "Got it. 4 steps captured.";
/** Widths of the four mock rows, in percent. */
export const MOCK_ROWS = [62, 48, 70, 40] as const;

export const CAP: Record<MethodKey, readonly string[]> = {
  record: [
    "Opened the new email from Northline in the Accounts inbox",
    "Downloaded the attached PDF invoice",
    "Copied supplier, amount and due date into “Invoices 2026”",
    "Labelled the email “Logged”",
  ],
  guided: [
    "Opened the newest invoice in the Accounts inbox",
    "Opened the PDF in the preview",
    "Pasted supplier, amount and due date into “Invoices 2026”",
    "Moved the email to the Logged folder",
  ],
  describe: [
    "Watch the Accounts inbox for invoice emails",
    "Open the attached PDF",
    "Copy supplier, amount and due date into “Invoices 2026”",
    "Label the email “Logged”",
  ],
  upload: [
    "Found 3 sheets in invoice-log-example.xlsx",
    "Columns: supplier, invoice number, amount, due date",
    "Each row matches one email in the Accounts inbox",
    "Emails with a row are labelled “Logged”",
  ],
};

export interface HelperSummaryFixture {
  readonly baseMonthlyAnswersAndFixes: number;
  readonly mistakesDeltaSinceJuly: string;
  readonly helperMonthLabel: string;
}

export const HELPER_SUMMARY_FIXTURE: HelperSummaryFixture = {
  baseMonthlyAnswersAndFixes: 41,
  mistakesDeltaSinceJuly: "−38%",
  helperMonthLabel: "September",
};

export interface CaptureFixtureEvent {
  readonly seq: number;
  readonly type: "skill.capture.step";
  readonly method: MethodKey;
  readonly stepIndex: number;
  readonly text: string;
  readonly delayMs: number;
  readonly source: "fixture";
}

export const CAPTURE_FIXTURE_EVENTS = Object.fromEntries(
  METHODS.map(({ key }) => [
    key,
    CAP[key].map(
      (text, stepIndex): CaptureFixtureEvent => ({
        seq: stepIndex + 1,
        type: "skill.capture.step",
        method: key,
        stepIndex,
        text,
        delayMs: STEP_MS,
        source: "fixture",
      }),
    ),
  ]),
) as unknown as Record<MethodKey, readonly CaptureFixtureEvent[]>;

export const DEFAULT_DESC =
  "When an invoice email arrives in the Accounts inbox, open the PDF, copy the supplier, amount and due date into the “Invoices 2026” sheet, then label the email “Logged”.";
export const DESCRIBE_HELP =
  "Write it like you’d explain it to a new colleague. Tilo asks if anything is unclear.";
export const DROP = {
  title: "Drop an example here",
  sub: "A finished spreadsheet, document or short screen video. Or click to use a sample.",
  doneTitle: "invoice-log-example.xlsx",
  doneSub: "3 sheets · 128 rows · Tilo read the pattern",
} as const;
export const NO_STEPS_YET = "Steps appear here as Tilo watches.";

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
export const LEARN_NOTE =
  "Tilo tries this once on a real invoice from today. Nothing is posted without your OK while the skill is learning.";
export const BUBBLE_TAIL =
  ". Change anything that looks wrong, and tell me where to stop and ask you.";

export const TRY = {
  practice: "Practice run · Northline invoice #2291",
  prompt: "Northline Components · £1,240.00 · due 9 Oct",
  promptTail: " to Invoices 2026?",
  yes: "Yes, add it",
  resultTitle: "Matched your way of doing it",
  resultSub: "4 of 4 steps · 1 min 08s · £0.38",
} as const;

export interface TryRunFixtureEvent {
  readonly seq: number;
  readonly type: "skill.try_run.step";
  readonly stepIndex: number;
  readonly text: string;
  readonly matched: boolean;
  readonly durationSec: number;
  readonly cost: number;
  readonly delayMs: number;
  readonly source: "fixture";
}

/** Fixture events driving the practice try-run (sum: 4 matched steps, 68s = 1 min 08s, £0.38). */
export const TRY_RUN_FIXTURE_EVENTS: readonly TryRunFixtureEvent[] = [
  {
    seq: 1,
    type: "skill.try_run.step",
    stepIndex: 0,
    text: PLAN[0].text,
    matched: true,
    durationSec: 14,
    cost: 0.05,
    delayMs: STEP_MS,
    source: "fixture",
  },
  {
    seq: 2,
    type: "skill.try_run.step",
    stepIndex: 1,
    text: PLAN[1].text,
    matched: true,
    durationSec: 18,
    cost: 0.09,
    delayMs: STEP_MS,
    source: "fixture",
  },
  {
    seq: 3,
    type: "skill.try_run.step",
    stepIndex: 2,
    text: PLAN[2].text,
    matched: true,
    durationSec: 21,
    cost: 0.14,
    delayMs: STEP_MS,
    source: "fixture",
  },
  {
    seq: 4,
    type: "skill.try_run.step",
    stepIndex: 3,
    text: PLAN[3].text,
    matched: true,
    durationSec: 15,
    cost: 0.1,
    delayMs: STEP_MS,
    source: "fixture",
  },
];

export function formatTryRunResult(
  events: readonly Pick<TryRunFixtureEvent, "matched" | "durationSec" | "cost">[],
  totalSteps: number = PLAN.length,
  currency: CurrencyCode = "GBP",
): { title: string; sub: string } {
  const matched = events.filter((e) => e.matched).length;
  const totalSec = events.reduce((sum, e) => sum + e.durationSec, 0);
  const totalCost = events.reduce((sum, e) => sum + e.cost, 0);
  const mins = Math.floor(totalSec / 60);
  const secs = String(totalSec % 60).padStart(2, "0");
  const dur = mins > 0 ? `${mins} min ${secs}s` : `${totalSec}s`;
  const title =
    matched === totalSteps
      ? TRY.resultTitle
      : `Matched ${matched} of ${totalSteps} steps of your way`;
  return {
    title,
    sub: `${matched} of ${totalSteps} steps · ${dur} · ${runMoney(totalCost, currency)}`,
  };
}

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
  currency: CurrencyCode = "GBP",
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

/** The estimates of Tilo's version; computed from the default plan and ledger prices. */
export const EST = estimateSkillPlan(PLAN, DEFAULT_ASK, "GBP");

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
