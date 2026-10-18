import { expect, it } from "vitest";
import type { Message } from "../../world/conversations";
import { unrecordedRoomParts } from "./ChatPopUp";

it("P0-CHAT-FUNCTIONS omits room bubbles once the world's recorded messages contain them", () => {
  const recorded = [
    { room: "room-1", turn: 2, kind: "asked" },
    { room: "room-1", turn: 2, kind: "replied" },
  ] as Message[];
  expect(unrecordedRoomParts("room-1", 2, recorded)).toEqual({ asked: false, replied: false });
  expect(unrecordedRoomParts("room-1", 3, recorded)).toEqual({ asked: true, replied: true });
});
