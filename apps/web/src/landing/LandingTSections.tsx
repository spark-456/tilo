import type { Plan } from "../park/api/types";
import { Reveal } from "./Reveal";
import { cityArt, helperArt, iconArt } from "./landingKit";

/* ---- Section 1: ONE LINE IN ---- */
interface ScoreRow {
  readonly k: string;
  readonly a: string;
  readonly b: string;
  readonly c: string;
  readonly aBold?: boolean;
  readonly bBold?: boolean;
  readonly cBold?: boolean;
}

const SCORE_DATA: readonly ScoreRow[] = [
  { k: "Price a pack", a: "£78", b: "£71", c: "£83", bBold: true },
  { k: "Warranty", a: "3 years", b: "2 years", c: "3 years", aBold: true, cBold: true },
  { k: "Ships in", a: "2 weeks", b: "6 weeks", c: "3 weeks", aBold: true },
  { k: "Replied", a: "Same day", b: "2 days", c: "Same day", aBold: true, cBold: true },
];

export function OneLineSection({ night }: { night: boolean }) {
  return (
    <Reveal
      as="section"
      className="landing-section landing-t-section landing-t-oneline"
      id="sentence"
      aria-labelledby="landing-sentence"
    >
      <div className="landing-t-oneline__copy">
        <span className="landing-eyebrow">ONE LINE IN</span>
        <h2 id="landing-sentence">You type one sentence. You get the whole thing back.</h2>
        <p className="landing-t-lead">
          No prompts to engineer, no tabs to juggle. Here’s a real one from this week.
        </p>
        <div className="landing-t-quote-box">“Compare 3 battery suppliers for the K1 scooter.”</div>
        <div className="landing-t-meta">
          <span>4 HELPERS</span>
          <span>·</span>
          <span>23 MIN</span>
          <span>·</span>
          <span>£1.84</span>
          <span>·</span>
          <span>1 YES FROM YOU</span>
        </div>
      </div>
      <Reveal className="landing-t-scorecard">
        <div className="landing-t-scorecard__head">
          <span className="landing-t-pill landing-t-pill--mint">Done</span>
          <span className="landing-t-scorecard__sub">Supplier scorecard · 1 page</span>
          <span className="landing-t-scorecard__pdf">↓ PDF</span>
        </div>
        <h3 className="landing-t-scorecard__title">Brightcell wins, narrowly.</h3>
        <div className="landing-t-table">
          <div className="landing-t-table-row landing-t-table-row--head">
            <span />
            <span>Brightcell</span>
            <span>Voltway</span>
            <span>Nordpack</span>
          </div>
          {SCORE_DATA.map((row) => (
            <div key={row.k} className="landing-t-table-row">
              <span className="landing-t-table-cell--dim">{row.k}</span>
              <span className={row.aBold ? "landing-t-bold" : undefined}>{row.a}</span>
              <span className={row.bBold ? "landing-t-bold" : undefined}>{row.b}</span>
              <span className={row.cBold ? "landing-t-bold" : undefined}>{row.c}</span>
            </div>
          ))}
        </div>
        <p className="landing-t-scorecard__note">
          Brightcell is £4 dearer a pack but has a 3-year warranty and ships in 2 weeks. Voltway is
          cheapest if you can wait 6.
        </p>
        <span className="landing-t-scorecard__buddy" aria-hidden="true">
          {helperArt({ role: "finance", expr: "happy" }, 80, night)}
        </span>
      </Reveal>
    </Reveal>
  );
}

