// LANDING-2: the product sections of the signed-out landing, between the recorded run and the closing call to action
// (design/studio-v2 "Tilo S Landing" look; tokens only). Every claim here is something the app, the API or the PRD
// already does, in the app's own words (Teach a skill, Your context, Team board, Needs you, Ledger, connector levels
// Off/Read/Draft/Act). What is not switched on everywhere yet carries a "Coming" or "Rolling out" chip, never a
// promise. Examples are labelled as examples; nothing here is a live number, quote or logo.
import type { ReactNode } from "react";
import { helperArt, iconArt } from "./landingKit";
import { Reveal } from "./Reveal";

type Chip = "soon" | "rolling" | "now";
const CHIP_TEXT: Record<Chip, string> = {
  soon: "Coming",
  rolling: "Rolling out",
  now: "Available",
};

function StatusChip({ kind, children }: { kind: Chip; children?: ReactNode }) {
  return (
    <span className={`landing-chip landing-chip--${kind}`}>{children ?? CHIP_TEXT[kind]}</span>
  );
}

function Head({
  id,
  eyebrow,
  title,
  lead,
}: { id: string; eyebrow: string; title: string; lead?: string }) {
  return (
    <Reveal className="landing-section__head">
      <span className="landing-eyebrow">{eyebrow}</span>
      <h2 id={id}>{title}</h2>
      {lead ? <p>{lead}</p> : null}
    </Reveal>
  );
}

function Ticks({ items }: { items: readonly string[] }) {
  return (
    <ul className="landing-rules">
      {items.map((t) => (
        <li key={t}>
          <span className="landing-rules__tick" aria-hidden="true">
            ✓
          </span>
          {t}
        </li>
      ))}
    </ul>
  );
}

/* ---- Skills that grow with you ---- */
const SKILL_LIFE: ReadonlyArray<readonly [string, string]> = [
  ["Teach it", "Describe the job in plain words. Tilo turns it into steps you can read and edit."],
  [
    "Check the steps",
    "Any step that sends, pays, deletes, shares or books is set to ask you first. That is built in.",
  ],
  [
    "Save it",
    "A saved skill starts as Learning, for just you or your team, to run on request, on a schedule or when something happens.",
  ],
  [
    "Rate and fix",
    "Mark a run down and say which step went wrong. The fix applies to the next run and is written down.",
  ],
  [
    "Earn trust",
    "After enough good runs you can mark a skill trusted. You can pause it at any time.",
  ],
];

const SKILLS: ReadonlyArray<{ name: string; line: string; icon: string; tint: string }> = [
  {
    name: "Web research",
    line: "Searches public pages and says where every fact came from.",
    icon: "search",
    tint: "blue",
  },
  {
    name: "Question bank",
    line: "Pulls multiple-choice questions out of past papers.",
    icon: "doc",
    tint: "green",
  },
  {
    name: "Quiz check",
    line: "Marks a quiz attempt and names the topics to practise.",
    icon: "chart",
    tint: "amber",
  },
  {
    name: "Teach your own",
    line: "Describe how you do something. Tilo drafts a skill you can check.",
    icon: "cap",
    tint: "lilac",
  },
];

