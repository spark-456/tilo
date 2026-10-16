// Tilo T Buddy: the mascot every Tilo T screen uses (design/tilo-t "Tilo S Buddy", drawn here from its markup; the
// design runtime is never ported). Moods: idle, talk, think, happy, listen, sad, hand, work, swim. The pose without
// motion is the inline transform, so reduced motion and the 'still' choice show a static pose; the loops (bob, blink,
// arms, mouth, thinking dots) are classes in motion.css.
// Honesty: the caller picks the mood from a recorded event and says which (for example work from building.constructing,
// hand from approval.requested, happy from world.completed, sad from world.failed). The idle bob and blink are ambient.
import type { CSSProperties } from "react";

export type TiloMood =
  | "idle"
  | "talk"
  | "think"
  | "happy"
  | "listen"
  | "sad"
  | "hand"
  | "work"
  | "swim";
export const TILO_MOODS: readonly TiloMood[] = [
  "idle",
  "talk",
  "think",
  "happy",
  "listen",
  "sad",
  "hand",
  "work",
  "swim",
];

export type TiloRole =
  | "director"
  | "research"
  | "builder"
  | "tester"
  | "browser"
  | "connector"
  | "delivery"
  | "designer"
  | "finance";

const ROLE: Readonly<Record<TiloRole, string>> = {
  director: "#E8643F",
  research: "#3F7FE0",
  builder: "#E57F3E",
  tester: "#C9982A",
  browser: "#2BA3B8",
  connector: "#D9588C",
  delivery: "#76A035",
  designer: "#A45DB8",
  finance: "#3E9A7C",
};

const hx = (c: string): number[] => [1, 3, 5].map((i) => Number.parseInt(c.slice(i, i + 2), 16));
const mix = (c: string, t: number[], f: number): string =>
  `#${hx(c)
    .map((v, i) =>
      Math.round(v + ((t[i] ?? 0) - v) * f)
        .toString(16)
        .padStart(2, "0"),
    )
    .join("")}`;

const at = (
  left: number | string,
  top: number | string,
  width: number | string,
  height: number | string,
  extra: CSSProperties = {},
): CSSProperties => ({ position: "absolute", left, top, width, height, ...extra });

// Mouth per mood: [left, top, width, height, radius].
function mouthFor(mood: TiloMood): [number, number, number, number, string] {
  if (mood === "happy" || mood === "swim") return [33, 34, 18, 10, "2px 2px 10px 10px"];
  if (mood === "sad") return [35, 38, 14, 6, "10px 10px 2px 2px"];
  if (mood === "talk") return [36, 35, 12, 10, "6px"];
  if (mood === "think" || mood === "hand") return [39, 37, 7, 7, "99px"];
  if (mood === "listen") return [37, 37, 10, 4, "3px"];
  return [36, 38, 12, 3, "2px"];
}

function armStatic(mood: TiloMood): { l: string; r: string } {
  const l =
    mood === "happy"
      ? "rotate(155deg)"
      : mood === "listen"
        ? "rotate(20deg)"
        : mood === "sad"
          ? "rotate(3deg)"
          : "rotate(8deg)";
  const r =
    mood === "happy"
      ? "rotate(-150deg)"
      : mood === "think"
        ? "rotate(-118deg)"
        : mood === "hand"
          ? "rotate(-170deg)"
          : mood === "listen"
            ? "rotate(-150deg)"
            : mood === "sad"
              ? "rotate(-3deg)"
              : "rotate(-8deg)";
  return { l, r };
}