/* ---- Section 2: HOW IT WORKS ---- */
export function HowSection() {
  return (
    <Reveal
      as="section"
      className="landing-section landing-t-section"
      id="how"
      aria-labelledby="landing-how"
    >
      <div className="landing-section__head">
        <span className="landing-eyebrow">HOW IT WORKS</span>
        <h2 id="landing-how">Three steps. No jargon, no surprises.</h2>
      </div>
      <ol className="landing-t-how-grid">
        <Reveal as="li" index={0} className="landing-t-how-card">
          <span className="landing-mono">01</span>
          <div className="landing-t-how-preview">
            <div className="landing-t-how-box">Compare 3 battery suppliers for the K1 scooter</div>
            <div className="landing-t-how-chips">
              <span>+ Attach</span>
              <span>Make a world</span>
            </div>
          </div>
          <h3>Describe it</h3>
          <p>Write it the way you’d ask a friend. Drop in files if they help.</p>
        </Reveal>
        <Reveal as="li" index={1} className="landing-t-how-card">
          <span className="landing-mono">02</span>
          <div className="landing-t-how-preview">
            <div className="landing-t-how-chips">
              <span className="landing-t-chip--dashed">2,000 units ✎</span>
              <span className="landing-t-chip--dashed">Ships to the UK ✎</span>
              <span className="landing-t-chip--dashed">By Friday ✎</span>
            </div>
            <div className="landing-t-how-cost">
              <div>
                <strong>About £2</strong>
                <small>asks before going over £5</small>
              </div>
              <span className="landing-t-btn-sm">Start →</span>
            </div>
          </div>
          <h3>Check the plan</h3>
          <p>
            See what Tilo assumed and fix anything in place. The cost is in real money, before it
            starts.
          </p>
        </Reveal>
        <Reveal as="li" index={2} className="landing-t-how-card">
          <span className="landing-mono">03</span>
          <div className="landing-t-how-preview landing-t-how-preview--city">
            <div className="landing-t-how-status">
              <span className="landing-t-dot--mint" aria-hidden="true" />
              Brightcell replied with a price
            </div>
          </div>
          <h3>Watch it happen</h3>
          <p>
            Helpers move around their little city as they work. Every step is written in plain
            sentences.
          </p>
        </Reveal>
      </ol>
    </Reveal>
  );
}

/* ---- Section 3: MEET THE TEAM ---- */
interface CrewMember {
  readonly role: string;
  readonly rank?: string;
  readonly name: string;
  readonly desc: string;
  readonly say: string;
  readonly expr: string;
}

const CREW: readonly CrewMember[] = [
  {
    role: "director",
    rank: "director",
    name: "Director",
    desc: "Plans the work",
    say: "I’ll split this into 4 parts.",
    expr: "talk",
  },
  {
    role: "research",
    name: "Researcher",
    desc: "Finds and checks",
    say: "Found 5 that aren’t on any list!",
    expr: "delighted",
  },
  {
    role: "writer",
    name: "Writer",
    desc: "Words that sound like you",
    say: "Draft’s ready, short and warm.",
    expr: "neutral",
  },
  {
    role: "planner",
    name: "Planner",
    desc: "Routes and schedules",
    say: "Coastal road. Skips the ghat.",
    expr: "neutral",
  },
  {
    role: "finance",
    name: "Money keeper",
    desc: "Prices and budgets",
    say: "That’s £2 under your cap.",
    expr: "happy",
  },
  {
    role: "connector",
    name: "Messenger",
    desc: "Talks to your apps",
    say: "Can I send it? Just say yes.",
    expr: "talk",
  },
];

