import { type Density, useDensity } from "../../../display/density";
import type { AppCtx } from "../../app/AppCtx";
import { PageSheet } from "../../components";
import { SettingsAppearance } from "../../shell/SettingsAppearance";
import { type RunSection, RunSectionView } from "./RunSections";
import { Routines } from "./routines/Routines";
import { Block } from "./shared";
import "./Admin.css";

const SECTIONS = ["settings", "autonomy", "channels", "estimate", "pilot"] as const;
export function SettingsSection() {
  const [density, setDensity] = useDensity();
  return (
    <div className="park-admin-sections">
      <Block title="Appearance">
        <SettingsAppearance />
        <fieldset>
          <legend>Display mode</legend>
          {(["friendly", "professional"] as Density[]).map((id) => (
            <label key={id}>
              <input
                type="radio"
                name="density"
                value={id}
                checked={density === id}
                onChange={() => setDensity(id)}
              />
              {id === "friendly" ? "Friendly" : "Professional"}
            </label>
          ))}
        </fieldset>
      </Block>
      <Block title="Routines">
        <Routines />
      </Block>
      <Block title="Consent">
        <p>Every opt-in is explicit and revocable.</p>
        <a href="/connectors">Review Gmail access</a> ·{" "}
        <a href="/profile?tab=notifications">Review Email</a>
        <p>Style profile settings and the pilot diary are not available yet.</p>
      </Block>
      <Block title="Your data">
        <p>
          Email bodies are never cached. The style profile keeps settings, not emails. Data stays in
          asia-southeast1.
        </p>
      </Block>
    </div>
  );
}
export function AdminPage({ app }: { app: AppCtx }) {
  const section = SECTIONS.find((s) => s === app.params.section) ?? "settings";
  return (
    <div data-testid="park-page-settings" className="park-admin">
      <PageSheet gap={22}>
        <h1>Settings</h1>
        <nav aria-label="Settings sections">
          {SECTIONS.map((s) => (
            <button
              key={s}
              type="button"
              aria-current={s === section ? "page" : undefined}
              onClick={() =>
                app.go("settings", {
                  section: s,
                  ...(app.params.world ? { world: app.params.world } : {}),
                })
              }
            >
              {s === "estimate" ? "How we estimate" : s[0]?.toUpperCase() + s.slice(1)}
            </button>
          ))}
        </nav>
        {section === "settings" ? (
          <SettingsSection />
        ) : section === "pilot" ? (
          <Block title="Pilot diary">
            <p>The daily diary and exit survey are not available yet. Nothing is sent or stored.</p>
          </Block>
        ) : (
          <RunSectionView
            key={`${section}/${app.params.world ?? ""}`}
            section={section as RunSection}
          />
        )}
      </PageSheet>
    </div>
  );
}
