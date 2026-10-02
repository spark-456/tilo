// S-22 Settings (PRD 18.3, 16.5): data, export, delete and the density mode. Nothing here is
// stored or sent yet, so every control is a placeholder and no setting claims a value. The
// privacy lines are PRD 16.5's. No design export covers a unified Settings screen: cards and rows
// after "Tilo Team.dc.html", neutral role tokens (design/source/INDEX.md, S-22).
import { Placeholder } from "./Placeholder";
import { Chip, Page, Row, Section } from "./kit";

// PRD 16.5 consent: each opt-in is explicit and revocable.
const CONSENTS = [
  ["Gmail access", "So Tilo can sort mail and send replies. You sign in with Google."],
  ["Style profile", "Greetings and sign-offs learned from your sent mail. Stored as settings."],
  ["WhatsApp", "Cards and replies on your phone, with a number you bind."],
  ["Pilot diary", "A daily note and an exit survey. Results are aggregated only."],
] as const;

export function S_22() {
  return (
    <Page
      testid="settings"
      title="Settings"
      sub="Your data, what Tilo may use, and how the app looks."
    >
      <Section
        title="Display"
        note="Friendly shows the characters and light motion. Professional shows labels and tighter spacing, with no decorative motion."
      >
        <ul className="rows">
          <Row name="Friendly" sub="The default" state={<Chip tone="fyi">Default</Chip>} />
          <Row name="Professional" sub="Smaller characters, labels on">
            <Placeholder label="Use Professional" compact />
          </Row>
        </ul>
      </Section>
      <Section title="Consent" note="Every one is explicit and can be taken back at any time.">
        <ul className="rows">
          {CONSENTS.map(([name, what]) => (
            <Row key={name} name={name} sub={what}>
              <Placeholder label={`Review ${name}`} compact />
            </Row>
          ))}
        </ul>
      </Section>
      <Section
        title="Your data"
        note="Email bodies are never cached. The style profile keeps settings, not emails. Data stays in asia-southeast1."
      >
        <ul className="rows">
          <Row name="Export my data" sub="Events, files and a provenance manifest.">
            <Placeholder label="Export" compact />
          </Row>
          <Row
            name="Delete my account and data"
            sub="Removed from every store within 30 days. This cannot be undone."
          >
            <Placeholder label="Delete" compact />
          </Row>
        </ul>
      </Section>
    </Page>
  );
}
