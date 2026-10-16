import { Reveal } from "./Reveal";

/** T board's week and pin layout, empty until the signed-in API supplies a person's data. */
export function WeekPreviewSection() {
  return (
    <Reveal as="section" className="landing-section landing-t-week" aria-labelledby="landing-week">
      <div className="landing-t-week__copy">
        <span className="landing-eyebrow">PIN BOARDS AND AGENDA</span>
        <h2 id="landing-week">Your week, and the bits worth keeping.</h2>
        <p>
          Pin a useful result to your board or your team’s. Your agenda keeps meetings, briefs and
          follow-ups in one place.
        </p>
      </div>
      <div className="landing-t-week__preview" aria-label="Empty agenda preview">
        <div className="landing-t-week__days" aria-hidden="true">
          {["Mon", "Tue", "Wed", "Thu", "Fri"].map((day) => (
            <span key={day}>{day}</span>
          ))}
        </div>
        <div className="landing-t-week__empty">
          <strong>Your meetings appear after sign-in</strong>
          <span>Briefs and minutes stay attached to the meeting they belong to.</span>
        </div>
        <div className="landing-t-week__pins" aria-label="Pin board preview">
          <span>MY PINS</span>
          <span>TEAM PINS</span>
        </div>
        <p>Pins from your results appear on the board you choose.</p>
      </div>
    </Reveal>
  );
}

const IDEAS = [
  "Compare three suppliers",
  "Prepare for a meeting",
  "Make a study quiz",
  "Draft a follow-up",
  "Plan a team offsite",
  "Summarise a document",
] as const;

/** Suggestions, explicitly labelled as examples: they do not claim past customer activity. */
export function TaskIdeasSection() {
  return (
    <Reveal as="section" className="landing-section landing-t-ideas" aria-labelledby="landing-ideas">
      <div className="landing-section__head">
        <span className="landing-eyebrow">IDEAS TO TRY</span>
        <h2 id="landing-ideas">A good place to start.</h2>
        <p>These are examples of jobs to describe after you sign in. Choose your own words.</p>
      </div>
      <ul>
        {IDEAS.map((idea) => (
          <li key={idea}>{idea}</li>
        ))}
      </ul>
    </Reveal>
  );
}
