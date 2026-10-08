// Hand-written ADDITIVE fixture data (WEB-9c): values the design prototype (tilo-app.js) does not hold as
// data but which its pages hard-coded as copy. They live here so a page's logic stays generic ("No
// scenario-specific code"). Not generated; `index.ts` merges them onto the generated fixtures, and the
// parity test compares only the prototype's own fields. Strings are the designed copy, verbatim.
import type { AgendaRules, DecisionFacts, DecisionKey, Ledger } from "../types";

/** What each decision is about, by key; read as `Decision.facts`. */
export const decisionFacts: Record<DecisionKey, DecisionFacts> = {
  depot: {
    project: "K1 electric scooter",
    subject: "Laptop Depot",
    amount: 3420,
    approver: "Alex Morgan",
    waiting: "Laptop Depot sign-off",
    decided: "Laptop Depot approved today",
    approvedNote: "Approved · £3,420 · K1 electric scooter",
    activity: "You approved £3,420 for Laptop Depot",
    spendNote: {
      waiting: "£3,420 is waiting for your sign-off at Laptop Depot.",
      decided: "Laptop Depot approved today for £3,420. It’s billed on delivery.",
    },
    details: [
      ["Your limit", "No limit"],
      ["Asked by", "Builder agent"],
      ["Waited", "1 h 10 min"],
    ],
  },
  mail: {
    project: "K1 electric scooter",
    subject: "Supplier brief",
    approver: "Alex Morgan",
    activity: "Sent the supplier brief to 3 battery suppliers",
    approveLabel: "Send brief",
    details: [
      ["Recipients", "3 battery suppliers"],
      ["Signed with", "Your approval"],
      ["Waited", "1 h 20 min"],
    ],
  },
};

/** How the Agenda page behaves, by pin kind and decision; read as `Agenda.rules`. */
export const agendaRules: AgendaRules = {
  month: "September",
  dateLine: "Thursday 24 September",
  boardSubs: { team: "Northwind Ops · 5 people and Tilo" },
  suggestions: {
    find: {
      label: "Find a time",
      action: "find",
      find: {
        title: "K1 Level 3 gate review · 30 min · Alex, Jin, Priya, Tom",
        sub: "Tilo checked all four calendars. Pick a dashed slot to book it.",
        event: { id: "gate", title: "K1 gate review" },
        pin: {
          id: "tg",
          title: "K1 gate review booked",
          role: "research",
          due: "Tilo booked · just now",
          color: "lilac",
          noteAfter:
            "Invites to Jin, Priya and Tom go out once Google Calendar is connected and you approve.",
        },
      },
    },
    focus: {
      label: "Block it",
      action: "accept",
      toast: "Blocked 09:30–11:30 on Monday on your Agenda",
      accepted: {
        title: "Focus time · Mon 28 Sep",
        note: "09:30–11:30, added to your Agenda",
        due: "Blocked by Tilo",
        color: "lilac",
        group: "week",
        by: "tilo",
      },
    },
  },
  briefRewrites: [
    {
      event: "gate",
      dec: "depot",
      startsWith: "Laptop Depot",
      text: "Laptop Depot budget was approved today.",
    },
  ],
};

/**
 * The Ledger's "Saved by memory" comparison (the prototype typed "Up £120 on August" as copy). `total` is the sum
 * of the fixture's `memory`; a ledger whose memory differs does not state it.
 */
export const ledgerMemoryUp: NonNullable<Ledger["memoryUp"]> = {
  amount: 120,
  since: "August",
  total: 640,
};

/** Monthly helper summary display fixtures for the Skills "Who helped this month" card. */
export const HELPER_SUMMARY_FIXTURE = {
  baseMonthlyAnswersAndFixes: 41,
  mistakesDeltaSinceJuly: "−38%",
  helperMonthLabel: "September",
} as const;
