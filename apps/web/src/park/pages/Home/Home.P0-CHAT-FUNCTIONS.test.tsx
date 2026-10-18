// @vitest-environment happy-dom
import { act } from "react";
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, mount } from "../../../../test-support/park/componentsHarness";
import { sessionView } from "../../../api/ClientProvider";
import { saveChats } from "../../chat/chatHistory";
import { ChatHistory } from "./Panels";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  localStorage.clear();
});

it("P0-CHAT-FUNCTIONS Home shows saved chats and working Routines and Workspaces destinations", () => {
  vi.spyOn(sessionView, "identity").mockReturnValue({ name: "Alice", email: "alice@example.com" });
  saveChats("alice@example.com", [
    {
      id: "chat-1",
      title: "A saved question",
      updatedAt: 1,
      turns: [{ id: 1, question: "A saved question", state: "error", message: "Try again" }],
    },
  ]);
  const onChat = vi.fn();
  const onWorlds = vi.fn();
  const view = mount(<ChatHistory onChat={onChat} onWorlds={onWorlds} />);
  expect(view.container.textContent).toContain("A saved question");
  const links = [...view.container.querySelectorAll("a")];
  expect(links.find((link) => link.textContent?.includes("Routines"))?.getAttribute("href")).toBe(
    "/worlds",
  );
  expect(links.find((link) => link.textContent?.includes("Workspaces"))?.getAttribute("href")).toBe(
    "/worlds",
  );
  act(() => links.find((link) => link.textContent?.includes("A saved question"))?.click());
  expect(onChat).toHaveBeenCalledWith("chat-1");
  act(() => links.find((link) => link.textContent?.includes("Routines"))?.click());
  expect(onWorlds).toHaveBeenCalledOnce();
});