export function MeetTheTeamSection({ night }: { night: boolean }) {
  return (
    <Reveal
      as="section"
      className="landing-section landing-t-section"
      id="team"
      aria-labelledby="landing-team"
    >
      <div className="landing-section__head landing-t-split-head">
        <div>
          <span className="landing-eyebrow">MEET THE TEAM</span>
          <h2 id="landing-team">Six helpers. Each one good at one thing.</h2>
        </div>
        <p className="landing-t-lead-side">
          Tilo picks who you need for each job, so a quick question gets one helper and a launch
          gets the whole crew.
        </p>
      </div>
      <div className="landing-t-team-stage">
        <ul className="landing-t-team-grid" aria-label="The six helpers">
          {CREW.map((c, i) => (
            <Reveal as="li" index={i} key={c.name} className="landing-t-team-card">
              <span className="landing-t-speech">{c.say}</span>
              <span className="landing-t-team-avatar" aria-hidden="true">
                {helperArt(
                  c.rank ? { rank: c.rank, expr: c.expr } : { role: c.role, expr: c.expr },
                  92,
                  night,
                )}
              </span>
              <div className="landing-t-team-meta">
                <strong>{c.name}</strong>
                <span>{c.desc}</span>
              </div>
            </Reveal>
          ))}
        </ul>
      </div>
    </Reveal>
  );
}

/* ---- Section 4: ONE BOX, TWO SPEEDS ---- */
export function SpeedsSection({ night, finalCity }: { night: boolean; finalCity: Plan | null }) {
  return (
    <Reveal
      as="section"
      className="landing-section landing-t-section"
      id="speeds"
      aria-labelledby="landing-speeds"
    >
      <div className="landing-section__head">
        <span className="landing-eyebrow">ONE BOX, TWO SPEEDS</span>
        <h2 id="landing-speeds">A quick answer, or a whole world.</h2>
        <p>Tilo picks the right size for the job. You can always switch.</p>
      </div>
      <div className="landing-t-speeds-grid">
        <Reveal as="article" className="landing-t-speed-card">
          <div className="landing-t-speed-card__head">
            <span className="landing-t-pill landing-t-pill--pri">QUICK ANSWER · 1 HELPER</span>
            <span className="landing-mono">seconds · pennies</span>
          </div>
          <h3>Ask a question, get an answer</h3>
          <div className="landing-t-chat-row">
            <div className="landing-t-chat-bubbles">
              <span className="landing-t-bubble-user">Does this hotel include breakfast?</span>
              <span className="landing-t-bubble-agent">
                Yes, for 2 adults. Your son’s is ₹350 a day.
              </span>
            </div>
            <span className="landing-t-speed-pic" aria-hidden="true">
              {helperArt({ role: "research", expr: "delighted" }, 120, night)}
            </span>
          </div>
        </Reveal>
        <Reveal as="article" index={1} className="landing-t-speed-card">
          <div className="landing-t-speed-card__head">
            <span className="landing-t-pill landing-t-pill--sunk">WORLD · A SMALL TEAM</span>
            <span className="landing-mono">minutes · you approve the cost</span>
          </div>
          <h3>Hand over a job, watch it get done</h3>
          <div className="landing-t-world-preview" aria-hidden="true">
            {finalCity ? cityArt(finalCity) : <div className="landing-t-world-preview__empty" />}
          </div>
        </Reveal>
      </div>
    </Reveal>
  );
}

/* ---- Section 5: APPROVE FROM ANYWHERE ---- */
const SAFETY_RULES = [
  "Asks before sending, buying, sharing or booking",
  "Shows the cost in money, before and as it goes",
  "Never goes over the cap you set",
  "Every step written down, so you can check it",
] as const;

