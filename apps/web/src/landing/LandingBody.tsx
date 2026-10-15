// STUDIO-6, LANDING-2: everything on the signed-out landing below the hero ("Tilo S Landing", design/studio-v2): the
// recorded stage, how it works, the two speeds, safety, then the product sections (skills, meeting notetaker, teams,
// getting started, pinboards and context, connectors, enterprise and personal, why Tilo: LandingSections.tsx), a
// closing call to action and the footer. Sections reveal as they scroll into view (Reveal.tsx). Its own chunk
// (SignInScreen lazy-loads it), so the sign-in buttons paint first and the art engines stay off the entry bundle
// (NFR-01). No invented numbers, quotes or logos: the examples are lines of the recorded run, the skills are the ones
// in the repository's skills/ folder, and the safety lines are what the policy engine and budgets do (PRD 9.4, 16).
import type { ReactNode } from "react";
import LandingStage, { RecordedStory } from "./LandingStage";
import {
  AudiencesSection,
  ConnectorsSection,
  ContextSection,
  MeetingsSection,
  OnboardingSection,
  SkillsSection,
  TeamsSection,
  WhySection,
} from "./LandingSections";
import { Reveal } from "./Reveal";
import { cityArt, helperArt } from "./landingKit";
import "./landing.sections.css";
import { RECORDED_RUN } from "./recordedRun";

const RULES = [
  "Asks before anything is sent, shared or booked",
  "Spending, sharing outside and anything you can’t undo always wait for a person",
  "Shows what a job will cost before it starts",
  "Stays inside the budget you approve",
  "Writes every step down, so you can check it",
];

function Recorded({ children }: { children: ReactNode }) {
  return <span className="landing-recorded">{children}</span>;
}

