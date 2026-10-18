// @vitest-environment happy-dom
import { act } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, mount } from "../../../../test-support/park/componentsHarness";
import { HttpClient } from "../../../api/http";
import { MeetingHall } from "./MeetingHall";

afterEach(cleanup);

describe("P0-MEETING-ROOM: World Meeting Hall as real meeting room", () => {
  it("renders a top-down table, seat per agent with role name (never ids), Call to the table tray, and buttons", async () => {
    const calls: [string, unknown][] = [];
    let currentRoom: Record<string, unknown> | null = null;

    const fetcher = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input).replace("https://api.test", "");
      const body = init?.body ? JSON.parse(String(init.body)) : null;
      calls.push([path, body]);

      if (path.endsWith("/layout")) {
        return new Response(
          JSON.stringify({
            semantic: {
              levels: [{ districts: [{ id: "d1", lead: "A_one" }] }],
              agents: [
                { id: "A_one", rank: "lead" },
                { id: "A_two", rank: "writer" },
                { id: "A_three", rank: "specialist" },
              ],
            },
          }),
          { status: 200 },
        );
      }
      if (path.endsWith("/events")) {
        return new Response(
          JSON.stringify({
            events: [
              { actor: "A_two", target: null, district: "d1" },
              { actor: "A_three", target: null, district: "d1" },
            ],
            next_cursor: null,
          }),
          { status: 200 },
        );
      }
      if (path.endsWith("/rooms") && init?.method === "POST") {
        currentRoom = {
          room_id: "01ARZ3NDEKTSV4RRFFQ69G5FAV",
          world_id: "w_one",
          run_id: "r_one",
          state: "open",
          reason: null,
          lead: "A_one",
          agents: body.agents,
          as_role: "owner",
          credit_cap: 5,
          credits_spent: 0,
          max_turns: 10,
          turns: [],
        };
        return new Response(JSON.stringify(currentRoom), { status: 200 });
      }
      if (path.endsWith("/turns") && init?.method === "POST") {
        const turn = {
          turn: 1,
          to: "A_two",
          mode: "quick",
          text: "What is your status?",
          reply: {
            from: "A_two",
            outcome: "answered",
            text: "Drafting the project brief now.",
            units: ["U1"],
            artifacts: [],
            proposal: null,
          },
          change: null,
        };
        currentRoom = {
          ...currentRoom,
          turns: [turn],
        };
        return new Response(JSON.stringify(turn), { status: 200 });
      }
      if (path.includes("/rooms/01ARZ3NDEKTSV4RRFFQ69G5FAV") && init?.method !== "POST") {
        return new Response(JSON.stringify(currentRoom), { status: 200 });
      }
      if (path.endsWith("/adjourn")) {
        currentRoom = { ...currentRoom, state: "adjourned", reason: "person" };
        return new Response(JSON.stringify(currentRoom), { status: 200 });
      }
      return new Response("{}", { status: 200 });
    });

    await act(async () => {
      mount(
        <MeetingHall
          worldId="w_one"
          client={new HttpClient({ baseUrl: "https://api.test", fetch: fetcher })}
        />,
      );
    });

    // 1. Table exists
    expect(document.querySelector(".park-meeting-table")).not.toBeNull();
    expect(document.querySelector(".park-meeting-table-title")?.textContent).toContain("Conference Table");

    // 2. Seats and avatar chips with role names, never IDs
    expect(document.body.textContent).not.toContain("A_one");
    expect(document.body.textContent).not.toContain("A_two");
    expect(document.body.textContent).not.toContain("A_three");

    const seats = document.querySelectorAll(".park-meeting-seat");
    expect(seats.length).toBeGreaterThanOrEqual(1);
    expect(document.querySelector(".park-meeting-seat-name")?.textContent).toContain("Lead");

    // 3. 'Call to the table' tray of the world's agents
    const tray = document.querySelector(".park-meeting-tray");
    expect(tray).not.toBeNull();
    expect(tray?.textContent).toContain("Call to the table");
    expect(tray?.textContent).toContain("Writer");
    expect(tray?.textContent).toContain("Specialist");

    // 4. Speaking ring indicator ONLY while that agent has a recorded message (initially none)
    expect(document.querySelector(".park-meeting-speaking-ring")).toBeNull();
    expect(document.querySelector(".park-meeting-seat--speaking")).toBeNull();

    // Seat an agent via Call to the table tray checkbox
    const writerBox = [...document.querySelectorAll("label.park-meeting-agentchip")].find((l) =>
      l.textContent?.includes("Writer"),
    )?.querySelector("input");
    expect(writerBox).not.toBeNull();
    await act(async () => {
      writerBox?.click();
    });

    // Convene room
    const conveneBtn = [...document.querySelectorAll("button")].find((b) => b.textContent === "Convene");
    expect(conveneBtn).not.toBeNull();
    await act(async () => {
      conveneBtn?.click();
    });

    expect(calls).toContainEqual(["/v1/worlds/w_one/rooms", { lead: "A_one", agents: ["A_two"] }]);

    // Room is convened: check message box below with Send, End conversation, Ask them to change direction
    const sendBtn = [...document.querySelectorAll("button")].find((b) => b.textContent === "Send");
    const endBtn = [...document.querySelectorAll("button")].find((b) => b.textContent === "End conversation");
    const changeDirBtn = [...document.querySelectorAll("button")].find((b) =>
      b.textContent === "Ask them to change direction",
    );
    expect(sendBtn).not.toBeNull();
    expect(endBtn).not.toBeNull();
    expect(changeDirBtn).not.toBeNull();

    // Click "Ask them to change direction" pre-populates textarea
    const textarea = document.querySelector("textarea") as HTMLTextAreaElement;
    expect(textarea).not.toBeNull();
    await act(async () => {
      changeDirBtn?.click();
    });
    expect(textarea.value).toContain("change direction");

    // Send question to Writer
    await act(async () => {
      textarea.value = "What is your status?";
      textarea.dispatchEvent(new Event("input", { bubbles: true }));
    });
    await act(async () => {
      sendBtn?.click();
    });

    // Transcript renders chat bubbles
    const userBubble = document.querySelector(".park-meeting-bubble--user");
    const agentBubble = document.querySelector(".park-meeting-bubble--agent");
    expect(userBubble).not.toBeNull();
    expect(userBubble?.textContent).toContain("What is your status?");
    expect(agentBubble).not.toBeNull();
    expect(agentBubble?.textContent).toContain("Drafting the project brief now.");
    expect(agentBubble?.textContent).toContain("Writer");

    // Speaking ring ONLY while agent has recorded message: Writer now has recorded message!
    const speakingSeat = document.querySelector(".park-meeting-seat--speaking");
    expect(speakingSeat).not.toBeNull();
    expect(speakingSeat?.textContent).toContain("Writer");
    expect(speakingSeat?.querySelector(".park-meeting-speaking-ring")).not.toBeNull();

    // End conversation adjourns
    await act(async () => {
      endBtn?.click();
    });
    expect(document.body.textContent).toContain("Adjourned · Closed by request");
  });
});
