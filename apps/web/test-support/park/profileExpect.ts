// WEB-12 test data (not a test): the Profile page exactly as the design renders it, typed out by hand from
// design_handoff_tilo_web_app/design/Tilo App Profile.dc.html, inventory.md "Tilo App Profile.dc.html" and
// the user fixture (api/fixtures/user.ts). Literals on purpose: a fixture that drifts from the design fails
// here. "Sample data" is shell-only (WEB-3b): nothing on this page says it.
// BQ-SET-2 (DECIDED 8 Oct, user approved): the two honest lines of FR-SET-01 and FR-SET-02 are visible text now,
// pinned below as PROFILE_COPY.saveNote and NOTIF_COPY.quietNote. They are the only strings added to the design's.

export const USER = {
  name: "Alex Morgan",
  initials: "AM",
  email: "alex@northwind.co",
  title: "Operations lead",
  tz: "Europe/London",
  lang: "English (UK)",
  hours: "08:30 – 17:30, Monday to Friday",
} as const;

export const SUBTITLE = `${USER.title} · Northwind Ops · Owner on the Team plan`;

/** The nav tabs in order; `h2` is the card heading the design shows on that tab (billing has none). */
export const TABS = [
  { id: "profile", label: "Profile", section: "Profile", h2: ["Profile"] },
  { id: "appearance", label: "Appearance", section: "Appearance", h2: ["Appearance"] },
  // UI-STUDIO-5: the Studio settings order adds Spending and limits and Ask before.
  {
    id: "limits",
    label: "Spending and limits",
    section: "Spending and limits",
    h2: ["Spending and limits"],
  },
  { id: "ask", label: "Ask before", section: "Ask before", h2: ["Ask me before Tilo…"] },
  { id: "notifications", label: "Notifications", section: "Notifications", h2: ["Notifications"] },
  { id: "security", label: "Security", section: "Security", h2: ["Security"] },
  { id: "billing", label: "Plan and billing", section: "Plan and billing", h2: ["Invoices"] },
] as const;
export type TabId = (typeof TABS)[number]["id"];

export const CONNECTORS = "Connectors";

/** `[label, help, initial value]`: the six form fields in design order. */
export const FIELDS = [
  ["Full name", "Shown to your team", USER.name],
  ["Work email", "Display only · does not change how you sign in", USER.email],
  ["Job title", "Helps Tilo route approvals", USER.title],
  ["Time zone", "Agenda and routines use this", USER.tz],
  ["Language", "For drafts Tilo writes for you", USER.lang],
  ["Working hours", "Tilo won’t book outside these", USER.hours],
] as const;

export const PROFILE_COPY = {
  sub: "How you appear to your team and how Tilo addresses you.",
  cancel: "Cancel",
  save: "Save changes",
  /** BQ-SET-2: FR-SET-01, shown above the footer (also the Save button's aria-description and title). */
  saveNote: "Saved to your Tilo account, so it follows you to your other devices.",
} as const;

export const CHANNELS = ["Phone", "Email", "Slack"] as const;
/** `[key, label, sub, [phone, email, slack]]`: the design's initial matrix. */
export const NOTIF: readonly (readonly [string, string, string, readonly boolean[]])[] = [
  [
    "decisions",
    "A decision needs you",
    "Budget sign-offs, gates and anything outside the company",
    [true, true, true],
  ],
  [
    "spend",
    "Spend goes over a limit",
    "A world or district passes its budget",
    [true, true, false],
  ],
  ["finished", "Work is ready", "Quick tasks and routine runs finish", [true, false, true]],
  [
    "digest",
    "Morning digest at 08:00",
    "What happened overnight and what’s next",
    [false, true, false],
  ],
  ["weekly", "Weekly ledger summary", "Every Monday, spend and hours saved", [false, true, true]],
];
export const switchLabel = (label: string, channel: string): string => `${label} by ${channel}`;

