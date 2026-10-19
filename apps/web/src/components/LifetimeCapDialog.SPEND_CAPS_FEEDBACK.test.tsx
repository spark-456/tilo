// @vitest-environment happy-dom
// SEC-16 lifetime cap, the pop-up (user request, 8 Oct 2026; not in the PRD; services/api/tests/API_SPEND_FEEDBACK.md).
// When a person hits their lifetime cap the app shows a friendly dialog instead of a bare error: they have used their
// beta allowance, new plans and subscriptions come after beta testing ends, and if they liked Tilo they can help with
// honest feedback and critique. It has a feedback box.
//
// The shared component: apps/web/src/components/LifetimeCapDialog.tsx, named export `LifetimeCapDialog`, props
//   submit: (text: string) => Promise<void>   resolves only when the server confirmed (HR-1: nothing is said before)
//   onClose: () => void
// Used by the Park shell and by the kept flow screens, so neither imports the other's tree (like ReplayBanner).
//
// What is pinned: the words (test-support/lifetimeCap.ts COPY); an accessible modal dialog; a textarea of plain text
// capped at 2,000 characters; "Thanks" appears ONLY after `submit` resolves (never while it is pending, never on a
// failure), a failure shows an error and keeps the text, a second tap while sending sends nothing more; closing
// never sends; markup in the text is never interpreted; plain role tokens only (no colour literals).
import { readFileSync, readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { act } from "react";
import { type Root, createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  COPY,
  MAX_FEEDBACK_CHARS,
  areaIn,
  buttonNamed,
  clickButton,
  dialogIn,
  flush,
  gate,
  nameOf,
  pressKey,
  squash,
  typeFeedback,
} from "../../test-support/lifetimeCap";
import { LifetimeCapDialog } from "./LifetimeCapDialog";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLElement;
let root: Root;
beforeEach(() => {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});
afterEach(() => {
  act(() => root.unmount());
  container.remove();
  document.body.innerHTML = "";
});

function show(submit: (text: string) => Promise<void>, onClose: () => void = () => undefined) {
  act(() => root.render(<LifetimeCapDialog submit={submit} onClose={onClose} />));
}
const dialog = () => dialogIn(container) as HTMLElement;
const area = () => areaIn(container) as HTMLTextAreaElement;
const send = () => buttonNamed(container, COPY.send) as HTMLButtonElement;
const said = () => squash(container.textContent);

describe("SEC-16 lifetime cap dialog: what it says", () => {
  it("SEC_16_FEEDBACK a modal dialog named by its title, with the three sentences the user asked for", () => {
    show(async () => undefined);
    const el = dialog();
    expect(el, "role=dialog").not.toBeNull();
    expect(el.getAttribute("aria-modal")).toBe("true");
    expect(nameOf(el)).toBe(COPY.title);
    const text = said();
    expect(text).toContain(COPY.allowance);
    expect(text).toContain(COPY.later);
    expect(text).toContain(COPY.ask);
  });

  it("SEC_16_FEEDBACK it names no amount, no error code and no server text", () => {
    show(async () => undefined);
    const text = said();
    expect(text).not.toMatch(/spend_cap_reached|403|paise|INR|₹|\b3,?000\b|lifetime spending cap/i);
    expect(text).not.toMatch(/error/i);
  });

  it("SEC_16_FEEDBACK a labelled feedback box (a textarea) and a Send button; nothing says Thanks yet", () => {
    show(async () => undefined);
    const box = area();
    expect(box, "a <textarea>").not.toBeNull();
    expect(nameOf(box)).toBe(COPY.label);
    expect(box.value).toBe("");
    expect(box.maxLength).toBe(MAX_FEEDBACK_CHARS);
    expect(send(), "Send feedback").not.toBeNull();
    expect(said()).not.toMatch(/thanks/i);
  });

  it("SEC_16_FEEDBACK it moves focus into the dialog when it opens", () => {
    show(async () => undefined);
    expect(dialog().contains(document.activeElement)).toBe(true);
  });
});

describe("SEC-16 lifetime cap dialog: sending feedback is honest", () => {
  it("SEC_16_FEEDBACK Send is disabled until there is text, and an empty or blank box sends nothing", () => {
    const submit = vi.fn(async () => undefined);
    show(submit);
    expect(send().disabled).toBe(true);
    clickButton(send());
    typeFeedback(area(), "   \n  ");
    expect(send().disabled).toBe(true);
    clickButton(send());
    expect(submit).not.toHaveBeenCalled();
    typeFeedback(area(), "Honest words");
    expect(send().disabled).toBe(false);
  });

  it("SEC_16_FEEDBACK Thanks appears only after the server confirms: not while it waits", async () => {
    const reply = gate<void>();
    const submit = vi.fn(() => reply.promise);
    show(submit);
    typeFeedback(area(), "The plan step was hard to find.");

    clickButton(send());
    await flush();

    expect(submit).toHaveBeenCalledTimes(1);
    expect(submit).toHaveBeenCalledWith("The plan step was hard to find.");
    expect(said(), "no Thanks while the request is in flight").not.toContain(COPY.thanks);
    expect(said()).not.toMatch(/thanks/i);
    const busy = buttonNamed(container, COPY.sending) ?? send();
    expect(busy.disabled || busy.getAttribute("aria-busy") === "true").toBe(true);

    await act(async () => reply.resolve());
    await flush();

    expect(said()).toContain(COPY.thanks);
    expect(container.querySelector('[role="status"]')?.textContent).toContain(COPY.thanks);
    expect(areaIn(container)?.value ?? "").toBe("");
    expect(buttonNamed(container, COPY.send), "nothing left to send").toBeNull();
  });

  it("SEC_16_FEEDBACK a second and third tap while sending send nothing more (double submit guarded)", async () => {
    const reply = gate<void>();
    const submit = vi.fn(() => reply.promise);
    show(submit);
    typeFeedback(area(), "Once only.");
    const button = send();

    clickButton(button);
    clickButton(button);
    clickButton(button);
    await flush();

    expect(submit).toHaveBeenCalledTimes(1);
    await act(async () => reply.resolve());
    await flush();
    expect(submit).toHaveBeenCalledTimes(1);
  });

  it.each([
    [
      "a 4xx the server refused",
      Object.assign(new Error("Your feedback is empty."), { status: 422 }),
    ],
    [
      "a 429 rate limit",
      Object.assign(new Error("slow down"), { status: 429, code: "rate_limited" }),
    ],
    ["a 5xx", Object.assign(new Error("Tilo had a problem on its side."), { status: 503 })],
    ["a network failure", new TypeError("Failed to fetch")],
  ])(
    "SEC_16_FEEDBACK %s: no Thanks, an error is shown, the text is kept and Send works again",
    async (_n, failure) => {
      const submit = vi.fn(async () => {
        throw failure;
      });
      show(submit);
      typeFeedback(area(), "Words I do not want to lose");

      clickButton(send());
      await flush();

      expect(said()).not.toMatch(/thanks/i);
      const alert = container.querySelector('[role="alert"]');
      expect(alert, "an error is announced").not.toBeNull();
      expect(squash(alert?.textContent)).toBe(COPY.failed);
      expect(said(), "the server's own words are not shown").not.toMatch(
        /slow down|empty|problem on its side|Failed to fetch/,
      );
      expect(area().value, "the text is kept").toBe("Words I do not want to lose");
      expect(send().disabled, "the person can try again").toBe(false);
    },
  );

  it("SEC_16_FEEDBACK after a failure a retry the server confirms ends in Thanks, with the same text", async () => {
    const first = gate<void>();
    const second = gate<void>();
    const queue = [first, second];
    const submit = vi.fn(() => (queue.shift() as ReturnType<typeof gate<void>>).promise);
    show(submit);
    typeFeedback(area(), "Try me twice");
    clickButton(send());
    await flush();
    await act(async () => first.reject(new Error("boom")));
    await flush();
    expect(said()).not.toMatch(/thanks/i);

    clickButton(send());
    await flush();
    expect(submit).toHaveBeenCalledTimes(2);
    expect(submit).toHaveBeenLastCalledWith("Try me twice");
    expect(
      container.querySelector('[role="alert"]'),
      "the old error is gone while it retries",
    ).toBeNull();
    expect(said()).not.toMatch(/thanks/i);

    await act(async () => second.resolve());
    await flush();
    expect(said()).toContain(COPY.thanks);
    expect(container.querySelector('[role="alert"]')).toBeNull();
  });
});

describe("SEC-16 lifetime cap dialog: closing and plain text", () => {
  it("SEC_16_FEEDBACK Close and Escape both call onClose and never send", () => {
    const submit = vi.fn(async () => undefined);
    const onClose = vi.fn();
    show(submit, onClose);
    typeFeedback(area(), "unsent words");

    clickButton(buttonNamed(container, COPY.close) as HTMLElement);
    pressKey(dialog(), "Escape");

    expect(onClose).toHaveBeenCalledTimes(2);
    expect(submit).not.toHaveBeenCalled();
  });

  it("SEC_16_FEEDBACK markup typed into the box is plain text: it is sent byte for byte and never becomes elements", async () => {
    const markup = '<img src=x onerror="alert(1)"><script>alert(2)</script><b>bold</b> & "q"';
    const submit = vi.fn(async () => undefined);
    show(submit);

    typeFeedback(area(), markup);
    expect(area().value).toBe(markup);
    expect(
      dialog().querySelector("img, script, b, iframe, svg"),
      "the text is not parsed",
    ).toBeNull();
    clickButton(send());
    await flush();

    expect(submit).toHaveBeenCalledWith(markup);
    expect(container.querySelector("img, script, b, iframe, svg")).toBeNull();
    expect(container.innerHTML).not.toContain("onerror");
  });

  it("SEC_16_FEEDBACK the box holds at most 2,000 characters", () => {
    show(async () => undefined);
    expect(area().maxLength).toBe(MAX_FEEDBACK_CHARS);
  });
});

describe("SEC-16 lifetime cap dialog: plain role tokens, no new brand", () => {
  const dir = join(dirname(fileURLToPath(import.meta.url)));
  const files = () =>
    readdirSync(dir).filter((f) => /^LifetimeCapDialog\.[a-z]+$/.test(f) && !f.includes(".test."));

  it("SEC_16_FEEDBACK the component exists as LifetimeCapDialog.tsx beside ReplayBanner", () => {
    expect(files()).toContain("LifetimeCapDialog.tsx");
  });

  it("SEC_16_FEEDBACK its source has no colour literal, no inline colour and no image", () => {
    for (const file of files()) {
      const source = readFileSync(join(dir, file), "utf8");
      expect(source, file).not.toMatch(/#[0-9a-fA-F]{3,8}\b/); // a #hex colour
      expect(source, file).not.toMatch(/\b(?:rgb|rgba|hsl|hsla)\(/);
      expect(source, file).not.toMatch(/style=\{\{[^}]*(?:color|background)/);
      expect(source, file).not.toMatch(/<img|url\(|\.png|\.svg|\.jpg/);
    }
  });
});
