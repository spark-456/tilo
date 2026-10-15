// @vitest-environment happy-dom
// LANDING-2: the signed-out landing as a complete product page. Every section has its heading, the nav points at real
// sections, "Continue with Google" stays the one filled button, what is not switched on says so ("Coming", "Rolling
// out"), nothing is claimed that Tilo does not do, the scroll reveal marks sections only when motion is welcome and
// the browser can tell what is in view, and the stylesheet brings no colour of its own.
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { act } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, mount, q, qa } from "../../test-support/park/componentsHarness";
import { SignInScreen } from "../auth/SignInScreen";
import { Reveal } from "./Reveal";

const media = (reduce: boolean) => (query: string) =>
  ({
    matches: reduce && query.includes("prefers-reduced-motion"),
    media: query,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
  }) as unknown as MediaQueryList;

type Callback = (entries: Partial<IntersectionObserverEntry>[]) => void;
const watchers: { el: Element; fire: Callback }[] = [];
class FakeObserver {
  constructor(private readonly cb: Callback) {}
  observe(el: Element) {
    watchers.push({ el, fire: this.cb });
  }
  disconnect() {}
  unobserve() {}
}

let restore: (() => void)[] = [];
const prefer = (reduce: boolean) => {
  const before = window.matchMedia;
  window.matchMedia = media(reduce);
  restore.push(() => {
    window.matchMedia = before;
  });
};
const withObserver = () => {
  vi.stubGlobal("IntersectionObserver", FakeObserver);
  restore.push(() => vi.unstubAllGlobals());
};

beforeEach(() => {
  watchers.length = 0;
  prefer(false);
});
afterEach(() => {
  cleanup();
  for (const r of restore) r();
  restore = [];
});

const settle = async () => {
  await act(async () => {
    await vi.dynamicImportSettled();
  });
  await act(async () => undefined);
};
const landing = () =>
  mount(
    <SignInScreen
      busy={false}
      failed={false}
      failedText="Failed."
      onGoogle={() => undefined}
      onDemo={() => undefined}
    />,
  );
const text = () => document.body.textContent ?? "";

const HEADINGS = [
  "Four steps. No jargon, no surprises.",
  "A quick answer, or a whole world.",
  "Nothing leaves without your yes.",
  "Skills that grow with you.",
  "A notetaker that tells people it’s there.",
  "Run it with your team.",
  "Signed in and working in one step.",
  "Everything in play, at a glance.",
  "Your tools, on your terms.",
  "Built for companies. Just as handy for one person.",
  "Agents you can actually watch, and trust.",
  "Your little city is waiting.",
];

describe("LANDING_2 the landing is a complete product page", () => {
  it("LANDING_2 every section heading renders: one h1, then an h2 per section, in order", async () => {
    landing();
    await settle();
    expect(qa(document.body, "h1")).toHaveLength(1);
    const h2 = qa(document.body, "h2").map((h) => h.textContent);
    expect(h2).toEqual(HEADINGS);
  });

  it("LANDING_2 each section is labelled by its own heading and every heading is real text", async () => {
    landing();
    await settle();
    const sections = qa<HTMLElement>(document.body, "main section");
    expect(sections).toHaveLength(HEADINGS.length);
    for (const s of sections) {
      const id = s.getAttribute("aria-labelledby");
      expect(id, "section without aria-labelledby").toBeTruthy();
      const h = document.getElementById(id as string);
      expect(h?.tagName).toBe("H2");
      expect(h?.textContent?.length).toBeGreaterThan(10);
    }
  });

  it("LANDING_2 the header links go to sections that exist", async () => {
    landing();
    await settle();
    const links = qa<HTMLAnchorElement>(q(document.body, "header nav"), "a");
    expect(links.map((a) => a.getAttribute("href"))).toEqual([
      "#how",
      "#skills",
      "#meetings",
      "#teams",
      "#connectors",
      "#why",
    ]);
    for (const a of links) {
      const id = (a.getAttribute("href") ?? "").slice(1);
      expect(document.getElementById(id), `#${id}`).not.toBeNull();
    }
  });

  it("LANDING_2 Continue with Google is still the one filled button, and the page has no field or form", async () => {
    landing();
    await settle();
    const named = qa<HTMLButtonElement>(document.body, "button").filter(
      (b) => (b.textContent ?? "").trim() === "Continue with Google",
    );
    expect(named).toHaveLength(1);
    expect(qa(document.body, ".landing-btn--primary")).toHaveLength(1);
    expect(qa(document.body, "input, textarea, form")).toHaveLength(0);
  });

  it("LANDING_2 the hero says what Tilo is: describe, a Director plans, teams run it, watch, approve", () => {
    landing();
    const lead = q(document.body, ".landing-hero__lead")?.textContent ?? "";
    for (const word of ["Plain words in", "Director", "teams", "watch", "approve"])
      expect(lead).toContain(word);
  });
});

