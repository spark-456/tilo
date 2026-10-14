// S-22 Settings (PRD 18.3, 16.5): display preferences, routines and consent.
// Appearance shares Profile controls; unavailable export/delete actions stay hidden. The
// privacy lines are PRD 16.5's. No design export covers a unified Settings screen: cards and rows
// after "Tilo Team.dc.html", neutral role tokens (design/source/INDEX.md, S-22).
import { type Density, useDensity } from "../display/density";
import { Routines } from "../park/pages/Admin/routines/Routines";
import { SettingsAppearance } from "../park/shell/SettingsAppearance";
import { AppLink } from "./AppLink";
import { Page, Row, Section } from "./kit";

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
        title="Appearance"
        note="Friendly is the default. Professional tightens the spacing and keeps decoration out. It changes how the app looks, never what happened, and it applies at once."
      >
        <SettingsAppearance />
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
      />
    </Page>
  );
}
