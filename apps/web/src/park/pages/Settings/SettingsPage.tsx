// UI-10 W7-FIX: Settings uses Park components and the existing routines client.
import { type ReactNode, useState } from "react";
import { createRoutinesClient } from "../../api/live/routines";
import { Card, PageSheet } from "../../components";
import { type Density, useDensity } from "../../shell/density";
import { RoutinesPanel } from "../Worlds/RoutinesPanel";

function SettingsSection({
  title,
  note,
  children,
}: { title: string; note: string; children: ReactNode }) {
  return (
    <Card>
      <h2>{title}</h2>
      <p>{note}</p>
      {children}
    </Card>
  );
}
function SettingsRow({ name, sub, children }: { name: string; sub: string; children: ReactNode }) {
  return (
    <li>
      <h3>{name}</h3>
      <p>{sub}</p>
      {children}
    </li>
  );
}

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

export function SettingsPage() {
  const [density, setDensity] = useDensity();
  const [routines] = useState(createRoutinesClient);
  return (
    <div data-testid="park-page-settings">
      <PageSheet>
        <div data-testid="settings">
          <h1>Settings</h1>
          <p>Your data, what Tilo may use, and how the app looks.</p>
        </div>
        <SettingsSection
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
        </SettingsSection>
        <SettingsSection
          title="Routines"
          note="Runs that repeat every week. Set one with Repeat weekly when you start a run."
        >
          {routines ? (
            <RoutinesPanel client={routines} />
          ) : (
            <>
              <p>No routines yet.</p>
              <p>Routines are listed when Tilo is connected to its server.</p>
              <a href="/start">Create a routine</a>
            </>
          )}
        </SettingsSection>
        <SettingsSection
          title="Consent"
          note="Every one is explicit and can be taken back at any time."
        >
          <ul className="blist">
            {CONSENTS.map(([name, what, to]) => (
              <SettingsRow key={name} name={name} sub={what}>
                {to && (
                  <a href={to} className="pill" aria-label={`Review ${name}`}>
                    Review
                  </a>
                )}
              </SettingsRow>
            ))}
          </ul>
        </SettingsSection>
        <SettingsSection
          title="Your data"
          note="Email bodies are never cached. The style profile keeps settings, not emails. Data stays in asia-southeast1."
        >
          <ul className="blist">
            <SettingsRow
              name="Export my data"
              sub="Events, files and a provenance manifest. Not available in the app yet."
            >
              <span>Export unavailable</span>
            </SettingsRow>
            <SettingsRow
              name="Delete my account and data"
              sub="Not available in the app yet. When it is, your data is removed from every store within 30 days, and this cannot be undone."
            >
              <span>Delete unavailable</span>
            </SettingsRow>
          </ul>
        </SettingsSection>
      </PageSheet>
    </div>
  );
}
