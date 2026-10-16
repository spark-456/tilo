import type { MemoryItem, MemoryItemKind } from "@tilo/contracts";
import { type FormEvent, useEffect, useState } from "react";
import type { MemoryApi } from "../../api/live/memory";

const KINDS: readonly MemoryItemKind[] = ["preference", "fact", "person"];
const byNewest = (a: MemoryItem, b: MemoryItem) =>
  b.updated_at.localeCompare(a.updated_at) || a.id.localeCompare(b.id);

export function MemoryPanel({ api }: { api: MemoryApi }) {
  const [items, setItems] = useState<MemoryItem[] | null>(null);
  const [loadError, setLoadError] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [editing, setEditing] = useState<string | null>(null);
  const [text, setText] = useState("");
  const [kind, setKind] = useState<MemoryItemKind>("preference");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  // biome-ignore lint/correctness/useExhaustiveDependencies: attempt explicitly retries a failed read.
  useEffect(() => {
    let active = true;
    api.list().then(
      (saved) => {
        if (active) {
          setItems(saved);
          setLoadError(false);
        }
      },
      () => {
        if (active) setLoadError(true);
      },
    );
    return () => {
      active = false;
    };
  }, [api, attempt]);

  const reset = () => {
    setEditing(null);
    setText("");
    setKind("preference");
  };
  const save = async (event: FormEvent) => {
    event.preventDefault();
    const value = text.trim();
    if (!items || busy || !value || value.length > 280 || (editing === null && items.length >= 100))
      return;
    setBusy(true);
    setMessage("");
    try {
      const saved =
        editing === null
          ? await api.create({ text: value, kind, source: "user" })
          : await api.update(editing, { text: value, kind });
      setItems(
        (current) =>
          current && [saved, ...current.filter((row) => row.id !== saved.id)].sort(byNewest),
      );
      reset();
      setMessage("Saved");
    } catch {
      setMessage("This memory could not be saved. Check it and try again.");
    } finally {
      setBusy(false);
    }
  };
  const remove = async (id: string) => {
    if (busy) return;
    setBusy(true);
    setMessage("");
    try {
      await api.remove(id);
      setItems((current) => current?.filter((row) => row.id !== id) ?? null);
      if (editing === id) reset();
      setMessage("Removed");
    } catch {
      setMessage("This memory could not be removed. Try again.");
    } finally {
      setBusy(false);
    }
  };
  return (
    <section aria-label="Tilo remembers" className="park-admin-memory">
      <h2>Tilo remembers</h2>
      <p>These notes are used in your own tasks. A note cannot authorise Tilo to act.</p>
      {items === null && !loadError ? <p>Loading memories…</p> : null}
      {loadError ? (
        <p role="alert">
          Could not load memories.{" "}
          <button type="button" onClick={() => setAttempt((n) => n + 1)}>
            Try again
          </button>
        </p>
      ) : null}
      {items ? (
        <>
          <p>{items.length} of 100 notes</p>
          <ul className="blist">
            {items.map((row) => (
              <li key={row.id}>
                <strong>{row.kind}</strong> <span>{row.text}</span>{" "}
                <button
                  type="button"
                  aria-label="Edit memory"
                  disabled={busy}
                  onClick={() => {
                    setEditing(row.id);
                    setText(row.text);
                    setKind(row.kind);
                    setMessage("");
                  }}
                >
                  Edit
                </button>{" "}
                <button
                  type="button"
                  aria-label="Delete memory"
                  disabled={busy}
                  onClick={() => void remove(row.id)}
                >
                  Delete
                </button>
              </li>
            ))}
          </ul>
          {items.length < 100 || editing !== null ? (
            <form onSubmit={(event) => void save(event)}>
              <label>
                Note
                <input
                  name="memory_text"
                  value={text}
                  maxLength={280}
                  required
                  onChange={(event) => setText(event.target.value)}
                />
              </label>
              <label>
                Kind
                <select
                  value={kind}
                  onChange={(event) => setKind(event.target.value as MemoryItemKind)}
                >
                  {KINDS.map((option) => (
                    <option key={option} value={option}>
                      {option}
                    </option>
                  ))}
                </select>
              </label>
              <button type="submit" disabled={busy || !text.trim()}>
                {editing === null ? "Add note" : "Save note"}
              </button>
              {editing !== null ? (
                <button type="button" onClick={reset}>
                  Cancel
                </button>
              ) : null}
            </form>
          ) : (
            <p>Remove a note before adding another.</p>
          )}
        </>
      ) : null}
      {message ? <output>{message}</output> : null}
    </section>
  );
}
