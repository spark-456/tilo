// Tilo W AgentSprite: the live agent sprite drawn directly from design/tilo-w/Tilo W Sprite.dc.html.
// 32x40 box scaled by scale (k).
// All animations routed through motion.css via CSS classes (honesty allowlist).
import type { CSSProperties, ReactElement } from "react";

export type AgentSpriteKind = "agent" | "lead" | "director";
export type AgentSpriteMood = "idle" | "work" | "talk" | "think" | "happy" | "sad" | "hand";
export type AgentSpriteWalk = "" | "A" | "B";
export type AgentSpriteFrame = "" | "contact" | "down" | "pass" | "up";

export interface AgentSpriteProps {
  scale?: number;
  col?: string;
  kind?: AgentSpriteKind;
  mood?: AgentSpriteMood;
  walk?: AgentSpriteWalk;
  n?: number;
  face?: "r" | "l";
  frame?: AgentSpriteFrame;
  lit?: boolean;
  label?: string;
  className?: string;
}

const hx = (c: string): number[] => {
  const clean = c.startsWith("#") ? c : `#${c}`;
  return [1, 3, 5].map((i) => Number.parseInt(clean.slice(i, i + 2), 16) || 0);
};

const mix = (col: string, t: number[], f: number): string =>
  "#" +
  hx(col)
    .map((v, i) => Math.round(v + ((t[i] ?? 0) - v) * f).toString(16).padStart(2, "0"))
    .join("");

const FRAMES: Record<string, [number, number, number, number, string]> = {
  contact: [26, -26, -22, 22, "scale(1.04, 0.95)"],
  down: [13, -13, -11, 11, "translateY(1px) scale(1.05, 0.94)"],
  pass: [0, 0, 0, 0, "translateY(-3px) scale(0.97, 1.03)"],
  up: [-13, 13, 11, -11, "translateY(-2px) scale(0.98, 1.02)"],
};

