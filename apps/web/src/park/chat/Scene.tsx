// UI-STUDIO-2: the four little rooms the helper sits in (design/studio-v2 "Tilo S Chat": office, balcony, beach,
// cosy room), drawn fresh from the artboard's shapes. Still art: the beach's drifting wave lines are drawn at rest.
// The colours are the artboard's picture colours (art, not UI roles); the dark theme dims the whole picture.
import type { CSSProperties, ReactNode } from "react";
import type { SceneId } from "./displayPrefs";

const at = (style: CSSProperties): CSSProperties => ({ position: "absolute", ...style });
const d = (style: CSSProperties, children?: ReactNode) => <div style={at(style)}>{children}</div>;

export const SCENE_SKY: Readonly<Record<SceneId, string>> = {
  office: "#ECEAE4",
  beach: "#CFE6F0",
  balcony: "#F3D6C6",
  room: "#E9DFD3",
};

/** Where the helper's feet sit, from the bottom of the scene. */
export const SCENE_FLOOR: Readonly<Record<SceneId, number>> = {
  office: 70,
  balcony: 62,
  beach: 64,
  room: 96,
};

const bar = (w: number, h: number, bg: string, extra: CSSProperties = {}) => (
  <span style={{ width: w, height: h, borderRadius: 3, background: bg, ...extra }} />
);
const glow = (w: string, h: string, bg: string) => (
  <span
    style={{
      flex: w,
      height: h,
      background: bg,
      borderRadius: "4px 4px 0 0",
      backgroundImage: "radial-gradient(#FFE7A8 2px,transparent 2.5px)",
      backgroundSize: "16px 18px",
    }}
  />
);

function Office() {
  const pane = {
    borderRadius: 6,
    background: "#D3E5EF",
    position: "relative",
    overflow: "hidden",
  } as const;
  return (
    <>
      {d({ inset: 0, background: "#ECEAE4" })}
      <div
        style={at({
          left: "8%",
          top: "12%",
          width: "42%",
          height: "38%",
          borderRadius: 14,
          background: "#FFFFFF",
          padding: 10,
          boxSizing: "border-box",
          display: "grid",
          gridTemplateColumns: "1fr 1fr",
          gap: 8,
        })}
      >
        <div style={pane}>
          {d({ left: "10%", bottom: 0, width: "22%", height: "55%", background: "#B9CDD9" })}
          {d({ left: "40%", bottom: 0, width: "18%", height: "80%", background: "#AFC4D1" })}
          {d({ left: "66%", bottom: 0, width: "26%", height: "40%", background: "#B9CDD9" })}
        </div>
        <div style={pane}>
          {d({ left: "8%", bottom: 0, width: "30%", height: "65%", background: "#AFC4D1" })}
          {d({ left: "50%", bottom: 0, width: "20%", height: "45%", background: "#B9CDD9" })}
          {d({
            right: "12%",
            top: "18%",
            width: 22,
            height: 22,
            borderRadius: 99,
            background: "#FFF1B8",
          })}
        </div>
        <div style={{ borderRadius: 6, background: "#D9E9F1" }} />
        <div style={{ borderRadius: 6, background: "#D9E9F1" }} />
      </div>
      <div
        style={at({
          right: "8%",
          top: "16%",
          width: "30%",
          display: "flex",
          flexDirection: "column",
        })}
      >
        <div
          style={{ display: "flex", alignItems: "flex-end", gap: 4, height: 64, padding: "0 10px" }}
        >
          {bar(14, 52, "#C9A27E")}
          {bar(12, 60, "#8AA6B8")}
          {bar(16, 46, "#D6C59A")}
          {bar(12, 56, "#B98A86")}
          <span style={{ flex: 1 }} />
          {bar(34, 34, "#86B98A", { borderRadius: 99, marginBottom: 6 })}
        </div>
        <div style={{ height: 8, borderRadius: 4, background: "#BDB6A6" }} />
        <div
          style={{ display: "flex", alignItems: "flex-end", gap: 4, height: 58, padding: "0 10px" }}
        >
          {bar(44, 30, "#E6DED0", { borderRadius: 6 })}
          {bar(12, 50, "#9DB59F")}
          {bar(14, 44, "#C7B07E")}
        </div>
        <div style={{ height: 8, borderRadius: 4, background: "#BDB6A6" }} />
      </div>
      {d({ left: 0, right: 0, bottom: 0, height: "26%", background: "#DCD8CE" })}
      {d({
        left: "6%",
        bottom: "22%",
        width: 56,
        height: 64,
        borderRadius: "0 0 12px 12px",
        background: "#C9B79C",
      })}
      {d({
        left: "calc(6% - 18px)",
        bottom: "calc(22% + 50px)",
        width: 50,
        height: 50,
        borderRadius: 99,
        background: "#7FB77E",
      })}
      {d({
        left: "calc(6% + 22px)",
        bottom: "calc(22% + 70px)",
        width: 56,
        height: 56,
        borderRadius: 99,
        background: "#6FA96F",
      })}
    </>
  );
}