export function SkillsSection() {
  return (
    <Reveal as="section" className="landing-section" id="skills" aria-labelledby="landing-skills">
      <Head
        id="landing-skills"
        eyebrow="SKILLS"
        title="Skills that grow with you."
        lead="Tilo starts with a ready-made library. Teach it your own in plain words, and each skill gets better as it runs."
      />
      <div className="landing-split">
        <Reveal as="ol" className="landing-life" aria-label="How a skill grows">
          {SKILL_LIFE.map(([name, line], i) => (
            <li key={name} className="landing-life__row">
              <span className="landing-life__n landing-mono" aria-hidden="true">
                {String(i + 1).padStart(2, "0")}
              </span>
              <span>
                <strong>{name}</strong>
                <span className="landing-life__line">{line}</span>
              </span>
            </li>
          ))}
        </Reveal>
        <div className="landing-stack">
          <ul className="landing-skills landing-skills--two" aria-label="Ready-made skills">
            {SKILLS.map((s, i) => (
              <Reveal as="li" index={i} key={s.name} className="landing-skill">
                <span className={`landing-skill__icon landing-tint--${s.tint}`} aria-hidden="true">
                  {iconArt(s.icon, 24)}
                </span>
                <span className="landing-skill__name">{s.name}</span>
                <span className="landing-skill__line">{s.line}</span>
              </Reveal>
            ))}
          </ul>
          <Reveal className="landing-card landing-card--flat">
            <h3>Skills learn from real runs</h3>
            <p>
              When a Team Lead answers a question during a run, they can propose that answer as a
              change to the skill. A domain expert reviews the exact difference before anything
              changes.
            </p>
            <p className="landing-card__soon">
              <StatusChip kind="soon" />
              Teach by recording your screen or adding an example file, and a try run that rehearses
              a skill first.
            </p>
          </Reveal>
        </div>
      </div>
    </Reveal>
  );
}

/* ---- Meeting notetaker ---- */
const MEETING_STEPS: ReadonlyArray<readonly [string, string]> = [
  [
    "Ask Tilo to host",
    "You approve a card that shows the title, the time and exactly who is invited. Then Tilo’s own meeting account creates the Google Meet.",
  ],
  [
    "It joins and says so",
    "At the time, Tilo’s notetaker enters as host, tells everyone it is taking notes before anything else, and never lets anyone in on its own.",
  ],
  [
    "Minutes you check",
    "After the call Tilo drafts a summary, the decisions and the action items. You read them and confirm.",
  ],
  [
    "Follow-ups you approve",
    "Pick who gets a follow-up and Tilo drafts it. It shows up in Needs you, and nothing is sent until you approve.",
  ],
];

export function MeetingsSection({ night }: { night: boolean }) {
  return (
    <Reveal
      as="section"
      className="landing-section"
      id="meetings"
      aria-labelledby="landing-meetings"
    >
      <Head
        id="landing-meetings"
        eyebrow="MEETING NOTETAKER"
        title="A notetaker that tells people it’s there."
        lead="Tilo can join your Google Meet as an open, disclosed notetaker, then turn the call into minutes and follow-ups that wait for your review."
      />
      <div className="landing-split">
        <ol className="landing-flow" aria-label="How a meeting goes">
          {MEETING_STEPS.map(([name, line], i) => (
            <Reveal as="li" index={i} key={name} className="landing-flow__row">
              <span className="landing-flow__n landing-mono" aria-hidden="true">
                {i + 1}
              </span>
              <span>
                <strong>{name}</strong>
                <span className="landing-life__line">{line}</span>
              </span>
            </Reveal>
          ))}
        </ol>
        <Reveal className="landing-card landing-minutes" aria-label="Example minutes">
          <span className="landing-minutes__who" aria-hidden="true">
            {helperArt({ role: "research", expr: "neutral" }, 72, night)}
          </span>
          <span className="landing-recorded">Example, not a real meeting</span>
          <h3>Minutes</h3>
          <dl className="landing-minutes__list">
            <dt>Summary</dt>
            <dd>The team agreed the order of work for the next two weeks.</dd>
            <dt>Decisions</dt>
            <dd>Start with the smaller pilot. Review it together on Friday.</dd>
            <dt>Action items</dt>
            <dd>One owner per item, each one checked by you before it counts.</dd>
          </dl>
          <p className="landing-minutes__gate">Needs your approval · nothing sent</p>
        </Reveal>
      </div>
      <Reveal className="landing-note">
        <StatusChip kind="rolling" />
        Meeting hosting and minutes are switched on per workspace as they are checked. A sample
        meeting never analyses a real call.
      </Reveal>
    </Reveal>
  );
}

