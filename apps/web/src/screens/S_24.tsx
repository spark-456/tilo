// S-24 Pilot diary and survey (PRD 18.3, 14.4): a daily diary and an exit survey, aggregated only.
// Nothing here is sent or stored, so the fields are visible, read-only and aria-disabled, and the
// submit control is a placeholder. No design export covers this screen: cards and rows after
// "Tilo Team.dc.html", neutral role tokens (design/source/INDEX.md, S-24).
import { useId } from "react";
import { Placeholder } from "./Placeholder";
import { Chip, Page, Section } from "./kit";

const DIARY = [
  ["What did Tilo do for you today?", "text"],
  ["How many minutes do you think it saved you?", "number"],
] as const;
const SURVEY = [
  "Did the drafts need edits before you sent them?",
  "Did Tilo ever ask too often, or too rarely?",
  "What would make you use Tilo every day?",
] as const;

/** A labelled field that cannot be used yet: read-only, aria-disabled and titled "Coming soon". */
function Field({ label, kind }: { label: string; kind: "text" | "number" }) {
  const id = useId();
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      {kind === "text" ? (
        <textarea id={id} readOnly aria-disabled="true" title="Coming soon" rows={3} />
      ) : (
        <input id={id} readOnly aria-disabled="true" title="Coming soon" type="number" />
      )}
    </div>
  );
}

export function S_24() {
  return (
    <Page
      testid="pilot"
      title="Pilot diary and survey"
      sub="A short note each day and one survey at the end. Results are aggregated; nobody sees your answers on their own."
    >
      <Section
        title="Today's diary"
        note="Two questions, a minute or less. Your own estimate is fine."
      >
        <Chip tone="soon">Coming soon</Chip>
        {DIARY.map(([label, kind]) => (
          <Field key={label} label={label} kind={kind} />
        ))}
        <Placeholder label="Save today's diary" compact />
      </Section>
      <Section title="Exit survey" note="Shown once, at the end of the pilot.">
        <Chip tone="soon">Coming soon</Chip>
        {SURVEY.map((q) => (
          <Field key={q} label={q} kind="text" />
        ))}
        <Placeholder label="Send the survey" compact />
      </Section>
    </Page>
  );
}