export default function LandingBody({
  night,
  busy,
  onGoogle,
  onDemo,
}: {
  readonly night: boolean;
  readonly busy: boolean;
  readonly onGoogle: () => void;
  readonly onDemo: () => void;
}) {
  const { facts, frames } = RECORDED_RUN;
  const finalCity = frames[frames.length - 1]?.plan ?? null;
  return (
    <>
      <div className="landing-hero__stage">
        <LandingStage night={night} />
      </div>
      <RecordedStory />

      <Reveal as="section" className="landing-section" id="how" aria-labelledby="landing-how">
        <div className="landing-section__head">
          <span className="landing-eyebrow">HOW IT WORKS</span>
          <h2 id="landing-how">Four steps. No jargon, no surprises.</h2>
          <p>
            Describe the work and a Director plans it. Agent teams run it, you watch it in a living
            city, and you approve what matters.
          </p>
        </div>
        <ol className="landing-steps landing-steps--four">
          <Reveal as="li" index={0} className="landing-step">
            <span className="landing-step__n landing-mono">01</span>
            <div className="landing-step__pic">
              <div className="landing-ask">{facts.ask}</div>
              <Recorded>From the recorded example</Recorded>
            </div>
            <h3>Describe it</h3>
            <p>Write it the way you’d ask a friend. Add files if they help.</p>
          </Reveal>
          <Reveal as="li" index={1} className="landing-step">
            <span className="landing-step__n landing-mono">02</span>
            <div className="landing-step__pic">
              <p className="landing-quote">{facts.planned}</p>
              <p className="landing-quote landing-quote--yes">{facts.budget}</p>
              <Recorded>From the recorded example</Recorded>
            </div>
            <h3>Check the plan</h3>
            <p>
              The Director drafts the plan and the team. See what it assumed, change anything, and
              see the cost before it starts.
            </p>
          </Reveal>
          <Reveal as="li" index={2} className="landing-step">
            <span className="landing-step__n landing-mono">03</span>
            <div className="landing-step__pic">
              {facts.work.slice(0, 2).map((line) => (
                <p key={line} className="landing-quote">
                  {line}
                </p>
              ))}
              <Recorded>From the recorded example</Recorded>
            </div>
            <h3>Watch it happen</h3>
            <p>
              Helpers work in their own little city. Read it as a Story in plain sentences, or open
              the Trace for every step.
            </p>
          </Reveal>
          <Reveal as="li" index={3} className="landing-step">
            <span className="landing-step__n landing-mono">04</span>
            <div className="landing-step__pic">
              <p className="landing-quote">{facts.gate}</p>
              <p className="landing-quote landing-quote--yes">{facts.yes}</p>
              <Recorded>From the recorded example</Recorded>
            </div>
            <h3>You approve</h3>
            <p>
              Answer from the web, your phone or email. Anything risky always waits for a person.
            </p>
          </Reveal>
        </ol>
      </Reveal>

      <Reveal as="section" className="landing-section" id="speeds" aria-labelledby="landing-speeds">
        <div className="landing-section__head">
          <span className="landing-eyebrow">ONE BOX, TWO SPEEDS</span>
          <h2 id="landing-speeds">A quick answer, or a whole world.</h2>
          <p>
            Ask a question, or hand over a whole job. If a question needs more, Tilo offers to make
            a world.
          </p>
        </div>
        <div className="landing-speeds">
          <Reveal as="article" className="landing-speed">
            <span className="landing-mono">QUICK ANSWER · ONE HELPER</span>
            <h3>Ask a question, get an answer</h3>
            <p>One helper answers you in the chat, and you see what it cost.</p>
            <div className="landing-speed__pic" aria-hidden="true">
              {helperArt({ role: "research", expr: "delighted" }, 170, night)}
            </div>
          </Reveal>
          <Reveal as="article" index={1} className="landing-speed">
            <span className="landing-mono">MAKE A WORLD · A SMALL TEAM</span>
            <h3>Hand over a job, watch it get done</h3>
            <p>A Director plans it, a team of helpers does it, and you approve the budget first.</p>
            <div className="landing-speed__pic landing-speed__pic--city" aria-hidden="true">
              {finalCity ? cityArt(finalCity) : null}
            </div>
          </Reveal>
        </div>
      </Reveal>

      <Reveal
        as="section"
        className="landing-section landing-safety"
        id="safety"
        aria-labelledby="landing-safety"
      >
        <div className="landing-safety__copy">
          <span className="landing-eyebrow">YOU’RE IN CHARGE</span>
          <h2 id="landing-safety">Nothing leaves without your yes.</h2>
          <p>
            Before Tilo sends, shares or books anything, it stops and asks, and says what will
            happen.
          </p>
          <ul className="landing-rules">
            {RULES.map((rule) => (
              <li key={rule}>
                <span className="landing-rules__tick" aria-hidden="true">
                  ✓
                </span>
                {rule}
              </li>
            ))}
          </ul>
        </div>
        <div className="landing-gate">
          <span className="landing-gate__head">
            <span className="landing-gate__dot" aria-hidden="true" />
            Needs you
          </span>
          <p className="landing-gate__ask">{facts.gate}</p>
          <p className="landing-quote landing-quote--yes">{facts.yes}</p>
          <p className="landing-quote">{facts.after}</p>
          <Recorded>From the recorded example</Recorded>
        </div>
      </Reveal>

      <SkillsSection />
      <MeetingsSection night={night} />
      <TeamsSection />
      <OnboardingSection />
      <ContextSection />
      <ConnectorsSection />
      <AudiencesSection />
      <WhySection />

      <Reveal
        as="section"
        className="landing-section landing-close"
        aria-labelledby="landing-close"
      >
        <div className="landing-close__copy">
          <h2 id="landing-close">Your little city is waiting.</h2>
          <p>Bring one job you’ve been putting off and see what your team does with it.</p>
          <div className="landing-close__actions">
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
              className="landing-link-btn landing-link-btn--big"
              disabled={busy}
              onClick={onDemo}
            >
              Try the demo
            </button>
          </div>
        </div>
        <span className="landing-close__helper" aria-hidden="true">
          {helperArt({ rank: "director", expr: "delighted" }, 200, night)}
        </span>
      </Reveal>

      <footer className="landing-foot">
        <span className="landing-foot__word">tilo</span>
        <span className="landing-foot__line">Describe the work. Watch your team do it.</span>
        <nav aria-label="Legal" className="landing-foot__links">
          <a href="/privacy">Privacy</a>
          <a href="/terms">Terms</a>
        </nav>
      </footer>
    </>
  );
}
