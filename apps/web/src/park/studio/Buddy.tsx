// UI-STUDIO-2: the Studio helper character (design/studio-v2 "Tilo S Buddy", drawn fresh from its markup; the
// design runtime is never ported). Every pose is STILL: the design's bob, blink, talking mouth, waving arm and
// thinking dots are motion with no recorded event behind them, so each mood is one fixed pose (HR-1, HR-2;
// docs/open-questions.md BQ-STUDIO-2). A mood is chosen by the caller from real state only.
import type { CSSProperties } from "react";

/** idle = nothing asked; reading = a request is in flight; talking = an answer is being shown; done = answered. */
export type BuddyMood = "idle" | "reading" | "talking" | "done";

export type BuddyRole = "director" | "research" | "builder" | "connector" | "designer" | "finance";

// The design's role colours (art, not UI roles: the character keeps them in both themes).
const ROLE: Readonly<Record<BuddyRole, string>> = {
  director: "#E8643F",
  research: "#3F7FE0",
  builder: "#E57F3E",
  connector: "#D9588C",
  designer: "#A45DB8",
  finance: "#3E9A7C",
};

const INK = "#1F1D2B";

function mix(hex: string, to: number, f: number): string {
  const parts = [1, 3, 5].map((i) => Number.parseInt(hex.slice(i, i + 2), 16));
  return `#${parts
    .map((v) =>
      Math.round(v + (to - v) * f)
        .toString(16)
        .padStart(2, "0"),
    )
    .join("")}`;
}

const box = (
  left: number,
  top: number,
  width: number,
  height: number,
  extra: CSSProperties = {},
): CSSProperties => ({ position: "absolute", left, top, width, height, ...extra });

// Mouth per mood: [left, top, width, height, radius] in the 200 x 236 drawing.
const MOUTH: Readonly<Record<BuddyMood, readonly [number, number, number, number, string]>> = {
  idle: [36, 38, 12, 3, "2px"],
  reading: [39, 37, 7, 7, "99px"],
  talking: [36, 35, 12, 10, "6px"],
  done: [33, 34, 18, 10, "2px 2px 10px 10px"],
};
// Arm angles per mood: [left, right].
const ARMS: Readonly<Record<BuddyMood, readonly [number, number]>> = {
  idle: [8, -8],
  reading: [8, -118],
  talking: [34, -48],
  done: [155, -150],
};

export function Buddy({
  mood = "idle",
  role = "director",
  size = 236,
}: {
  mood?: BuddyMood;
  role?: BuddyRole;
  /** Height in px; the width follows (200:236). */
  size?: number;
}) {
  const k = size / 236;
  const col = ROLE[role];
  const lt = (f: number) => mix(col, 255, f);
  const dk = (f: number) => mix(col, 0, f);
  const limb = dk(0.3);
  const limbD = dk(0.45);
  const happy = mood === "done";
  const [mx, my, mw, mh, mr] = MOUTH[mood];
  const [armL, armR] = ARMS[mood];
  const blush = happy || mood === "talking" ? 0.9 : 0.45;
  const arm = (left: number, angle: number) => (
    <div
      style={box(left, 96, 20, 58, {
        borderRadius: 6,
        background: limb,
        transformOrigin: "10px 6px",
        transform: `rotate(${angle}deg)`,
      })}
    >
      <span style={box(-1, 44, 22, 16, { borderRadius: 5, background: limbD })} />
    </div>
  );
  const eye = (left: number) =>
    happy ? (
      <span
        style={box(left - 2, 16, 15, 9, {
          boxSizing: "border-box",
          border: `3.5px solid ${INK}`,
          borderBottom: 0,
          borderRadius: "10px 10px 0 0",
        })}
      />
    ) : (
      <span style={box(left, 13, 11, 14, { borderRadius: 6, background: INK })}>
        <span style={box(2, 2, 4, 4, { borderRadius: 9, background: "#FFFFFF" })} />
      </span>
    );
  return (
    <div
      aria-hidden="true"
      className="park-buddy"
      data-mood={mood}
      style={{ position: "relative", width: Math.round(200 * k), height: size, flex: "none" }}
    >
      <div style={box(0, 0, 200, 236, { transform: `scale(${k})`, transformOrigin: "0 0" })}>
        <div
          style={box(46, 212, 116, 16, {
            borderRadius: "50%",
            background: "#000000",
            opacity: 0.16,
          })}
        />
        {mood === "reading" ? (
          <div style={{ position: "absolute", left: 150, top: 6, display: "flex", gap: 6 }}>
            {[0.35, 0.65, 1].map((o) => (
              <span
                key={o}
                style={{ width: 10, height: 10, borderRadius: 99, background: col, opacity: o }}
              />
            ))}
          </div>
        ) : null}
        <div style={box(0, happy ? -10 : 0, 200, 220)}>
          <div style={box(68, 188, 24, 26, { borderRadius: 5, background: limb })} />
          <div style={box(112, 188, 24, 26, { borderRadius: 5, background: limb })} />
          {arm(26, armL)}
          {role === "director" ? (
            <>
              <div style={box(70, 44, 20, 26, { borderRadius: 4, background: dk(0.22) })} />
              <div style={box(94, 30, 22, 40, { borderRadius: 4, background: col })} />
              <div
                style={box(94, 30, 22, 7, { borderRadius: "4px 4px 0 0", background: lt(0.25) })}
              />
              <div style={box(120, 44, 20, 26, { borderRadius: 4, background: dk(0.22) })} />
            </>
          ) : null}
          <div
            style={box(44, 62, 124, 10, {
              background: lt(0.25),
              clipPath: "polygon(0 100%,10px 0,100% 0,112px 100%)",
            })}
          />
          <div
            style={box(156, 62, 12, 134, {
              background: dk(0.22),
              clipPath: "polygon(0 10px,100% 0,100% 124px,0 100%)",
            })}
          />
          <div
            style={box(44, 72, 112, 124, {
              borderRadius: "10px 6px 12px 12px",
              background: col,
              boxShadow: `inset 0 -8px 0 ${dk(0.08)}`,
            })}
          />
          <div
            style={box(58, 88, 84, 54, {
              borderRadius: 14,
              background: "#FFFFFF",
              boxShadow: "inset 0 -4px 0 rgba(0,0,0,.06)",
            })}
          >
            <div
              style={box(0, 0, 84, 54, {
                transform: mood === "reading" ? "translateY(-3px)" : "none",
              })}
            >
              {eye(20)}
              {eye(53)}
            </div>
            <span
              style={box(9, 31, 10, 6, { borderRadius: 99, background: lt(0.45), opacity: blush })}
            />
            <span
              style={box(65, 31, 10, 6, { borderRadius: 99, background: lt(0.45), opacity: blush })}
            />
            <span style={box(mx, my, mw, mh, { borderRadius: mr, background: INK })} />
          </div>
          {arm(168, armR)}
        </div>
      </div>
    </div>
  );
}
