// @vitest-environment happy-dom
// ADR35_L6c / FR_CON_02: the field form of a needs-you card that asks for fields, and "Show me" of a live item document.
import type { Card } from "@tilo/contracts";
import { act } from "react";
import { type Root, createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import { type FieldSpec, type FieldsApi, fieldProblem, fieldSpecsOf } from "../api/fields";
import { TiloApiError } from "../api/http";
import { CardView } from "./CardView";
import { FieldsForm } from "./FieldsForm";
import { ItemDocumentView } from "./ItemDocumentView";
import { decodeItemDocument } from "./itemDocument";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root | null = null;
afterEach(() => {
  act(() => root?.unmount());
  document.body.replaceChildren();
});

async function draw(node: React.ReactElement): Promise<HTMLElement> {
  act(() => root?.unmount());
  document.body.replaceChildren();
  const container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  await act(async () => root?.render(node));
  return container;
}

const SPECS: FieldSpec[] = [
  {
    name: "recipient",
    label: "Send to",
    hint: "Plain addresses, commas between.",
    maxLength: 1000,
  },
  { name: "subject", label: "Subject", hint: "A short line.", maxLength: 20 },
];
const make = (over: Partial<FieldsApi> = {}): FieldsApi & { supplied: unknown[] } => {
  const supplied: unknown[] = [];
  return {
    supplied,
    getCardFields: async () => SPECS,
    supplyCardFields: async (_id, values) => {
      supplied.push(values);
    },
    ...over,
  };
};
async function type(c: HTMLElement, name: string, value: string) {
  const input = c.querySelector<HTMLInputElement>(`input[name="${name}"]`);
  if (!input) throw new Error(`no ${name} input`);
  await act(async () => {
    const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
    set?.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
}
const submit = (c: HTMLElement) =>
  act(async () => {
    c.querySelector("form")?.dispatchEvent(
      new Event("submit", { bubbles: true, cancelable: true }),
    );
  });
const alerts = (c: HTMLElement) =>
  [...c.querySelectorAll('[role="alert"]')].map((a) => a.textContent);

describe("ADR35_L6c FR_CON_02 the fields form", () => {
  it("renders one labelled input per asked field with its hint, and names the form", async () => {
    const c = await draw(<FieldsForm api={make()} cardId="c1" />);
    expect(c.querySelector("form")?.getAttribute("aria-label")).toBe("What to add");
    for (const s of SPECS) {
      const input = c.querySelector<HTMLInputElement>(`input[name="${s.name}"]`);
      expect(input?.required).toBe(true);
      expect(input?.labels?.[0]?.textContent).toBe(s.label);
      const hint = document.getElementById(
        `${input?.getAttribute("aria-describedby")?.split(" ")[0]}`,
      );
      expect(hint?.textContent).toBe(s.hint);
    }
    expect(c.querySelector("button.primary")?.textContent).toBe("Add it");
  });

  it("checks before sending: blank and a bad address are announced and the first is focused", async () => {
    const api = make();
    const c = await draw(<FieldsForm api={api} cardId="c1" />);
    await submit(c);
    expect(alerts(c)).toEqual(["Send to is needed.", "Subject is needed."]);
    expect(c.querySelector('input[name="recipient"]')?.getAttribute("aria-invalid")).toBe("true");
    await type(c, "recipient", "Bob <bob@example.org>");
    await type(c, "subject", "ok");
    await submit(c);
    expect(alerts(c)).toEqual([
      "Use plain email addresses like name@example.org, separated by commas.",
    ]);
    expect(api.supplied).toEqual([]);
  });

  it("posts the typed values once and says what happens next; the inputs lock", async () => {
    const api = make();
    const c = await draw(<FieldsForm api={api} cardId="c1" />);
    await type(c, "recipient", " a@example.org, b@example.org ");
    await type(c, "subject", "Q3 note");
    await submit(c);
    expect(api.supplied).toEqual([
      { recipient: "a@example.org, b@example.org", subject: "Q3 note" },
    ]);
    expect(c.querySelector("output")?.textContent).toContain("Waiting for the item to come back");
    expect(c.querySelector<HTMLButtonElement>("button.primary")?.disabled).toBe(true);
    expect(c.querySelector<HTMLInputElement>('input[name="subject"]')?.disabled).toBe(true);
  });

  it("is disabled while sending and shows the API's plain 422 reason, then lets the person fix and resend", async () => {
    let settle: (e?: unknown) => void = () => {};
    const calls: unknown[] = [];
    const api = make({
      supplyCardFields: (_id, values) => {
        calls.push(values);
        return new Promise<void>((resolve, reject) => {
          settle = (e) => (e ? reject(e) : resolve());
        });
      },
    });
    const c = await draw(<FieldsForm api={api} cardId="c1" />);
    await type(c, "recipient", "a@example.org");
    await type(c, "subject", "Hi");
    await submit(c);
    expect(c.querySelector("button.primary")?.getAttribute("aria-busy")).toBe("true");
    expect(c.querySelector<HTMLButtonElement>("button.primary")?.disabled).toBe(true);
    await submit(c); // a second submit while sending is ignored
    expect(calls).toHaveLength(1);
    await act(async () =>
      settle(
        new TiloApiError("the subject has line breaks or hidden characters", 422, false, true),
      ),
    );
    expect(alerts(c)).toEqual([
      "Could not add that: the subject has line breaks or hidden characters. Nothing was changed. You can try again.",
    ]);
    expect(c.querySelector<HTMLButtonElement>("button.primary")?.disabled).toBe(false);
    expect(c.querySelector<HTMLInputElement>('input[name="subject"]')?.value).toBe("Hi"); // kept to fix
  });

  it("shows a load failure with a retry, and Hold is offered only when the card has it", async () => {
    let n = 0;
    const api = make({
      getCardFields: async () => {
        n += 1;
        if (n === 1) throw new TiloApiError("Tilo could not be reached.", null, true);
        return SPECS;
      },
    });
    const hold = vi.fn();
    const c = await draw(<FieldsForm api={api} cardId="c1" onHold={hold} />);
    expect(alerts(c)[0]).toContain("Could not load what to add");
    await act(async () => c.querySelector<HTMLButtonElement>("button.secondary")?.click());
    expect(c.querySelector("form")).not.toBeNull();
    await act(async () =>
      [...c.querySelectorAll<HTMLButtonElement>("button")]
        .find((b) => b.textContent === "Hold")
        ?.click(),
    );
    expect(hold).toHaveBeenCalledTimes(1);
  });

  it("a card that asks (provide) is drawn as the form, not as a tap on Add it", async () => {
    const card = {
      id: "01".padEnd(26, "0"),
      world_id: "w_a",
      run_id: "r_a",
      kind: "needs_you",
      rung: "needs_you",
      header: { building: "B1", agent: "A_x" },
      what_happened: "Send: needs recipient.",
      why_it_matters: "Nothing is sent.",
      options: [
        { id: "provide", label: "Add it", suggested: true, irreversible: false, reason: "r" },
        { id: "hold", label: "Hold", suggested: false, irreversible: false },
      ],
      add_context: false,
      actions: ["show_me"],
      answer_channels: ["web"],
      created_at: "2026-10-09T09:00:00.000Z",
      timeout: 86400,
      safe_default: "hold",
      gate: null,
      consent: null,
    } as unknown as Card;
    const c = await draw(<CardView card={card} layout={null} answer={null} fields={make()} />);
    expect(c.querySelector("form")).not.toBeNull();
    expect(c.querySelector('[role="radiogroup"]')).toBeNull();
    const plain = await draw(<CardView card={card} layout={null} answer={null} />);
    expect(plain.querySelector("form")).toBeNull(); // no fields API (fixtures): the ordinary card
  });

  it("reads a reply only in the documented shape", () => {
    expect(
      fieldSpecsOf({ fields: [{ name: "subject", label: "Subject", hint: "h", max_length: 150 }] }),
    ).toEqual([{ name: "subject", label: "Subject", hint: "h", maxLength: 150 }]);
    for (const bad of [
      null,
      {},
      { fields: [] },
      { fields: [{ name: "Bad Name" }] },
      { fields: "x" },
    ]) {
      expect(fieldSpecsOf(bad)).toBeNull();
    }
    expect(fieldProblem(SPECS[1] as FieldSpec, "a\r\nb")).toContain("one line");
  });
});

const b64 = (s: string | Uint8Array) => btoa(typeof s === "string" ? s : String.fromCharCode(...s));

describe("ADR35_L6c FR_CON_02 show me of an item document", () => {
  it("shows an email's subject, recipients and body", async () => {
    const raw = JSON.stringify({ kind: "email", subject: "Q3 note", body_text: "Hello\nthere" });
    const c = await draw(
      <ItemDocumentView document={raw} recipients={["a@example.org", "b@example.org"]} />,
    );
    expect(c.textContent).toContain("Q3 note");
    expect(c.textContent).toContain("a@example.org, b@example.org");
    expect(c.querySelector("pre")?.textContent).toBe("Hello\nthere");
  });

  it("decodes a text file's base64 and shows its name, type and text", async () => {
    const raw = JSON.stringify({
      kind: "file",
      name: "n.txt",
      mime_type: "text/plain",
      content_b64: b64("line one\nline two"),
    });
    const c = await draw(<ItemDocumentView document={raw} />);
    expect(c.textContent).toContain("n.txt");
    expect(c.textContent).toContain("text/plain");
    expect(c.querySelector("pre")?.textContent).toBe("line one\nline two");
  });

  it("says 'binary file, N bytes' for a binary file and shows no content", async () => {
    const bytes = new Uint8Array([0x89, 0x50, 0x4e, 0x47, 0, 1, 2, 255]);
    const raw = JSON.stringify({
      kind: "file",
      name: "p.png",
      mime_type: "image/png",
      content_b64: b64(bytes),
    });
    const c = await draw(<ItemDocumentView document={raw} />);
    expect(c.textContent).toContain("binary file, 8 bytes");
    expect(c.textContent).toContain("p.png");
    expect(c.querySelector("pre")).toBeNull();
    const notUtf8 = JSON.stringify({
      kind: "file",
      name: "x.txt",
      mime_type: "text/plain",
      content_b64: b64(new Uint8Array([0xff, 0xfe, 0x41])),
    });
    expect(decodeItemDocument(notUtf8)).toMatchObject({ kind: "file", text: null, bytes: 3 });
  });

  it("renders an injection attempt as text: no element, attribute or script is made from a document", async () => {
    const evil = '<img src=x onerror="window.__pwned=1"><script>window.__pwned=1</script>';
    const file = JSON.stringify({
      kind: "file",
      name: evil,
      mime_type: "text/html",
      content_b64: b64(evil),
    });
    const mail = JSON.stringify({ kind: "email", subject: evil, body_text: evil });
    for (const doc of [file, mail]) {
      const c = await draw(<ItemDocumentView document={doc} recipients={[evil]} />);
      expect(c.querySelector("img, script, a, iframe")).toBeNull();
      expect(c.textContent).toContain(evil);
      expect((window as unknown as { __pwned?: number }).__pwned).toBeUndefined();
    }
  });

  it("shows an event's title, times and zone, and says plainly when a document cannot be read", async () => {
    const event = JSON.stringify({
      kind: "calendar_event",
      title: "Review",
      start: "2026-10-12T09:00:00Z",
      end: "2026-10-12T09:30:00Z",
      time_zone: "Asia/Kolkata",
    });
    const c = await draw(<ItemDocumentView document={event} />);
    for (const t of ["Review", "2026-10-12T09:00:00Z", "2026-10-12T09:30:00Z", "Asia/Kolkata"]) {
      expect(c.textContent).toContain(t);
    }
    const bad = [
      "not json",
      "[]",
      '{"kind":"nope"}',
      '{"kind":"file","name":"a","mime_type":"text/plain","content_b64":"@@@"}',
      '{"kind":"email","subject":1}',
    ];
    for (const raw of bad) expect(decodeItemDocument(raw)).toEqual({ kind: "unreadable" });
    const shown = await draw(<ItemDocumentView document="not json" />);
    expect(shown.textContent).toContain("cannot be shown here");
  });
});
