// @vitest-environment happy-dom
// FR-HIL-12 (web side): an Approver answers a gate from a shared link after sign-in. The API decides everything
// (services/api tests/API_FR_HIL_12.md); the page shows the gate card it is given, sends ONE answer, and never
// puts the token anywhere but the two request paths.
import { act } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, click, mount, q, qa } from "../../test-support/park/componentsHarness";
import { TiloApiError } from "../api/http";
import { SharePage } from "./SharePage";
import { answerShare, gateViewOf, openShare, refusalOf, tokenOf } from "./shareLink";

afterEach(cleanup);

const TOKEN = ["tok", "en", "/with space"].join("-"); // assembled at runtime: not a real secret
const gateCard = (over: Record<string, unknown> = {}) => ({
  card: {
    kind: "gate",
    what_happened: "Send the supplier order",
    why_it_matters: "The order cannot be taken back once sent.",
    gate: {
      id: "g1",
      action: { exact: "Email 3 purchase orders", type: "send", connector: "gmail" },
      recipients: ["a@example.com", "b@example.com"],
      irreversible: true,
      risk_tier: "T3",
    },
    options: [
      { id: "approve", label: "Approve", suggested: false, irreversible: true },
      { id: "hold", label: "Hold", suggested: true, irreversible: false },
    ],
    ...over,
  },
});
const apiError = (status: number | null, retryable = false) =>
  new TiloApiError("x", status, retryable, false);

function http(over: { get?: () => Promise<unknown>; post?: () => Promise<unknown> } = {}) {
  return {
    getJson: vi.fn(over.get ?? (async () => gateCard())),
    postJson: vi.fn(over.post ?? (async () => ({ outcome: "answered" }))),
  };
}
const settle = () =>
  act(async () => {
    await Promise.resolve();
  });
const must = <T,>(v: T | null | undefined): T => {
  if (v === null || v === undefined) throw new Error("missing");
  return v;
};
const byText = (root: ParentNode, sel: string, t: string) =>
  must(qa<HTMLElement>(root, sel).find((e) => (e.textContent ?? "").trim() === t));

describe("FR_HIL_12 the share address and the gate view", () => {
  it("FR_HIL_12 tokenOf reads /share/<token> only, decoded, and nothing else", () => {
    expect(tokenOf(`/share/${encodeURIComponent(TOKEN)}`)).toBe(TOKEN);
    expect(tokenOf("/share/abc/")).toBe("abc");
    for (const p of ["/share", "/share/", "/share/a/b", "/shared/abc", "/", "/share/%E0%A4%A"])
      expect(tokenOf(p), p).toBeNull();
  });

  it("FR_HIL_12 a gate card becomes a view of the card's own words; anything else is unreadable", () => {
    const v = gateViewOf(gateCard());
    expect(v?.action).toBe("Email 3 purchase orders");
    expect(v?.recipients).toEqual(["a@example.com", "b@example.com"]);
    expect(v?.options.map((o) => o.id)).toEqual(["approve", "hold"]);
    for (const bad of [
      null,
      {},
      { card: null },
      gateCard({ kind: "needs_you" }),
      gateCard({ gate: null }),
      gateCard({ options: [{ id: "a", label: "A" }] }),
      gateCard({ what_happened: "" }),
    ])
      expect(gateViewOf(bad), JSON.stringify(bad)).toBeNull();
  });

  it("FR_HIL_12 refusals: 401 sign in; 404/410/403/400 one unavailable line; 409 paused; 5xx or network try again", () => {
    expect(refusalOf(apiError(401))).toBe("sign_in");
    for (const s of [400, 403, 404, 410])
      expect(refusalOf(apiError(s)), String(s)).toBe("unavailable");
    expect(refusalOf(apiError(409))).toBe("paused");
    expect(refusalOf(apiError(503, true))).toBe("try_again");
    expect(refusalOf(apiError(null, true))).toBe("try_again");
    expect(refusalOf(new Error("boom"))).toBe("try_again");
  });
});

describe("FR_HIL_12 the calls", () => {
  it("FR_HIL_12 openShare is one GET of /share/<encoded token>; answerShare is one POST of the option alone", async () => {
    const h = http();
    expect(await openShare(h, TOKEN)).toHaveProperty("view");
    expect(h.getJson).toHaveBeenCalledTimes(1);
    expect(h.getJson).toHaveBeenCalledWith(`/share/${encodeURIComponent(TOKEN)}`);
    expect(await answerShare(h, TOKEN, "approve")).toBe("answered");
    expect(h.postJson).toHaveBeenCalledTimes(1);
    expect(h.postJson).toHaveBeenCalledWith(`/share/${encodeURIComponent(TOKEN)}/answer`, {
      option: "approve",
    });
  });

  it("FR_HIL_12 a failed answer is not retried, and an unexpected 200 body is not shown as answered", async () => {
    const failing = http({ post: async () => Promise.reject(apiError(503, true)) });
    expect(await answerShare(failing, TOKEN, "approve")).toBe("try_again");
    expect(failing.postJson).toHaveBeenCalledTimes(1);
    const odd = http({ post: async () => ({ outcome: "rejected" }) });
    expect(await answerShare(odd, TOKEN, "approve")).toBe("unreadable");
  });
});

