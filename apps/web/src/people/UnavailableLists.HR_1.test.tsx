// @vitest-environment happy-dom
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, mount } from "../../test-support/park/componentsHarness";
import { ClientProvider } from "../api/ClientProvider";
import { HttpClient } from "../api/http";
import { S_26 } from "../screens/S_26";
import { S_28 } from "../screens/S_28";

afterEach(cleanup);
it("HR_1 FR_PA_03 FR_PB_01 live sessions never show fixture meetings or pins when list routes are absent", () => {
  const fetch = vi.fn();
  const client = new HttpClient({ baseUrl: "https://api.test", fetch });
  for (const screen of [<S_26 key="meetings" params={[]} />, <S_28 key="pins" />]) {
    const m = mount(<ClientProvider client={client}>{screen}</ClientProvider>);
    expect(m.container.textContent).toContain("Not available yet");
    expect(
      m.container.querySelectorAll('a[href^="/meetings/"], [data-testid="pin-row"]'),
    ).toHaveLength(0);
    expect(m.container.textContent).not.toContain("sample data");
    m.unmount();
  }
  expect(fetch).not.toHaveBeenCalled();
});
