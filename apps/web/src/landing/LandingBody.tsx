// STUDIO-6, LANDING-2, FT-UX-2: signed-out landing matching design/tilo-t "Tilo T Landing.dc.html":
// hero prompt, highlights, recorded stage and story, then the 14 Tilo T sections and footer.
// Reveal.tsx provides scroll reveals.
import "../design/tilo-t/styles";
import LandingStage, { RecordedStory } from "./LandingStage";
import {
  AgendaSection,
  AudiencesSection,
  CloseSection,
  ConnectorsSection,
  DaySection,
  HowSection,
  MarqueeSection,
  MeetTheTeamSection,
  MeetingsSection,
  OneLineSection,
  SafetySection,
  SkillsSection,
  SpeedsSection,
  TeamsSection,
  WhySection,
} from "./LandingTSections";
import { helperArt } from "./landingKit";
import "./landing.sections.css";
import "./landing.motion.css";
import "./landing.t.css";
import { RECORDED_RUN } from "./recordedRun";

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
      <div className="landing-prompt-wrap">
        <form
          className="landing-prompt"
          onSubmit={(event) => {
            event.preventDefault();
            if (!busy) onGoogle();
          }}
        >
          <span className="landing-prompt__helper" aria-hidden="true">
            {helperArt({ role: "research", expr: "delighted" }, 46, night)}
          </span>
          <input
            type="text"
            aria-label="What do you want done?"
            aria-describedby="landing-prompt-note"
            placeholder="Describe one job…"
            autoComplete="off"
            disabled={busy}
            onInput={() => {
              if (!busy) onGoogle();
            }}
          />
          <button type="submit" className="landing-btn landing-btn--secondary" disabled={busy}>
            Try it <span aria-hidden="true">→</span>
          </button>
        </form>
        <p id="landing-prompt-note">Sign in to turn your idea into a plan.</p>
      </div>
      <aside
        className="landing-ticker"
        // biome-ignore lint/a11y/noNoninteractiveTabindex: keyboard users need to scroll the highlights.
        tabIndex={0}
        aria-label="Highlights from the recorded example"
      >
        <span className="landing-ticker__label landing-mono">Recorded example</span>
        <ul>
          {[facts.planned, facts.budget, facts.done].filter(Boolean).map((fact) => (
            <li key={fact}>
              <span aria-hidden="true">✓</span>
              {fact}
            </li>
          ))}
        </ul>
      </aside>
      <div className="landing-hero__stage">
        <LandingStage night={night} />
      </div>
      <RecordedStory />

      <OneLineSection night={night} />
      <HowSection />
      <MeetTheTeamSection night={night} />
      <SpeedsSection night={night} finalCity={finalCity} />
      <SafetySection />
      <SkillsSection />
      <MeetingsSection />
      <TeamsSection />
      <AgendaSection />
      <ConnectorsSection />
      <AudiencesSection night={night} />
      <WhySection night={night} />
      <DaySection />
      <MarqueeSection />
      <CloseSection night={night} busy={busy} onGoogle={onGoogle} onDemo={onDemo} />

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