export function AgentSprite({
  scale = 1,
  col = "#E8643F",
  kind = "agent",
  mood = "idle",
  walk = "",
  n = 3,
  face = "r",
  frame = "",
  lit = false,
  label,
  className,
}: AgentSpriteProps): ReactElement {
  const k = scale;
  const walking = Boolean(walk && !frame);
  const F = frame ? FRAMES[frame] : undefined;

  const arms =
    mood === "hand"
      ? [8, -165]
      : mood === "happy"
        ? [150, -150]
        : mood === "sad"
          ? [3, -3]
          : mood === "talk"
            ? [14, -26]
            : [8, -8];

  const r = (d: number) => `rotate(${d}deg)`;

  const top = mix(col, [255, 255, 255], 0.3);
  const shade = mix(col, [0, 0, 0], 0.18);
  const limb = mix(col, [0, 0, 0], 0.32);
  const limbD = mix(col, [0, 0, 0], 0.45);

  const crown = kind === "director";
  const lead = kind === "lead";
  const faceT = face === "l" ? "scaleX(-1)" : "none";
  const bodyS = F ? F[4] : mood === "sad" ? "rotate(4deg)" : "none";

  const legLS = F ? r(F[0]) : "none";
  const legRS = F ? r(F[1]) : "none";
  const armLS = F ? r(F[2]) : r(arms[0] ?? 8);
  const armRS = F ? r(F[3]) : r(arms[1] ?? -8);

  const eyesOpen = mood !== "happy";
  const eyesHappy = mood === "happy";
  const eyeT =
    mood === "sad"
      ? "translateY(2px)"
      : mood === "think"
        ? "translate(1px, -1px)"
        : mood === "talk"
          ? "translateX(1px)"
          : "none";

  const bobClass = walking
    ? `tw-sprite__bob--walk${walk}`
    : mood === "happy" && !frame
      ? "tw-sprite__bob--happy"
      : "";
  const legLClass = walking ? `tw-sprite__legL--walk${walk}` : "";
  const legRClass = walking ? `tw-sprite__legR--walk${walk}` : "";
  const armLClass = walking
    ? `tw-sprite__armL--walk${walk}`
    : mood === "work" && !frame
      ? "tw-sprite__armL--work"
      : "";
  const armRClass = walking
    ? `tw-sprite__armR--walk${walk}`
    : mood === "work" && !frame
      ? "tw-sprite__armR--work"
      : "";

  return (
    <div
      className={`tw-sprite ${className ?? ""}`}
      data-kind={kind}
      data-mood={mood}
      data-walk={walk || undefined}
      data-lit={lit ? "true" : undefined}
      role={label ? "img" : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
      style={{
        position: "relative",
        width: `${(32 * k).toFixed(1)}px`,
        height: `${(40 * k).toFixed(1)}px`,
        ...({ "--wWalkStrides": n } as CSSProperties),
      }}
    >
      <div
        style={{
          position: "absolute",
          left: 0,
          top: 0,
          width: 32,
          height: 40,
          transform: `scale(${k})`,
          transformOrigin: "0 0",
        }}
      >
        {/* Foot shadow */}
        <span
          style={{
            position: "absolute",
            left: 6,
            top: 34,
            width: 20,
            height: 6,
            borderRadius: "50%",
            background: "#000000",
            opacity: 0.16,
          }}
        />

        {/* Hover / selected lit ring */}
        {lit ? (
          <span
            className="tw-sprite__ring"
            style={{
              position: "absolute",
              left: 0,
              top: 31,
              width: 32,
              height: 12,
              boxSizing: "border-box",
              borderRadius: "50%",
              border: `2px solid ${col}`,
            }}
          />
        ) : null}

        {/* Direction container */}
        <div
          style={{
            position: "absolute",
            left: 0,
            top: 0,
            width: 32,
            height: 40,
            transform: faceT,
            transformOrigin: "16px 20px",
          }}
        >
          {/* Bobbing & squash body */}
          <div
            className={bobClass}
            style={{
              position: "absolute",
              left: 0,
              top: 0,
              width: 32,
              height: 40,
              transformOrigin: "16px 37px",
              transform: bodyS,
            }}
          >
            {/* Left leg */}
            <span
              className={legLClass}
              style={{
                position: "absolute",
                left: 10,
                top: 27,
                width: 5,
                height: 9,
                borderRadius: 2,
                background: limb,
                transformOrigin: "2.5px 1px",
                transform: legLS,
              }}
            />

            {/* Right leg */}
            <span
              className={legRClass}
              style={{
                position: "absolute",
                left: 17,
                top: 27,
                width: 5,
                height: 9,
                borderRadius: 2,
                background: limbD,
                transformOrigin: "2.5px 1px",
                transform: legRS,
              }}
            />

            {/* Left arm */}
            <span
              className={armLClass}
              style={{
                position: "absolute",
                left: 3,
                top: 15,
                width: 4,
                height: 10,
                borderRadius: 2,
                background: limbD,
                transformOrigin: "2px 1.5px",
                transform: armLS,
              }}
            />

            {/* Director crown: 3 spikes */}
            {crown ? (
              <>
                <span
                  style={{
                    position: "absolute",
                    left: 10,
                    top: 5,
                    width: 3,
                    height: 5,
                    borderRadius: 1,
                    background: col,
                  }}
                />
                <span
                  style={{
                    position: "absolute",
                    left: 14.5,
                    top: 2.5,
                    width: 3,
                    height: 7,
                    borderRadius: 1,
                    background: top,
                  }}
                />
                <span
                  style={{
                    position: "absolute",
                    left: 19,
                    top: 5,
                    width: 3,
                    height: 5,
                    borderRadius: 1,
                    background: col,
                  }}
                />
              </>
            ) : null}

            {/* Lead single spike */}
            {lead ? (
              <span
                style={{
                  position: "absolute",
                  left: 14.5,
                  top: 4.5,
                  width: 3,
                  height: 5,
                  borderRadius: 1,
                  background: top,
                }}
              />
            ) : null}

            {/* Head / Body */}
            <span
              style={{
                position: "absolute",
                left: 6,
                top: 9,
                width: 20,
                height: 20,
                borderRadius: "6px 6px 7px 7px",
                background: col,
                boxShadow: `inset -3px -3px 0 ${shade}`,
              }}
            />

            {/* Visor */}
            <span
              style={{
                position: "absolute",
                left: 9,
                top: 13,
                width: 14,
                height: 8,
                borderRadius: 4,
                background: "#FFFFFF",
                overflow: "hidden",
              }}
            >
              {eyesOpen ? (
                <>
                  <span
                    style={{
                      position: "absolute",
                      left: 3,
                      top: 2.2,
                      width: 2.5,
                      height: 3.5,
                      borderRadius: 1.5,
                      background: "#1F1D2B",
                      transform: eyeT,
                    }}
                  />
                  <span
                    style={{
                      position: "absolute",
                      left: 8.5,
                      top: 2.2,
                      width: 2.5,
                      height: 3.5,
                      borderRadius: 1.5,
                      background: "#1F1D2B",
                      transform: eyeT,
                    }}
                  />
                </>
              ) : null}

              {eyesHappy ? (
                <>
                  <span
                    style={{
                      position: "absolute",
                      left: 2.5,
                      top: 3,
                      width: 4,
                      height: 2.5,
                      boxSizing: "border-box",
                      border: "1.2px solid #1F1D2B",
                      borderBottom: 0,
                      borderRadius: "3px 3px 0 0",
                    }}
                  />
                  <span
                    style={{
                      position: "absolute",
                      left: 8,
                      top: 3,
                      width: 4,
                      height: 2.5,
                      boxSizing: "border-box",
                      border: "1.2px solid #1F1D2B",
                      borderBottom: 0,
                      borderRadius: "3px 3px 0 0",
                    }}
                  />
                </>
              ) : null}
            </span>

            {/* Right arm */}
            <span
              className={armRClass}
              style={{
                position: "absolute",
                left: 25,
                top: 15,
                width: 4,
                height: 10,
                borderRadius: 2,
                background: limb,
                transformOrigin: "2px 1.5px",
                transform: armRS,
              }}
            />
          </div>
        </div>
      </div>
    </div>
  );
}
