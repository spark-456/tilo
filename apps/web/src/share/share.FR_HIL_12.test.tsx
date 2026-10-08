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

const TOKEN = "Ab_1-".repeat(9); // 45 characters of the right shape; made here, not a real secret
const OTHER = "Zy_9-".repeat(9);
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
  it("FR_HIL_12 tokenOf reads /share/<token> only, and only a token-shaped one; '.' and '..' never become a path", () => {
    expect(tokenOf(`/share/${TOKEN}`)).toBe(TOKEN);
    expect(tokenOf(`/share/${TOKEN}/`)).toBe(TOKEN);
    for (const p of [
      "/share",
      "/share/",
      `/share/${TOKEN}/b`,
      `/shared/${TOKEN}`,
      "/",
      "/share/.",
      "/share/..",
      "/share/abc",
      "/share/%E0%A4%A",
      `/share/${encodeURIComponent("a b".repeat(10))}`,
    ])
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

  it("FR_HIL_12 refusals: 401 sign in; 404/410/403/400 one unavailable line; 409 busy; 5xx or network try again", () => {
    expect(refusalOf(apiError(401))).toBe("sign_in");
    for (const s of [400, 403, 404, 410])
      expect(refusalOf(apiError(s)), String(s)).toBe("unavailable");
    expect(refusalOf(apiError(409))).toBe("busy");
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
    expect(await answerShare(failing, TOKEN, "approve")).toBe("unconfirmed");
    expect(failing.postJson).toHaveBeenCalledTimes(1);
    const odd = http({ post: async () => ({ outcome: "rejected" }) });
    expect(await answerShare(odd, TOKEN, "approve")).toBe("unconfirmed");
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
    expect(root.textContent).toContain("Once done, it can't be undone.");
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
    expect(q(root, '[data-testid="share-answered"]').textContent).toContain(
      "approval was recorded",
    );
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
        <SharePage
          http={http({ get: async () => Promise.reject(apiError(status)) })}
          token={TOKEN}
        />,
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
    const m = mount(<SharePage http={h} token={TOKEN} />);
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
    const m = mount(<SharePage http={h} token={TOKEN} />);
    await settle();
    click(must(m.container.querySelector<HTMLInputElement>('input[type="radio"]')));
    await settle();
    click(byText(m.container, "button", "Approve"));
    await settle();
    expect(q(m.container, '[data-testid="share-refused"]').textContent).toContain(
      "Check before trying again",
    );
    expect(m.container.querySelector("section")).not.toBeNull();
    await settle();
    expect(h.postJson).toHaveBeenCalledTimes(1);
  });

  it("FR_HIL_12 with no API behind the client (the fixture client) the page says the link is not available and fetches nothing", async () => {
    const spy = vi.fn();
    vi.stubGlobal("fetch", spy);
    const m = mount(<SharePage token={TOKEN} />);
    await settle();
    expect(q(m.container, '[data-testid="share-refused"]').textContent).toBe(
      "This link is not available.",
    );
    expect(spy).not.toHaveBeenCalled();
    vi.unstubAllGlobals();
  });
});