function Beach() {
  return (
    <>
      {d({ inset: 0, background: "#CFE6F0" })}
      {d({
        right: "14%",
        top: "12%",
        width: 92,
        height: 92,
        borderRadius: 99,
        background: "#FFE08A",
        boxShadow: "0 0 0 18px rgba(255,224,138,.35)",
      })}
      {d(
        { left: 0, right: 0, top: "44%", height: "22%", background: "#8CC9DC", overflow: "hidden" },
        <>
          {d({
            left: -40,
            right: -40,
            top: "22%",
            height: 6,
            borderRadius: 99,
            background: "#B6E0EC",
          })}
          {d({
            left: -40,
            right: -40,
            top: "58%",
            height: 5,
            borderRadius: 99,
            background: "#A9D8E6",
          })}
        </>,
      )}
      {d({ left: 0, right: 0, bottom: 0, height: "36%", background: "#F1E3C3" })}
      {d({
        left: "10%",
        bottom: "30%",
        width: 6,
        height: 190,
        background: "#8A7A66",
        borderRadius: 3,
      })}
      {d(
        {
          left: "calc(10% - 92px)",
          bottom: "calc(30% + 168px)",
          width: 190,
          height: 86,
          borderRadius: "190px 190px 0 0",
          background: "#F07B62",
          overflow: "hidden",
        },
        d({ left: 62, top: 0, width: 66, height: 86, background: "#FFF4E8" }),
      )}
      {d({
        left: "50%",
        bottom: "9%",
        transform: "translateX(-50%)",
        width: 300,
        maxWidth: "70%",
        height: 64,
        borderRadius: 16,
        background: "repeating-linear-gradient(90deg,#FFFFFF 0 26px,#9BD3E3 26px 52px)",
      })}
      {d({
        right: "16%",
        bottom: "12%",
        width: 54,
        height: 54,
        borderRadius: 99,
        background: "conic-gradient(#F07B62 0 25%,#FFFFFF 0 50%,#FFD36E 0 75%,#FFFFFF 0)",
      })}
    </>
  );
}

function Balcony() {
  const dots = ["#FFD86B", "#FF9F7A", "#FFD86B", "#9ED9A9", "#FFD86B", "#FF9F7A"];
  const drop = [4, 6, 7, 6, 4, 2];
  return (
    <>
      {d({ inset: 0, background: "#F3D6C6" })}
      {d({ left: 0, right: 0, top: "22%", height: "30%", background: "#EFC6B6" })}
      {d({
        left: "58%",
        top: "10%",
        width: 70,
        height: 70,
        borderRadius: 99,
        background: "#FFE7B5",
      })}
      <div
        style={at({
          left: 0,
          right: 0,
          top: "30%",
          height: "36%",
          display: "flex",
          alignItems: "flex-end",
          gap: 8,
          padding: "0 12px",
        })}
      >
        <span
          style={{ flex: 1, height: "52%", background: "#A79FB3", borderRadius: "4px 4px 0 0" }}
        />
        {glow(".7", "80%", "#9B92A9")}
        {glow("1.2", "62%", "#AFA7BA")}
        <span
          style={{ flex: 0.6, height: "96%", background: "#958CA3", borderRadius: "4px 4px 0 0" }}
        />
        {glow("1", "58%", "#A79FB3")}
        <span
          style={{ flex: 0.8, height: "74%", background: "#9B92A9", borderRadius: "4px 4px 0 0" }}
        />
      </div>
      {d({ left: 0, right: 0, bottom: 0, height: "34%", background: "#D9CBBE" })}
      {d({
        left: "6%",
        right: "6%",
        top: "16%",
        height: 2,
        background: "#6B6170",
        borderRadius: 2,
        transform: "rotate(-2deg)",
      })}
      <div
        style={at({
          left: "6%",
          right: "6%",
          top: "16%",
          display: "flex",
          justifyContent: "space-between",
          transform: "rotate(-2deg)",
        })}
      >
        {dots.map((c, i) => (
          // biome-ignore lint/suspicious/noArrayIndexKey: fixed bunting, no identity
          <span
            key={i}
            style={{ width: 10, height: 10, borderRadius: 99, background: c, marginTop: drop[i] }}
          />
        ))}
      </div>
      {d({
        left: "5%",
        bottom: "30%",
        width: 60,
        height: 56,
        borderRadius: "0 0 12px 12px",
        background: "#B98763",
      })}
      {d({
        left: "calc(5% - 6px)",
        bottom: "calc(30% + 46px)",
        width: 72,
        height: 60,
        borderRadius: 99,
        background: "#78AE7C",
      })}
    </>
  );
}

