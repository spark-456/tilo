// UI-STUDIO-1: the Light, Dark and System switch (design/studio-v2 "Tilo S Nav", account menu "Theme"). It writes the
// `time` preference the Profile appearance controls use: day is light, night is dark, system follows the device.
import "./studio.components.css";

export type Appearance = "day" | "night" | "system";

export const APPEARANCES: readonly (readonly [Appearance, string])[] = [
  ["day", "Light"],
  ["night", "Dark"],
  ["system", "System"],
];

/** The stored appearance: anything that is not night or system is light (the default). */
export function appearanceOf(pref: unknown): Appearance {
  return pref === "night" || pref === "system" ? pref : "day";
}

/** Three toggle buttons, the chosen one pressed (the same pattern as the Profile appearance cards). */
export function ThemeSwitch({
  value,
  onChange,
}: {
  value: Appearance;
  onChange: (next: Appearance) => void;
}) {
  return (
    <fieldset className="park-theme">
      <legend className="park-theme__label">Theme</legend>
      <div className="park-theme__group">
        {APPEARANCES.map(([id, label]) => (
          <button
            key={id}
            type="button"
            aria-pressed={value === id}
            data-appearance={id}
            className={`park-theme__opt${value === id ? " park-theme__opt--on" : ""}`}
            onClick={() => onChange(id)}
          >
            {label}
          </button>
        ))}
      </div>
    </fieldset>
  );
}
