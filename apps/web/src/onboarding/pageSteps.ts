import { PAGE_LABEL, type PageId } from "../park/app/AppCtx";
import type { TourStep } from "./steps";

const CONTENT: Record<PageId, [string, string]> = {
  chat: [
    "Ask a quick question",
    "One helper answers right away and never acts for you. Bigger jobs become a world.",
  ],
  more: ["Find another page", "Open the tools and recorded activity for this project."],
  home: [
    "Describe the work",
    "Use the composer to describe a task. Read the proposed plan before starting.",
  ],
  worlds: [
    "Choose a project",
    "Open a project to see its recorded work. Sample projects are labelled and read-only.",
  ],
  world: [
    "Explore this project",
    "Explore the recorded run and its views. Sample content is not your work.",
  ],
  agenda: [
    "Plan your week",
    "Review your plate and calendar. Sample items are labelled and do not change your calendar.",
  ],
  skills: [
    "Explore skills",
    "Browse the skills available to agent teams and the history recorded for them.",
  ],
  needs: [
    "Answer what is waiting",
    "Read what each answer does before you give it. Nothing is sent until you answer.",
  ],
  ledger: [
    "Review recorded costs",
    "See recorded spend and decisions. Sample costs are not charges to your account.",
  ],
  team: [
    "See your team",
    "Review people and roles. Any sample people are fictional and clearly labelled.",
  ],
  connectors: [
    "Check real connections",
    "Connections show their real state. A tour never connects a tool or grants access.",
  ],
  settings: [
    "Review display and data preferences",
    "Display controls apply at once. Review routines and consent here; unavailable actions say so.",
  ],
  library: [
    "See what Tilo made",
    "Finished work from your projects is listed here as it is delivered. A tour changes nothing.",
  ],
  profile: [
    "Review your settings",
    "Your profile shows your real account and preferences. A tour changes nothing.",
  ],
};

/** Each mark points to page content or the existing account/help control, never a fabricated control. */
export function pageTourSteps(page: PageId): TourStep[] {
  const root = () => document.querySelector(`[data-testid="park-page-${page}"]`);
  const [title, body] = CONTENT[page];
  return [
    {
      id: `${page}-overview`,
      title: PAGE_LABEL[page],
      body:
        page === "connectors" || page === "profile" || page === "settings"
          ? `This is ${PAGE_LABEL[page]}. It shows your real state; the tour changes nothing.`
          : `This is ${PAGE_LABEL[page]}. Sample content is labelled; your own data replaces it after your first run.`,
      target: () => root()?.querySelector("h1") ?? root(),
    },
    {
      id: `${page}-content`,
      title,
      body,
      target: () =>
        (page === "home" ? root()?.querySelector(".park-home-composer") : null) ??
        root()?.querySelector("section, article, input, textarea, button") ??
        root(),
    },
    {
      id: `${page}-help`,
      title: "Find help again",
      body: "Replay the tour from the account menu. Not now dismisses only this page's invitation.",
      target: () => document.querySelector('button[aria-label="Account menu"]'),
    },
  ];
}
