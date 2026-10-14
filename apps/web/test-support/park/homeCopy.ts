import suggestions from "../../../../config/home_suggestions.json";

// WEB-4 test support: the Home page's copy and numbers, written out from the reference
// (design_handoff_tilo_web_app/design/Tilo App Home.dc.html and tilo-app.js), so a test names the design's
// own strings and not whatever the page renders. Nothing here is bundled.

export type ModeKey = "quick" | "routine" | "workspace";

export interface ModeCopy {
  readonly key: ModeKey;
  /** The option label in "Size of job". */
  readonly label: string;
  /** The tier badge on the plan card (the reference upper-cases the tier). */
  readonly tier: string;
  /** The word in "Tilo is drafting a <word> for ...". */
  readonly word: string;
  /** The example task: the input placeholder is `e.g. <example>`, and it stands in for an empty query. */
  readonly example: string;
  /** The label of the start control while the composer is idle. */
  readonly start: string;
  readonly hint: string;
  readonly chips: readonly string[];
  readonly agents: string;
  readonly cost: string;
  readonly eta: string;
  /** The plan card's confirm button. */
  readonly confirm: string;
  readonly steps: readonly string[];
}

export const MODES: readonly ModeCopy[] = [
  {
    key: "quick",
    label: "Quick task",
    tier: "VILLAGE",
    word: "village",
    example: "Summarise this week’s customer feedback",
    start: "Start task",
    hint: "You see the plan and the cost before any agent starts.",
    chips: suggestions.map((suggestion) => suggestion.label),
    agents: "2",
    cost: "about £0.60",
    eta: "about 6 min",
    confirm: "Start now",
    steps: [
      "Gather what it needs from your connected tools",
      "Do the work with 2 agents",
      "Hand you the result to review",
    ],
  },
  {
    key: "routine",
    label: "Routine",
    tier: "TOWN",
    word: "town",
    example: "Every Monday, match invoices to purchase orders",
    start: "Set up routine",
    hint: "You approve the first run. After that it runs on its own.",
    chips: ["Weekly invoice match", "Monday pricing check", "Daily inbox triage"],
    agents: "4",
    cost: "about £0.40 a run",
    eta: "first run tomorrow 08:00",
    confirm: "Schedule it",
    steps: [
      "Run once tomorrow at 08:00 for your approval",
      "Then repeat on the schedule you set",
      "Ask you if anything looks unusual",
    ],
  },
  {
    key: "workspace",
    label: "Workspace",
    tier: "CITY",
    word: "city",
    example: "Onboard 12 new hires across email, HR and laptops",
    start: "Plan project",
    hint: "Tilo drafts districts, teams and gates for your sign-off.",
    chips: ["Product launch", "Supplier onboarding", "Quarterly audit prep"],
    agents: "18",
    cost: "£400 budget to start",
    eta: "plan in about 2 min",
    confirm: "Draft the city",
    steps: [
      "Draft districts, teams and gates",
      "Estimate budget and timeline",
      "Wait for your sign-off before any spend",
    ],
  },
];

export const QUICK: ModeCopy = MODES[0] as ModeCopy;
export const ROUTINE: ModeCopy = MODES[1] as ModeCopy;
export const WORKSPACE: ModeCopy = MODES[2] as ModeCopy;

/** The "Live now" rows with both decisions open (dec = {}), in order: name, sub-line, progress. The
 * reference lists the worlds that need you or run, five at most. */
export const LIVE_OPEN = [
  { id: "k1", name: "K1 electric scooter", sub: "2 decisions waiting", prog: 46 },
  { id: "hires", name: "Onboard 12 new hires", sub: "Running · 58%", prog: 58 },
  { id: "northline", name: "Northline onboarding", sub: "Running · 72%", prog: 72 },
  { id: "calls", name: "Call summary", sub: "About 3 min left", prog: 80 },
  { id: "venues", name: "Venue options", sub: "5 of 8 venues checked", prog: 62 },
] as const;

/** "Up next today": the first two of today's agenda events after 09:18 in the fixture's own order
 * (the reference does not sort them, so "Read Tilo’s brief" at 13:30 is not one of the two). */
export const UP_NEXT = [
  { time: "10:30", title: "Focus · Q4 plan", sub: "Google Calendar · 90 min" },
  { time: "14:00", title: "Supplier sync · Northline", sub: "Tilo’s brief is ready" },
] as const;

/** Strings that only the sample data can produce: none may show where the data did not load. */
export const SAMPLE_ONLY = [
  "£2,412",
  "£8,000",
  "£6,300",
  "£3,420",
  "K1 electric scooter",
  "Onboard 12 new hires",
  "Northline onboarding",
  "Call summary",
  "Venue options",
  "Alex",
  "Supplier sync",
  "Focus · Q4 plan",
  "38 agents",
] as const;

/** The pins of the reference, by index of `app.pins`: which world, and the line under its name. */
export const PIN_WORLDS = ["k1", "hires", "invoice"] as const;
