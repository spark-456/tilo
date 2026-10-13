// WEB-6 test support: the World page's copy and numbers, written out from the reference
// (design_handoff_tilo_web_app/design/Tilo App World.dc.html, its data in tilo-app.js and the README "World
// detail"), so a test names the design's own strings and not whatever the page renders. Nothing here is bundled.

export interface WorldCopy {
  readonly id: string;
  readonly name: string;
  /** `<TIER> · <TOOL>` upper-cased (reference `eyebrow`). */
  readonly eyebrow: string;
  /** The status chip next to the eyebrow when the world is not paused and no decision is open. */
  readonly chip: string;
  /** `Owned by X · started Y · N agent(s)`. */
  readonly meta: string;
  /** The tag in the corner of the map. */
  readonly heroTag: string;
  /** The label at the end of the progress bar: `prog %`, else the world's `nextV`. */
  readonly progress: string;
  /** The bar's width in percent: `prog`, else 0. */
  readonly progW: number;
  readonly spend: string;
  /** The "of £4,000" / "per run" text beside the spend value ("" when the world has none). */
  readonly of: string;
  /** The note under the spend card. */
  readonly spendNote: string;
  /** The spend bar's width in percent, or null when the world has no budget (no bar). */
  readonly spendW: number | null;
  /** The facts grid: Owner, Started, <nextL>, Agents. */
  readonly facts: readonly (readonly [string, string])[];
  /** The skill chips (skills whose `used` holds the world). */
  readonly skills: readonly string[];
  /** The tool chips as [monogram, name], in the order the skills list them, without repeats. */
  readonly tools: readonly (readonly [string, string])[];
  readonly mainTitle: "Districts" | "Run history" | "Result";
  readonly mainSub: string;
}

export const K1: WorldCopy = {
  id: "k1",
  name: "K1 electric scooter",
  eyebrow: "CITY · WORKSPACE",
  chip: "Running",
  meta: "Owned by Alex Morgan · started 2 Sep · 38 agents",
  heroTag: "Level 3 of 6 · Prototypes and suppliers",
  progress: "46%",
  progW: 46,
  spend: "£1,386",
  of: "of £4,000",
  spendNote: "£3,420 is waiting for your sign-off at Laptop Depot.",
  spendW: 34.65,
  facts: [
    ["Owner", "Alex Morgan"],
    ["Started", "2 Sep"],
    ["Launch", "14 Nov"],
    ["Agents", "38"],
  ],
  skills: ["Draft a supplier brief", "Check firmware test results"],
  tools: [
    ["D", "Google Drive"],
    ["G", "Gmail"],
    ["S", "Slack"],
  ],
  mainTitle: "Districts",
  mainSub: "5 districts",
};

export const K1_DECIDED_SPEND_NOTE =
  "Laptop Depot approved today for £3,420. It’s billed on delivery.";

export const HIRES: WorldCopy = {
  id: "hires",
  name: "Onboard 12 new hires",
  eyebrow: "CITY · WORKSPACE",
  chip: "Running",
  meta: "Owned by Alex Morgan · started 14 Sep · 14 agents",
  heroTag: "4 districts · 14 agents",
  progress: "58%",
  progW: 58,
  spend: "£228",
  of: "of £600",
  spendNote: "38% of budget used. Forecast within budget.",
  spendW: 38,
  facts: [
    ["Owner", "Alex Morgan"],
    ["Started", "14 Sep"],
    ["Due", "Fri 2 Oct"],
    ["Agents", "14"],
  ],
  skills: ["Set up a new starter"],
  // Google Workspace has no connector of that name: the reference maps it to Gmail's monogram (MAP).
  tools: [
    ["G", "Google Workspace"],
    ["B", "BambooHR"],
    ["S", "Slack"],
  ],
  mainTitle: "Districts",
  mainSub: "4 districts",
};

export const NORTHLINE: WorldCopy = {
  id: "northline",
  name: "Supplier onboarding · Northline",
  eyebrow: "TOWN · WORKSPACE",
  chip: "Running",
  meta: "Owned by Jin Park · started 16 Sep · 7 agents",
  heroTag: "Small project · 7 agents",
  progress: "72%",
  progW: 72,
  spend: "£342",
  of: "of £500",
  // UI-10 B3: £342 is the project's spend so far, not a per-run cost, so a budgeted Town says so.
  spendNote: "£342 so far. Billed monthly.",
  spendW: 68.4,
  facts: [
    ["Owner", "Jin Park"],
    ["Started", "16 Sep"],
    ["Due", "Wed 30 Sep"],
    ["Agents", "7"],
  ],
  skills: ["Draft a supplier brief"],
  tools: [
    ["D", "Google Drive"],
    ["G", "Gmail"],
  ],
  mainTitle: "Run history",
  mainSub: "3 recent runs",
};