export function SafetySection() {
  return (
    <Reveal
      as="section"
      className="landing-section landing-t-section landing-t-grid-2"
      id="safety"
      aria-labelledby="landing-safety"
    >
      <div className="landing-t-safety__copy">
        <span className="landing-eyebrow">APPROVE FROM ANYWHERE</span>
        <h2 id="landing-safety">Nothing important happens without a yes.</h2>
        <p className="landing-t-lead">
          Tilo stops and asks before it does anything you can’t undo, and tells you exactly what
          will happen.
        </p>
        <ul className="landing-rules">
          {SAFETY_RULES.map((rule) => (
            <li key={rule}>
              <span className="landing-rules__tick" aria-hidden="true">
                ✓
              </span>
              {rule}
            </li>
          ))}
        </ul>
      </div>
      <Reveal className="landing-t-gate-card">
        <div className="landing-t-gate-card__head">
          <span className="landing-t-dot--amber" aria-hidden="true" />
          Compare 3 suppliers · needs you
        </div>
        <h3 className="landing-t-gate-card__title">Can Tilo email 3 suppliers for a price?</h3>
        <div className="landing-t-gate-card__warning">
          <span className="landing-t-gate-card__icon" aria-hidden="true">
            {iconArt("mail", 20)}
          </span>
          <span>This will send an email to 3 people. Cost £0.30.</span>
        </div>
        <div className="landing-t-gate-card__actions">
          <button type="button" className="landing-t-btn-act">
            Yes, send them
          </button>
          <button type="button" className="landing-btn landing-btn--secondary landing-btn--sm">
            Change
          </button>
          <button type="button" className="landing-link-btn landing-t-gate-card__no">
            No
          </button>
        </div>
      </Reveal>
    </Reveal>
  );
}

/* ---- Section 6: SKILLS ---- */
const SKILLS = [
  {
    name: "Find hidden gems",
    desc: "Digs past top-10 lists for places locals love.",
    icon: "search",
    tint: "sky",
  },
  {
    name: "Compare options",
    desc: "Lines up choices side by side and picks a winner.",
    icon: "chart",
    tint: "teal",
  },
  {
    name: "Write a friendly reply",
    desc: "Drafts a reply in your voice, ready to send.",
    icon: "mail",
    tint: "lilac",
  },
  {
    name: "Teach your own",
    desc: "Show Tilo once. It turns it into a skill.",
    icon: "cap",
    tint: "pri",
  },
] as const;

export function SkillsSection() {
  return (
    <Reveal
      as="section"
      className="landing-section landing-t-section"
      id="skills"
      aria-labelledby="landing-skills"
    >
      <div className="landing-section__head landing-t-split-head">
        <div>
          <span className="landing-eyebrow">SKILLS</span>
          <h2 id="landing-skills">Skills that grow with you.</h2>
          <p>Dozens built in. Show Tilo how you like something done once, and it remembers.</p>
        </div>
        <span className="landing-t-btn-outline">Browse all skills →</span>
      </div>
      <ul className="landing-t-skills-grid" aria-label="Available skills">
        {SKILLS.map((s, i) => (
          <Reveal as="li" index={i} key={s.name} className="landing-t-skill-card">
            <span
              className={`landing-t-icon-tile landing-t-icon-tile--${s.tint}`}
              aria-hidden="true"
            >
              {iconArt(s.icon, 24)}
            </span>
            <div className="landing-t-skill-meta">
              <strong>{s.name}</strong>
              <p>{s.desc}</p>
            </div>
          </Reveal>
        ))}
      </ul>
    </Reveal>
  );
}

/* ---- Section 7: MEETINGS WITH TILO ---- */
export function MeetingsSection() {
  return (
    <Reveal
      as="section"
      className="landing-section landing-t-section landing-t-grid-2"
      id="meetings"
      aria-labelledby="landing-meetings"
    >
      <div>
        <span className="landing-eyebrow">MEETINGS WITH TILO</span>
        <h2 id="landing-meetings">It joins, takes minutes, and follows up.</h2>
        <p className="landing-t-lead">
          Send Tilo to any call. It gets a brief ready 15 minutes before, writes the minutes as you
          talk, and drafts the follow-ups for your yes.
        </p>
      </div>
      <Reveal className="landing-t-card-box landing-t-meetings-card">
        <div className="landing-t-meetings-head">
          <span className="landing-mono">MINUTES · LIVE</span>
          <ul className="landing-t-minutes-list">
            <li>11:04 · Price settled at €74 a pack</li>
            <li>11:09 · Ships 2 weeks after order</li>
            <li>11:12 · Warranty terms in writing</li>
          </ul>
        </div>
        <div className="landing-t-meetings-followups">
          <span className="landing-t-pill landing-t-pill--lime">3 follow-ups drafted</span>
          <span className="landing-t-pill landing-t-pill--card">
            Report pinned to the team board
          </span>
        </div>
        <div className="landing-t-card-foot landing-mono">
          <span>JOINS</span>
          <span>·</span>
          <span>TAKES MINUTES</span>
          <span>·</span>
          <span>FOLLOWS UP</span>
        </div>
      </Reveal>
    </Reveal>
  );
}