export function Buddy({
  mood = "idle",
  role = "director",
  size = 236,
  look = "c",
  delay = 0,
  label,
}: {
  mood?: TiloMood;
  role?: TiloRole;
  /** Height in px; the width follows (200:236). */
  size?: number;
  /** Where the eyes look: centre, left or right. */
  look?: "c" | "l" | "r";
  /** Seconds to offset the ambient loops, so a row of helpers does not move in step. */
  delay?: number;
  /** Set only when the picture stands alone; otherwise it is decoration. */
  label?: string;
}) {
  const k = size / 236;
  const col = ROLE[role] ?? ROLE.director;
  const white: number[] = [255, 255, 255];
  const black: number[] = [0, 0, 0];
  const lt = (f: number) => mix(col, white, f);
  const dk = (f: number) => mix(col, black, f);
  const cT = lt(0.25);
  const cR = dk(0.22);
  const cShade = dk(0.08);
  const limb = dk(0.3);
  const limbD = dk(0.45);
  const blushC = lt(0.45);
  const happy = mood === "happy";
  const swim = mood === "swim";
  const sad = mood === "sad";
  const think = mood === "think";
  const hand = mood === "hand";
  const work = mood === "work";
  const talk = mood === "talk";
  const lx = look === "l" ? -5 : look === "r" ? 5 : 0;
  const ey = think ? -3 : sad || work ? 3 : hand ? -2 : 0;
  const [mX, mY, mW, mH, mR] = mouthFor(mood);
  const arms = armStatic(mood);
  const eyeShift = lx || ey ? `translate(${lx}px,${ey}px)` : "none";
  const blush = happy || talk || swim ? 0.9 : sad ? 0 : 0.45;
  const tilt = mood === "listen" ? "rotate(-7deg)" : sad ? "rotate(2deg)" : "none";
  const eyeBox = (left: number): CSSProperties =>
    at(left, 13, 11, 14, { borderRadius: 6, background: "#1F1D2B" });
  const glint = (
    <span style={at(2, 2, 4, 4, { borderRadius: 9, background: "#FFFFFF" })} />
  );
  const arm = (left: number, rot: string, cls: string): JSX.Element => (
    <div
      className={cls}
      style={at(left, 96, 20, 58, {
        borderRadius: 6,
        background: limb,
        transformOrigin: "10px 6px",
        transform: rot,
      })}
    >
      <span style={at(-1, "auto", 22, 16, { bottom: -2, borderRadius: 5, background: limbD })} />
    </div>
  );
  const happyEye = (left: number): CSSProperties =>
    at(left, 16, 15, 9, {
      boxSizing: "border-box",
      border: "3.5px solid #1F1D2B",
      borderBottom: 0,
      borderRadius: "10px 10px 0 0",
    });
  return (
    <div
      className="tt-bd"
      data-mood={mood}
      data-role={role}
      role={label ? "img" : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
      style={
        {
          position: "relative",
          width: `${(200 * k).toFixed(1)}px`,
          height: `${size}px`,
          "--tt-delay": `${delay}s`,
        } as CSSProperties
      }
    >
      <div
        style={at(0, 0, 200, 236, { transform: `scale(${k.toFixed(4)})`, transformOrigin: "0 0" })}
      >
        <div
          className="tt-bd__shadow"
          style={at(46, 212, 116, 16, { borderRadius: "50%", background: "#000000", opacity: 0.16 })}
        />
        {think ? (
          <div className="tt-bd__dots" style={{ ...at(150, 6, "auto", "auto"), display: "flex", gap: 6 }}>
            {[0, 1, 2].map((i) => (
              <span
                key={i}
                style={{ width: 10, height: 10, borderRadius: 99, background: col }}
              />
            ))}
          </div>
        ) : null}
        <div style={at(0, 0, 200, 220, { transform: tilt, transformOrigin: "100px 200px" })}>
          <div className="tt-bd__bob" style={at(0, 0, 200, 220)}>
            <div style={at(68, 188, 24, 26, { borderRadius: 5, background: limb })} />
            <div style={at(112, 188, 24, 26, { borderRadius: 5, background: limb })} />
            <div
              style={at(92, 188, 6, 26, {
                background: limbD,
                clipPath: "polygon(0 4px,100% 0,100% 22px,0 100%)",
              })}
            />
            <div
              style={at(136, 188, 6, 26, {
                background: limbD,
                clipPath: "polygon(0 4px,100% 0,100% 22px,0 100%)",
              })}
            />
            {arm(26, arms.l, "tt-bd__armL")}
            {role === "director" ? (
              <>
                <div style={at(70, 44, 20, 26, { borderRadius: 4, background: cR })} />
                <div style={at(94, 30, 22, 40, { borderRadius: 4, background: col })} />
                <div style={at(94, 30, 22, 7, { borderRadius: "4px 4px 0 0", background: cT })} />
                <div style={at(120, 44, 20, 26, { borderRadius: 4, background: cR })} />
              </>
            ) : null}
            {role === "builder" ? (
              <>
                <div style={at(94, 44, 22, 26, { borderRadius: 4, background: col })} />
                <div style={at(94, 44, 22, 7, { borderRadius: "4px 4px 0 0", background: cT })} />
              </>
            ) : null}
            <div
              style={at(44, 62, 124, 10, {
                background: cT,
                clipPath: "polygon(0 100%,10px 0,100% 0,112px 100%)",
              })}
            />
            <div
              style={at(156, 62, 12, 134, {
                background: cR,
                clipPath: "polygon(0 10px,100% 0,100% 124px,0 100%)",
              })}
            />
            <div
              style={at(44, 72, 112, 124, {
                borderRadius: "10px 6px 12px 12px",
                background: col,
                boxShadow: `inset 0 -8px 0 ${cShade}`,
              })}
            />
            <div
              style={at(58, 88, 84, 54, {
                borderRadius: 14,
                background: "#FFFFFF",
                boxShadow: "inset 0 -4px 0 rgba(0,0,0,.06)",
              })}
            >
              <div style={at(0, 0, 84, 54, { transform: eyeShift })}>
                {happy || swim ? (
                  <>
                    <span style={happyEye(18)} />
                    <span style={happyEye(51)} />
                  </>
                ) : (
                  <>
                    <span className="tt-bd__eye" style={eyeBox(20)}>
                      {glint}
                    </span>
                    <span className="tt-bd__eye" style={eyeBox(53)}>
                      {glint}
                    </span>
                  </>
                )}
              </div>
              <span
                style={at(9, 31, 10, 6, { borderRadius: 99, background: blushC, opacity: blush })}
              />
              <span
                style={at(65, 31, 10, 6, { borderRadius: 99, background: blushC, opacity: blush })}
              />
              <span
                className="tt-bd__mouth"
                style={at(mX, mY, mW, mH, {
                  borderRadius: mR,
                  background: "#1F1D2B",
                  transformOrigin: "50% 30%",
                  transform: talk ? "scaleY(.5)" : "none",
                })}
              />
            </div>
            {arm(168, arms.r, "tt-bd__armR")}
          </div>
        </div>
      </div>
    </div>
  );
}