describe("FR_HIL_12 review fixes (security round 1)", () => {
  it("FR_HIL_12 a new token is a new page: the old card and choice go, nothing is checked, nothing is posted to the new token", async () => {
    const h = http({
      get: async () => gateCard(),
    });
    const m = mount(<SharePage http={h} token={TOKEN} />);
    await settle();
    click(must(m.container.querySelector<HTMLInputElement>('input[type="radio"]')));
    await settle();
    expect(qa<HTMLInputElement>(m.container, 'input[type="radio"]').some((r) => r.checked)).toBe(
      true,
    );
    m.render(<SharePage http={h} token={OTHER} />);
    await settle();
    expect(h.getJson).toHaveBeenLastCalledWith(`/share/${OTHER}`);
    expect(qa<HTMLInputElement>(m.container, 'input[type="radio"]').some((r) => r.checked)).toBe(
      false,
    );
    expect((byText(m.container, "button", "Choose an option") as HTMLButtonElement).disabled).toBe(
      true,
    );
    expect(h.postJson).not.toHaveBeenCalled();
  });

  it("FR_HIL_12 while the new token's card is loading the old card is not on screen", async () => {
    let release: (v: unknown) => void = () => undefined;
    const h = http();
    const m = mount(<SharePage http={h} token={TOKEN} />);
    await settle();
    h.getJson.mockImplementationOnce(
      () =>
        new Promise((r) => {
          release = r;
        }),
    );
    m.render(<SharePage http={h} token={OTHER} />);
    await settle();
    expect(m.container.querySelector("section")).toBeNull();
    release(gateCard());
    await settle();
    expect(m.container.querySelector("section")).not.toBeNull();
  });

  it("FR_HIL_12 an answer that may have been written is never reported as unchanged (null status, 500, 503, odd 200)", async () => {
    for (const failure of [apiError(null, true), apiError(500, true), apiError(503, true)]) {
      const h = http({ post: async () => Promise.reject(failure) });
      const m = mount(<SharePage http={h} token={TOKEN} />);
      await settle();
      click(must(m.container.querySelector<HTMLInputElement>('input[type="radio"]')));
      await settle();
      click(byText(m.container, "button", "Approve"));
      await settle();
      const line = q(m.container, '[data-testid="share-refused"]').textContent ?? "";
      expect(line, String(failure.status)).toContain("Check before trying again");
      expect(line).not.toContain("Nothing was changed");
      cleanup();
    }
    const odd = http({ post: async () => ({ outcome: "rejected" }) });
    const m = mount(<SharePage http={odd} token={TOKEN} />);
    await settle();
    click(must(m.container.querySelector<HTMLInputElement>('input[type="radio"]')));
    await settle();
    click(byText(m.container, "button", "Approve"));
    await settle();
    const line = q(m.container, '[data-testid="share-refused"]').textContent ?? "";
    expect(line).toContain("Check before trying again");
    expect(line).not.toContain("Nothing was changed");
  });

  it("FR_HIL_12 Hold says what happened (nothing was sent) and is not shown as a recorded approval", async () => {
    const h = http();
    const m = mount(<SharePage http={h} token={TOKEN} />);
    await settle();
    click(must(qa<HTMLInputElement>(m.container, 'input[type="radio"]')[1]));
    await settle();
    click(byText(m.container, "button", "Hold"));
    await settle();
    const said = q(m.container, '[data-testid="share-answered"]').textContent ?? "";
    expect(said).toContain("Nothing was sent");
    expect(said).not.toContain("recorded");
  });

  it("FR_HIL_12 the facts match the gate sheet: tier, what it holds, and 'No one' with no recipients", async () => {
    const card = gateCard();
    (card.card.gate as Record<string, unknown>).recipients = [];
    ((card.card.gate as Record<string, unknown>).action as Record<string, unknown>).item = {
      artifact_id: "art_x",
      version: 2,
      label: "Order sheet",
    };
    const m = mount(<SharePage http={http({ get: async () => card })} token={TOKEN} />);
    await settle();
    const facts = q(m.container, '[data-testid="share-facts"]').textContent ?? "";
    expect(facts).toContain("No one: nothing leaves your own Drive.");
    expect(facts).toContain("Order sheet (version 2)");
    expect(facts).toContain("T3: a person always decides this.");
  });

  it("FR_HIL_12 a token that is not token-shaped (the prop too) makes no request at all", async () => {
    for (const bad of [".", "..", "a/b", "short", "x".repeat(200)]) {
      const h = http();
      const m = mount(<SharePage http={h} token={bad} />);
      await settle();
      expect(h.getJson, bad).not.toHaveBeenCalled();
      expect(q(m.container, '[data-testid="share-refused"]').textContent).toBe(
        "This link is not available.",
      );
      cleanup();
    }
  });
});
