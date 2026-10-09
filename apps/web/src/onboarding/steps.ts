// ONBOARD-1: the welcome and the tour's words, and where each coach mark points. The words say what Tilo is and what
// each place is for; none says that anything ran, is running or finished (HR-1..HR-7), and none presses (UX-7).
import type { PageId } from "../park/app/AppCtx";
import { parkPath } from "../park/app/router";

export interface TourCopy {
  id: string;
  title: string;
  body: string;
}

const NAV = [
  [
    "worlds",
    "Worlds",
    "Each project is a world. Open one to see its team and what is recorded for it.",
  ],
  ["skills", "Skills", "The abilities your agent teams draw on. Browse them here."],
  ["ledger", "Ledger", "Every cost and every decision your agents make, in one place."],
  ["agenda", "Agenda", "Pins from your team and Tilo, and a week that stays in sync."],
  ["team", "Team", "The people and agents on your team, and their roles."],
] as const satisfies readonly (readonly [PageId, string, string])[];

export const COPY = {
  welcomeTitle: "Welcome to Tilo",
  welcomeLede: "Tilo helps you get work done with a team of agents, and you stay in charge.",
  welcomeSteps: [
    { title: "Describe the work", body: "Say what you need in your own words on Home." },
    {
      title: "The Director plans it",
      body: "A Director drafts a plan and the team for it. You read it before anything starts.",
    },
    {
      title: "Agent teams run it, and you approve",
      body: "Teams do the work and ask you at the points that matter. Nothing that needs your say-so happens without it.",
    },
  ],
  welcomeNote: "You can take the tour again from the account menu.",
  takeTour: "Take the tour",
  skipWelcome: "Skip for now",
  tour: [
    {
      id: "intake",
      title: "Describe the work",
      body: "Type the job in your own words. Tilo drafts a plan for you to read before anything starts.",
    },
    ...NAV.map(([id, title, body]) => ({ id, title, body })),
    {
      id: "bell",
      title: "Notifications",
      body: "Anything that needs your say-so shows up here. Nothing important is decided for you.",
    },
    {
      id: "account",
      title: "Account menu",
      body: "Profile, connectors, team and sign out. Take this tour again from here whenever you like.",
    },
  ] satisfies TourCopy[],
  sample: {
    id: "sample",
    title: "A sample project",
    body: "A read-only sample project is ready to look through. It is a sample, not your work.",
    open: "Open the sample project",
  },
  skipTour: "Skip tour",
  back: "Back",
  next: "Next",
  done: "Done",
} as const;

export const SAMPLE_STEP_ID = COPY.sample.id;

const visible = (el: Element | null): Element | null =>
  el instanceof HTMLElement && el.isConnected && !el.hidden ? el : null;

const nav = (id: PageId) => (): Element | null =>
  visible(document.querySelector(`nav[aria-label="Main"] a[href="${parkPath(id)}"]`));

/** The real element each step points at, looked up when the step shows (null: the mark sits in the middle). */
export const TARGETS: Record<string, () => Element | null> = {
  intake: () => visible(document.querySelector('input[aria-label="Describe your task"]')),
  worlds: nav("worlds"),
  skills: nav("skills"),
  ledger: nav("ledger"),
  agenda: nav("agenda"),
  team: nav("team"),
  bell: () => visible(document.querySelector('button[aria-label="Notifications"]')),
  account: () => visible(document.querySelector('button[aria-label="Account menu"]')),
};

export interface TourStep extends TourCopy {
  target: () => Element | null;
}

/** The tour's steps; the sample project's is last and exists only when the worlds list marked one. */
export function tourSteps(sampleId: string | null): TourStep[] {
  const steps: TourStep[] = COPY.tour.map((s) => ({ ...s, target: TARGETS[s.id] ?? (() => null) }));
  if (sampleId) {
    steps.push({
      id: COPY.sample.id,
      title: COPY.sample.title,
      body: COPY.sample.body,
      target: () => null,
    });
  }
  return steps;
}
