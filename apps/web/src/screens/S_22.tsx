// S-22 Settings (PRD 18.3, 16.5): data, export, delete and the density mode. Nothing here is
// stored or sent yet, so every control is a placeholder and no setting claims a value. The
// privacy lines are PRD 16.5's. No design export covers a unified Settings screen: cards and rows
// after "Tilo Team.dc.html", neutral role tokens (design/source/INDEX.md, S-22).
import { type Density, useDensity } from "../display/density";
import { AppLink } from "./AppLink";
import { Placeholder } from "./Placeholder";
import { Page, Row, Section } from "./kit";
import { Routines } from "./routines/Routines";

// PRD 16.5 consent: each opt-in is explicit and revocable.
// `to` is where the access is shown and managed today; an opt-in with no screen of its own yet has
// none, and no dead control stands in for it.
const CONSENTS: ReadonlyArray<readonly [string, string, string | null]> = [
  [
    "Gmail access",
    "So Tilo can sort mail and send replies. You sign in with Google; Tilo never sees your password.",
    "/connections",
  ],
  [
    "Style profile",
    "Greetings and sign-offs learned from your sent mail. Stored as settings.",
    null,
  ],
  ["Email", "Notifications and question cards, with the preferences you set.", "/channels"],
  ["Pilot diary", "A daily note and an exit survey. Results are aggregated only.", "/pilot"],
];

const MODES: ReadonlyArray<readonly [Density, string, string]> = [
  ["friendly", "Friendly", "The default look"],
  ["professional", "Professional", "Tighter spacing, no decoration"],
];

export function S_22() {
  const [density, setDensity] = useDensity();
  return (
    <Page
      testid="settings"
      title="Settings"
      sub="Your data, what Tilo may use, and how the app looks."
    >
      <Section
        title="Display"
        note="Friendly is the default. Professional tightens the spacing and keeps decoration out. It changes how the app looks, never what happened, and it applies at once."
      >
        <fieldset className="segmented" data-testid="density">
          <legend className="visually-hidden">Display mode</legend>
          {MODES.map(([id, name, what]) => (
            <label key={id} className="segment">
              <input
                type="radio"
                name="density"
                value={id}
                checked={density === id}
                onChange={() => setDensity(id)}
              />
              <span>
                <b>{name}</b>
                <small>{what}</small>
              </span>
            </label>
          ))}
        </fieldset>
      </Section>
      <Section
        title="Routines"
        note="Runs that repeat every week. Set one with Repeat weekly when you start a run."
        reserve={[6, 10]}
      >
        <Routines />
      </Section>
      <Section title="Consent" note="Every one is explicit and can be taken back at any time.">
        <ul className="blist">
          {CONSENTS.map(([name, what, to]) => (
            <Row key={name} name={name} sub={what}>
              {to && (
                <AppLink to={to} className="pill" aria-label={`Review ${name}`}>
                  Review
                </AppLink>
              )}
            </Row>
          ))}
        </ul>
      </Section>
      <Section
        title="Your data"
        note="Email bodies are never cached. The style profile keeps settings, not emails. Data stays in asia-southeast1."
      >
        <ul className="blist">
          <Row
            name="Export my data"
            sub="Events, files and a provenance manifest. Not available in the app yet."
          >
            <Placeholder label="Export" compact />
          </Row>
          <Row
            name="Delete my account and data"
            sub="Not available in the app yet. When it is, your data is removed from every store within 30 days, and this cannot be undone."
          >
            <Placeholder label="Delete" compact />
          </Row>
        </ul>
      </Section>
    </Page>
  );
}