describe("LANDING_2 what it says is true, and what is not live says so", () => {
  it("LANDING_2 the pillars are all there: skills, notetaker, teams, onboarding, pins, connectors, both audiences", async () => {
    landing();
    await settle();
    for (const part of [
      "Teach it",
      "Skills learn from real runs",
      "disclosed notetaker",
      "Create a team and invite people by email",
      "Who can say yes",
      "One step to start",
      "A short first-run tour",
      "A sample project",
      "Pinboards in the Agenda",
      "Your context",
      "ENTERPRISE AND TEAMS",
      "PERSONAL PRODUCTIVITY",
      "Built on Google Cloud",
    ])
      expect(text(), part).toContain(part);
  });

  it("LANDING_2 not-yet-live things carry a Coming or Rolling out chip", async () => {
    landing();
    await settle();
    const li = (name: string) =>
      qa<HTMLElement>(document.body, ".landing-app").find((e) => e.textContent?.startsWith(name));
    expect(li("Canva")?.textContent).toContain("Coming");
    expect(li("Slack")?.textContent).toContain("Coming");
    expect(li("Meeting host")?.textContent).toContain("Rolling out");
    expect(li("Gmail")?.textContent).toContain("Google sign-in");
    expect(li("Lovable")?.textContent).toContain("Brief hand-off");
    expect(q(document.body, "#meetings")?.textContent).toContain("Rolling out");
    expect(q(document.body, "#skills")?.textContent).toContain("Coming");
  });

  it("LANDING_2 meeting claims keep a person in the loop: approve the host card, confirm minutes, approve the follow-up", async () => {
    landing();
    await settle();
    const m = q(document.body, "#meetings")?.textContent ?? "";
    expect(m).toContain("You approve a card");
    expect(m).toContain("never lets anyone in on its own");
    expect(m).toContain("You read them and confirm");
    expect(m).toContain("nothing is sent until you approve");
    expect(m).toContain("Example, not a real meeting");
  });

  it("LANDING_2 connectors: Tilo never sees passwords; levels are the app's own; no WhatsApp or invented numbers", async () => {
    landing();
    await settle();
    const c = q(document.body, "#connectors")?.textContent ?? "";
    expect(c).toContain("never sees or stores your passwords");
    expect(c).toContain("Off, Read, Draft or Act");
    expect(text()).not.toMatch(/whatsapp/i);
    expect(text()).not.toMatch(/\d+\s?(%|x faster|hours saved)/i);
  });

  it("LANDING_2 the footer still links Privacy and Terms", async () => {
    landing();
    await settle();
    const nav = q(document.body, 'footer nav[aria-label="Legal"]');
    expect(qa<HTMLAnchorElement>(nav, "a").map((a) => a.getAttribute("href"))).toEqual([
      "/privacy",
      "/terms",
    ]);
  });
});

describe("LANDING_2 the scroll reveal", () => {
  it("LANDING_2 with motion welcome sections are marked, and marked in once they scroll into view", async () => {
    withObserver();
    landing();
    await settle();
    const marked = qa<HTMLElement>(document.body, ".landing-reveal");
    expect(marked.length).toBeGreaterThan(20);
    expect(qa(document.body, ".landing-reveal.is-in")).toHaveLength(0);
    const first = watchers.find((w) => w.el.id === "how");
    expect(first).toBeDefined();
    act(() => first?.fire([{ isIntersecting: true, boundingClientRect: { top: 400 } as DOMRect }]));
    expect(document.getElementById("how")?.classList.contains("is-in")).toBe(true);
    expect(document.getElementById("teams")?.classList.contains("is-in")).toBe(false);
  });

  it("LANDING_2 a section already scrolled past (an anchor jump) is shown, not left hidden", async () => {
    withObserver();
    landing();
    await settle();
    const w = watchers.find((x) => x.el.id === "why");
    act(() =>
      w?.fire([
        { isIntersecting: false, boundingClientRect: { top: -900 } as DOMRect, rootBounds: null },
      ]),
    );
    expect(document.getElementById("why")?.classList.contains("is-in")).toBe(true);
  });

  it("LANDING_2 with reduced motion no reveal class is put on the page at all", async () => {
    prefer(true);
    withObserver();
    landing();
    await settle();
    expect(qa(document.body, ".landing-reveal, .is-in")).toHaveLength(0);
    expect(watchers).toHaveLength(0);
    expect(document.getElementById("how")).not.toBeNull(); // the content is simply there
  });

  it("LANDING_2 a browser with no IntersectionObserver gets the plain page, nothing hidden", async () => {
    vi.stubGlobal("IntersectionObserver", undefined);
    restore.push(() => vi.unstubAllGlobals());
    landing();
    await settle();
    expect(qa(document.body, ".landing-reveal")).toHaveLength(0);
  });

  it("LANDING_2 Reveal passes its attributes through and numbers its place for the stagger", () => {
    withObserver();
    mount(
      <Reveal as="li" index={3} id="x" className="a" aria-label="L">
        t
      </Reveal>,
    );
    const el = document.getElementById("x") as HTMLElement;
    expect(el.tagName).toBe("LI");
    expect(el.className).toBe("a landing-reveal");
    expect(el.style.getPropertyValue("--i")).toBe("3");
    expect(el.getAttribute("aria-label")).toBe("L");
  });
});

describe("LANDING_2 the stylesheet", () => {
  const css = readFileSync(join(__dirname, "landing.sections.css"), "utf8");
  it("LANDING_2 brings no colour of its own and no motion (HR-1: motion has its own reviewed file)", () => {
    const code = css.replace(/\/\*[\s\S]*?\*\//g, "");
    expect(code).not.toMatch(/#[0-9a-fA-F]{3,8}\b/);
    expect(code).not.toMatch(/\brgba?\(|\bhsla?\(/);
    expect(code).not.toMatch(/@keyframes|animation|transition/);
  });
});
