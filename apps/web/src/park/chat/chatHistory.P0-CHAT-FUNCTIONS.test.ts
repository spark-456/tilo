// @vitest-environment happy-dom
import { beforeEach, expect, it } from "vitest";
import { type SavedChat, readChats, saveChats } from "./chatHistory";

beforeEach(() => localStorage.clear());

it("P0-CHAT-FUNCTIONS restores separate conversations newest first without duplicate turns", () => {
  const older: SavedChat = {
    id: "older",
    title: "First question",
    updatedAt: 1,
    turns: [{ id: 1, question: "First question", state: "error", message: "Try again" }],
  };
  const newer: SavedChat = {
    id: "newer",
    title: "Next question",
    updatedAt: 2,
    turns: [{ id: 1, question: "Next question", state: "error", message: "Try again" }],
  };
  saveChats("person@example.com", [older, newer, newer]);
  expect(readChats("person@example.com").map((chat) => chat.id)).toEqual(["newer", "older"]);
  expect(readChats("other@example.com")).toEqual([]);
});
