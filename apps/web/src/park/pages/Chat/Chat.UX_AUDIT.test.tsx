// @vitest-environment happy-dom
// UX-AUDIT: a disabled "Turn into a world" says why (nothing has been asked yet).
import { afterEach, expect, it, vi } from "vitest";
import { fakeApi, fakeScheduler, stubApp } from "../../../../test-support/park/appHarness";
import { cleanup, mount } from "../../../../test-support/park/componentsHarness";
import { settle } from "../../../../test-support/park/homeHarness";
import { ParkProvider } from "../../app/context";
import { ChatPage } from "./ChatPage";

afterEach(() => {
  cleanup();
  window.localStorage.clear();
});

it("UX_AUDIT_chat_turn_into_a_world_says_why_it_is_disabled", async () => {
  const app = stubApp("chat");
  const m = mount(
    <ParkProvider
      api={fakeApi()}
      worldClient={null}
      navigate={vi.fn()}
      schedule={fakeScheduler().schedule}
      viewport={{ vw: 1440, vh: 900 }}
    >
      <ChatPage app={app} />
    </ParkProvider>,
  );
  await settle();
  const turn = [...m.container.querySelectorAll("button")].find(
    (b) => b.textContent?.trim() === "Turn into a world",
  );
  expect(turn?.disabled).toBe(true);
  expect(turn?.title).toBe("Ask a question first");
});
