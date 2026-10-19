// @vitest-environment happy-dom
import { afterEach, expect, it } from "vitest";
import { cleanup, mount } from "../../../../test-support/park/componentsHarness";
import { LiveConnectors } from "./LiveConnectors";
afterEach(cleanup);
it("does not duplicate the unavailable meeting host and retains unrelated unknown tools", () => {
  const connector = {
    id: "meeting_host",
    name: "Host",
    cat: "",
    mono: "M",
    col: "",
    st: "available" as const,
    live: { stateKnown: false, scopes: [], notConfigured: true },
  };
  const { container } = mount(
    <LiveConnectors
      connectors={[
        connector,
        { ...connector, id: "crm", name: "CRM", live: { stateKnown: false, scopes: [] } },
      ]}
    />,
  );
  expect(container.querySelector('[aria-label="Host"]')).toBeNull();
  expect(container.querySelector('[aria-label="CRM"]')?.textContent).toContain(
    "Connection state not available yet",
  );
});
