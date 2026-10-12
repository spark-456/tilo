// @vitest-environment happy-dom
import { act } from "react";
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, click, mount, q } from "../../test-support/park/componentsHarness";
import { LivePins } from "./LivePins";
const env = vi.hoisted(() => ({ demo: false, url: "https://api.test", signedIn: true }));
vi.mock("../api/ClientProvider", () => ({
  get API_URL() {
    return env.url;
  },
  sessionView: { demo: () => env.demo },
  authToken: async () => "fake.token.value",
  appCheckToken: async () => null,
}));
vi.mock("../auth/session", () => ({
  session: {
    subscribe: () => () => {},
    getState: () => (env.signedIn ? google : unavailable),
  },
}));
const google = { status: "google", displayName: "Person", email: null };
const unavailable = { status: "unavailable" };
const pin = (id = "pb_own", user = "u_self", status = "active") => ({
  id,
  title: "Recorded pin",
  body: null,
  status,
  created_at: "2026-10-12T00:00:00Z",
  set_up_by: user,
  scope: { kind: "personal", user },
});
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
const read = (url: unknown, items: unknown[] = []) =>
  json(String(url).endsWith("/plate") ? { user: "u_self" } : { items, truncated: false });
async function settle() {
  await act(async () => {
    for (let n = 0; n < 80; n++) await Promise.resolve();
  });
}
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  Object.assign(env, { demo: false, url: "https://api.test", signedIn: true });
});
const button = (root: HTMLElement, text: string) => {
  const found = [...root.querySelectorAll("button")].find((b) => b.textContent === text);
  if (!found) throw Error(`Missing button: ${text}`);
  return found;
};
function fill(root: HTMLElement) {
  const title = q<HTMLInputElement>(root, 'input[name="title"]');
  const scope = q<HTMLSelectElement>(root, 'select[name="scope"]');
  act(() => {
    title.value = "My note";
    scope.value = "personal";
  });
}
it("FR_PB_01_02_05 verifies caller from plate, never offers another setter's delete", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url) =>
      read(url, [
        pin(),
        { ...pin("pb_myteam"), scope: { kind: "team", team: "tm_one" } },
        { ...pin("pb_team", "u_other"), scope: { kind: "team", team: "tm_one" } },
      ]),
    ),
  );
  const m = mount(<LivePins />);
  await settle();
  expect(m.container.querySelectorAll('button[aria-label^="Delete:"]')).toHaveLength(2);
  expect(m.container.textContent).toContain("Add pin");
  expect(m.container.textContent).toContain("Moving pins is not available yet");
});
it.each([false, true])(
  "FR_PB_02 create waits for confirmed record, malformed=%s",
  async (malformed) => {
    let resolve!: (v: Response) => void;
    const fetch = vi.fn(async (url, init) =>
      init?.method === "POST"
        ? new Promise<Response>((r) => {
            resolve = r;
          })
        : read(url),
    );
    vi.stubGlobal("fetch", fetch);
    const m = mount(<LivePins />);
    await settle();
    fill(m.container);
    click(button(m.container, "Add pin"));
    await settle();
    expect(m.container.textContent).toContain("No pinboard items yet");
    expect(button(m.container, "Saving…").disabled).toBe(true);
    expect(
      JSON.parse(fetch.mock.calls.find((c) => c[1]?.method === "POST")?.[1].body ?? "null"),
    ).toEqual({ title: "My note", kind: "note", body: null, url: null });
    resolve(
      json(
        malformed
          ? { id: "pb_bad", status: "active" }
          : { ...pin("pb_new"), title: "Server redacted note" },
        201,
      ),
    );
    await settle();
    expect(m.container.textContent).toContain(
      malformed ? "Could not confirm" : "Server redacted note",
    );
    if (malformed) expect(m.container.textContent).toContain("No pinboard items yet");
  },
);
it("FR_PB_05 failed delete keeps row, confirmed removed reply removes it", async () => {
  let fail = true;
  const fetch = vi.fn(async (url, init) =>
    init?.method === "POST"
      ? fail
        ? json({}, 409)
        : json(pin("pb_own", "u_self", "removed"))
      : read(url, [pin()]),
  );
  vi.stubGlobal("fetch", fetch);
  const m = mount(<LivePins />);
  await settle();
  click(q(m.container, 'button[aria-label^="Delete:"]'));
  await settle();
  expect(m.container.textContent).toContain("Recorded pin");
  expect(m.container.querySelector('[role="alert"]')).not.toBeNull();
  fail = false;
  click(q(m.container, 'button[aria-label^="Delete:"]'));
  await settle();
  expect(m.container.textContent).toContain("No pinboard items yet");
  expect(fetch.mock.calls.filter((c) => c[1]?.method === "POST")).toHaveLength(2);
});
it.each(["demo", "noAPI", "unverified"])(
  "FR_PB_02 %s has no write controls or writes",
  async (gate) => {
    env.demo = gate === "demo";
    env.url = gate === "noAPI" ? "" : env.url;
    env.signedIn = gate !== "unverified";
    const fetch = vi.fn(async () => json({ items: [pin()], truncated: false }));
    vi.stubGlobal("fetch", fetch);
    const m = mount(<LivePins />);
    await settle();
    expect(m.container.querySelector("form")).toBeNull();
    expect(m.container.querySelector('button[aria-label^="Delete:"]')).toBeNull();
    expect(fetch.mock.calls).toHaveLength(gate === "unverified" ? 1 : 0);
  },
);
it("FR_PB_02 malformed identity never enables writes", async () => {
  const fetch = vi.fn(async (url) =>
    String(url).endsWith("/plate")
      ? json({ user: "email@example.test" })
      : json({ items: [pin()], truncated: false }),
  );
  vi.stubGlobal("fetch", fetch);
  const m = mount(<LivePins />);
  await settle();
  expect(m.container.querySelector("form")).toBeNull();
  expect(m.container.textContent).toContain("read only");
});
