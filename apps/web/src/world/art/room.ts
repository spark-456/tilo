// MROOM-ART / ADR-0028: a fixed 960×540 scene viewed from the person's seat.
// Each attendee owns one anchor and a Graphics; the scene host positions and scales the agents.
import type { Graphics } from "pixi.js";
import tokens from "../../design/tokens";
import { drawAgent } from "./agent";
import { PALETTE, dk, lt } from "./color";
import { poly } from "./iso";

export interface SeatAnchor {
  x: number;
  y: number;
  scale: number;
}
const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v));
const hall = tokens.color.district.hall;

/** Lead first, then alternate sides from far to near; prefixes never move when attendees arrive. */
export function seatAnchors(count: number): SeatAnchor[] {
  if (!Number.isFinite(count)) return [];
  const all: SeatAnchor[] = [{ x: 480, y: 225, scale: 0.85 }];
  for (let pair = 0; pair < 4; pair++) {
    const spread = 65 + pair * 24;
    const y = 265 + pair * 48;
    const scale = 0.95 + pair * 0.16;
    all.push({ x: 480 - spread, y, scale }, { x: 480 + spread, y, scale });
  }
  return all.slice(0, clamp(Math.floor(count), 0, 8));
}

export function drawRoomShell(g: Graphics, w: number, h: number): void {
  if (!Number.isFinite(w) || !Number.isFinite(h) || w <= 0 || h <= 0) return;
  g.context.save().scale(w / 960, h / 540);
  g.rect(0, 0, 960, 540).fill(PALETTE.white);
  poly(
    g,
    [
      [0, 0],
      [960, 0],
      [960, 240],
      [0, 240],
    ],
    lt(hall, 0.86),
  );
  poly(
    g,
    [
      [0, 240],
      [960, 240],
      [960, 540],
      [0, 540],
    ],
    tokens.color.surface["2"],
  );
  for (const x of [0, 240, 480, 720, 960])
    g.moveTo(480 + (x - 480) * 0.35, 240)
      .lineTo(x, 540)
      .stroke({ color: lt(hall, 0.65), width: 1 });
  g.rect(650, 60, 170, 112).fill(PALETTE.white).stroke({ color: hall, width: 5 });
  g.rect(658, 68, 154, 96).fill(lt(tokens.color.district.research, 0.8));
  g.moveTo(735, 68).lineTo(735, 164).stroke({ color: PALETTE.white, width: 5 });
  g.rect(125, 80, 86, 160).fill(lt(hall, 0.5)).stroke({ color: hall, width: 4 });
  g.circle(195, 165, 4).fill(PALETTE.ink2);
  g.context.restore();
}

/** Chair coordinates are local to an anchor; depth is zero at the far end, one at the viewer. */
export function drawChair(g: Graphics, side: string, depth: number): void {
  const size = 0.85 + clamp(Number.isFinite(depth) ? depth : 0, 0, 1) * 0.6;
  g.context.save().scale(side === "right" ? -size : size, size);
  g.roundRect(-18, -36, 36, 28, 5)
    .fill(lt(hall, 0.25))
    .stroke({ color: dk(hall), width: 2 });
  poly(
    g,
    [
      [-20, -10],
      [12, -10],
      [22, 1],
      [-10, 5],
    ],
    hall,
  );
  for (const x of [-12, 14]) g.moveTo(x, 1).lineTo(x, 16).stroke({ color: PALETTE.ink2, width: 3 });
  g.context.restore();
}

export function drawTable(g: Graphics, seats: number): void {
  for (const anchor of seatAnchors(seats)) {
    g.context.save().translate(anchor.x, anchor.y);
    drawChair(g, anchor.x > 480 ? "right" : "left", (anchor.y - 225) / 190);
    g.context.restore();
  }
  poly(
    g,
    [
      [310, 435],
      [650, 435],
      [650, 452],
      [310, 452],
    ],
    dk(hall, 0.25),
  );
  poly(
    g,
    [
      [440, 248],
      [520, 248],
      [650, 435],
      [310, 435],
    ],
    lt(hall, 0.42),
  );
  g.moveTo(335, 452)
    .lineTo(335, 480)
    .moveTo(625, 452)
    .lineTo(625, 480)
    .stroke({ color: dk(hall, 0.3), width: 12 });
}

/** The existing rank rig, compressed into a seated body with bent legs, preserving its identity colour. */
export function drawSeatedAgent(g: Graphics, rank: string, tint: string, facing: string): void {
  const col = rank === "director" ? tokens.color.brand.primary : tint;
  g.context.save().scale(facing === "right" ? -1 : 1, 0.8);
  drawAgent(g, rank, tint);
  poly(
    g,
    [
      [-8, -3],
      [5, -3],
      [16, 3],
      [13, 7],
      [-3, 3],
    ],
    dk(col, 0.3),
  );
  poly(
    g,
    [
      [-3, 3],
      [13, 7],
      [13, 12],
      [8, 12],
    ],
    dk(col, 0.3),
  );
  g.context.restore();
}

export function drawPersonSeat(g: Graphics): void {
  poly(
    g,
    [
      [335, 540],
      [365, 508],
      [425, 492],
      [535, 492],
      [595, 508],
      [625, 540],
    ],
    PALETTE.ink2,
  );
  g.ellipse(397, 491, 23, 9).fill(lt(hall, 0.68));
  g.ellipse(563, 491, 23, 9).fill(lt(hall, 0.68));
}

export function drawHalo(g: Graphics, anchor: SeatAnchor, tint: string): void {
  g.ellipse(anchor.x, anchor.y, 21 * anchor.scale, 9 * anchor.scale).stroke({
    color: lt(tint, 0.5),
    width: 3,
    alpha: 0.7,
  });
}

/** Drawn only when the host selects a recorded reply. The host controls pulse visibility. */
export function drawSpeakingCue(
  g: Graphics,
  anchor: SeatAnchor,
  tint: string,
  still: boolean,
): void {
  const color = lt(tint, 0.5);
  if (still)
    g.moveTo(anchor.x - 3 * anchor.scale, anchor.y - 15 * anchor.scale)
      .lineTo(anchor.x + 3 * anchor.scale, anchor.y - 15 * anchor.scale)
      .stroke({ color, width: 2 });
  else
    g.ellipse(anchor.x, anchor.y - 12 * anchor.scale, 28 * anchor.scale, 18 * anchor.scale).stroke({
      color,
      width: 5,
      alpha: 0.25,
    });
}