export const INVOICE: WorldCopy = {
  id: "invoice",
  name: "Weekly invoice match",
  eyebrow: "TOWN · ROUTINE",
  chip: "Scheduled",
  meta: "Owned by Priya Shah · started June · 5 agents",
  heroTag: "Runs on a schedule · Next run Mon 09:00",
  progress: "Mon 09:00",
  progW: 0,
  spend: "£0.60",
  of: "per run",
  spendNote: "Each run costs about £0.60. Billed monthly.",
  spendW: null,
  facts: [
    ["Owner", "Priya Shah"],
    ["Started", "June"],
    ["Next run", "Mon 09:00"],
    ["Agents", "5"],
  ],
  skills: ["Match invoices to purchase orders"],
  tools: [
    ["G", "Gmail"],
    ["X", "Xero"],
    ["D", "Google Sheets"],
  ],
  mainTitle: "Run history",
  mainSub: "3 recent runs",
};

export const CALLS: WorldCopy = {
  id: "calls",
  name: "Summarise yesterday’s calls",
  eyebrow: "VILLAGE · QUICK TASK",
  chip: "Running",
  meta: "Owned by Alex Morgan · started 09:04 · 1 agent",
  heroTag: "Quick task · 1 agent",
  progress: "80%",
  progW: 80,
  spend: "£0.40",
  of: "",
  spendNote: "Quick tasks are billed when they finish.",
  spendW: null,
  facts: [
    ["Owner", "Alex Morgan"],
    ["Started", "09:04"],
    ["Recorded state", "ends in 3 min"],
    ["Agents", "1"],
  ],
  skills: ["Summarise call notes"],
  tools: [
    ["D", "Google Drive"],
    ["S", "Slack"],
  ],
  mainTitle: "Result",
  mainSub: "About 3 min left",
};

export const COMP: WorldCopy = {
  id: "comp",
  name: "Competitor pricing",
  eyebrow: "VILLAGE · QUICK TASK",
  chip: "Ready",
  meta: "Owned by Tom Reyes · started 10:52 · 1 agent",
  heroTag: "Quick task · 1 agent",
  progress: "100%",
  progW: 100,
  spend: "£0.70",
  of: "",
  spendNote: "Quick tasks are billed when they finish.",
  spendW: null,
  facts: [
    ["Owner", "Tom Reyes"],
    ["Started", "10:52"],
    ["Ready", "11:18"],
    ["Agents", "1"],
  ],
  skills: ["Scan competitor prices"],
  // "Web" is drawn with the monogram W; "Google Sheets" maps to the Drive connector's monogram.
  tools: [
    ["W", "Web"],
    ["D", "Google Sheets"],
  ],
  mainTitle: "Result",
  mainSub: "Report · today 11:18",
};

/** A Village with no skill: "Uses Tilo’s general skills" and the fallback tools Gmail and Google Drive. */
export const VENUES: WorldCopy = {
  id: "venues",
  name: "Offsite venue options",
  eyebrow: "VILLAGE · QUICK TASK",
  chip: "Running",
  meta: "Owned by Alex Morgan · started 09:01 · 2 agents",
  heroTag: "Quick task · 2 agents",
  progress: "62%",
  progW: 62,
  spend: "£0.90",
  of: "",
  spendNote: "Quick tasks are billed when they finish.",
  spendW: null,
  facts: [
    ["Owner", "Alex Morgan"],
    ["Started", "09:01"],
    ["Recorded state", "ends in 6 min"],
    ["Agents", "2"],
  ],
  skills: [],
  tools: [
    ["G", "Gmail"],
    ["D", "Google Drive"],
  ],
  mainTitle: "Result",
  mainSub: "5 of 8 venues checked",
};

export const ALL: readonly WorldCopy[] = [K1, HIRES, NORTHLINE, INVOICE, CALLS, COMP, VENUES];

/** The districts of K1: name, note, "d of t buildings · n agents", bar width, chip, by `dec`. */
export interface DistrictCopy {
  readonly name: string;
  readonly note: string;
  readonly count: string;
  readonly w: number;
  readonly chip: "Needs you" | "Building" | "Done" | "Planned";
}
export function k1Districts(dec: { depot?: boolean; mail?: boolean }): DistrictCopy[] {
  return [
    {
      name: "Town Hall",
      note: "Director and tester on watch",
      count: "3 of 3 buildings · 4 agents",
      w: 100,
      chip: "Building",
    },
    dec.depot
      ? {
          name: "Firmware",
          note: "Laptop Depot is building",
          count: "2 of 2 buildings · 12 agents",
          w: 100,
          chip: "Building",
        }
      : {
          name: "Firmware",
          note: "Laptop Depot waiting on budget",
          count: "1 of 2 buildings · 12 agents",
          w: 50,
          chip: "Needs you",
        },
    {
      name: "Research",
      note: "Cell comparison finished",
      count: "2 of 2 buildings · 9 agents",
      w: 100,
      chip: "Done",
    },
    dec.mail
      ? {
          name: "Suppliers",
          note: "Brief out with 3 suppliers",
          count: "2 of 2 buildings · 8 agents",
          w: 100,
          chip: "Building",
        }
      : {
          name: "Suppliers",
          note: "Mail Room gate waiting",
          count: "1 of 2 buildings · 8 agents",
          w: 50,
          chip: "Needs you",
        },
    {
      name: "Launch",
      note: "Opens at Level 5",
      count: "0 of 2 buildings · 5 agents",
      w: 0,
      chip: "Planned",
    },
  ];
}

