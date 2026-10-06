// Name tags on the canvas: a white pill for a building, a tinted one for a district. Ported from
// design/source/tilo-world.js (label, tag; ADR-0003) as Pixi Text over a rounded rect. The
// type is 12px (the PRD 18.2 ramp's smallest step); the face is the one main.tsx has already
// loaded before first render, so a tag never reflows.
import { Container, Graphics, Text } from "pixi.js";
import tokens from "../../design/tokens";
import { PALETTE, dk } from "./color";

const RES = Math.min(3, Math.max(2, typeof devicePixelRatio === "number" ? devicePixelRatio : 2));

/** A pill centred on (0, 0): `fill` behind `ink` text; `line` is its outline when it has one. */
export function makePill(
  text: string,
  o: { fill: string; ink: string; line?: string; lip?: boolean },
): Container {
  const t = new Text({
    text,
    resolution: RES,
    style: { fontFamily: tokens.font.ui, fontSize: 12, fontWeight: "700", fill: o.ink },
  });
  t.anchor.set(0.5);
  const [w, h] = [t.width + 16, 20];
  const bg = new Graphics();
  if (o.lip) bg.roundRect(-w / 2, -h / 2 + 2, w, h, h / 2).fill({ color: dk(o.fill, 0.25) });
  bg.roundRect(-w / 2, -h / 2, w, h, h / 2).fill({ color: o.fill });
  if (o.line) bg.stroke({ width: 1.5, color: o.line });
  const c = new Container();
  c.addChild(bg, t);
  return c;
}

export const buildingTag = (name: string) =>
  makePill(name, { fill: PALETTE.white, ink: PALETTE.ink, line: PALETTE.pillLine });
export const districtTag = (name: string, tint: string) =>
  makePill(name, { fill: dk(tint, 0.28), ink: PALETTE.white, lip: true });
export const islandTag = (name: string) =>
  makePill(name, { fill: PALETTE.ink2, ink: PALETTE.white, lip: true });
// Dark text on the neutral policy fill: white on it would be under 4.5:1.
export const policyTag = () =>
  makePill("Policy", { fill: tokens.color.policy, ink: PALETTE.ink, lip: true });