/* ---- Teams ---- */
const TEAM_POINTS = [
  "Create a team and invite people by email. Resend or cancel an invite at any time.",
  "Give each person a role and their own spend limit.",
  "Shared team worlds are visible to every member, with their contributions. Only personal items stay private.",
  "Choose who signs off each kind of approval. The rules that must always ask can’t be switched off, and every change is logged.",
  "A Team board in the Agenda for everyone, and a My board only you and Tilo can see.",
];
const ALWAYS_ASK = ["Spending money", "Sharing outside the team", "Anything that can’t be undone"];

export function TeamsSection() {
  return (
    <Reveal as="section" className="landing-section" id="teams" aria-labelledby="landing-teams">
      <Head
        id="landing-teams"
        eyebrow="TEAMS"
        title="Run it with your team."
        lead="Work is shared, limits are clear, and the big decisions always go to a person."
      />
      <div className="landing-split">
        <Reveal>
          <Ticks items={TEAM_POINTS} />
        </Reveal>
        <Reveal className="landing-card" aria-label="Who can say yes">
          <h3>Who can say yes</h3>
          <p className="landing-card__lead">
            These always wait for a person, whoever started the work.
          </p>
          <ul className="landing-always">
            {ALWAYS_ASK.map((a) => (
              <li key={a}>
                <span className="landing-always__lock" aria-hidden="true">
                  {iconArt("lock", 18)}
                </span>
                <span>
                  <strong>{a}</strong>
                  <span className="landing-life__line">Always waits for a person’s yes</span>
                </span>
              </li>
            ))}
          </ul>
          <p className="landing-card__soon">
            <StatusChip kind="soon" />A backup approver for when someone is away.
          </p>
        </Reveal>
      </div>
    </Reveal>
  );
}

/* ---- Onboarding ---- */
const ONBOARD = [
  {
    icon: "bolt",
    title: "One step to start",
    line: "Type the job on Home and Tilo goes straight to a running world. No questions by default: the assumptions it made are shown, and you can change any of them.",
  },
  {
    icon: "eye",
    title: "A short first-run tour",
    line: "Describe, plan, run, approve: four quick stops. Take the tour again whenever you like from the account menu.",
  },
  {
    icon: "grid",
    title: "A sample project",
    line: "A read-only sample world is ready to look through, clearly marked as a sample and not your work.",
  },
] as const;

export function OnboardingSection() {
  return (
    <Reveal
      as="section"
      className="landing-section"
      id="onboarding"
      aria-labelledby="landing-onboarding"
    >
      <Head
        id="landing-onboarding"
        eyebrow="GETTING STARTED"
        title="Signed in and working in one step."
        lead="Sign in with Google, say what you need, and your first world is running. Nothing to set up first."
      />
      <ul className="landing-trio">
        {ONBOARD.map((o, i) => (
          <Reveal as="li" index={i} key={o.title} className="landing-card">
            <span className="landing-skill__icon landing-tint--lilac" aria-hidden="true">
              {iconArt(o.icon, 24)}
            </span>
            <h3>{o.title}</h3>
            <p>{o.line}</p>
          </Reveal>
        ))}
      </ul>
    </Reveal>
  );
}

/* ---- Pinboards and your context ---- */
const PINS_ME = ["Draft the supplier reply", "Book the Thursday review"];
const PINS_TEAM = ["Collect this week’s numbers", "Prepare the board pack"];

function Board({ title, sub, pins }: { title: string; sub: string; pins: readonly string[] }) {
  return (
    <div className="landing-board">
      <strong>{title}</strong>
      <span className="landing-life__line">{sub}</span>
      <ul className="landing-board__pins">
        {pins.map((p) => (
          <li key={p} className="landing-pin">
            {p}
          </li>
        ))}
      </ul>
    </div>
  );
}