export const NOTIF_COPY = {
  sub: "Choose where Tilo reaches you. Decisions always reach you somewhere.",
  columns: ["WHEN", "PHONE", "EMAIL", "SLACK"],
  quiet: "Quiet hours · 19:00 to 08:00",
  quietSub: "Decision threshold: Not available yet",
  quietLabel: "Quiet hours",
  needOne: "Decisions need at least one channel",
  /** BQ-SET-2: FR-SET-02, shown under the Quiet hours row (also that switch's aria-description). */
  quietNote:
    "Quiet hours silence the phone only. A decision that needs you is never hidden by quiet hours: it waits in Needs you.",
} as const;

export const APPEARANCE_COPY = {
  sub: "Your city, your way. Changes apply straight away.",
  // UI-STUDIO-1: the Studio settings' Light, Dark and System (follows the device).
  timeTitle: "Theme",
  times: [
    ["Light", "Bright lawns"],
    ["Dark", "Lamps and glow"],
    ["System", "Follows your device"],
  ],
  motionTitle: "Motion in the city",
  motions: ["Lively", "Calm", "Still"],
  help: {
    lively: "Full speed on Home. The city pauses when you leave Home.",
    calm: "Agents and cars move slowly. The city pauses when you leave Home.",
    still: "Nothing moves. Best for older laptops and long sessions.",
  },
  // UI-STUDIO-5: the scene behind the helper in Chat (display state on this device).
  sceneTitle: "Your Tilo hangs out in",
  sceneSub: "The scene behind your helper in Chat. Kept on this device only.",
  scenes: ["Office", "Balcony", "Beach", "Cosy room"],
} as const;

/** UI-STUDIO-5: Spending and limits, and Ask before, on the fixture Api (no team rules: says so). */
export const LIMITS_COPY = {
  sub: "Spending money always waits for a yes. These are the numbers Tilo checks against.",
  strings: [
    "Spent so far",
    "£2,412",
    "of £8,000 budget",
    "You can say yes to",
    "Not available yet",
    "An Owner sets this on the Team page",
    "Each day and each world",
    "Daily and per-world caps are not kept yet",
    "Open the Team page",
  ],
  askTitle: "Ask me before Tilo…",
  askSub: "These show up in Needs you. Turn one off and Tilo goes ahead without asking.",
  notConnected: "Not connected yet. Sign in to see your team’s rules.",
} as const;

/** Swatch colours of the two time-of-day cards: `[ground, block1, block2, block3]`. */
// UI-STUDIO-5: each look previews the Studio theme (ground, heading line, card, primary button).
export const SWATCHES = {
  day: ["#F6F6F4", "#0B0B0C", "#FFFFFF", "#0B0B0C"],
  night: ["#0A0A0B", "#F4F4F2", "#141416", "#C8F23A"],
} as const;

export const SECURITY_COPY = {
  sub: "Sign-in, devices and how approvals are confirmed.",
  rows: [
    // QA-DEMO-1: the design's "Confirm approvals with Face ID" row is gone (the mobile app is a concept).
    ["Two-step sign-in", "On · authenticator app", "Manage", "Two-step settings"],
  ],
  signedIn: "Signed in on",
  everywhere: "Sign out everywhere else",
  everywhereToast: "Signed out everywhere except this device",
  thisDevice: "This device",
  signOut: "Sign out",
} as const;

/** `[title, sub, current]` in design order. */
export const SESSIONS = [
  ["MacBook Pro · Chrome", "London · active now", true],
  ["iPhone 15 · Tilo app", "London · 2 hours ago · Face ID for approvals", false],
  ["iPad · Safari", "Manchester · yesterday", false],
] as const;

export const BILLING_COPY = {
  planLabel: "PLAN",
  plan: "Team",
  planSub: "5 seats, shared boards, two-person approvals. Renews 1 October.",
  compare: "Compare plans",
  compareToast: "Plan comparison opens here",
  spendLabel: "AGENT SPEND · SEPTEMBER",
  spend: "£2,412",
  of: "of £8,000",
  openLedger: "Open the Ledger",
  paymentLabel: "PAYMENT",
  card: "Visa ending 4242",
  invoicesTo: "Invoices go to finance@northwind.co",
  update: "Update",
  updateToast: "Card update is handled by our payment provider",
  invoices: "Invoices",
  paid: "Paid",
  download: "Download",
} as const;

