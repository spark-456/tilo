// WEB-10 test data (not a test): the Team page exactly as the design renders it on first paint, typed out
// by hand from design_handoff_tilo_web_app/design/Tilo App Team.dc.html, inventory.md and the Team fixture
// (tilo-app.js team, learn.helpers). Literals on purpose: a fixture that drifts from the design fails here.

export const PEOPLE = [
  {
    id: "am",
    name: "Alex Morgan",
    init: "AM",
    sub: "alex@northwind.co · Operations lead",
    role: "Owner",
    limit: "No limit",
    helped: "28",
    bar: "100%",
    active: "Now",
  },
  {
    id: "ps",
    name: "Priya Shah",
    init: "PS",
    sub: "priya@northwind.co · Finance",
    role: "Approver",
    limit: "£2,500",
    helped: "17",
    bar: "61%",
    active: "2h ago",
  },
  {
    id: "jp",
    name: "Jin Park",
    init: "JP",
    sub: "jin@northwind.co · Supply chain",
    role: "Approver",
    limit: "£1,000",
    helped: "14",
    bar: "50%",
    active: "Yesterday",
  },
  {
    id: "tr",
    name: "Tom Reyes",
    init: "TR",
    sub: "tom@northwind.co · Sales",
    role: "Member",
    limit: "£250",
    helped: "4",
    bar: "14%",
    active: "Mon",
  },
  {
    id: "so",
    name: "Sam Ode",
    init: "SO",
    sub: "sam@northwind.co · Design",
    role: "Viewer",
    limit: "—",
    helped: "0",
    bar: "0%",
    active: "Last week",
  },
] as const;

export const ROLES = ["Owner", "Approver", "Member", "Viewer"] as const;
/** Spend limit column by role after a role change (the design's LIM table; a changed role drops its own limit). */
export const LIMIT_BY_ROLE: Record<string, string> = {
  Owner: "No limit",
  Approver: "£1,000",
  Member: "£250",
  Viewer: "—",
};

export const COVERAGE = [
  {
    id: "small",
    what: "Spend up to £1,000",
    who: ["Priya Shah", "Jin Park"],
    initials: ["PS", "JP"],
    names: "Priya, Jin",
    wait: "6 min",
    covered: true,
    options: [],
  },
  {
    id: "big",
    what: "Spend up to £2,500",
    who: ["Priya Shah"],
    initials: ["PS"],
    names: "Priya only",
    wait: "14 min",
    covered: false,
    options: ["Jin Park", "Tom Reyes"],
  },
  {
    id: "share",
    what: "Sharing outside the company",
    who: ["Jin Park"],
    initials: ["JP"],
    names: "Jin only",
    wait: "2 h 10 min",
    covered: false,
    options: ["Priya Shah", "Tom Reyes"],
  },
  {
    id: "gate",
    what: "Gate sign-offs",
    who: ["Jin Park"],
    initials: ["JP"],
    names: "Jin only",
    wait: "38 min",
    covered: false,
    options: ["Priya Shah", "Tom Reyes"],
  },
] as const;

export const RULES = [
  ["Spending over £250", "An approver signs off, within their limit", true],
  ["Sharing anything outside the company", "The owner or an approver signs off", true],
  ["Actions that can’t be undone", "Deleting, paying or mass emails need two people", true],
  ["Giving a skill more access to a tool", "Only the owner can change tool access", true],
  ["Routines that fall on a weekend", "Hold until Monday morning", false],
] as const;

/** `[label, [owner, approver, member, viewer]]`: the fixture's bit masks 7, 7, 3, 3, 3, 1, 1, 15 spelled out. */
export const MATRIX: readonly (readonly [string, readonly boolean[]])[] = [
  ["Start quick tasks", [true, true, true, false]],
  ["Build routines", [true, true, true, false]],
  ["Open workspaces", [true, true, false, false]],
  ["Approve spend up to their limit", [true, true, false, false]],
  ["Approve sharing outside", [true, true, false, false]],
  ["Change tool access", [true, false, false, false]],
  ["Invite people", [true, false, false, false]],
  ["See the ledger", [true, true, true, true]],
];

export const COPY = {
  title: "Team",
  count: "5 people",
  intro: "The people who share this space, and the helpers who work for all of you.", // UI-STUDIO-5
  invite: "Invite",
  headers: ["PERSON", "ROLE", "SPEND LIMIT", "HELPED TILO", "ACTIVE"],
  you: "You",
  coverageTitle: "Who signs off, and how fast",
  coverageSub: "Average wait this month, from the Ledger. Alex can approve anything as owner.",
  waitLink: "See wait times",
  addBackup: "Add a backup…",
  covered: "Covered",
  rulesTitle: "When agents stop and ask",
  rulesSub: "These rules apply in every world.",
  matrixTitle: "What each role can do",
  emailPlaceholder: "name@northwind.co",
} as const;

/** Every visible string of the first paint, once each (the page's own text, options included). */
export const FIRST_PAINT_STRINGS: readonly string[] = [
  COPY.title,
  COPY.count,
  COPY.intro,
  COPY.invite,
  ...COPY.headers,
  COPY.you,
  ...PEOPLE.flatMap((p) => [p.name, p.init, p.sub, p.limit, p.helped, p.active]),
  ...ROLES,
  COPY.coverageTitle,
  COPY.coverageSub,
  COPY.waitLink,
  COPY.addBackup,
  COPY.covered,
  ...COVERAGE.flatMap((c) => [c.what, c.names, c.wait, ...c.initials, ...c.options]),
  COPY.rulesTitle,
  COPY.rulesSub,
  ...RULES.map((r) => r[0]),
  ...RULES.map((r) => r[1]),
  COPY.matrixTitle,
  ...MATRIX.map((m) => m[0]),
];
