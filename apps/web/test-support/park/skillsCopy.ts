// WEB-8a test support: the copy and the flow data of the Skills page's header and "Teach Tilo something new"
// card, taken from the user's design:
//   design_handoff_tilo_web_app/design/Tilo App Skills.dc.html (the markup and the `renderVals` data),
//   README "Skills" items 1 and 2, inventory.md "Tilo App Skills.dc.html" (static copy and labelled regions).
// Strings keep the design's typographic quotes and apostrophes. Nothing here is bundled.

/** STUDIO-4 (design/studio-v2 "Tilo S Skills"). */
export const INTRO =
  "Things your helpers already know how to do. Open one to see its steps, or teach Tilo something new.";
export const CARD_TITLE = "Teach Tilo something new";
export const CARD_SUB =
  "Show it once. Tilo repeats it, you check the result, and it becomes a skill your agents can reuse.";

/** The step bar, in order (STUDIO-4: the 3-step wizard). */
export const STEP_LABELS = ["Describe it", "Show an example", "Review the steps"] as const;

export const DEFAULT_NAME = "Log new supplier invoices";
export const DEFAULT_DESC =
  "When an invoice email arrives in the Accounts inbox, open the PDF, copy the supplier, amount and due date into the “Invoices 2026” sheet, then label the email “Logged”.";

export const METHODS = [
  { key: "record", name: "Record my screen", desc: "Do it once while Tilo watches" },
  { key: "guided", name: "Guided walkthrough", desc: "Click through it in Tilo’s browser" },
  { key: "describe", name: "Describe it", desc: "Explain in words, Tilo tries it" },
  { key: "upload", name: "Upload an example", desc: "A finished doc, video or sheet" },
] as const;
export type MethodKey = (typeof METHODS)[number]["key"];

/** What the mock browser shows for the two screen methods. */
export const SCREEN = {
  record: {
    url: "mail.northwind.co/accounts",
    hint: "Do the task as normal. Tilo notes each step.",
    start: "Start recording",
  },
  guided: {
    url: "Tilo browser · Accounts inbox",
    hint: "Tilo highlights what it sees and asks as you go.",
    start: "Start walkthrough",
  },
} as const;
export const CAPTURED_HINT = "Got it. 4 steps captured.";

/** The 4 steps "What Tilo has picked up" lists, per method (the first N once N are captured). */
export const CAP: Record<MethodKey, readonly [string, string, string, string]> = {
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

export const DESCRIBE_HELP =
  "Write it like you’d explain it to a new colleague. Tilo asks if anything is unclear.";
export const DROP = {
  title: "Drop an example here",
  sub: "A finished spreadsheet, document or short screen video. Or click to use a sample.",
  doneTitle: "invoice-log-example.xlsx",
  doneSub: "3 sheets · 128 rows · Tilo read the pattern",
} as const;

export const NO_STEPS_YET = "Steps appear here as Tilo watches.";

/** Tilo's version: the 4 plan steps with the tool and level each uses. */
export const PLAN = [
  { text: "Check the Accounts inbox for new supplier invoices", tool: "Gmail · Read" },
  { text: "Read supplier, invoice number, amount and due date from the PDF", tool: "Files · Read" },
  { text: "Add a row to “Invoices 2026”", tool: "Google Sheets · Act" },
  { text: "Label the email “Logged”", tool: "Gmail · Act" },
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

export const EST = {
  runLabel: "Each run",
  runValue: "~£0.40",
  timeLabel: "Time",
  timeValue: "~1 min",
  stopsLabel: "Stops to ask",
} as const;

export const TRY = {
  practice: "Practice run · Northline invoice #2291",
  prompt: "Northline Components · £1,240.00 · due 9 Oct",
  yes: "Yes, add it",
  resultTitle: "Matched your way of doing it",
  resultSub: "4 of 4 steps · 1 min 08s · £0.38",
} as const;

export const SAVE = {
  nameLabel: "Skill name",
  who: "Who can use it",
  scopes: ["Just me", "Northwind Ops"],
  when: "When it runs",
  triggers: ["When I ask", "Weekdays 09:00", "When an invoice arrives"],
  note: "It starts as Learning. I’ll ask before adding rows until we’ve had 5 good runs together, then you can mark it trusted.",
} as const;

export type Scope = "Just me" | "Northwind Ops";
export type Trigger = (typeof SAVE.triggers)[number];

/** The saved banner's second line and the toast, as the design's `savedSub` and `save` build them. */
export const SAVED_SUB: Record<Scope, string> = {
  "Northwind Ops": "Shared with Northwind Ops",
  "Just me": "Just for you",
};
export const SAVED_TRIGGER: Record<Trigger, string> = {
  "When I ask": "runs when you ask",
  "Weekdays 09:00": "runs every weekday at 09:00",
  "When an invoice arrives": "runs when an invoice arrives",
};
export const savedLine = (scope: Scope, trig: Trigger): string =>
  `${SAVED_SUB[scope]} · ${SAVED_TRIGGER[trig]} · starts as Learning`;
// HR W23 (PRD 9.4): the fixture save cannot make a skill live for a person or team.
export const savedToast = (name: string, _scope: Scope): string =>
  `Sample skill “${name}” saved on this page only. Nothing is live or scheduled.`;
export const savedTitle = (name: string): string => `“${name}” is now a skill`;

/** What "Save skill" hands to `saveSkill` on top of the draft skill `log` (design: the `S.live` override). */
export const SAVED_OVERRIDE = {
  st: "learning",
  status: "live",
  runs: 1,
  rate: 100,
  last: "Just now",
  first: 0.38,
  now: 0.38,
  from: "taught by you",
  owner: "Alex Morgan",
} as const;