/* ---- Section 8: TEAMS AND SHARED WORLDS ---- */
export function TeamsSection() {
  return (
    <Reveal
      as="section"
      className="landing-section landing-t-section landing-t-grid-2"
      id="teams"
      aria-labelledby="landing-teams"
    >
      <Reveal className="landing-t-card-box landing-t-teams-card">
        <ul className="landing-t-teams-activity" aria-label="Team activity">
          <li className="landing-t-team-activity-item">
            <span className="landing-t-avatar-chip landing-t-avatar-chip--sky">JO</span>
            <span>Jo is watching the Q3 deck</span>
          </li>
          <li className="landing-t-team-activity-item">
            <span className="landing-t-avatar-chip landing-t-avatar-chip--teal">OB</span>
            <span>Oskar approved the supplier email</span>
          </li>
          <li className="landing-t-team-activity-item">
            <span className="landing-t-avatar-chip landing-t-avatar-chip--lilac">MR</span>
            <span>Maya shared Porto offsite with 4 people</span>
          </li>
        </ul>
        <div className="landing-t-card-foot landing-mono">
          <span>OWNER · MEMBER</span>
          <span>·</span>
          <span>ONE CREDIT CAP</span>
          <span>·</span>
          <span>SHARED WORLDS</span>
        </div>
      </Reveal>
      <div>
        <span className="landing-eyebrow">TEAMS AND SHARED WORLDS</span>
        <h2 id="landing-teams">One town for the whole team.</h2>
        <p className="landing-t-lead">
          Share a world and everyone sees the same city, the same story and the same approvals.
          Owners set one credit cap for all.
        </p>
      </div>
    </Reveal>
  );
}

/* ---- Section 9: PIN BOARDS AND AGENDA ---- */
export function AgendaSection() {
  return (
    <Reveal
      as="section"
      className="landing-section landing-t-section landing-t-grid-2"
      id="agenda"
      aria-labelledby="landing-week"
    >
      <div>
        <span className="landing-eyebrow">PIN BOARDS AND AGENDA</span>
        <h2 id="landing-week">Your week, and the bits worth keeping.</h2>
        <p className="landing-t-lead">
          Pin anything from a result with one click. Your agenda shows which meetings Tilo joins and
          what it has ready.
        </p>
        <p className="landing-t-dim-note">Your meetings appear after sign-in.</p>
      </div>
      <Reveal className="landing-t-card-box landing-t-agenda-card">
        <div className="landing-t-day-strip">
          <div className="landing-t-day-slot">
            <span className="landing-mono">9:30</span>
            <strong>Standup</strong>
            <small>Tilo joins</small>
          </div>
          <div className="landing-t-day-slot landing-t-day-slot--sel">
            <span className="landing-mono">11:00</span>
            <strong>Supplier call</strong>
            <small>Brief ready</small>
          </div>
          <div className="landing-t-day-slot">
            <span className="landing-mono">14:00</span>
            <strong>Due: Q3 deck</strong>
            <small>80% done</small>
          </div>
        </div>
        <div className="landing-t-pins-row">
          <div className="landing-t-pin landing-t-pin--amber">
            <strong>Brightcell: €74 a pack</strong>
            <span>from Compare 3 suppliers</span>
          </div>
          <div className="landing-t-pin landing-t-pin--pri">
            <strong>Porto: Casa do Rio</strong>
            <span>pinned from a world</span>
          </div>
          <div className="landing-t-pin landing-t-pin--sky">
            <strong>Call Lin back</strong>
            <span>before Friday</span>
          </div>
        </div>
        <div className="landing-t-card-foot landing-mono">
          <span>PIN FROM ANY RESULT · DRAG TO REORDER · MINE OR THE TEAM’S</span>
        </div>
      </Reveal>
    </Reveal>
  );
}