describe("FR_HIL_12 the page", () => {
  it("FR_HIL_12 shows the gate, pre-selects nothing, and sends one answer after a deliberate choice", async () => {
    const h = http();
    const m = mount(<SharePage http={h} token={TOKEN} />);
    await settle();
    const root = m.container;
    expect(q(root, '[data-testid="share-action"]').textContent).toBe("Email 3 purchase orders");
    expect(root.textContent).toContain("a@example.com, b@example.com");
    expect(root.textContent).toContain("This cannot be undone.");
    const radios = qa<HTMLInputElement>(root, 'input[type="radio"]');
    expect(radios).toHaveLength(2);
    expect(radios.some((r) => r.checked)).toBe(false); // not even the suggested option
    const send = byText(root, "button", "Choose an option") as HTMLButtonElement;
    expect(send.disabled).toBe(true);
    click(must(radios[0]));
    await settle();
    const go = byText(root, "button", "Approve");
    click(go);
    click(go); // a second tap while sending sends nothing more
    await settle();
    expect(h.postJson).toHaveBeenCalledTimes(1);
    expect(q(root, '[data-testid="share-answered"]').textContent).toContain("recorded");
    expect(root.querySelector('input[type="radio"]')).toBeNull();
  });

  it("FR_HIL_12 the token appears in no text, title, link or attribute of the page", async () => {
    const m = mount(<SharePage http={http()} token={TOKEN} />);
    await settle();
    const html = m.container.innerHTML;
    expect(html).not.toContain(TOKEN);
    expect(html).not.toContain(encodeURIComponent(TOKEN));
    expect(document.title).not.toContain(TOKEN);
    expect(qa(m.container, "a")).toHaveLength(0);
  });

  it("FR_HIL_12 each refusal is one honest line; an unavailable link shows no card and never says why", async () => {
    for (const [status, line] of [
      [401, "Sign in with the account this link was shared with"],
      [404, "This link is not available."],
      [410, "This link is not available."],
      [403, "This link is not available."],
    ] as const) {
      const m = mount(
        <SharePage http={http({ get: async () => Promise.reject(apiError(status)) })} token="t" />,
      );
      await settle();
      expect(q(m.container, '[data-testid="share-refused"]').textContent, String(status)).toContain(
        line,
      );
      expect(m.container.querySelector("section")).toBeNull();
      cleanup();
    }
  });

  it("FR_HIL_12 a link answered elsewhere between open and send ends in the unavailable line with no card", async () => {
    const h = http({ post: async () => Promise.reject(apiError(410)) });
    const m = mount(<SharePage http={h} token="t" />);
    await settle();
    click(must(m.container.querySelector<HTMLInputElement>('input[type="radio"]')));
    await settle();
    click(byText(m.container, "button", "Approve"));
    await settle();
    expect(q(m.container, '[data-testid="share-refused"]').textContent).toBe(
      "This link is not available.",
    );
    expect(m.container.querySelector("section")).toBeNull();
  });

  it("FR_HIL_12 a failure the person can try again keeps the card and sends nothing by itself", async () => {
    const h = http({ post: async () => Promise.reject(apiError(503, true)) });
    const m = mount(<SharePage http={h} token="t" />);
    await settle();
    click(must(m.container.querySelector<HTMLInputElement>('input[type="radio"]')));
    await settle();
    click(byText(m.container, "button", "Approve"));
    await settle();
    expect(q(m.container, '[data-testid="share-refused"]').textContent).toContain(
      "Nothing was changed",
    );
    expect(m.container.querySelector("section")).not.toBeNull();
    await settle();
    expect(h.postJson).toHaveBeenCalledTimes(1);
  });

  it("FR_HIL_12 with no API behind the client (the fixture client) the page says the link is not available and fetches nothing", async () => {
    const spy = vi.fn();
    vi.stubGlobal("fetch", spy);
    const m = mount(<SharePage token="t" />);
    await settle();
    expect(q(m.container, '[data-testid="share-refused"]').textContent).toBe(
      "This link is not available.",
    );
    expect(spy).not.toHaveBeenCalled();
    vi.unstubAllGlobals();
  });
});
