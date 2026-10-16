import { useRef, useState } from "react";

/** CX-T-AGENDA: menu choices follow the routes this session can actually use. */
export function AgendaNewMenu({
  createPin,
  onPinCreated,
  canHost,
}: {
  createPin: ((title: string, idempotencyKey: string) => Promise<void>) | null;
  onPinCreated: () => void;
  canHost: boolean;
}) {
  const [pinOpen, setPinOpen] = useState(false);
  const [title, setTitle] = useState("");
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");
  const key = useRef<string | null>(null);
  const details = useRef<HTMLDetailsElement>(null);
  const save = async () => {
    const name = title.trim();
    if (!name || !createPin || saving) return;
    setSaving(true);
    setMessage("");
    key.current ??= crypto.randomUUID();
    try {
      await createPin(name, key.current);
      key.current = null;
      setTitle("");
      setPinOpen(false);
      setMessage("Pin saved");
      onPinCreated();
    } catch {
      setMessage("Could not confirm the pin was saved. Check your pinboard before trying again.");
    } finally {
      setSaving(false);
    }
  };
  return (
    <div className="park-agenda-new">
      <details ref={details}>
        <summary>+ New</summary>
        <div className="park-agenda-new__menu" role="menu" aria-label="New item">
          <span role="menuitem" tabIndex={-1} aria-label="Calendar item" aria-disabled="true">
            Calendar item <small>Not available here yet</small>
          </span>
          {createPin ? (
            <button
              type="button"
              role="menuitem"
              onClick={() => {
                setPinOpen(true);
                if (details.current) details.current.open = false;
              }}
            >
              Pin <small>A note for you</small>
            </button>
          ) : (
            <span role="menuitem" tabIndex={-1} aria-label="Pin" aria-disabled="true">
              Pin <small>Not available here yet</small>
            </span>
          )}
          {canHost ? (
            <a role="menuitem" href="#agenda-meetings">
              Meeting with Tilo <small>Use the meeting host form</small>
            </a>
          ) : (
            <span role="menuitem" tabIndex={-1} aria-label="Meeting with Tilo" aria-disabled="true">
              Meeting with Tilo <small>Connect the meeting host first</small>
            </span>
          )}
        </div>
      </details>
      {pinOpen && createPin ? (
        <form
          className="park-agenda-new__pin"
          onSubmit={(event) => {
            event.preventDefault();
            void save();
          }}
        >
          <label>
            Pin title
            <input
              name="pin-title"
              value={title}
              maxLength={120}
              onChange={(event) => {
                key.current = null;
                setTitle(event.target.value);
              }}
            />
          </label>
          <button type="submit" disabled={saving || !title.trim()}>
            {saving ? "Saving pin…" : "Save pin"}
          </button>
        </form>
      ) : null}
      {message ? <output>{message}</output> : null}
    </div>
  );
}