function Room() {
  const shelf = (children?: ReactNode) => (
    <div
      style={{
        flex: 1,
        borderRadius: 4,
        background: "#A9805B",
        display: "flex",
        alignItems: "flex-end",
        gap: 3,
        padding: "0 6px",
      }}
    >
      {children}
    </div>
  );
  const book = (w: number, h: string, bg: string) => (
    <span style={{ width: w, height: h, background: bg, borderRadius: 2 }} />
  );
  return (
    <>
      {d({ inset: 0, background: "#E9DFD3" })}
      <div
        style={at({
          left: "10%",
          top: "12%",
          width: "30%",
          height: "34%",
          borderRadius: 12,
          background: "#FFFFFF",
          padding: 8,
          boxSizing: "border-box",
        })}
      >
        <div
          style={{
            position: "relative",
            width: "100%",
            height: "100%",
            borderRadius: 6,
            background: "#2E3550",
            overflow: "hidden",
          }}
        >
          {d({
            right: "18%",
            top: "20%",
            width: 30,
            height: 30,
            borderRadius: 99,
            background: "#FFF1C9",
          })}
          {d({
            left: "20%",
            top: "30%",
            width: 3,
            height: 3,
            borderRadius: 9,
            background: "#FFFFFF",
          })}
          {d({
            left: "40%",
            top: "16%",
            width: 3,
            height: 3,
            borderRadius: 9,
            background: "#FFFFFF",
          })}
          {d({
            left: "30%",
            top: "60%",
            width: 2,
            height: 2,
            borderRadius: 9,
            background: "#FFFFFF",
          })}
        </div>
      </div>
      <div
        style={at({
          right: "10%",
          top: "10%",
          width: "26%",
          height: "52%",
          borderRadius: 10,
          background: "#C29A74",
          padding: 8,
          boxSizing: "border-box",
          display: "flex",
          flexDirection: "column",
          gap: 8,
        })}
      >
        {shelf(
          <>
            {book(10, "80%", "#E8C27A")}
            {book(12, "70%", "#8FB3C7")}
            {book(9, "88%", "#D98E7E")}
            {book(12, "64%", "#A7C59A")}
          </>,
        )}
        {shelf(
          <>
            {book(12, "76%", "#C9B3E0")}
            {book(10, "86%", "#E8C27A")}
            <span style={{ flex: 1 }} />
            <span
              style={{
                width: 22,
                height: 22,
                borderRadius: 99,
                background: "#7FB77E",
                marginBottom: 2,
              }}
            />
          </>,
        )}
        {shelf()}
      </div>
      {d({ left: 0, right: 0, bottom: 0, height: "28%", background: "#CDB8A2" })}
      {d({
        left: "50%",
        bottom: "4%",
        transform: "translateX(-50%)",
        width: 420,
        maxWidth: "90%",
        height: 70,
        borderRadius: "50%",
        background: "#D9A99A",
      })}
      {d({
        left: "50%",
        bottom: "16%",
        transform: "translateX(-50%)",
        width: 330,
        maxWidth: "76%",
        height: 250,
        maxHeight: "60%",
        borderRadius: "60px 60px 24px 24px",
        background: "#B07D55",
      })}
      {d({
        left: "8%",
        bottom: "26%",
        width: 6,
        height: 240,
        maxHeight: "50%",
        background: "#6B5B4A",
      })}
    </>
  );
}

/** The scene behind the helper (decoration: aria-hidden by the caller's figure). */
export function SceneArt({ scene }: { scene: SceneId }) {
  return (
    <div className="park-chat-scene__art">
      {scene === "office" ? (
        <Office />
      ) : scene === "beach" ? (
        <Beach />
      ) : scene === "balcony" ? (
        <Balcony />
      ) : (
        <Room />
      )}
    </div>
  );
}

/** What stands in front of the helper (the office desk, the balcony rail). */
export function SceneFront({ scene }: { scene: SceneId }) {
  if (scene === "office")
    return (
      <div className="park-chat-scene__front">
        {d({
          left: "12%",
          right: "12%",
          bottom: 0,
          height: 120,
          borderRadius: "18px 18px 0 0",
          background: "#2B2B2E",
        })}
        {d({
          left: "18%",
          bottom: 120,
          width: 120,
          height: 10,
          borderRadius: 4,
          background: "#CFCFCA",
        })}
        {d({
          right: "20%",
          bottom: 120,
          width: 30,
          height: 36,
          borderRadius: "4px 4px 8px 8px",
          background: "#F07B62",
        })}
      </div>
    );
  if (scene === "balcony")
    return (
      <div className="park-chat-scene__front">
        <div style={at({ left: 0, right: 0, bottom: 0, height: 130 })}>
          {d({ left: 0, right: 0, top: 0, height: 10, background: "#3B3540", borderRadius: 4 })}
          {d({
            left: 0,
            right: 0,
            top: 10,
            bottom: 0,
            background: "repeating-linear-gradient(90deg,#3B3540 0 6px,transparent 6px 36px)",
          })}
        </div>
      </div>
    );
  return null;
}
