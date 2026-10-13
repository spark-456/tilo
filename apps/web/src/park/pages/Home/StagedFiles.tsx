import { type ReactNode, useRef, useState } from "react";
import { ACCEPTED, ACCEPT_ATTR, MAX_BYTES, MAX_FILES, isAccepted } from "./uploadRules";

/** WEB-W1: files picked or pasted into the Home composer, held until Start sends them on the one `POST /intake`. */
export interface Staging {
  readonly files: readonly File[];
  readonly onChange: (files: File[]) => void;
  /** Why uploads cannot work right now; null when they can. Shown, never hidden. */
  readonly disabledReason: string | null;
}

const clip = (s: string, n = 80) => (s.length <= n ? s : `${s.slice(0, n - 1)}…`);

export function StagedFiles({ staging, children }: { staging: Staging; children: ReactNode }) {
  const picker = useRef<HTMLInputElement>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const off = staging.disabledReason !== null;

  function add(incoming: File[]) {
    if (off || incoming.length === 0) return;
    const next = [...staging.files];
    let total = next.reduce((sum, f) => sum + f.size, 0);
    let said: string | null = null;
    for (const file of incoming) {
      if (!isAccepted(file.name)) {
        said = `${clip(file.name || "A file")} is not accepted; attach ${ACCEPTED} files.`;
      } else if (next.length >= MAX_FILES) {
        said = `${next.length} files attached; the limit is ${MAX_FILES}.`;
      } else if (total + file.size > MAX_BYTES) {
        said = `The files total more than ${MAX_BYTES / (1024 * 1024)} MB.`;
      } else {
        next.push(file);
        total += file.size;
      }
    }
    setProblem(said);
    if (next.length !== staging.files.length) staging.onChange(next);
  }

  return (
    <div
      className="park-home-intake park-home-intake--staged"
      onPaste={(event) => {
        const files = Array.from(event.clipboardData?.files ?? []);
        if (files.length === 0 || off) return; // plain text pastes into the box as usual
        event.preventDefault();
        add(files);
      }}
    >
      {children}
      <div className="park-home-attach">
        <button
          type="button"
          className="park-home-change"
          data-testid="composer-attach"
          aria-disabled={off}
          title={staging.disabledReason ?? "Attach files to this task"}
          onClick={() => {
            if (!off) picker.current?.click();
          }}
        >
          Attach a file
        </button>
        <input
          ref={picker}
          type="file"
          multiple
          hidden
          accept={ACCEPT_ATTR}
          disabled={off}
          aria-label="Choose files to attach"
          onChange={(event) => {
            add(Array.from(event.target.files ?? []));
            event.target.value = "";
          }}
        />
        {staging.disabledReason ? (
          <span className="park-home-attach__note">{staging.disabledReason}</span>
        ) : null}
      </div>
      {problem ? (
        <p role="alert" className="park-home-attach__note">
          {problem}
        </p>
      ) : null}
      {staging.files.length > 0 ? (
        <ul className="park-home-attach__chips" aria-label="Attached files">
          {staging.files.map((file, i) => (
            <li key={`${file.name}-${i}`} className="park-home-attach__chip">
              <span>{file.name}</span>
              <button
                type="button"
                className="park-home-attach__remove"
                aria-label={`Remove ${file.name}`}
                onClick={() => {
                  setProblem(null);
                  staging.onChange(staging.files.filter((_, j) => j !== i));
                }}
              >
                ×
              </button>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