/** `[title, amount, month used in the toast]` */
export const INVOICES = [
  ["September 2026 · 5 seats", "£245.00", "September 2026"],
  ["August 2026 · 5 seats", "£245.00", "August 2026"],
  ["July 2026 · 4 seats", "£196.00", "July 2026"],
] as const;

const header: readonly string[] = [
  USER.initials,
  USER.name,
  SUBTITLE,
  CONNECTORS,
  ...TABS.map((t) => t.label),
];

/** Every visible string of the page frame plus one tab, once each (the page's own text, options included). */
export const STRINGS: Record<TabId, readonly string[]> = {
  profile: [
    ...header,
    PROFILE_COPY.sub,
    ...FIELDS.flatMap((f) => [f[0], f[1]]),
    PROFILE_COPY.cancel,
    PROFILE_COPY.save,
    PROFILE_COPY.saveNote,
  ],
  notifications: [
    ...header,
    NOTIF_COPY.sub,
    ...NOTIF_COPY.columns,
    ...NOTIF.flatMap((n) => [n[1], n[2]]),
    NOTIF_COPY.quiet,
    NOTIF_COPY.quietSub,
    NOTIF_COPY.quietNote,
    PROFILE_COPY.cancel,
    PROFILE_COPY.save,
  ],
  appearance: [
    ...header,
    APPEARANCE_COPY.sub,
    APPEARANCE_COPY.timeTitle,
    ...APPEARANCE_COPY.times.flat(),
    APPEARANCE_COPY.motionTitle,
    ...APPEARANCE_COPY.motions,
    APPEARANCE_COPY.help.lively,
    APPEARANCE_COPY.sceneTitle,
    APPEARANCE_COPY.sceneSub,
    ...APPEARANCE_COPY.scenes,
  ],
  limits: [...header, LIMITS_COPY.sub, ...LIMITS_COPY.strings, LIMITS_COPY.notConnected],
  ask: [...header, LIMITS_COPY.askTitle, LIMITS_COPY.askSub, LIMITS_COPY.notConnected],
  security: [
    ...header,
    SECURITY_COPY.sub,
    ...SECURITY_COPY.rows.flatMap((r) => [r[0], r[1], r[2]]),
    SECURITY_COPY.signedIn,
    SECURITY_COPY.everywhere,
    ...SESSIONS.flatMap((s) => [s[0], s[1]]),
    SECURITY_COPY.thisDevice,
    SECURITY_COPY.signOut,
  ],
  billing: [
    ...header,
    BILLING_COPY.planLabel,
    BILLING_COPY.plan,
    BILLING_COPY.planSub,
    BILLING_COPY.compare,
    BILLING_COPY.spendLabel,
    BILLING_COPY.spend,
    BILLING_COPY.of,
    BILLING_COPY.openLedger,
    BILLING_COPY.paymentLabel,
    BILLING_COPY.card,
    BILLING_COPY.invoicesTo,
    BILLING_COPY.update,
    BILLING_COPY.invoices,
    ...INVOICES.flatMap((i) => [i[0], i[1]]),
    BILLING_COPY.paid,
  ],
};

/** Every aria-label on the page for a tab (a multiset, sorted); the nav is always "Settings". */
export const ARIA_LABELS: Record<TabId, readonly string[]> = {
  profile: ["Settings", "Profile"],
  notifications: [
    "Settings",
    "Notifications",
    ...NOTIF.flatMap((n) => CHANNELS.map((c) => switchLabel(n[1], c))),
    NOTIF_COPY.quietLabel,
  ],
  appearance: ["Settings", "Appearance"],
  limits: ["Settings", "Spending and limits"],
  ask: ["Settings", "Ask before"],
  security: ["Settings", "Security"],
  billing: [
    "Settings",
    "Plan and billing",
    BILLING_COPY.download,
    BILLING_COPY.download,
    BILLING_COPY.download,
  ],
};