/* ---- Section 10: CONNECTORS ---- */
const CONNECTORS = [
  { name: "Gmail", connected: true },
  { name: "Calendar", connected: true },
  { name: "Drive", connected: true },
  { name: "Sheets", connected: true },
  { name: "Slack", connected: true },
  { name: "GitHub", connected: true },
  { name: "Figma", connected: false },
  { name: "Any website", connected: false },
] as const;

export function ConnectorsSection() {
  return (
    <Reveal
      as="section"
      className="landing-section landing-t-section landing-t-grid-2"
      id="connectors"
      aria-labelledby="landing-connectors"
    >
      <Reveal className="landing-t-card-box">
        <ul className="landing-t-apps-grid" aria-label="Available app connectors">
          {CONNECTORS.map((app) => (
            <li key={app.name} className="landing-t-app-tile">
              <span className="landing-t-app-icon" aria-hidden="true">
                {iconArt("plug", 20)}
              </span>
              <strong>{app.name}</strong>
              <span
                className={
                  app.connected ? "landing-t-app-status--mint" : "landing-t-app-status--dim"
                }
              >
                {app.connected ? "● Connected" : "Connect"}
              </span>
            </li>
          ))}
        </ul>
      </Reveal>
      <div>
        <span className="landing-eyebrow">CONNECTORS</span>
        <h2 id="landing-connectors">Works with the apps you already use.</h2>
        <p className="landing-t-lead">
          Each connection says in plain words what Tilo may do. Reading is fine; sending, paying and
          sharing always ask first.
        </p>
        <p className="landing-t-dim-note">
          Tilo never sees or stores your passwords. You sign in with the app itself, see every
          permission in plain words first, and can disconnect at any time.
        </p>
      </div>
    </Reveal>
  );
}

/* ---- Section 11: FOR YOU, AND FOR YOUR COMPANY ---- */
const PERSONAL = [
  "Inbox, errands and trips off your plate",
  "Quick answers in seconds",
  "Skills that learn how you like things",
  "A monthly credit cap you choose",
] as const;

const ENTERPRISE = [
  "Owner and Member roles",
  "Shared worlds, pins and approvals",
  "One team credit cap, per-step costs",
  "A full event log of every step",
] as const;

export function AudiencesSection({ night }: { night: boolean }) {
  return (
    <Reveal
      as="section"
      className="landing-section landing-t-section"
      id="audiences"
      aria-labelledby="landing-audiences"
    >
      <div className="landing-section__head">
        <span className="landing-eyebrow">FOR YOU, AND FOR YOUR COMPANY</span>
        <h2 id="landing-audiences">Personal help, team-grade control.</h2>
      </div>
      <div className="landing-t-audiences-grid">
        <Reveal as="article" className="landing-t-audience-card">
          <div className="landing-t-audience-head">
            <span className="landing-t-audience-avatar" aria-hidden="true">
              {helperArt({ role: "research", expr: "delighted" }, 54, night)}
            </span>
            <h3>Personal</h3>
          </div>
          <ul className="landing-rules">
            {PERSONAL.map((item) => (
              <li key={item}>
                <span className="landing-rules__tick" aria-hidden="true">
                  ✓
                </span>
                {item}
              </li>
            ))}
          </ul>
        </Reveal>
        <Reveal
          as="article"
          index={1}
          className="landing-t-audience-card landing-t-audience-card--dark"
        >
          <div className="landing-t-audience-head">
            <span className="landing-t-audience-avatar" aria-hidden="true">
              {helperArt({ rank: "director", expr: "talk" }, 54, night)}
            </span>
            <h3>Enterprise</h3>
          </div>
          <ul className="landing-rules">
            {ENTERPRISE.map((item) => (
              <li key={item}>
                <span className="landing-rules__tick" aria-hidden="true">
                  ✓
                </span>
                {item}
              </li>
            ))}
          </ul>
        </Reveal>
      </div>
    </Reveal>
  );
}

