import type { AppCtx } from "../../app/AppCtx";
import "./Profile.css";

const SWATCH = {
  day: ["#B6DCA0", "#F4B23E", "#3E9BE6", "#EC6AA6"],
  night: ["#2C3556", "#FFD98A", "#5A6BD0", "#7A62F5"],
} as const;
// UI-STUDIO-1: Light, Dark or System (follows the device), the Studio settings' names for the `time` preference.
const TIMES = [
  ["day", "Light", "Bright lawns"],
  ["night", "Dark", "Lamps and glow"],
  ["system", "System", "Follows your device"],
] as const;
const MOTIONS = [
  ["lively", "Lively", "Full speed on Home. The city pauses when you leave Home."],
  ["calm", "Calm", "Agents and cars move slowly. The city pauses when you leave Home."],
  ["still", "Still", "Nothing moves. Best for older laptops and long sessions."],
] as const;

const cls = (...names: (string | false)[]): string => names.filter(Boolean).join(" ");

/** UI-10 W8: Profile and Settings use the same controls and owning Park preferences. */
export function AppearanceControls({ app }: { app: AppCtx }) {
  const motion = MOTIONS.find((m) => m[0] === app.motion) ?? MOTIONS[1];
  const chosen = app.prefs.time === "system" ? "system" : app.time;
  return (
    <>
      <h3 className="park-profile-group">Theme</h3>
      <div className="park-profile-times">
        {TIMES.map(([id, name, sub]) => {
          // System shows both: the day swatch with the night ground beside it.
          const [ground, a, b, c] = SWATCH[id === "system" ? "day" : id];
          const fill =
            id === "system"
              ? `linear-gradient(90deg, ${ground} 50%, ${SWATCH.night[0]} 50%)`
              : ground;
          return (
            <button
              key={id}
              type="button"
              aria-pressed={chosen === id}
              className={cls("park-profile-time", chosen === id && "park-profile-time--on")}
              onClick={() => app.setPref("time", id)}
            >
              <div className="park-profile-swatch" style={{ background: fill }}>
                <div
                  className="park-profile-block park-profile-block--a"
                  style={{ background: a }}
                />
                <div
                  className="park-profile-block park-profile-block--b"
                  style={{ background: b }}
                />
                <div
                  className="park-profile-block park-profile-block--c"
                  style={{ background: c }}
                />
              </div>
              <div>
                <div className="park-profile-tname">{name}</div>
                <div className="park-profile-tsub">{sub}</div>
              </div>
            </button>
          );
        })}
      </div>
      <h3 className="park-profile-group">Motion in the city</h3>
      <div className="park-profile-motion">
        {MOTIONS.map(([id, name]) => (
          <button
            key={id}
            type="button"
            aria-pressed={motion[0] === id}
            className={cls("park-profile-mopt", motion[0] === id && "park-profile-mopt--on")}
            onClick={() => app.setPref("motion", id)}
          >
            {name}
          </button>
        ))}
      </div>
      <p className="park-profile-motion-help">{motion[2]}</p>
    </>
  );
}
