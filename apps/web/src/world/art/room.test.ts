// @vitest-environment happy-dom
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { Graphics } from "pixi.js";
import { expect, it } from "vitest";
import tokens from "../../design/tokens";
import {
  drawChair,
  drawHalo,
  drawPersonSeat,
  drawRoomShell,
  drawSeatedAgent,
  drawSpeakingCue,
  drawTable,
  seatAnchors,
} from "./room";

it("MROOM_ART seat anchors are deterministic, bounded and preserve attendee order up to eight", () => {
  for (let count = 0; count <= 8; count++) {
    const seats = seatAnchors(count);
    expect(seats).toEqual(seatAnchors(count));
    expect(seats).toHaveLength(count);
    expect(seats).toEqual(seatAnchors(8).slice(0, count));
    for (const seat of seats) {
      expect(seat.x).toBeGreaterThanOrEqual(285);
      expect(seat.x).toBeLessThanOrEqual(675);
      expect(seat.y).toBeGreaterThan(0);
      expect(seat.y).toBeLessThan(500);
      expect(seat.scale).toBeGreaterThan(0);
    }
  }
  for (const count of [-1, Number.NaN, Number.POSITIVE_INFINITY])
    expect(seatAnchors(count)).toEqual([]);
  expect(seatAnchors(99)).toHaveLength(8);
});
it("MROOM_ART every exact export draws into real Pixi Graphics without throwing", () => {
  const anchor = { x: 480, y: 240, scale: 1 };
  const tint = tokens.color.district.hall;
  const draws = [
    (g: Graphics) => drawRoomShell(g, 960, 540),
    (g: Graphics) => drawTable(g, 8),
    (g: Graphics) => drawChair(g, "left", 0.5),
    (g: Graphics) => drawChair(g, "right", 1),
    (g: Graphics) => drawPersonSeat(g),
    (g: Graphics) => drawHalo(g, anchor, tint),
    (g: Graphics) => drawSpeakingCue(g, anchor, tint, true),
    (g: Graphics) => drawSpeakingCue(g, anchor, tint, false),
    ...["lead", "specialist", "director"].flatMap((rank) =>
      ["left", "right", "front"].map(
        (facing) => (g: Graphics) => drawSeatedAgent(g, rank, tint, facing),
      ),
    ),
  ];
  for (const draw of draws) {
    const g = new Graphics();
    expect(() => draw(g)).not.toThrow();
    expect(g.context.instructions.length).toBeGreaterThan(0);
    g.destroy(true);
  }
});
it("MROOM_ART is still procedural art with no clocks or animation APIs", () => {
  const source = readFileSync(join(__dirname, "room.ts"), "utf8");
  expect(source).not.toMatch(
    /setTimeout|setInterval|requestAnimationFrame|Ticker|\.ticker|\.animate\(/,
  );
  expect(source).not.toMatch(/\.(png|jpe?g|webp)|Texture\.from|Assets\.load/);
});