/* ---- Section 12: WHY TILO ---- */
export function WhySection({ night }: { night: boolean }) {
  return (
    <Reveal
      as="section"
      className="landing-section landing-t-section"
      id="why"
      aria-labelledby="landing-why"
    >
      <div className="landing-section__head">
        <span className="landing-eyebrow">WHY TILO</span>
        <h2 id="landing-why">Honest by design.</h2>
      </div>
      <div className="landing-t-why-grid">
        <Reveal as="article" className="landing-t-why-card">
          <div className="landing-t-why-preview landing-mono">
            <span>building.constructing → scaffold rises</span>
            <span>agent.handoff → bots meet, note shown</span>
            <span>artifact.delivered → parcel lands</span>
          </div>
          <h3>Honest progress</h3>
          <p>
            Nothing in your city moves unless something really happened. No fake progress bars,
            ever.
          </p>
        </Reveal>
        <Reveal as="article" index={1} className="landing-t-why-card">
          <div className="landing-t-why-preview landing-t-why-preview--center">
            <span aria-hidden="true">
              {helperArt({ role: "connector", expr: "talk" }, 64, night)}
            </span>
            <span className="landing-t-pill landing-t-pill--pri">Approve</span>
          </div>
          <h3>Approvals for risky steps</h3>
          <p>
            Sending, paying, booking and sharing wait for you, with the exact text and the risk in
            plain words.
          </p>
        </Reveal>
        <Reveal as="article" index={2} className="landing-t-why-card">
          <div className="landing-t-why-preview landing-t-why-preview--cap">
            <div className="landing-t-cap-bar">
              <strong>76 of 120 credits</strong>
              <small>your cap</small>
            </div>
            <div className="landing-t-progress">
              <div className="landing-t-progress-fill" />
            </div>
            <span className="landing-t-cap-note">
              Asks before it goes over. Every step shows what it cost.
            </span>
          </div>
          <h3>Credits you control</h3>
          <p>
            See the cost before a world starts, watch it as it runs, and set a cap Tilo never
            crosses.
          </p>
        </Reveal>
      </div>
    </Reveal>
  );
}

/* ---- Section 13: A DAY IN YOUR TOWN ---- */
interface DayEvent {
  readonly time: string;
  readonly title: string;
  readonly desc: string;
  readonly meta: string;
  readonly tint: string;
  readonly dark?: boolean;
}

const DAY_EVENTS: readonly DayEvent[] = [
  {
    time: "8:00",
    title: "Inbox sorted",
    desc: "23 emails read. 3 need you, the rest are filed.",
    meta: "MESSENGER · £0.06",
    tint: "pink",
  },
  {
    time: "10:30",
    title: "Brief for your 11:00",
    desc: "Oskar quoted £71 on the phone but £78 in writing.",
    meta: "DIRECTOR · £0.04",
    tint: "pri",
  },
  {
    time: "13:00",
    title: "Quotes compared",
    desc: "3 suppliers, 1 page, a clear winner.",
    meta: "MONEY KEEPER · £1.84",
    tint: "mint",
  },
  {
    time: "16:00",
    title: "Friday update written",
    desc: "Thanked Jo for the pricing table.",
    meta: "WRITER · £0.09",
    tint: "lilac",
  },
  {
    time: "22:00",
    title: "Overnight job",
    desc: "Checking 12 hotels while you sleep.",
    meta: "RESEARCHER · RUNNING",
    tint: "sky",
    dark: true,
  },
];