export function ContextSection() {
  return (
    <Reveal as="section" className="landing-section" id="context" aria-labelledby="landing-context">
      <Head
        id="landing-context"
        eyebrow="PINBOARDS AND CONTEXT"
        title="Everything in play, at a glance."
        lead="Pins hold what needs doing. Your context shows what Tilo is working with, right next to the page you’re on."
      />
      <div className="landing-split">
        <Reveal className="landing-card">
          <h3>Pinboards in the Agenda</h3>
          <p>
            Pins come from your team and from Tilo, who can suggest one for you to accept. Your week
            stays in sync beside them.
          </p>
          <div className="landing-boards">
            <Board title="Team board" sub="Everyone on the team and Tilo" pins={PINS_TEAM} />
            <Board title="My board" sub="Only you and Tilo can see this" pins={PINS_ME} />
          </div>
          <span className="landing-recorded">Example pins</span>
        </Reveal>
        <Reveal className="landing-card">
          <h3>Your context</h3>
          <p>
            One panel on the right of any page. Open it from the button, or with Alt + Shift + C.
          </p>
          <ul className="landing-ctx">
            <li>
              <strong>Now</strong>
              <span className="landing-life__line">
                What’s waiting for you, today’s work and meetings.
              </span>
            </li>
            <li>
              <strong>This project</strong>
              <span className="landing-life__line">The project you’re in and its decisions.</span>
            </li>
            <li>
              <strong>Workspace</strong>
              <span className="landing-life__line">Your team and the tools you’ve connected.</span>
            </li>
          </ul>
        </Reveal>
      </div>
    </Reveal>
  );
}

/* ---- Connectors ---- */
interface App {
  readonly name: string;
  readonly line: string;
  readonly chip: Chip;
  /** The chip's own words, where "Available" would say too much. */
  readonly say?: string;
  readonly note?: string;
  readonly icon: string;
}
const GOOGLE = "Google sign-in";
const APPS: readonly App[] = [
  {
    name: "Gmail",
    line: "Read mail and draft replies for you to review.",
    chip: "now",
    say: GOOGLE,
    icon: "mail",
  },
  {
    name: "Google Calendar",
    line: "See your week and put things on it.",
    chip: "now",
    say: GOOGLE,
    icon: "calendar",
  },
  {
    name: "Google Drive",
    line: "Read and prepare files you choose.",
    chip: "now",
    say: GOOGLE,
    icon: "doc",
  },
  {
    name: "Meeting host",
    line: "Hosts and joins Google Meet as your notetaker.",
    chip: "rolling",
    icon: "screen",
  },
  {
    name: "Slack",
    line: "Share a world link through an approval card.",
    chip: "soon",
    icon: "share",
  },
  {
    name: "Lovable",
    line: "Tilo writes the build brief. You press send in Lovable.",
    chip: "now",
    say: "Brief hand-off",
    note: "A direct connection is coming.",
    icon: "make",
  },
  { name: "Canva", line: "Decks and documents from approved content.", chip: "soon", icon: "pen" },
  {
    name: "More tools",
    line: "Notion, GitHub, Jira and others are listed, each with its own sign-in.",
    chip: "soon",
    icon: "plug",
  },
];

export function ConnectorsSection() {
  return (
    <Reveal
      as="section"
      className="landing-section"
      id="connectors"
      aria-labelledby="landing-connectors"
    >
      <Head
        id="landing-connectors"
        eyebrow="CONNECTORS"
        title="Your tools, on your terms."
        lead="Connect the apps you use. For each one you decide what Tilo may do: Off, Read, Draft or Act."
      />
      <ul className="landing-apps">
        {APPS.map((a, i) => (
          <Reveal as="li" index={i} key={a.name} className="landing-app">
            <span className="landing-app__icon" aria-hidden="true">
              {iconArt(a.icon, 22)}
            </span>
            <span className="landing-app__body">
              <span className="landing-app__top">
                <strong>{a.name}</strong>
                <StatusChip kind={a.chip}>{a.say}</StatusChip>
              </span>
              <span className="landing-life__line">
                {a.line}
                {a.note ? ` ${a.note}` : ""}
              </span>
            </span>
          </Reveal>
        ))}
      </ul>
      <Reveal className="landing-note landing-note--plain">
        <span className="landing-note__icon" aria-hidden="true">
          {iconArt("key", 18)}
        </span>
        Tilo never sees or stores your passwords. You sign in with the app itself, see every
        permission in plain words first, and can disconnect at any time.
      </Reveal>
    </Reveal>
  );
}

