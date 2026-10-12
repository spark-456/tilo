import { type ReactNode, useRef, useState } from "react";

// I6 local UI seam only. No HTTP transport or KnowledgeItem contract is introduced here.
export type IntakeInput = { kind: "file"; file: File } | { kind: "text"; text: string };
export type IntakeResult = { id: string } & (
  | { state: "understood"; preview: string }
  | { state: "unreadable"; reason: string }
);
export interface IntakeClient {
  read(input: IntakeInput): Promise<IntakeResult>;
  /** Resolves only after the source and its derived data have been deleted. */
  remove(id: string): Promise<void>;
}
type Item = {
  key: number;
  title: string;
  result?: IntakeResult;
  error?: string | undefined;
  removing?: boolean;
};

export function IntakeControl({
  client,
  children,
}: { client?: IntakeClient | undefined; children: ReactNode }) {
  const [items, setItems] = useState<Item[]>([]);
  const [text, setText] = useState("");
  const next = useRef(0);
  const picker = useRef<HTMLInputElement>(null);
  function patch(key: number, update: Partial<Item>) {
    setItems((old) => old.map((item) => (item.key === key ? { ...item, ...update } : item)));
  }
  function add(input: IntakeInput) {
    if (!client) return;
    const key = next.current++;
    setItems((old) => [
      ...old,
      { key, title: input.kind === "file" ? input.file.name : "Pasted text" },
    ]);
    // Deferred invocation also catches a synchronous transport failure.
    void Promise.resolve()
      .then(() => client.read(input))
      .then(
        (result) => patch(key, { result }),
        () => patch(key, { error: "Intake request failed. Try again later." }),
      );
  }
  async function remove(item: Item) {
    if (!client) return;
    patch(item.key, { removing: true, error: undefined });
    try {
      if (item.result) await client.remove(item.result.id);
      setItems((old) => old.filter((other) => other.key !== item.key));
    } catch {
      patch(item.key, { removing: false, error: "Could not remove this item. Try again." });
    }
  }
  return (
    <fieldset
      className="park-home-intake"
      onDragOver={(event) => event.preventDefault()}
      onDrop={(event) => {
        event.preventDefault();
        for (const file of Array.from(event.dataTransfer.files)) add({ kind: "file", file });
      }}
      onPaste={(event) => {
        if (!client || !event.clipboardData.files.length) return;
        event.preventDefault();
        for (const file of Array.from(event.clipboardData.files)) add({ kind: "file", file });
      }}
    >
      <legend className="park-home-intake__label">Task and sources</legend>
      {children}
      <button
        type="button"
        className="park-home-change"
        disabled={!client}
        aria-disabled={!client}
        title={!client ? "File intake is not available yet" : "Choose files to read"}
        onClick={() => picker.current?.click()}
      >
        Add anything
      </button>
      <input
        ref={picker}
        type="file"
        multiple
        hidden
        disabled={!client}
        aria-label="Choose sources"
        onChange={(event) => {
          for (const file of Array.from(event.target.files ?? [])) add({ kind: "file", file });
          event.target.value = "";
        }}
      />
      {!client ? (
        <p>File intake is not available yet. You can still describe your task.</p>
      ) : (
        <>
          <p>Drop files here or paste notes below. Items are not attached to your task yet.</p>
          <textarea
            aria-label="Paste source text"
            value={text}
            onChange={(event) => setText(event.target.value)}
            onPaste={(event) => {
              if (event.clipboardData.files.length) return;
              event.preventDefault();
              const pasted = event.clipboardData.getData("text/plain");
              const start = event.currentTarget.selectionStart;
              const end = event.currentTarget.selectionEnd;
              setText((old) => old.slice(0, start) + pasted + old.slice(end));
            }}
          />
          <button
            type="button"
            className="park-home-change"
            aria-label="Read pasted text"
            disabled={!text.trim()}
            onClick={() => {
              add({ kind: "text", text });
              setText("");
            }}
          >
            Read pasted text
          </button>
        </>
      )}
      <ul aria-live="polite">
        {items.map((item) => (
          <li key={item.key}>
            <strong>{item.title}</strong>{" "}
            <span className="park-home-intake__status">
              {item.result
                ? item.result.state === "understood"
                  ? "Understood"
                  : `Could not read: ${item.result.reason}`
                : item.error
                  ? `Could not read: ${item.error}`
                  : "Reading"}
            </span>
            {item.result?.state === "understood" ? <p>{item.result.preview}</p> : null}
            {item.result && item.error ? <p role="alert">{item.error}</p> : null}
            <button
              type="button"
              className="park-home-change"
              aria-label={`Remove ${item.title}`}
              disabled={item.removing || (!item.result && !item.error)}
              onClick={() => {
                void remove(item);
              }}
            >
              {item.removing ? "Removing" : "Remove"}
            </button>
          </li>
        ))}
      </ul>
    </fieldset>
  );
}
