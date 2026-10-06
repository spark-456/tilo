// Hand-written ADDITIVE fixture data (WEB-9c): values the design prototype (tilo-app.js) does not hold as
// data but which its pages hard-coded as copy. They live here so a page's logic stays generic ("No
// scenario-specific code"). Not generated; `index.ts` merges them onto the generated fixtures, and the
// parity test compares only the prototype's own fields. Strings are the designed copy, verbatim.
import type { AgendaRules, DecisionFacts, DecisionKey } from "../types";

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
  },
  mail: {
    project: "K1 electric scooter",
    subject: "Supplier brief",
    approver: "Alex Morgan",
    activity: "Sent the supplier brief to 3 battery suppliers",
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
          noteAfter: "Invites sent to Jin, Priya and Tom.",
        },
      },
    },
    focus: {
      label: "Block it",
      action: "accept",
      toast: "Blocked 09:30–11:30 on Monday in Google Calendar",
      accepted: {
        title: "Focus time · Mon 28 Sep",
        note: "09:30–11:30, added to your Google Calendar",
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