/** An activity row: who, text, time (the DOM order of the reference row). */
export type ActivityCopy = readonly [who: string, text: string, t: string];

export const K1_ACTIVITY: readonly ActivityCopy[] = [
  ["Builder", "Paused Laptop Depot. £3,420 is above the £2,500 district limit.", "11:52"],
  [
    "Courier lead",
    "Drafted a brief for 3 battery suppliers. Waiting at the Mail Room gate.",
    "11:40",
  ],
  ["Researcher", "Finished the battery cell comparison from 14 sources.", "11:18"],
  ["Tester", "Firmware 0.4.2 passed 31 of 32 checks. One retry queued.", "10:05"],
  ["Director", "Opened Level 3: prototypes and suppliers.", "09:30"],
];
export const K1_ACTIVITY_DEPOT: ActivityCopy = [
  "You",
  "Approved £3,420 for Laptop Depot.",
  "Just now",
];
export const K1_ACTIVITY_MAIL: ActivityCopy = [
  "You",
  "Sent the supplier brief to 3 battery suppliers.",
  "Just now",
];

/** The two decisions of K1 as the Waiting card shows them. */
export const DECISIONS = {
  depot: {
    title: "Laptop Depot · budget sign-off",
    body: "6 test laptops for firmware, £3,420. Above the £2,500 district limit.",
    yes: "Approve £3,420",
    done: "Approved · just now",
  },
  mail: {
    title: "Mail Room gate · supplier brief",
    body: "Brief ready for 3 battery suppliers outside the company. Nothing sent yet.",
    yes: "Send brief",
    done: "Sent to 3 suppliers · just now",
  },
} as const;

/** The runs of the Town worlds: what, when, cost, in the reference's DOM order (what, when, cost). */
export const NORTHLINE_RUNS: readonly (readonly [string, string, string])[] = [
  ["Portal access requested", "Today 08:10", "£1.20"],
  ["Contract sent for signature", "Tue 22 Sep", "£0.80"],
  ["Supplier details checked", "Mon 21 Sep", "£2.10"],
];
export const INVOICE_RUNS: readonly (readonly [string, string, string])[] = [
  ["142 matched · 3 flagged", "Mon 21 Sep 09:00", "£0.60"],
  ["131 matched · 0 flagged", "Mon 14 Sep 09:00", "£0.58"],
  ["127 matched · 1 flagged", "Mon 7 Sep 09:00", "£0.55"],
];

export const OUT = {
  calls: "Summary of 7 calls, with actions per owner",
  comp: "Report: 2 rivals cut prices by 6–8% this week",
  venues: "Shortlist of 3 venues for 20 people, under £4k",
} as const;

export const TOASTS = {
  later: "Tilo will remind you at 16:00",
  paused: "Sample only: paused on this page. Nothing real changed.", // issue 932: a sample world claims no real outcome
  resumed: "Sample only: resumed on this page. Nothing real changed.",
  shared: "Link copied. This is a sample world, so there is nothing real to share.",
  run: "Sample only: nothing was started. This demo world has no runner behind it.", // UI-10 B1: no run is claimed
  open: "Sample only: nothing was opened. This demo world has no result file behind it.",
  slack: "Shared to #ops in Slack",
} as const;

/** UI-10 B1: a real (signed-in, live) world has no run-now or open-result route yet, so the buttons say why they are off. */
export const OFF = {
  run: "Starting a run from this page is not connected yet. No run would start.",
  open: "This result has no file linked yet, so there is nothing to open.",
} as const;

export const NO_RUNS = "No runs yet. The first run waits for your approval.";
export const NO_SKILLS = "Uses Tilo’s general skills";

/** Strings that only the fixture data holds: none may show while the data is loading or not connected. */
export const SAMPLE_ONLY: readonly string[] = [
  "K1 electric scooter",
  "Alex Morgan",
  "Laptop Depot",
  "£1,386",
  "Level 3 of 6",
  "WAITING FOR YOU",
];