/* ---- Enterprise and personal ---- */
const ENTERPRISE = [
  "A ledger of every cost and decision, so finance and auditors can see what happened and why.",
  "A policy engine with risk tiers. The riskiest actions always need a person, and no model decides that.",
  "Budgets, per-person spend limits and credit caps, with the cost shown before work starts.",
  "Team visibility: shared worlds, named approvers, roles and logged rule changes.",
  "A Pause-all control and a Trace of every step.",
];
const PERSONAL = [
  "Trip plans with the cost shown before anything is booked.",
  "Email drafts that wait for you to read and send them.",
  "Research that names where each fact came from.",
  "Your agenda and meeting follow-ups, drafted for you to review.",
  "Study help: a question bank from past papers and quiz marking.",
];

export function AudiencesSection() {
  return (
    <Reveal
      as="section"
      className="landing-section"
      id="audiences"
      aria-labelledby="landing-audiences"
    >
      <Head
        id="landing-audiences"
        eyebrow="FOR WORK AND FOR YOU"
        title="Built for companies. Just as handy for one person."
      />
      <div className="landing-twin">
        <Reveal as="article" className="landing-card" aria-labelledby="landing-aud-ent">
          <span className="landing-eyebrow">ENTERPRISE AND TEAMS</span>
          <h3 id="landing-aud-ent">Control without the paperwork</h3>
          <Ticks items={ENTERPRISE} />
        </Reveal>
        <Reveal as="article" index={1} className="landing-card" aria-labelledby="landing-aud-me">
          <span className="landing-eyebrow">PERSONAL PRODUCTIVITY</span>
          <h3 id="landing-aud-me">Your own small team</h3>
          <Ticks items={PERSONAL} />
        </Reveal>
      </div>
    </Reveal>
  );
}

/* ---- Why Tilo ---- */
const WHY: ReadonlyArray<readonly [string, string, string]> = [
  [
    "eye",
    "Honest, visible work",
    "Nothing in the world moves unless something was recorded. What you watch is what happened.",
  ],
  [
    "coin",
    "Cost first",
    "You see the price before work starts and stay inside the budget you approve.",
  ],
  [
    "check",
    "A person approves anything risky",
    "Spending, sharing outside and anything irreversible wait for a yes, every time.",
  ],
  [
    "swap",
    "Not tied to one model",
    "Models are configuration, not code. Tilo can change which one does a job without changing what you see.",
  ],
  [
    "globe",
    "Built on Google Cloud",
    "Runs on Cloud Run and Firestore, with Gemini among the models it uses.",
  ],
];

export function WhySection() {
  return (
    <Reveal as="section" className="landing-section" id="why" aria-labelledby="landing-why">
      <Head
        id="landing-why"
        eyebrow="WHY TILO"
        title="Agents you can actually watch, and trust."
        lead="Most AI work happens out of sight. Tilo shows it, prices it, and asks before it matters."
      />
      <ul className="landing-why">
        {WHY.map(([icon, name, line], i) => (
          <Reveal as="li" index={i} key={name} className="landing-why__item">
            <span className="landing-skill__icon landing-tint--green" aria-hidden="true">
              {iconArt(icon, 24)}
            </span>
            <h3>{name}</h3>
            <p>{line}</p>
          </Reveal>
        ))}
      </ul>
    </Reveal>
  );
}
