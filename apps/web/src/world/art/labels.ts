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

/** WORLD-LIVE: a speech bubble whose tail tip is at (0, 0) and which grows upward: the receiver's name in bold,
 * then the real note, wrapped at 170 px. Dark text on the white pill fill (same pair as the building tags). */
export function makeBubble(to: string, note: string): Container {
  const head = new Text({
    text: to,
    resolution: RES,
    style: { fontFamily: tokens.font.ui, fontSize: 12, fontWeight: "700", fill: PALETTE.ink },
  });
  const body = new Text({
    text: note,
    resolution: RES,
    style: {
      fontFamily: tokens.font.ui,
      fontSize: 12,
      fontWeight: "400",
      fill: PALETTE.ink,
      wordWrap: true,
      wordWrapWidth: 170,
    },
  });
  const [padX, padY, tail] = [8, 6, 7];
  head.position.set(padX, padY);
  body.position.set(padX, padY + head.height + 1);
  const w = Math.max(head.width, body.width) + 2 * padX;
  const h = padY * 2 + head.height + 1 + body.height;
  const bg = new Graphics();
  bg.roundRect(-w / 2, -h - tail, w, h, 8).fill({ color: PALETTE.white });
  bg.roundRect(-w / 2, -h - tail, w, h, 8).stroke({ width: 1.5, color: PALETTE.pillLine });
  bg.poly([-5, -tail - 0.75, 5, -tail - 0.75, 0, 0]).fill({ color: PALETTE.white });
  bg.poly([-5, -tail, 0, 0, 5, -tail]).stroke({ width: 1.5, color: PALETTE.pillLine });
  head.position.set(-w / 2 + padX, -h - tail + padY);
  body.position.set(-w / 2 + padX, -h - tail + padY + head.height + 1);
  const c = new Container();
  c.addChild(bg, head, body);
  return c;
}

/** WORLD-LIVE: the tool icon over a working agent, centred on (0, 0): a ringed disc with a spanner shape, so the
 * state is a shape and not a colour. Static: it is there because agent.working was recorded, and it does not move. */
export function drawTool(g: Graphics): void {
  g.circle(0, 0, 10).fill({ color: PALETTE.white }).stroke({ width: 1.5, color: PALETTE.ink });
  g.moveTo(-4.5, 4.5).lineTo(2, -2).stroke({ width: 2.6, color: PALETTE.ink, cap: "round" });
  g.circle(3.6, -3.6, 3.2).stroke({ width: 2, color: PALETTE.ink });
}