export function DaySection() {
  return (
    <Reveal
      as="section"
      className="landing-section landing-t-section"
      id="day"
      aria-labelledby="landing-day"
    >
      <div className="landing-section__head">
        <span className="landing-eyebrow">A DAY IN YOUR TOWN</span>
        <h2 id="landing-day">While you get on with your day.</h2>
      </div>
      <ol className="landing-t-day-grid" aria-label="A day timeline">
        {DAY_EVENTS.map((e, i) => (
          <Reveal as="li" index={i} key={e.time} className="landing-t-day-stop">
            <span
              className={`landing-t-day-pill landing-t-day-pill--${e.tint} ${e.dark ? "landing-t-day-pill--dark" : ""}`}
            >
              <span className="landing-mono">{e.time}</span>
            </span>
            <div className={`landing-t-day-card ${e.dark ? "landing-t-day-card--dark" : ""}`}>
              <strong>{e.title}</strong>
              <p>{e.desc}</p>
              <span className="landing-mono landing-t-day-meta">{e.meta}</span>
            </div>
          </Reveal>
        ))}
      </ol>
    </Reveal>
  );
}

/* ---- Section 14: THINGS PEOPLE HANDED TO TILO THIS WEEK ---- */
const ASKS_ROW_1 = [
  "Plan our team offsite in Porto",
  "Find a cheaper broadband deal",
  "Reply to every review from last week",
  "Turn this PDF into 5 slides",
  "Chase the 3 overdue invoices",
  "Find a dentist open on Saturdays",
] as const;

const ASKS_ROW_2 = [
  "Compare 3 suppliers",
  "Book a table for 6 on Friday",
  "Draft a job post for a designer",
  "Summarise yesterday’s calls",
  "Plan a road trip to Gokarna",
  "Write a kind no to this request",
] as const;

export function MarqueeSection() {
  return (
    <aside className="landing-t-marquee-wrap" aria-label="Recent tasks handed to Tilo">
      <div className="landing-eyebrow landing-t-marquee-title">
        THINGS PEOPLE HANDED TO TILO THIS WEEK
      </div>
      <div className="landing-t-marquee-row">
        {ASKS_ROW_1.map((ask) => (
          <span key={ask} className="landing-t-marquee-pill">
            {ask}
          </span>
        ))}
      </div>
      <div className="landing-t-marquee-row">
        {ASKS_ROW_2.map((ask) => (
          <span key={ask} className="landing-t-marquee-pill landing-t-marquee-pill--lime">
            {ask}
          </span>
        ))}
      </div>
    </aside>
  );
}

/* ---- Section 15: CLOSE ---- */
export function CloseSection({
  night,
  busy,
  onGoogle,
  onDemo,
}: {
  night: boolean;
  busy: boolean;
  onGoogle: () => void;
  onDemo: () => void;
}) {
  return (
    <Reveal
      as="section"
      className="landing-section landing-t-section landing-t-close"
      id="close"
      aria-labelledby="landing-close"
    >
      <div className="landing-t-close-card">
        <div className="landing-t-close-copy">
          <h2 id="landing-close">Your little city is waiting.</h2>
          <p>
            Free to try. Bring one job you’ve been putting off and see what your team does with it.
          </p>
          <div className="landing-hero__actions">
            <button
              type="button"
              className="landing-btn landing-btn--secondary"
              disabled={busy}
              onClick={onGoogle}
            >
              Sign in with Google
            </button>
            <button
              type="button"
              className="landing-link-btn landing-link-btn--big landing-t-close-demo"
              disabled={busy}
              onClick={onDemo}
            >
              Explore a demo town
            </button>
          </div>
        </div>
        <span className="landing-t-close-buddy" aria-hidden="true">
          {helperArt({ rank: "director", expr: "delighted" }, 160, night)}
        </span>
      </div>
    </Reveal>
  );
}
